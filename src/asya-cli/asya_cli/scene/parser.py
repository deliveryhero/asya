"""
Scene DSL parser.

Parses Python source code into Scene IR, tracking imports and validating DSL constraints.
"""

import ast

from asya_cli.scene.errors import CompileError, create_error
from asya_cli.scene.ir import (
    ActorCall,
    ClassInstantiation,
    ConditionalGoto,
    Goto,
    Label,
    PayloadMutation,
    Router,
    SceneIR,
)


class ImportTracker:
    """
    Track imports to resolve qualified names.

    Handles:
    - from module import name [as alias]
    - import module [as alias]
    """

    def __init__(self):
        # Map: name → full_qualified_path
        self.imports: dict[str, str] = {}

    def add_from_import(self, module: str, name: str, asname: str | None = None):
        """
        Add 'from module import name [as asname]' to tracker.

        Args:
            module: Module path (e.g., "my_module.processors")
            name: Imported name (e.g., "ImageProcessor")
            asname: Alias if 'as' was used
        """
        key = asname if asname else name
        self.imports[key] = f"{module}.{name}"

    def add_import(self, module: str, asname: str | None = None):
        """
        Add 'import module [as asname]' to tracker.

        Args:
            module: Module path (e.g., "my_module")
            asname: Alias if 'as' was used
        """
        key = asname if asname else module
        self.imports[key] = module

    def resolve(self, name: str) -> str:
        """
        Resolve a name to its full qualified path.

        Args:
            name: Name to resolve (e.g., "ImageProcessor" or "my_module.func")

        Returns:
            Full qualified path, or name as-is if not found in imports
        """
        # Check if name is qualified (contains '.')
        if "." in name:
            # Split and try to resolve first part
            first_part = name.split(".")[0]
            if first_part in self.imports:
                # Replace first part with qualified path
                rest = ".".join(name.split(".")[1:])
                return f"{self.imports[first_part]}.{rest}"
            return name

        # Simple name, look up directly
        return self.imports.get(name, name)


