"""Parse flow DSL from Python AST."""

import ast

from asya_cli.flow.errors import FlowCompileError
from asya_cli.flow.ir import ActorCall, Condition, IROperation, Mutation, Return


class FlowParser:
    def __init__(self, source_code: str, filename: str):
        self.source_code = source_code
        self.filename = filename
        self.flow_name: str | None = None

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
        elif isinstance(stmt, ast.Return):
            return [Return(lineno=stmt.lineno)]
        elif isinstance(stmt, ast.Pass):
            return []
        else:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported statement type: {type(stmt).__name__}")

    def _parse_assign(self, stmt: ast.Assign) -> list[IROperation]:
        if len(stmt.targets) != 1:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Multiple assignment targets not supported")

        target = stmt.targets[0]

        if isinstance(target, ast.Name) and target.id in ("p", "payload"):
            if isinstance(stmt.value, ast.Call):
                return [self._parse_actor_call(stmt)]
            else:
                raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Invalid assignment to 'p'")
        elif isinstance(target, ast.Subscript):
            code = ast.unparse(stmt)
            return [Mutation(lineno=stmt.lineno, code=code)]
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
