"""Parse flow DSL from Python AST."""

from __future__ import annotations

import ast

from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.ir import (
    ActorCall,
    Break,
    Condition,
    Continue,
    ExceptHandler,
    FanOutCall,
    IROperation,
    Mutation,
    Raise,
    Return,
    TryExcept,
    WhileLoop,
)


# Parameter names accepted in flow function signatures.
# The canonical name used in generated code is "p".
VALID_PARAM_NAMES = ("p", "payload", "state")

# Function definition types (sync and async)
_FUNC_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


class _ParamNormalizer(ast.NodeTransformer):
    """Rename flow parameter references to the canonical name 'p'.

    Generated router code uses ``p = payload``, so all mutations and
    condition tests must reference ``p``.  This transformer
    rewrites the AST *before* unparsing so downstream code stays simple.
    """

    def __init__(self, old_name: str) -> None:
        self.old_name = old_name

    def visit_Name(self, node: ast.Name) -> ast.Name:  # noqa: N802
        if node.id == self.old_name:
            node.id = "p"
        return node


class FlowParser:
    def __init__(self, source_code: str, filename: str, module_path: str = ""):
        self.source_code = source_code
        self.filename = filename
        self.module_path = module_path
        self.flow_name: str | None = None
        self.is_async: bool = False  # Whether flow function is async def
        self.instances: dict[str, str] = {}  # Map instance variable to class name
        self.class_methods: set[str] = set()  # Track class method handlers
        self._loop_depth: int = 0  # Track nesting depth for break/continue validation
        self._try_depth: int = 0  # Track nesting depth for nested try rejection
        self._except_depth: int = 0  # Track nesting depth for raise validation

    def parse(self) -> tuple[str, list[IROperation]]:
        try:
            tree = ast.parse(self.source_code, filename=self.filename)
        except SyntaxError as e:
            raise FlowCompileError(f"Syntax error in {self.filename}:{e.lineno}: {e.msg}") from e

        flow_func = self._find_flow_function(tree)
        if not flow_func:
            raise FlowCompileError("No flow function found (signature: def name(p: dict) -> dict)")

        self.flow_name = flow_func.name
        self.is_async = isinstance(flow_func, ast.AsyncFunctionDef)

        # Normalize parameter name to "p" so generated code is consistent
        param_name = flow_func.args.args[0].arg
        if param_name != "p":
            normalizer = _ParamNormalizer(param_name)
            for i, stmt in enumerate(flow_func.body):
                flow_func.body[i] = normalizer.visit(stmt)
            ast.fix_missing_locations(flow_func)

        operations = self._parse_body(flow_func.body)
        return self.flow_name, operations

    def get_class_methods(self) -> set[str]:
        """Return set of handler names that are class methods."""
        return self.class_methods.copy()

    def _find_flow_function(self, tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for node in tree.body:
            if isinstance(node, _FUNC_DEF_TYPES) and self._is_flow_function(node):
                return node
        return None

    def _is_flow_function(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        if len(func.args.args) != 1:
            return False
        arg = func.args.args[0]
        if arg.arg not in VALID_PARAM_NAMES:
            return False
        return bool(func.returns)

    def _parse_body(self, stmts: list[ast.stmt]) -> list[IROperation]:
        operations = []
        for stmt in stmts:
            ops = self._parse_statement(stmt)
            operations.extend(ops)
        return operations

    def _parse_statement(self, stmt: ast.stmt) -> list[IROperation]:
        if isinstance(stmt, ast.Assign):
            return self._parse_assign(stmt)
        elif isinstance(stmt, ast.AugAssign):
            return self._parse_augassign(stmt)
        elif isinstance(stmt, ast.If):
            return self._parse_if(stmt)
        elif isinstance(stmt, ast.While):
            return self._parse_while(stmt)
        elif isinstance(stmt, ast.Try):
            return self._parse_try(stmt)
        elif isinstance(stmt, ast.For):
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: 'for' loops are not supported. Use 'while' loops instead"
            )
        elif isinstance(stmt, ast.Return):
            return [Return(lineno=stmt.lineno)]
        elif isinstance(stmt, ast.Pass):
            return []
        elif isinstance(stmt, ast.Break):
            if self._loop_depth == 0:
                raise FlowCompileError(f"{self.filename}:{stmt.lineno}: 'break' outside loop")
            return [Break(lineno=stmt.lineno)]
        elif isinstance(stmt, ast.Continue):
            if self._loop_depth == 0:
                raise FlowCompileError(f"{self.filename}:{stmt.lineno}: 'continue' outside loop")
            return [Continue(lineno=stmt.lineno)]
        elif isinstance(stmt, ast.Raise):
            return self._parse_raise(stmt)
        elif isinstance(stmt, ast.Expr):
            return self._parse_expr(stmt)
        else:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported statement type: {type(stmt).__name__}")

    def _parse_assign(self, stmt: ast.Assign) -> list[IROperation]:
        if len(stmt.targets) != 1:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Multiple assignment targets not supported")

        target = stmt.targets[0]

        if isinstance(target, ast.Name) and target.id in ("p", "payload"):
            # Assignment to p: must be actor call (possibly wrapped in await)
            value = stmt.value
            if isinstance(value, ast.Await):
                value = value.value
            if isinstance(value, ast.Call):
                return [self._parse_actor_call(stmt)]
            else:
                raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Invalid assignment to 'p'")
        elif isinstance(target, ast.Subscript):
            # Check for fan-out patterns only on payload subscripts (p["key"])
            base: ast.expr = target
            while isinstance(base, ast.Subscript):
                base = base.value
            if isinstance(base, ast.Name) and base.id == "p":
                value = stmt.value
                # Unwrap list() wrapper — list(await asyncio.gather(...)) is equivalent
                # to await asyncio.gather(...) for fan-out detection purposes
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "list"
                    and len(value.args) == 1
                    and not value.keywords
                ):
                    value = value.args[0]
                # Unwrap await for asyncio.gather detection
                if isinstance(value, ast.Await):
                    value = value.value
                if isinstance(value, ast.ListComp):
                    return [self._parse_fanout_comprehension(stmt, target, value)]
                elif isinstance(value, ast.List) and self._list_contains_actor_calls(value):
                    return [self._parse_fanout_literal(stmt, target, value)]
                elif isinstance(value, ast.Call) and self._is_asyncio_gather(value):
                    return [self._parse_fanout_gather(stmt, target, value)]
            # Subscript assignment: payload mutation
            code = ast.unparse(stmt)
            return [Mutation(lineno=stmt.lineno, code=code)]
        elif isinstance(target, ast.Name) and isinstance(stmt.value, ast.Call):
            # Assignment to variable: could be class instantiation or invalid
            call = stmt.value

            # Check if it's a call to a capitalized name (likely a class)
            is_class_call = isinstance(call.func, ast.Name) and call.func.id[0].isupper()

            if call.args or call.keywords:
                # Has arguments
                if is_class_call:
                    # Class instantiation with arguments - validate and reject
                    self._validate_class_instantiation(stmt)
                    return []  # Never reached, but helps mypy
                else:
                    # Function call assigned to variable - not supported
                    raise FlowCompileError(
                        f"{self.filename}:{stmt.lineno}: Unsupported assignment target. "
                        f"Handler results must be assigned to 'p', not '{target.id}'"
                    )
            else:
                # No arguments - valid class instantiation
                # Extract class name from the call
                if isinstance(call.func, ast.Name):
                    class_name = call.func.id
                elif isinstance(call.func, ast.Attribute):
                    class_name = ast.unparse(call.func)
                else:
                    raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported class instantiation")

                self.instances[target.id] = class_name
                return []  # No operation generated - just tracking
        else:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported assignment target")

    def _parse_augassign(self, stmt: ast.AugAssign) -> list[IROperation]:
        code = ast.unparse(stmt)
        return [Mutation(lineno=stmt.lineno, code=code)]

    def _parse_actor_call(self, stmt: ast.Assign) -> ActorCall:
        call = stmt.value
        # Unwrap await: `p = await handler(p)` → extract the Call
        if isinstance(call, ast.Await):
            call = call.value
        if not isinstance(call, ast.Call):
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Expected function call")

        if isinstance(call.func, ast.Name):
            actor_name = call.func.id
        elif isinstance(call.func, ast.Attribute):
            # Check if this is a method call on an instantiated class
            if isinstance(call.func.value, ast.Name) and call.func.value.id in self.instances:
                # Instance method call - use module.ClassName.method format
                instance_var = call.func.value.id
                class_name = self.instances[instance_var]
                method_name = call.func.attr
                # Prefix with module path if available and class is local
                if self.module_path and "." not in class_name:
                    actor_name = f"{self.module_path}.{class_name}.{method_name}"
                else:
                    actor_name = f"{class_name}.{method_name}"
                # Track that this is a class method
                self.class_methods.add(actor_name)
            else:
                # Regular attribute access (module.function)
                actor_name = ast.unparse(call.func)
        else:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported call type")

        if len(call.args) != 1:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Actor call must have exactly one argument (p)")

        return ActorCall(lineno=stmt.lineno, name=actor_name)

    def _parse_if(self, stmt: ast.If) -> list[IROperation]:
        test = ast.unparse(stmt.test)
        true_branch = self._parse_body(stmt.body)
        false_branch = self._parse_body(stmt.orelse) if stmt.orelse else []

        return [Condition(lineno=stmt.lineno, test=test, true_branch=true_branch, false_branch=false_branch)]

    def _parse_while(self, stmt: ast.While) -> list[IROperation]:
        if stmt.orelse:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: 'else' clause on 'while' loops is not supported")

        # Determine loop condition: `while True` → None, otherwise the test expression
        test: str | None = None
        if not (isinstance(stmt.test, ast.Constant) and stmt.test.value is True):
            test = ast.unparse(stmt.test)

        self._loop_depth += 1
        try:
            body = self._parse_body(stmt.body)
        finally:
            self._loop_depth -= 1

        return [WhileLoop(lineno=stmt.lineno, test=test, body=body)]

    def _parse_try(self, stmt: ast.Try) -> list[IROperation]:
        # Reject nested try-except
        if self._try_depth > 0:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Nested try-except is not supported")

        # Reject try-else
        if stmt.orelse:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: 'else' clause on 'try' is not supported")

        # Must have at least one except handler
        if not stmt.handlers:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: 'try' must have at least one 'except' handler")

        # Parse except handlers
        handlers = []
        for handler in stmt.handlers:
            # Reject `except ... as e:` binding
            if handler.name is not None:
                raise FlowCompileError(
                    f"{self.filename}:{handler.lineno}: 'except ... as {handler.name}' binding is not supported"
                )

            # Parse exception types
            error_types: list[str] | None = None
            if handler.type is not None:
                if isinstance(handler.type, ast.Tuple):
                    error_types = []
                    for elt in handler.type.elts:
                        if isinstance(elt, ast.Name):
                            error_types.append(elt.id)
                        else:
                            raise FlowCompileError(
                                f"{self.filename}:{handler.lineno}: Unsupported exception type expression"
                            )
                elif isinstance(handler.type, ast.Name):
                    error_types = [handler.type.id]
                else:
                    raise FlowCompileError(f"{self.filename}:{handler.lineno}: Unsupported exception type expression")

            # Parse handler body within except depth tracking
            self._except_depth += 1
            try:
                handler_body = self._parse_body(handler.body)
            finally:
                self._except_depth -= 1

            handlers.append(ExceptHandler(lineno=handler.lineno, error_types=error_types, body=handler_body))

        # Parse try body and finally body within try depth tracking
        self._try_depth += 1
        try:
            body = self._parse_body(stmt.body)
            finally_body = self._parse_body(stmt.finalbody) if stmt.finalbody else []
        finally:
            self._try_depth -= 1

        return [TryExcept(lineno=stmt.lineno, body=body, handlers=handlers, finally_body=finally_body)]

    def _parse_raise(self, stmt: ast.Raise) -> list[IROperation]:
        if self._except_depth == 0:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: 'raise' outside except handler")
        if stmt.exc is not None:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: 'raise' with arguments is not supported (use bare 'raise' to re-raise)"
            )
        return [Raise(lineno=stmt.lineno)]

    def _parse_expr(self, stmt: ast.Expr) -> list[IROperation]:
        """Handle bare expression statements with descriptive errors."""
        value = stmt.value
        if isinstance(value, ast.Yield | ast.YieldFrom):
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: 'yield' is not supported in flow definitions")
        if isinstance(value, ast.Await):
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: standalone 'await' is not supported; "
                f"assign the result to 'p' (e.g. p = await handler(p))"
            )
        if isinstance(value, ast.Call):
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: standalone function call is not supported; "
                f"assign the result to 'p' (e.g. p = handler(p))"
            )
        raise FlowCompileError(f"{self.filename}:{stmt.lineno}: expression statements are not supported")

    # -- Fan-out parsing helpers --------------------------------------------------

    def _extract_target_key(self, target: ast.Subscript) -> str:
        """Extract a JSON Pointer from a payload subscript chain.

        ``p["results"]``         → ``"/results"``
        ``p["output"]["results"]`` → ``"/output/results"``
        """
        parts: list[str] = []
        node: ast.expr = target
        while isinstance(node, ast.Subscript):
            if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
                raise FlowCompileError(f"{self.filename}:{target.lineno}: Fan-out target key must be a string constant")
            parts.append(node.slice.value)
            node = node.value
        parts.reverse()
        return "/" + "/".join(parts)

    def _extract_fanout_actor_call(self, node: ast.expr) -> tuple[str, str]:
        """Extract (actor_name, payload_expr) from a single call node.

        Unwraps ``await`` if present. Validates that the call has exactly one argument.
        """
        if isinstance(node, ast.Await):
            node = node.value
        if not isinstance(node, ast.Call):
            raise FlowCompileError(
                f"{self.filename}:{node.lineno}: Fan-out element must be an actor call, got {type(node).__name__}"
            )
        call = node
        if isinstance(call.func, ast.Name):
            actor_name = call.func.id
        elif isinstance(call.func, ast.Attribute):
            actor_name = ast.unparse(call.func)
        else:
            raise FlowCompileError(f"{self.filename}:{call.lineno}: Unsupported call type in fan-out")
        if len(call.args) != 1:
            raise FlowCompileError(f"{self.filename}:{call.lineno}: Fan-out actor call must have exactly one argument")
        payload_expr = ast.unparse(call.args[0])
        return (actor_name, payload_expr)

    def _parse_fanout_comprehension(
        self, stmt: ast.Assign, target: ast.Subscript, listcomp: ast.ListComp
    ) -> FanOutCall:
        """Parse ``p["key"] = [actor(x) for x in iterable]``."""
        if len(listcomp.generators) != 1:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Nested comprehensions are not supported in fan-out")
        gen = listcomp.generators[0]
        if gen.ifs:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Filter conditions in fan-out comprehensions are not supported"
            )
        actor_name, payload_expr = self._extract_fanout_actor_call(listcomp.elt)
        iter_var = ast.unparse(gen.target)
        iterable = ast.unparse(gen.iter)
        return FanOutCall(
            lineno=stmt.lineno,
            target_key=self._extract_target_key(target),
            pattern="comprehension",
            actor_calls=[(actor_name, payload_expr)],
            iter_var=iter_var,
            iterable=iterable,
        )

    def _is_actor_call_node(self, node: ast.expr) -> bool:
        """Check if an AST node looks like an actor call.

        Actor calls are bare function calls (``agent(p)``) or method calls
        on class instances (``model.predict(p)``).  Method calls on the
        payload parameter (``p.get("k")``, ``p["k"].upper()``) are NOT
        actor calls — they are payload operations.
        """
        if isinstance(node, ast.Await):
            node = node.value
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):
            return True
        if isinstance(func, ast.Attribute):
            # Walk to the root of the attribute chain to check
            # whether it originates from the payload parameter.
            base: ast.expr = func.value
            while isinstance(base, ast.Subscript | ast.Attribute):
                base = base.value
            return not (isinstance(base, ast.Name) and base.id == "p")
        return False

    def _list_contains_actor_calls(self, lst: ast.List) -> bool:
        """Return True if the list has at least one actor-call element."""
        return any(self._is_actor_call_node(elt) for elt in lst.elts)

    def _parse_fanout_literal(self, stmt: ast.Assign, target: ast.Subscript, lst: ast.List) -> FanOutCall:
        """Parse ``p["key"] = [actor_a(x), actor_b(y), ...]``."""
        actor_calls = [self._extract_fanout_actor_call(elt) for elt in lst.elts]
        return FanOutCall(
            lineno=stmt.lineno,
            target_key=self._extract_target_key(target),
            pattern="literal",
            actor_calls=actor_calls,
        )

    def _is_asyncio_gather(self, call: ast.Call) -> bool:
        """Check if a call node is ``asyncio.gather(...)``."""
        return (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "gather"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "asyncio"
        )

    def _parse_fanout_gather(self, stmt: ast.Assign, target: ast.Subscript, call: ast.Call) -> FanOutCall:
        """Parse ``p["key"] = await asyncio.gather(...)``."""
        target_key = self._extract_target_key(target)
        # Case 1: asyncio.gather(*(actor(x) for x in iterable))
        if (
            len(call.args) == 1
            and isinstance(call.args[0], ast.Starred)
            and isinstance(call.args[0].value, ast.GeneratorExp)
        ):
            genexp = call.args[0].value
            if len(genexp.generators) != 1:
                raise FlowCompileError(
                    f"{self.filename}:{stmt.lineno}: Nested comprehensions are not supported in asyncio.gather fan-out"
                )
            gen = genexp.generators[0]
            if gen.ifs:
                raise FlowCompileError(
                    f"{self.filename}:{stmt.lineno}: Filter conditions in asyncio.gather fan-out are not supported"
                )
            actor_name, payload_expr = self._extract_fanout_actor_call(genexp.elt)
            iter_var = ast.unparse(gen.target)
            iterable = ast.unparse(gen.iter)
            return FanOutCall(
                lineno=stmt.lineno,
                target_key=target_key,
                pattern="gather",
                actor_calls=[(actor_name, payload_expr)],
                iter_var=iter_var,
                iterable=iterable,
            )
        # Case 2: asyncio.gather(actor_a(x), actor_b(y), ...)
        if not call.args:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: asyncio.gather must have at least one argument")
        actor_calls = [self._extract_fanout_actor_call(arg) for arg in call.args]
        return FanOutCall(
            lineno=stmt.lineno,
            target_key=target_key,
            pattern="gather",
            actor_calls=actor_calls,
        )

    def _validate_class_instantiation(self, stmt: ast.Assign) -> None:
        """Validate that class instantiation uses only default arguments."""
        call = stmt.value
        if not isinstance(call, ast.Call):
            return

        # Check that call has no arguments (all must have defaults)
        if call.args:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Class instantiation must use only default arguments. "
                f"Found {len(call.args)} positional arguments."
            )

        # Check for keyword arguments
        if call.keywords:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Class instantiation must use only default arguments. "
                f"Found keyword arguments: {', '.join(kw.arg for kw in call.keywords if kw.arg)}"
            )
