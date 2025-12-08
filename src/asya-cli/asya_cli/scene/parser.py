"""
Flow DSL parser.

Parses Python source code into Flow IR, tracking imports and validating DSL constraints.
"""

import ast

from asya_cli.scene.errors import CompileError, create_error
from asya_cli.scene.ir import (
    ActorCall,
    ClassInstantiation,
    ConditionalGoto,
    SceneIR,
    Goto,
    Label,
    Operation,
    PayloadMutation,
    ReturnPayload,
    Router,
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
    Parse Python source code into Flow IR.

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
                    fix_hint="Fix Python syntax errors before compiling flow",
                    code_context=context,
                )
            )
            return None

        # Extract imports
        imports = self._extract_imports(tree)

        # Find flow function
        flow_func = self._find_flow_function(tree)
        if not flow_func:
            return None

        # Validate function signature FIRST (so param_name is set)
        param_name = self._validate_signature(flow_func)
        if param_name is None:
            return None

        # Store param_name for use in parsing
        self.param_name = param_name

        # Parse function body
        operations = self._parse_function_body(flow_func)
        if operations is None:
            return None

        return SceneIR(
            name=flow_func.name,
            param_name=param_name,
            operations=operations,
            source_file=self.source_file,
            lineno=flow_func.lineno,
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

    def _find_flow_function(self, tree: ast.Module) -> ast.FunctionDef | None:
        """
        Find the flow function in the module.

        For now, looks for function with name starting with 'flow_' or just 'flow'.
        Later we can make this configurable.
        """
        flow_functions = []

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("flow"):
                flow_functions.append(node)

        if not flow_functions:
            from asya_cli.scene.errors import SourceLocation

            location = SourceLocation(line=1, col=0, source_file=self.source_file)
            self.errors.append(
                CompileError(
                    location=location,
                    message="No flow function found",
                    explanation="Flow file must contain a function with name starting with 'flow'",
                    fix_hint="Define a function like: def flow_my_pipeline(p: dict) -> dict:",
                )
            )
            return None

        if len(flow_functions) > 1:
            from asya_cli.scene.errors import SourceLocation

            location = SourceLocation(line=1, col=0, source_file=self.source_file)
            self.errors.append(
                CompileError(
                    location=location,
                    message=f"Multiple flow functions found: {[f.name for f in flow_functions]}",
                    explanation="Flow file should contain only one flow function",
                    fix_hint="Keep only one flow function, or compile them separately",
                )
            )
            return None

        return flow_functions[0]

    def _validate_signature(self, func: ast.FunctionDef) -> str | None:
        """
        Validate function signature: def flow_name(p: dict) -> dict

        Returns:
            Parameter name if valid, None otherwise
        """
        # Check exactly one parameter
        if len(func.args.args) != 1:
            self.errors.append(
                create_error(
                    message=f"Flow function must have exactly 1 parameter, got {len(func.args.args)}",
                    node=func,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL requires single dict parameter for payload",
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
                    explanation="Flow DSL requires typed parameter for clarity",
                    fix_hint=f"Change to: {param_name}: dict",
                )
            )
            return None

        # Check return type annotation
        if not func.returns:
            self.errors.append(
                create_error(
                    message="Flow function must have return type annotation '-> dict'",
                    node=func,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL requires return type for clarity",
                    fix_hint=f"Change signature to: def {func.name}({param_name}: dict) -> dict:",
                )
            )
            return None

        return param_name

    def _parse_function_body(self, func: ast.FunctionDef) -> list[Operation] | None:
        """Parse function body into operations."""
        operations = []

        for stmt in func.body:
            op = self._parse_statement(stmt)
            if op is not None:
                if isinstance(op, list):
                    operations.extend(op)
                else:
                    operations.append(op)

        # Check that function ends with return
        if not operations or not isinstance(operations[-1], Return):
            self.errors.append(
                create_error(
                    message="Flow function must end with 'return p' statement",
                    node=func,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL requires explicit return of payload",
                    fix_hint="Add 'return p' at the end of the function",
                )
            )
            return None

        return operations if not self.errors else None

    def _parse_statement(self, stmt: ast.stmt) -> Operation | list[Operation] | None:
        """Parse a single statement into operation(s)."""
        if isinstance(stmt, ast.Expr):
            # Skip docstrings and standalone expressions
            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                # It's a docstring, skip it
                return None
            # Other expressions are not supported
            self.errors.append(
                create_error(
                    message="Standalone expressions are not supported in Flow DSL",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL only supports assignments, if/while, and return",
                    fix_hint="Remove standalone expression or assign it to a variable",
                )
            )
            return None
        elif isinstance(stmt, ast.Assign):
            return self._parse_assignment(stmt)
        elif isinstance(stmt, ast.AugAssign):
            return self._parse_augmented_assignment(stmt)
        elif isinstance(stmt, ast.If):
            return self._parse_if(stmt)
        elif isinstance(stmt, ast.While):
            return self._parse_while(stmt)
        elif isinstance(stmt, ast.Return):
            return self._parse_return(stmt)
        elif isinstance(stmt, ast.Break):
            return Break(line=stmt.lineno, col=stmt.col_offset)
        elif isinstance(stmt, ast.Continue):
            return Continue(line=stmt.lineno, col=stmt.col_offset)
        elif isinstance(stmt, ast.Pass):
            # Pass statements are no-ops, skip them
            return None
        elif isinstance(stmt, ast.For):
            self.errors.append(
                create_error(
                    message="'for' loops are not supported in Flow DSL",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL only supports 'while' loops for clear async control flow",
                    fix_hint="Convert to while loop with explicit index: i = 0; while i < len(items): ...; i += 1",
                )
            )
            return None
        elif isinstance(stmt, ast.Try | ast.With | ast.Raise):
            self.errors.append(
                create_error(
                    message=f"'{stmt.__class__.__name__}' statements are not supported in Flow DSL",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Error handling and context managers are managed at actor level",
                    fix_hint="Remove error handling from flow logic",
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
                    explanation="Flow DSL only supports assignments, if/while, and return",
                )
            )
            return None

    def _parse_assignment(self, stmt: ast.Assign) -> Operation | list[Operation] | None:
        """
        Parse assignment statement.

        Handles:
        - p = handler(p) - handler call
        - p["key"] = value - payload mutation
        - var = ClassName(...) - class instantiation
        """
        if len(stmt.targets) != 1:
            self.errors.append(
                create_error(
                    message="Multiple assignment targets not supported",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL requires single assignment target",
                    fix_hint="Split into multiple statements",
                )
            )
            return None

        target = stmt.targets[0]

        # Case 1: payload = handler(payload) or payload = var.method(payload)
        if isinstance(target, ast.Name):
            target_name = target.id

            # Check if it's a handler call
            if isinstance(stmt.value, ast.Call):
                # Check if it's class instantiation (target is not the payload param)
                if target_name != self.param_name:
                    return self._parse_class_instantiation(stmt, target_name)

                # It's a handler call: payload = handler(payload)
                return self._parse_handler_call(stmt, target_name)

            # Wrong syntax
            self.errors.append(
                create_error(
                    message=f"Invalid assignment to '{target_name}'",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation=f"Assignments must be handler calls ({self.param_name} = handler({self.param_name})) or payload mutations ({self.param_name}['key'] = value)",
                )
            )
            return None

        # Case 2: payload["key"] = value
        elif isinstance(target, ast.Subscript):
            return self._parse_payload_mutation(stmt, target)

        else:
            self.errors.append(
                create_error(
                    message=f"Unsupported assignment target type: {target.__class__.__name__}",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL only supports 'p = handler(p)' and 'p[\"key\"] = value'",
                )
            )
            return None

    def _parse_handler_call(self, stmt: ast.Assign, target_name: str) -> HandlerCall | None:
        """
        Parse handler call: payload = handler(payload) or payload = instance.method(payload)

        Args:
            stmt: Assignment statement
            target_name: Target variable name (payload parameter name)

        Returns:
            HandlerCall operation or None if invalid
        """
        call = stmt.value
        assert isinstance(call, ast.Call)  # Type narrowing for mypy

        # Validate arguments: must be single arg with value matching param name
        if len(call.args) != 1 or call.keywords:
            self.errors.append(
                create_error(
                    message=f"Handler calls must have exactly one argument '{self.param_name}'",
                    node=call,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL handlers receive only the payload",
                    fix_hint=f"Change to: {self.param_name} = handler({self.param_name})",
                )
            )
            return None

        arg = call.args[0]
        if not isinstance(arg, ast.Name) or arg.id != self.param_name:
            self.errors.append(
                create_error(
                    message=f"Handler argument must be '{self.param_name}', got '{ast.unparse(arg)}'",
                    node=arg,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL requires explicit payload passing",
                    fix_hint=f"Change to: {self.param_name} = handler({self.param_name})",
                )
            )
            return None

        # Determine function name and qualified name
        func_name, qualified_name = self._resolve_call_target(call.func)

        return HandlerCall(
            line=stmt.lineno,
            col=stmt.col_offset,
            func_name=func_name,
            qualified_name=qualified_name,
            target=target_name,
        )

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

    def _parse_class_instantiation(self, stmt: ast.Assign, var_name: str) -> ClassInstantiation | None:
        """
        Parse class instantiation: var = ClassName(args)

        Args:
            stmt: Assignment statement
            var_name: Variable being assigned to

        Returns:
            ClassInstantiation operation
        """
        call = stmt.value
        assert isinstance(call, ast.Call)  # Type narrowing for mypy

        if not isinstance(call.func, ast.Name):
            self.errors.append(
                create_error(
                    message="Class instantiation must use simple class name",
                    node=call,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL requires direct class instantiation",
                    fix_hint="Import class and use: var = ClassName(args)",
                )
            )
            return None

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

    def _parse_payload_mutation(self, stmt: ast.Assign, target: ast.Subscript) -> Assignment | None:
        """
        Parse payload mutation: payload["key"] = value

        Args:
            stmt: Assignment statement
            target: Subscript target (payload["key"])

        Returns:
            Assignment operation or None if invalid
        """
        # Validate: must be payload[...]
        if not isinstance(target.value, ast.Name) or target.value.id != self.param_name:
            self.errors.append(
                create_error(
                    message=f"Subscript assignment must be on '{self.param_name}'",
                    node=target,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation=f"Flow DSL only allows payload mutations via {self.param_name}[...]",
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
                    explanation="Flow DSL requires static keys for payload mutations",
                    fix_hint="Use constant string: p['key'] = value",
                )
            )
            return None

        value_str = ast.unparse(stmt.value)

        return Assignment(
            line=stmt.lineno,
            col=stmt.col_offset,
            target=self.param_name,
            key=key,
            value_ast=stmt.value,
            value_str=value_str,
        )

    def _parse_augmented_assignment(self, stmt: ast.AugAssign) -> Assignment | None:
        """
        Parse augmented assignment: payload["key"] += value

        Converts to Assignment IR with combined expression.

        Args:
            stmt: AugAssign statement

        Returns:
            Assignment operation or None if invalid
        """
        # Validate: target must be payload[...]
        if not isinstance(stmt.target, ast.Subscript):
            self.errors.append(
                create_error(
                    message="Augmented assignment must be on payload subscript",
                    node=stmt.target,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation=f"Flow DSL only allows augmented assignments via {self.param_name}['key']",
                    fix_hint=f"Change to: {self.param_name}['key'] += value",
                )
            )
            return None

        target = stmt.target

        # Validate: must be payload[...]
        if not isinstance(target.value, ast.Name) or target.value.id != self.param_name:
            self.errors.append(
                create_error(
                    message=f"Augmented assignment must be on '{self.param_name}'",
                    node=target,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation=f"Flow DSL only allows payload mutations via {self.param_name}[...]",
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
                    explanation="Flow DSL requires static keys for payload mutations",
                    fix_hint="Use constant string: p['key'] += value",
                )
            )
            return None

        # Convert augmented assignment to regular assignment
        # payload["key"] += value becomes payload["key"] = payload["key"] + value
        # Create BinOp: payload["key"] + value
        combined_expr = ast.BinOp(
            left=ast.Subscript(
                value=ast.Name(id=self.param_name, ctx=ast.Load()),
                slice=ast.Constant(value=key),
                ctx=ast.Load(),
            ),
            op=stmt.op,
            right=stmt.value,
        )

        value_str = ast.unparse(combined_expr)

        return Assignment(
            line=stmt.lineno,
            col=stmt.col_offset,
            target=self.param_name,
            key=key,
            value_ast=combined_expr,
            value_str=value_str,
        )

    def _parse_if(self, stmt: ast.If) -> IfBlock | None:
        """Parse if/elif/else statement."""
        condition_str = ast.unparse(stmt.test)

        # Parse branches
        then_ops = []
        for s in stmt.body:
            op = self._parse_statement(s)
            if op is not None:
                if isinstance(op, list):
                    then_ops.extend(op)
                else:
                    then_ops.append(op)

        # Parse elif/else
        elif_blocks: list[tuple[ast.expr, str, list[Operation]]] = []
        else_ops: list[Operation] = []

        if stmt.orelse:
            # Check if it's elif or else
            if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                # It's elif - flatten into elif_blocks
                elif_stmt = stmt.orelse[0]
                self._parse_elif_chain(elif_stmt, elif_blocks, else_ops)
            else:
                # It's else
                for s in stmt.orelse:
                    op = self._parse_statement(s)
                    if op is not None:
                        if isinstance(op, list):
                            else_ops.extend(op)
                        else:
                            else_ops.append(op)

        return IfBlock(
            line=stmt.lineno,
            col=stmt.col_offset,
            condition=stmt.test,
            condition_str=condition_str,
            then_ops=then_ops,
            elif_blocks=elif_blocks,
            else_ops=else_ops,
        )

    def _parse_elif_chain(
        self, stmt: ast.If, elif_blocks: list[tuple[ast.expr, str, list[Operation]]], else_ops: list[Operation]
    ):
        """Recursively parse elif chain."""
        condition_str = ast.unparse(stmt.test)

        # Parse this elif's body
        body_ops = []
        for s in stmt.body:
            op = self._parse_statement(s)
            if op is not None:
                if isinstance(op, list):
                    body_ops.extend(op)
                else:
                    body_ops.append(op)

        elif_blocks.append((stmt.test, condition_str, body_ops))

        # Check for more elif/else
        if stmt.orelse:
            if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                # Another elif
                self._parse_elif_chain(stmt.orelse[0], elif_blocks, else_ops)
            else:
                # Final else
                for s in stmt.orelse:
                    op = self._parse_statement(s)
                    if op is not None:
                        if isinstance(op, list):
                            else_ops.extend(op)
                        else:
                            else_ops.append(op)

    def _parse_while(self, stmt: ast.While) -> WhileLoop | None:
        """Parse while loop."""
        condition_str = ast.unparse(stmt.test)

        # Parse body
        body_ops = []
        for s in stmt.body:
            op = self._parse_statement(s)
            if op is not None:
                if isinstance(op, list):
                    body_ops.extend(op)
                else:
                    body_ops.append(op)

        # While loops should not have else clause in Flow DSL
        if stmt.orelse:
            self.errors.append(
                create_error(
                    message="While loops cannot have 'else' clause in Flow DSL",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL keeps control flow simple",
                    fix_hint="Remove 'else' clause from while loop",
                )
            )
            return None

        return WhileLoop(
            line=stmt.lineno,
            col=stmt.col_offset,
            condition=stmt.test,
            condition_str=condition_str,
            body_ops=body_ops,
        )

    def _parse_return(self, stmt: ast.Return) -> Return | None:
        """Parse return statement."""
        if not stmt.value:
            self.errors.append(
                create_error(
                    message="Return statement must return a value",
                    node=stmt,
                    source_file=self.source_file,
                    source_lines=self.source_lines,
                    explanation="Flow DSL requires returning the payload",
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
                    explanation="Flow DSL requires explicit payload return",
                    fix_hint=f"Change to: return {self.param_name}",
                )
            )
            return None

        return Return(line=stmt.lineno, col=stmt.col_offset, value=self.param_name)
