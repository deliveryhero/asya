"""Parse scene DSL from Python AST."""

import ast
from typing import List, Optional, Tuple

from asya_cli.scene.errors import SceneCompileError
from asya_cli.scene.ir import ActorCall, Condition, IROperation, Mutation


class SceneParser:
    def __init__(self, source_code: str, filename: str):
        self.source_code = source_code
        self.filename = filename
        self.scene_name: Optional[str] = None

    def parse(self) -> Tuple[str, List[IROperation]]:
        try:
            tree = ast.parse(self.source_code, filename=self.filename)
        except SyntaxError as e:
            raise SceneCompileError(f"Syntax error in {self.filename}:{e.lineno}: {e.msg}")

        scene_func = self._find_scene_function(tree)
        if not scene_func:
            raise SceneCompileError("No scene function found (signature: def name(p: dict) -> dict)")

        self.scene_name = scene_func.name
        operations = self._parse_body(scene_func.body)
        return self.scene_name, operations

    def _find_scene_function(self, tree: ast.Module) -> Optional[ast.FunctionDef]:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if self._is_scene_function(node):
                    return node
        return None

    def _is_scene_function(self, func: ast.FunctionDef) -> bool:
        if len(func.args.args) != 1:
            return False
        arg = func.args.args[0]
        if arg.arg not in ("p", "payload"):
            return False
        if not func.returns:
            return False
        return True

    def _parse_body(self, stmts: List[ast.stmt]) -> List[IROperation]:
        operations = []
        for stmt in stmts:
            ops = self._parse_statement(stmt)
            operations.extend(ops)
        return operations

    def _parse_statement(self, stmt: ast.stmt) -> List[IROperation]:
        if isinstance(stmt, ast.Assign):
            return self._parse_assign(stmt)
        elif isinstance(stmt, ast.AugAssign):
            return self._parse_augassign(stmt)
        elif isinstance(stmt, ast.If):
            return self._parse_if(stmt)
        elif isinstance(stmt, ast.Return):
            return []
        elif isinstance(stmt, ast.Pass):
            return []
        else:
            raise SceneCompileError(
                f"{self.filename}:{stmt.lineno}: Unsupported statement type: {type(stmt).__name__}"
            )

    def _parse_assign(self, stmt: ast.Assign) -> List[IROperation]:
        if len(stmt.targets) != 1:
            raise SceneCompileError(f"{self.filename}:{stmt.lineno}: Multiple assignment targets not supported")

        target = stmt.targets[0]

        if isinstance(target, ast.Name) and target.id in ("p", "payload"):
            if isinstance(stmt.value, ast.Call):
                return [self._parse_actor_call(stmt)]
            else:
                raise SceneCompileError(f"{self.filename}:{stmt.lineno}: Invalid assignment to 'p'")
        elif isinstance(target, ast.Subscript):
            code = ast.unparse(stmt)
            return [Mutation(lineno=stmt.lineno, code=code)]
        else:
            raise SceneCompileError(f"{self.filename}:{stmt.lineno}: Unsupported assignment target")

    def _parse_augassign(self, stmt: ast.AugAssign) -> List[IROperation]:
        code = ast.unparse(stmt)
        return [Mutation(lineno=stmt.lineno, code=code)]

    def _parse_actor_call(self, stmt: ast.Assign) -> ActorCall:
        call = stmt.value
        if not isinstance(call, ast.Call):
            raise SceneCompileError(f"{self.filename}:{stmt.lineno}: Expected function call")

        if isinstance(call.func, ast.Name):
            actor_name = call.func.id
        elif isinstance(call.func, ast.Attribute):
            actor_name = ast.unparse(call.func)
        else:
            raise SceneCompileError(f"{self.filename}:{stmt.lineno}: Unsupported call type")

        if len(call.args) != 1:
            raise SceneCompileError(f"{self.filename}:{stmt.lineno}: Actor call must have exactly one argument (p)")

        return ActorCall(lineno=stmt.lineno, name=actor_name)

    def _parse_if(self, stmt: ast.If) -> List[IROperation]:
        test = ast.unparse(stmt.test)
        true_branch = self._parse_body(stmt.body)
        false_branch = self._parse_body(stmt.orelse) if stmt.orelse else []

        return [Condition(lineno=stmt.lineno, test=test, true_branch=true_branch, false_branch=false_branch)]