class SceneParser:
    """
    Parse Python source code into Scene IR.

    Validates DSL constraints and builds intermediate representation.
    """

    def __init__(self, source_file: str, source_code: str):
        self.source_file = source_file
        self.source_code = source_code
        self.source_lines = source_code.splitlines()

        self.import_tracker = ImportTracker()
        self.class_instances: dict[str, str] = {}  # var_name → qualified_class_name
        self.errors: list[CompileError] = []
        self.param_name: str = "p"  # Default parameter name, updated after parsing signature

        self._label_counter = 0  # For generating unique labels
        self._router_counter = 0  # For generating unique router IDs
        self._loop_stack: list[tuple[str, str]] = []  # Stack of (start_label, exit_label) for loops

    def _new_label(self, prefix: str = "L") -> str:
        """Generate unique label name."""
        self._label_counter += 1
        return f"{prefix}{self._label_counter}"

    def _new_router_id(self) -> str:
        """Generate unique router ID."""
        self._router_counter += 1
        return f"router_{self._router_counter}"

    def _transform_if_to_gotos(
        self, stmt: ast.If
    ) -> list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]:
        """
        Transform if/elif/else to Label/ConditionalGoto/Goto primitives.

        Python:
            if cond_a:
                ops_a
            elif cond_b:
                ops_b
            else:
                ops_c

        IR:
            ConditionalGoto(cond_a, "branch_a", "check_b")
            Label("branch_a")
            <ops_a>
            Goto("after_if")
            Label("check_b")
            ConditionalGoto(cond_b, "branch_b", "branch_else")
            Label("branch_b")
            <ops_b>
            Goto("after_if")
            Label("branch_else")
            <ops_c>
            Label("after_if")
        """
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall] = []
        after_label = self._new_label("after_if")

        # Main if condition
        then_label = self._new_label("then")
        else_label = self._new_label("else") if stmt.orelse else after_label

        operations.append(
            ConditionalGoto(
                line=stmt.lineno,
                col=stmt.col_offset,
                condition_str=ast.unparse(stmt.test),
                condition_ast=stmt.test,
                true_target=then_label,
                false_target=else_label,
            )
        )

        # Then branch
        operations.append(Label(line=stmt.lineno, col=stmt.col_offset, name=then_label))
        for s in stmt.body:
            ops = self._parse_statement_to_router_ops(s)
            if ops:
                operations.extend(ops)
        if stmt.orelse:
            operations.append(Goto(line=stmt.lineno, col=stmt.col_offset, target=after_label))

        # Elif/else chain
        if stmt.orelse:
            operations.append(Label(line=stmt.lineno, col=stmt.col_offset, name=else_label))
            if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                # Elif - recursively transform
                elif_ops = self._transform_if_to_gotos(stmt.orelse[0])
                operations.extend(elif_ops)
            else:
                # Else block
                for s in stmt.orelse:
                    ops = self._parse_statement_to_router_ops(s)
                    if ops:
                        operations.extend(ops)

        # After label
        operations.append(Label(line=stmt.lineno, col=stmt.col_offset, name=after_label))

        return operations

    def _transform_while_to_gotos(
        self, stmt: ast.While
    ) -> list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]:
        """
        Transform while loop to Label/ConditionalGoto/Goto primitives.

        Python:
            while condition:
                body

        IR:
            Label("loop_start")
            ConditionalGoto(condition, "loop_body", "loop_exit")
            Label("loop_body")
            <body>
            Goto("loop_start")
            Label("loop_exit")
        """
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall] = []

        start_label = self._new_label("loop_start")
        body_label = self._new_label("loop_body")
        exit_label = self._new_label("loop_exit")

        # Push loop context for break/continue
        self._loop_stack.append((start_label, exit_label))

        # Loop start
        operations.append(Label(line=stmt.lineno, col=stmt.col_offset, name=start_label))

        # Condition check
        operations.append(
            ConditionalGoto(
                line=stmt.lineno,
                col=stmt.col_offset,
                condition_str=ast.unparse(stmt.test),
                condition_ast=stmt.test,
                true_target=body_label,
                false_target=exit_label,
            )
        )

        # Loop body
        operations.append(Label(line=stmt.lineno, col=stmt.col_offset, name=body_label))
        for s in stmt.body:
            ops = self._parse_statement_to_router_ops(s)
            if ops:
                operations.extend(ops)

        # Jump back to start
        operations.append(Goto(line=stmt.lineno, col=stmt.col_offset, target=start_label))

        # Loop exit
        operations.append(Label(line=stmt.lineno, col=stmt.col_offset, name=exit_label))

        # Pop loop context
        self._loop_stack.pop()

        return operations

    def _parse_statement_to_router_ops(
        self, stmt: ast.stmt
    ) -> list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall] | None:
        """
        Parse a statement into router-level operations.

        Returns list of operations, or None if error/skip.
        """
        if isinstance(stmt, ast.Expr):
            # Skip docstrings
            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                return None
            self.errors.append(
                create_error(
                    message="Standalone expressions are not supported in Scene DSL",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL only supports assignments, if/while, and return",
                    fix_hint="Remove standalone expression or assign it to a variable",
                )
            )
            return None

        elif isinstance(stmt, ast.Assign):
            return self._parse_assignment_to_router_ops(stmt)

        elif isinstance(stmt, ast.AugAssign):
            return self._parse_augmented_assignment_to_router_ops(stmt)

        elif isinstance(stmt, ast.If):
            return self._transform_if_to_gotos(stmt)

        elif isinstance(stmt, ast.While):
            return self._transform_while_to_gotos(stmt)

        elif isinstance(stmt, ast.Break):
            if not self._loop_stack:
                self.errors.append(
                    create_error(
                        message="'break' outside loop",
                        node=stmt,
                        source_file=self.source_file,
                        source_lines=self.source_lines,
                        explanation="break can only appear inside while loops",
                        fix_hint="Remove break or place it inside a while loop",
                    )
                )
                return None
            _, exit_label = self._loop_stack[-1]
            return [Goto(line=stmt.lineno, col=stmt.col_offset, target=exit_label)]

        elif isinstance(stmt, ast.Continue):
            if not self._loop_stack:
                self.errors.append(
                    create_error(
                        message="'continue' outside loop",
                        node=stmt,
                        source_file=self.source_file,
                        source_lines=self.source_lines,
                        explanation="continue can only appear inside while loops",
                        fix_hint="Remove continue or place it inside a while loop",
                    )
                )
                return None
            start_label, _ = self._loop_stack[-1]
            return [Goto(line=stmt.lineno, col=stmt.col_offset, target=start_label)]

        elif isinstance(stmt, ast.Pass):
            return None

        elif isinstance(stmt, ast.Return):
            # Return statements should not appear in router ops
            self.errors.append(
                create_error(
                    message="Return statement inside control scene not supported",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Return must be at top level of scene function",
                    fix_hint="Move return to end of function",
                )
            )
            return None

        elif isinstance(stmt, ast.For):
            self.errors.append(
                create_error(
                    message="'for' loops are not supported in Scene DSL",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL only supports 'while' loops for clear async control scene",
                    fix_hint="Convert to while loop with explicit index: i = 0; while i < len(items): ...; i += 1",
                )
            )
            return None

        elif isinstance(stmt, ast.Try | ast.With | ast.Raise):
            self.errors.append(
                create_error(
                    message=f"'{stmt.__class__.__name__}' statements are not supported in Scene DSL",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Error handling and context managers are managed at actor level",
                    fix_hint="Remove error handling from scene logic",
                )
            )
            return None

        else:
            self.errors.append(
                create_error(
                    message=f"Unsupported statement type: {stmt.__class__.__name__}",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL only supports assignments, if/while, and return",
                )
            )
            return None

    def _parse_assignment_to_router_ops(
        self, stmt: ast.Assign
    ) -> list[PayloadMutation | ClassInstantiation | ActorCall] | None:
        """
        Parse assignment in router context.

        Handles:
        - p = handler(p) - ActorCall (conditional actor call inside router)
        - p["key"] = value - PayloadMutation
        - var = ClassName(...) - ClassInstantiation
        """
        if len(stmt.targets) != 1:
            self.errors.append(
                create_error(
                    message="Multiple assignment targets not supported",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL requires single assignment target",
                    fix_hint="Split into multiple statements",
                )
            )
            return None

        target = stmt.targets[0]

        # Case 1: p = handler(p) - ActorCall
        if isinstance(target, ast.Name) and isinstance(stmt.value, ast.Call):
            target_name = target.id

            if target_name == self.param_name:
                # Handler call
                func_name, qualified_name = self._resolve_call_target(stmt.value.func)

                # Validate single argument
                if len(stmt.value.args) != 1 or stmt.value.keywords:
                    self.errors.append(
                        create_error(
                            message=f"Handler calls must have exactly one argument '{self.param_name}'",
                            node=stmt.value,
                            source_file=self.source_file,
                            source_lines=self.source_lines,
                            explanation="Scene DSL handlers receive only the payload",
                            fix_hint=f"Change to: {self.param_name} = handler({self.param_name})",
                        )
                    )
                    return None

                arg = stmt.value.args[0]
                if not isinstance(arg, ast.Name) or arg.id != self.param_name:
                    self.errors.append(
                        create_error(
                            message=f"Handler argument must be '{self.param_name}', got '{ast.unparse(arg)}'",
                            node=arg,
                            source_file=self.source_file,
                            source_lines=self.source_lines,
                            explanation="Scene DSL requires explicit payload passing",
                            fix_hint=f"Change to: {self.param_name} = handler({self.param_name})",
                        )
                    )
                    return None

                return [
                    ActorCall(
                        line=stmt.lineno,
                        col=stmt.col_offset,
                        qualified_name=qualified_name,
                        display_name=func_name,
                    )
                ]
            else:
                # Class instantiation
                return [self._parse_class_instantiation_op(stmt, target_name)]

        # Case 2: p["key"] = value - PayloadMutation
        elif isinstance(target, ast.Subscript):
            if not isinstance(target.value, ast.Name) or target.value.id != self.param_name:
                self.errors.append(
                    create_error(
                        message=f"Subscript assignment must be on '{self.param_name}'",
                        node=target,
                        source_file=self.source_file,
                        source_lines=self.source_lines,
                        explanation=f"Scene DSL only allows payload mutations via {self.param_name}[...]",
                        fix_hint=f"Change to: {self.param_name}['key'] = value",
                    )
                )
                return None

            # Extract key
            if isinstance(target.slice, ast.Constant):
                key = target.slice.value
                if not isinstance(key, str):
                    self.errors.append(
                        create_error(
                            message=f"Subscript key must be string, got {type(key).__name__}",
                            node=target.slice,
                            source_file=self.source_file,
                            source_lines=self.source_lines,
                            explanation="Payload keys must be strings",
                            fix_hint="Use string key: p['key'] = value",
                        )
                    )
                    return None
            else:
                self.errors.append(
                    create_error(
                        message="Subscript key must be a constant string",
                        node=target.slice,
                        source_file=self.source_file,
                        source_lines=self.source_lines,
                        explanation="Scene DSL requires static keys for payload mutations",
                        fix_hint="Use constant string: p['key'] = value",
                    )
                )
                return None

            return [
                PayloadMutation(
                    line=stmt.lineno,
                    col=stmt.col_offset,
                    key=key,
                    value_str=ast.unparse(stmt.value),
                    value_ast=stmt.value,
                )
            ]

        else:
            self.errors.append(
                create_error(
                    message=f"Unsupported assignment target type: {target.__class__.__name__}",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL only supports 'p = handler(p)' and 'p[\"key\"] = value'",
                )
            )
            return None

    def _parse_augmented_assignment_to_router_ops(self, stmt: ast.AugAssign) -> list[PayloadMutation] | None:
        """
        Parse augmented assignment in router context: p["key"] += value

        Converts to PayloadMutation with combined expression.
        """
        if not isinstance(stmt.target, ast.Subscript):
            self.errors.append(
                create_error(
                    message="Augmented assignment must be on payload subscript",
                    node=stmt.target,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation=f"Scene DSL only allows augmented assignments via {self.param_name}['key']",
                    fix_hint=f"Change to: {self.param_name}['key'] += value",
                )
            )
            return None

        target = stmt.target

        if not isinstance(target.value, ast.Name) or target.value.id != self.param_name:
            self.errors.append(
                create_error(
                    message=f"Augmented assignment must be on '{self.param_name}'",
                    node=target,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation=f"Scene DSL only allows payload mutations via {self.param_name}[...]",
                    fix_hint=f"Change to: {self.param_name}['key'] += value",
                )
            )
            return None

        # Extract key
        if isinstance(target.slice, ast.Constant):
            key = target.slice.value
            if not isinstance(key, str):
                self.errors.append(
                    create_error(
                        message=f"Subscript key must be string, got {type(key).__name__}",
                        node=target.slice,
                        source_file=self.source_file,
                        source_lines=self.source_lines,
                        explanation="Payload keys must be strings",
                        fix_hint="Use string key: p['key'] += value",
                    )
                )
                return None
        else:
            self.errors.append(
                create_error(
                    message="Subscript key must be a constant string",
                    node=target.slice,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL requires static keys for payload mutations",
                    fix_hint="Use constant string: p['key'] += value",
                )
            )
            return None

        # Convert augmented assignment to regular mutation
        # p["key"] += value becomes p["key"] = p["key"] + value
        combined_expr = ast.BinOp(
            left=ast.Subscript(
                value=ast.Name(id=self.param_name, ctx=ast.Load()),
                slice=ast.Constant(value=key),
                ctx=ast.Load(),
            ),
            op=stmt.op,
            right=stmt.value,
        )

        return [
            PayloadMutation(
                line=stmt.lineno,
                col=stmt.col_offset,
                key=key,
                value_str=ast.unparse(combined_expr),
                value_ast=combined_expr,
            )
        ]

    def _parse_class_instantiation_op(self, stmt: ast.Assign, var_name: str) -> ClassInstantiation:
        """Parse class instantiation for router operations."""
        call = stmt.value
        assert isinstance(call, ast.Call)

        if not isinstance(call.func, ast.Name):
            self.errors.append(
                create_error(
                    message="Class instantiation must use simple class name",
                    node=call,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL requires direct class instantiation",
                    fix_hint="Import class and use: var = ClassName(args)",
                )
            )
            raise ValueError("Invalid class instantiation")

        class_name = call.func.id
        qualified_name = self.import_tracker.resolve(class_name)

        # Track this instance
        self.class_instances[var_name] = qualified_name

        # Extract args and kwargs
        args = call.args
        kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}

        return ClassInstantiation(
            line=stmt.lineno,
            col=stmt.col_offset,
            var_name=var_name,
            class_name=class_name,
            qualified_name=qualified_name,
            args=args,
            kwargs=kwargs,
        )

    def parse(self) -> SceneIR | None:
        """
        Parse source code into SceneIR.

        Returns:
            SceneIR if successful, None if errors occurred
        """
        try:
            tree = ast.parse(self.source_code, filename=self.source_file)
        except SyntaxError as e:
            from asya_cli.scene.errors import SourceLocation, get_code_context

            location = SourceLocation(line=e.lineno or 1, col=e.offset or 0, source_file=self.source_file)
            context = get_code_context(self.source_lines, e.lineno or 1)
            self.errors.append(
                CompileError(
                    location=location,
                    message=f"Syntax error: {e.msg}",
                    explanation="Python syntax error in source file",
                    fix_hint="Fix Python syntax errors before compiling scene",
                    code_context=context,
                )
            )
            return None

        # Extract imports
        imports = self._extract_imports(tree)

        # Find scene function
        scene_func = self._find_scene_function(tree)
        if not scene_func:
            return None

        # Validate function signature FIRST (so param_name is set)
        param_name = self._validate_signature(scene_func)
        if param_name is None:
            return None

        # Store param_name for use in parsing
        self.param_name = param_name

        # Parse function body
        steps = self._parse_function_body(scene_func)
        if steps is None:
            return None

        return SceneIR(
            name=scene_func.name,
            param_name=param_name,
            steps=steps,
            source_file=self.source_file,
            lineno=scene_func.lineno,
            imports=imports,
            class_instances=self.class_instances,
        )

    def _extract_imports(self, tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
        """Extract and track all imports."""
        imports: list[ast.Import | ast.ImportFrom] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.append(node)
                for alias in node.names:
                    self.import_tracker.add_import(alias.name, alias.asname)

            elif isinstance(node, ast.ImportFrom):
                imports.append(node)
                module = node.module or ""
                for alias in node.names:
                    self.import_tracker.add_from_import(module, alias.name, alias.asname)

        return imports

    def _find_scene_function(self, tree: ast.Module) -> ast.FunctionDef | None:
        """
        Find the scene function in the module.

        For now, looks for function with name starting with 'scene'.
        Later we can make this configurable.
        """
        scene_functions = []

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and "scene" in node.name:
                scene_functions.append(node)

        if not scene_functions:
            from asya_cli.scene.errors import SourceLocation

            location = SourceLocation(line=1, col=0, source_file=self.source_file)
            self.errors.append(
                CompileError(
                    location=location,
                    message="No scene function found",
                    explanation="Scene file must contain a function with name starting with 'scene'",
                    fix_hint="Define a function like: def scene_my_pipeline(p: dict) -> dict:",
                )
            )
            return None

        if len(scene_functions) > 1:
            from asya_cli.scene.errors import SourceLocation

            location = SourceLocation(line=1, col=0, source_file=self.source_file)
            self.errors.append(
                CompileError(
                    location=location,
                    message=f"Multiple scene functions found: {[f.name for f in scene_functions]}",
                    explanation="Scene file should contain only one scene function",
                    fix_hint="Keep only one scene function, or compile them separately",
                )
            )
            return None

        return scene_functions[0]

    def _validate_signature(self, func: ast.FunctionDef) -> str | None:
        """
        Validate function signature: def scene_name(p: dict) -> dict

        Returns:
            Parameter name if valid, None otherwise
        """
        # Check exactly one parameter
        if len(func.args.args) != 1:
            self.errors.append(
                create_error(
                    message=f"Scene function must have exactly 1 parameter, got {len(func.args.args)}",
                    node=func,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL requires single dict parameter for payload",
                    fix_hint=f"Change signature to: def {func.name}(p: dict) -> dict:",
                )
            )
            return None

        param = func.args.args[0]
        param_name = param.arg

        # Check parameter has type annotation of dict
        if not param.annotation:
            self.errors.append(
                create_error(
                    message=f"Parameter '{param_name}' must have type annotation 'dict'",
                    node=param,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL requires typed parameter for clarity",
                    fix_hint=f"Change to: {param_name}: dict",
                )
            )
            return None

        # Check return type annotation
        if not func.returns:
            self.errors.append(
                create_error(
                    message="Scene function must have return type annotation '-> dict'",
                    node=func,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Scene DSL requires return type for clarity",
                    fix_hint=f"Change signature to: def {func.name}({param_name}: dict) -> dict:",
                )
            )
            return None

        return param_name

    def _parse_function_body(self, func: ast.FunctionDef) -> list[ActorCall | Router] | None:
        """
        Parse function body into scene steps (ActorCall | Router).

        Grouping algorithm:
        - Top-level p = handler(p) → Scene-level ActorCall
        - Control scene / mutations → Grouped into Router
        - Return statement → Implicit, validate but don't include in IR
        """
        steps: list[ActorCall | Router] = []
        router_ops: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall] = []
        router_start_line = 0

        for stmt in func.body:
            # Check for return statement (should be last)
            if isinstance(stmt, ast.Return):
                if not stmt.value:
                    self.errors.append(
                        create_error(
                            message="Return statement must return a value",
                            node=stmt,
                            source_file=self.source_file,
                            source_lines=self.source_lines,
                            explanation="Scene DSL requires returning the payload",
                            fix_hint=f"Change to: return {self.param_name}",
                        )
                    )
                    return None

                if not isinstance(stmt.value, ast.Name) or stmt.value.id != self.param_name:
                    self.errors.append(
                        create_error(
                            message=f"Return statement must return '{self.param_name}', got '{ast.unparse(stmt.value)}'",
                            node=stmt.value,
                            source_file=self.source_file,
                            source_lines=self.source_lines,
                            explanation="Scene DSL requires explicit payload return",
                            fix_hint=f"Change to: return {self.param_name}",
                        )
                    )
                    return None

                # Flush any pending router
                if router_ops:
                    steps.append(
                        Router(
                            line=router_start_line,
                            col=0,
                            router_id=self._new_router_id(),
                            operations=router_ops,
                        )
                    )
                    router_ops = []

                # Return is implicit, don't add to IR
                continue

            # Skip docstrings
            if (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                continue

            # Check if it's a scene-level actor call
            if self._is_scene_level_actor_call(stmt):
                # Flush any pending router
                if router_ops:
                    steps.append(
                        Router(
                            line=router_start_line,
                            col=0,
                            router_id=self._new_router_id(),
                            operations=router_ops,
                        )
                    )
                    router_ops = []

                # Parse as scene-level actor call
                assert isinstance(stmt, ast.Assign)
                call = stmt.value
                assert isinstance(call, ast.Call)
                func_name, qualified_name = self._resolve_call_target(call.func)

                steps.append(
                    ActorCall(
                        line=stmt.lineno,
                        col=stmt.col_offset,
                        qualified_name=qualified_name,
                        display_name=func_name,
                    )
                )
            else:
                # Router operation - parse and collect
                if not router_ops:
                    router_start_line = stmt.lineno

                ops = self._parse_statement_to_router_ops(stmt)
                if ops:
                    router_ops.extend(ops)

        # Flush any final router
        if router_ops:
            steps.append(
                Router(
                    line=router_start_line,
                    col=0,
                    router_id=self._new_router_id(),
                    operations=router_ops,
                )
            )

        return steps if not self.errors else None

    def _is_scene_level_actor_call(self, stmt: ast.stmt) -> bool:
        """
        Check if statement is a scene-level actor call: p = handler(p)

        Scene-level means top-level, unconditional actor call.
        """
        if not isinstance(stmt, ast.Assign):
            return False

        if len(stmt.targets) != 1:
            return False

        target = stmt.targets[0]

        # Must be: p = ... where target is param_name
        if not isinstance(target, ast.Name) or target.id != self.param_name:
            return False

        # Must be a call
        if not isinstance(stmt.value, ast.Call):
            return False

        # Validate it's a valid handler call (single arg = param_name)
        call = stmt.value
        if len(call.args) != 1 or call.keywords:
            return False

        arg = call.args[0]
        if not isinstance(arg, ast.Name) or arg.id != self.param_name:
            return False

        return True

    def _resolve_call_target(self, func: ast.expr) -> tuple[str, str]:
        """
        Resolve function call target to (func_name, qualified_name).

        Handles:
        - handler(p) → ("handler", "module.handler")
        - instance.method(p) → ("instance.method", "module.Class.method")
        """
        if isinstance(func, ast.Name):
            # Simple function call: handler(p)
            func_name = func.id
            qualified_name = self.import_tracker.resolve(func_name)
            return func_name, qualified_name

        elif isinstance(func, ast.Attribute):
            # Method call: instance.method(p)
            if isinstance(func.value, ast.Name):
                var_name = func.value.id
                method_name = func.attr
                func_name = f"{var_name}.{method_name}"

                # Check if var_name is a class instance
                if var_name in self.class_instances:
                    class_qualified = self.class_instances[var_name]
                    qualified_name = f"{class_qualified}.{method_name}"
                else:
                    # Might be module.function
                    qualified_name = self.import_tracker.resolve(func_name)

                return func_name, qualified_name

        # Fallback: use unparsed expression
        func_name = ast.unparse(func)
        return func_name, func_name
