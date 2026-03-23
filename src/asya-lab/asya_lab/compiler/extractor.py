"""Value extractor: pull spec values from AST Call nodes using where: trees.

Given a ``CompilerRule`` with a ``where:`` tree and an ``ast.Call`` node, the
extractor binds call arguments to parameter names and walks the tree to
collect ``{spec_path: value}`` pairs that the compiler writes into the
AsyncActor manifest.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
from typing import Any

from asya_lab.compiler.rules import CompilerRule, ParamSpec, WhereNode


log = logging.getLogger(__name__)


class ValueExtractor:
    """Extract spec values from AST Call nodes guided by compiler rules.

    Args:
        imports: Optional mapping of bare names to fully-qualified names
            (e.g. ``{"stop_after_attempt": "tenacity.stop_after_attempt"}``).
            Used to resolve positional-argument names for bare function calls
            that can't otherwise be introspected.
    """

    def __init__(self, imports: dict[str, str] | None = None) -> None:
        self._imports = imports or {}

    def extract(self, node: ast.expr, rule: CompilerRule) -> dict[str, object]:
        """Main entry point.

        Args:
            node: An ``ast.Call`` (or arbitrary ``ast.expr``).
            rule: Compiler rule whose ``where:`` tree guides extraction.

        Returns:
            Mapping of spec paths to extracted values, e.g.
            ``{"spec.resiliency.timeout": 30}``.
        """
        if not isinstance(node, ast.Call) or not rule.where:
            return {}

        bound = self._bind_args(node)
        result: dict[str, object] = {}
        for child in rule.where:
            self._walk(child, bound, result)
        return result

    # -- argument binding ---------------------------------------------------

    def _bind_args(self, call: ast.Call) -> dict[str, ast.expr]:
        """Bind keyword and positional arguments of *call* to param names.

        Keywords are bound directly.  Positional arguments are resolved via
        ``inspect.signature`` when the function is importable; otherwise
        the positional index (as a string) is used as a fallback key.
        """
        bound: dict[str, ast.expr] = {}

        # Keywords first (always known).
        for kw in call.keywords:
            if kw.arg is not None:
                bound[kw.arg] = kw.value

        # Positional arguments — try to resolve parameter names.
        if call.args:
            func_name = self._resolve_func_name(call.func)
            # Resolve bare names via import map (e.g. stop_after_attempt → tenacity.stop_after_attempt)
            if func_name and "." not in func_name and func_name in self._imports:
                func_name = self._imports[func_name]
            param_names = self._get_param_names(func_name) if func_name else None

            for idx, arg in enumerate(call.args):
                if param_names and idx < len(param_names):
                    bound[param_names[idx]] = arg
                else:
                    bound[str(idx)] = arg

        return bound

    # -- param resolution ---------------------------------------------------

    @staticmethod
    def _resolve_param(
        param: str | int | ParamSpec,
        bound: dict[str, ast.expr],
    ) -> ast.expr | None:
        """Look up a parameter in the bound-args dict.

        Handles three param shapes:
          - ``str``: keyword name lookup (e.g. ``"delay"``)
          - ``int``: positional index lookup (e.g. ``0`` → ``"0"``)
          - ``ParamSpec``: try kwarg first, then positional index fallback
        """
        if isinstance(param, ParamSpec):
            if param.kwarg is not None:
                node = bound.get(param.kwarg)
                if node is not None:
                    return node
            if param.arg is not None:
                return bound.get(str(param.arg))
            return None
        if isinstance(param, int):
            return bound.get(str(param))
        return bound.get(param)

    # -- where-tree walker --------------------------------------------------

    def _walk(
        self,
        node: WhereNode,
        bound: dict[str, ast.expr],
        result: dict[str, object],
        *,
        call_name: str | None = None,
    ) -> None:
        """Recursively walk a ``WhereNode`` tree, populating *result*.

        Args:
            call_name: Resolved function name of the current AST Call context,
                used to discriminate match-only nodes.
        """
        if node.param is not None:
            ast_node = self._resolve_param(node.param, bound)
            if ast_node is None:
                return

            # Terminal node: extract value and store.
            if node.assign_to and not node.where:
                value = self._extract_value(ast_node)
                if value is not None:
                    result[node.assign_to] = value
                return

            # Non-terminal with children: recurse into nested call(s).
            if node.where:
                if isinstance(ast_node, ast.Call):
                    child_bound = self._bind_args(ast_node)
                    child_name = self._resolve_func_name(ast_node.func)
                    for child in node.where:
                        self._walk(child, child_bound, result, call_name=child_name)
                elif isinstance(ast_node, ast.BinOp) and node.flatten_on:
                    calls = self._flatten_binop(ast_node, node.flatten_on)
                    for call in calls:
                        child_bound = self._bind_args(call)
                        child_name = self._resolve_func_name(call.func)
                        for child in node.where:
                            self._walk(child, child_bound, result, call_name=child_name)
            return

        # match-only node (no param): recurse only if function name matches.
        if node.match and node.where:
            if call_name is not None and call_name != node.match:
                return
            for child in node.where:
                self._walk(child, bound, result, call_name=call_name)

    # -- BinOp flattening ---------------------------------------------------

    @staticmethod
    def _flatten_binop(node: ast.expr, operator: str) -> list[ast.Call]:
        """Flatten a BinOp tree into a list of Call nodes.

        Only flattens nodes using the specified operator (e.g. ``"|"`` for
        ``ast.BitOr``).  Unrecognized operators are not traversed.
        """
        op_types: dict[str, type] = {
            "|": ast.BitOr,
            "&": ast.BitAnd,
            "+": ast.Add,
        }
        expected_op = op_types.get(operator)
        result: list[ast.Call] = []

        def _collect(n: ast.expr) -> None:
            if isinstance(n, ast.Call):
                result.append(n)
            elif isinstance(n, ast.BinOp) and expected_op and isinstance(n.op, expected_op):
                _collect(n.left)
                _collect(n.right)

        _collect(node)
        return result

    # -- value extraction ---------------------------------------------------

    @staticmethod
    def _extract_value(node: ast.expr) -> Any:
        """Extract a plain Python value from a simple AST expression.

        Handles constants, names, tuples of names, and unary negation.
        Returns ``None`` for complex expressions that cannot be statically
        evaluated.
        """
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Tuple):
            parts = []
            for elt in node.elts:
                v = ValueExtractor._extract_value(elt)
                if v is None:
                    return None
                parts.append(str(v))
            return ", ".join(parts)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            operand = ValueExtractor._extract_value(node.operand)
            if isinstance(operand, int | float):
                return -operand
        return None

    # -- function resolution ------------------------------------------------

    @staticmethod
    def _resolve_func_name(func: ast.expr) -> str | None:
        """Resolve a dotted function name from an AST function expression.

        Handles ``ast.Name`` (``foo``) and ``ast.Attribute`` chains
        (``asyncio.timeout``, ``a.b.c``).
        """
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts: list[str] = [func.attr]
            node: ast.expr = func.value
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
                return ".".join(reversed(parts))
        return None

    @staticmethod
    def _get_param_names(func_name: str) -> list[str] | None:
        """Import *func_name* and return its parameter names via inspect.

        Returns ``None`` if the function cannot be imported or introspected.
        """
        parts = func_name.rsplit(".", 1)
        if len(parts) == 2:
            module_path, attr_name = parts
        else:
            return None

        try:
            mod = importlib.import_module(module_path)  # nosemgrep: non-literal-import
            func = getattr(mod, attr_name, None)
            if func is None:
                return None
            sig = inspect.signature(func)
            return [
                p.name
                for p in sig.parameters.values()
                if p.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]
        except Exception:
            log.debug("Cannot introspect %s", func_name, exc_info=True)
            return None
