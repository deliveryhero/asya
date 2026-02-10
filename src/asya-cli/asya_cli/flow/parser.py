"""Parse flow DSL from Python AST."""

from __future__ import annotations

import ast

from asya_cli.flow.errors import FlowCompileError
from asya_cli.flow.ir import ActorCall, Break, Condition, Continue, IROperation, Mutation, Return, WhileLoop


class FlowParser:
    def __init__(self, source_code: str, filename: str, module_path: str = ""):
        self.source_code = source_code
        self.filename = filename
        self.module_path = module_path
        self.flow_name: str | None = None
        self.instances: dict[str, str] = {}  # Map instance variable to class name
        self.class_methods: set[str] = set()  # Track class method handlers
        self._loop_depth: int = 0  # Track nesting depth for break/continue validation

    def parse(self) -> tuple[str, list[IROperation]]:
        try:
            tree = ast.parse(self.source_code, filename=self.filename)
        except SyntaxError as e:
            raise FlowCompileError(f"Syntax error in {self.filename}:{e.lineno}: {e.msg}") from e

        flow_func = self._find_flow_function(tree)
        if not flow_func:
            raise FlowCompileError("No flow function found (signature: def name(p: dict) -> dict)")

        self.flow_name = flow_func.name
        operations = self._parse_body(flow_func.body)
        return self.flow_name, operations

    def get_class_methods(self) -> set[str]:
        """Return set of handler names that are class methods."""
        return self.class_methods.copy()

    def _find_flow_function(self, tree: ast.Module) -> ast.FunctionDef | None:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and self._is_flow_function(node):
                return node
        return None

    def _is_flow_function(self, func: ast.FunctionDef) -> bool:
        if len(func.args.args) != 1:
            return False
        arg = func.args.args[0]
        if arg.arg not in ("p", "payload"):
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
        else:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported statement type: {type(stmt).__name__}")

    def _parse_assign(self, stmt: ast.Assign) -> list[IROperation]:
        if len(stmt.targets) != 1:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Multiple assignment targets not supported")

        target = stmt.targets[0]

        if isinstance(target, ast.Name) and target.id in ("p", "payload"):
            # Assignment to p: must be actor call
            if isinstance(stmt.value, ast.Call):
                return [self._parse_actor_call(stmt)]
            else:
                raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Invalid assignment to 'p'")
        elif isinstance(target, ast.Subscript):
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
