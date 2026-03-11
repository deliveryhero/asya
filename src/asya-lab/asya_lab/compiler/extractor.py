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

from asya_lab.compiler.rules import CompilerRule, WhereNode


log = logging.getLogger(__name__)


class ValueExtractor:
    """Extract spec values from AST Call nodes guided by compiler rules."""

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
            param_names = self._get_param_names(func_name) if func_name else None

            for idx, arg in enumerate(call.args):
                if param_names and idx < len(param_names):
                    bound[param_names[idx]] = arg
                else:
                    bound[str(idx)] = arg

        return bound

    # -- where-tree walker --------------------------------------------------

    def _walk(
        self,
        node: WhereNode,
        bound: dict[str, ast.expr],
        result: dict[str, object],
    ) -> None:
        """Recursively walk a ``WhereNode`` tree, populating *result*."""
        if node.param:
            ast_node = bound.get(node.param)
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
                    for child in node.where:
                        self._walk(child, child_bound, result)
                elif isinstance(ast_node, ast.BinOp):
                    calls = self._flatten_binop(ast_node)
                    for call in calls:
                        child_bound = self._bind_args(call)
                        for child in node.where:
                            self._walk(child, child_bound, result)
            return

        # match-only node (no param): just recurse children with same bindings.
        if node.match and node.where:
            for child in node.where:
                self._walk(child, bound, result)

    # -- BinOp flattening ---------------------------------------------------

    @staticmethod
    def _flatten_binop(node: ast.expr) -> list[ast.Call]:
        """Flatten ``a | b | c`` BinOp tree into a list of Call nodes."""
        result: list[ast.Call] = []

        def _collect(n: ast.expr) -> None:
            if isinstance(n, ast.Call):
                result.append(n)
            elif isinstance(n, ast.BinOp):
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
