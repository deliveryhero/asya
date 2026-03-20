"""Parse flow DSL from Python AST."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.rules import CompilerRule, CompilerRules


if TYPE_CHECKING:
    from asya_lab.compiler.rules import RuleEngine


# ---------------------------------------------------------------------------
# Operation types (replaces ir.py)
# ---------------------------------------------------------------------------


@dataclass
class ActorCall:
    name: str
    lineno: int
    source_file: str = ""


@dataclass
class Mutation:
    code: str
    lineno: int


@dataclass
class Conditional:
    test: str
    true_branch: list[Operation]
    false_branch: list[Operation]
    lineno: int


@dataclass
class Loop:
    test: str | None  # None = while True
    body: list[Operation]
    lineno: int


@dataclass
class FanOut:
    target_key: str
    pattern: str  # "comprehension" | "literal" | "gather"
    actor_calls: list[tuple[str, str]]  # (actor_name, payload_expr)
    lineno: int
    iter_var: str | None = None
    iterable: str | None = None


@dataclass
class Break:
    lineno: int


@dataclass
class Continue:
    lineno: int


@dataclass
class Return:
    lineno: int


Operation = ActorCall | Mutation | Conditional | Loop | FanOut | Break | Continue | Return


@dataclass
class AsyaDirective:
    """Inline comment override for compiler rules."""

    treat_as: str  # "actor" | "inline"


_DIRECTIVE_PATTERN = re.compile(r"#\s*asya:\s*(\w+)")

_DEFAULT_WRAPPERS = frozenset({"actor", "flow", "inline", "unfold"})

_VALID_DIRECTIVES = frozenset({"actor", "flow", "inline", "unfold", "config"})


@dataclass
class ParseResult:
    flow_name: str
    operations: list[Operation]
    actors: list[str]  # all actor names referenced
    resiliency_rules: list[dict] = field(default_factory=list)
    extracted_configs: list[dict] = field(default_factory=list)
    ignore_decorators: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)
    inline_defs: list[str] = field(default_factory=list)
    is_async: bool = False
    class_methods: set[str] = field(default_factory=set)
    import_map: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Parameter names accepted in flow function signatures.
VALID_PARAM_NAMES = ("p", "payload", "state")

_FUNC_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _strip_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef, decorator_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Return a copy of a function node with the named decorator removed."""
    import copy

    node = copy.deepcopy(node)
    node.decorator_list = [d for d in node.decorator_list if not (isinstance(d, ast.Name) and d.id == decorator_name)]
    return node


class _ParamNormalizer(ast.NodeTransformer):
    """Rename flow parameter references to the canonical name 'p'."""

    def __init__(self, old_name: str) -> None:
        self.old_name = old_name

    def visit_Name(self, node: ast.Name) -> ast.Name:  # noqa: N802
        if node.id == self.old_name:
            node.id = "p"
        return node


class FlowParser:
    def __init__(
        self,
        source_code: str,
        filename: str,
        module_path: str = "",
        rules: CompilerRules | None = None,
        known_wrappers: frozenset[str] | None = None,
        rule_engine: RuleEngine | None = None,
    ):
        self.source_code = source_code
        self.filename = filename
        self.module_path = module_path
        self.rules: CompilerRules = rules if rules is not None else CompilerRules()
        self.flow_name: str | None = None
        self.is_async: bool = False
        self.instances: dict[str, str] = {}
        self.class_methods: set[str] = set()
        self.import_map: dict[str, str] = {}
        self._loop_depth: int = 0
        self.extracted_configs: list[dict] = []
        self.module_constants: list[str] = []
        self._actors: list[str] = []
        self._known_wrappers: frozenset[str] = known_wrappers or _DEFAULT_WRAPPERS
        self._source_lines: list[str] = source_code.splitlines()
        self._directives: dict[int, AsyaDirective] = self._extract_directives()
        self._decorator_index: dict[str, str] = {}
        self._inline_funcs: set[str] = set()
        self._rule_engine: RuleEngine | None = rule_engine

    def parse(self) -> ParseResult:
        try:
            tree = ast.parse(self.source_code, filename=self.filename)
        except SyntaxError as e:
            raise FlowCompileError(f"Syntax error in {self.filename}:{e.lineno}: {e.msg}") from e

        self._collect_imports(tree)
        self._collect_module_constants(tree)
        self._decorator_index = self._build_decorator_index(tree)
        flow_func = self._find_flow_function(tree)
        if not flow_func:
            raise FlowCompileError(
                "No @flow function found. Mark the entry point with @flow:\n"
                "\n"
                "    @flow\n"
                "    def my_flow(p: dict) -> dict:\n"
                "        ..."
            )

        self.flow_name = flow_func.name
        self.is_async = isinstance(flow_func, ast.AsyncFunctionDef)

        param_name = flow_func.args.args[0].arg
        if param_name != "p":
            normalizer = _ParamNormalizer(param_name)
            for i, stmt in enumerate(flow_func.body):
                flow_func.body[i] = normalizer.visit(stmt)
            ast.fix_missing_locations(flow_func)

        operations = self._parse_body(flow_func.body)
        inline_defs = self._collect_inline_defs(tree)

        return ParseResult(
            flow_name=self.flow_name,
            operations=operations,
            actors=list(self._actors),
            extracted_configs=self.extracted_configs,
            imports=list(self.import_map.values()),
            constants=self.module_constants,
            inline_defs=inline_defs,
            is_async=self.is_async,
            class_methods=self.class_methods.copy(),
            import_map=dict(self.import_map),
        )

    # -- Compatibility methods for existing compiler.py --
    def get_class_methods(self) -> set[str]:
        return self.class_methods.copy()

    def get_import_map(self) -> dict[str, str]:
        return dict(self.import_map)

    def get_module_constants(self) -> list[str]:
        return list(self.module_constants)

    def _extract_directives(self) -> dict[int, AsyaDirective]:
        directives: dict[int, AsyaDirective] = {}
        for i, line in enumerate(self._source_lines, 1):
            m = _DIRECTIVE_PATTERN.search(line)
            if m:
                directives[i] = AsyaDirective(treat_as=m.group(1))
        return directives

    def _build_decorator_index(self, tree: ast.Module) -> dict[str, str]:
        """Map function name to treat-as value for same-file definitions."""
        index: dict[str, str] = {}
        for node in tree.body:
            if not isinstance(node, _FUNC_DEF_TYPES):
                continue
            for dec in node.decorator_list:
                dec_name: str | None = None
                if isinstance(dec, ast.Name):
                    dec_name = dec.id
                elif isinstance(dec, ast.Attribute):
                    dec_name = ast.unparse(dec)
                if dec_name in self._known_wrappers:
                    index[node.name] = dec_name
                    break
        return index

    # -- Import/constant collection --

    def _collect_imports(self, tree: ast.Module) -> None:
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    local_name = alias.asname if alias.asname else alias.name
                    self.import_map[local_name] = f"{node.module}.{alias.name}"

    def _collect_module_constants(self, tree: ast.Module) -> None:
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
            ):
                self.module_constants.append(ast.unparse(node))

    def _collect_inline_defs(self, tree: ast.Module) -> list[str]:
        """Collect @inline function definitions to include in generated routers.

        Also collects module-level imports used by inline functions so the
        generated routers.py has all necessary dependencies.
        """
        inline_names = set(self._inline_funcs)

        inline_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in tree.body:
            if isinstance(node, _FUNC_DEF_TYPES) and node.name in inline_names:
                inline_nodes.append(node)

        if not inline_nodes:
            return []

        # Collect names referenced by inline functions
        referenced: set[str] = set()
        for node in inline_nodes:
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    referenced.add(child.id)
                elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                    referenced.add(child.value.id)

        # Collect matching imports from the source module
        defs: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    if local in referenced:
                        defs.append(ast.unparse(node))
                        break
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    local = alias.asname or alias.name
                    if local in referenced:
                        defs.append(ast.unparse(node))
                        break

        # Emit stripped inline function definitions
        for node in inline_nodes:
            stripped = _strip_decorator(node, "inline")
            defs.append(ast.unparse(stripped))

        return defs

    # -- Flow function detection --

    def _find_flow_function(self, tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in tree.body:
            if isinstance(node, _FUNC_DEF_TYPES) and self._has_flow_decorator(node):
                candidates.append(node)

        if len(candidates) > 1:
            locs = ", ".join(f"{c.name}:{c.lineno}" for c in candidates)
            raise FlowCompileError(f"Multiple @flow decorators found ({locs}); exactly one is required")

        if not candidates:
            return None

        func = candidates[0]
        func.decorator_list = [d for d in func.decorator_list if not self._is_flow_decorator(d)]
        self._validate_flow_signature(func)
        return func

    @staticmethod
    def _is_flow_decorator(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id == "flow"

    def _has_flow_decorator(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return any(self._is_flow_decorator(d) for d in func.decorator_list)

    def _validate_flow_signature(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if len(func.args.args) != 1:
            raise FlowCompileError(
                f"{self.filename}:{func.lineno}: @flow function '{func.name}' must have exactly one parameter"
            )
        arg = func.args.args[0]
        if arg.arg not in VALID_PARAM_NAMES:
            raise FlowCompileError(
                f"{self.filename}:{func.lineno}: @flow function '{func.name}' parameter must be "
                f"one of {VALID_PARAM_NAMES}, got '{arg.arg}'"
            )
        if not func.returns:
            raise FlowCompileError(
                f"{self.filename}:{func.lineno}: @flow function '{func.name}' must have a return type annotation"
            )

    # -- Statement parsing --

    def _parse_body(self, stmts: list[ast.stmt]) -> list[Operation]:
        operations: list[Operation] = []
        for stmt in stmts:
            ops = self._parse_statement(stmt)
            operations.extend(ops)
        return operations

    def _parse_statement(self, stmt: ast.stmt) -> list[Operation]:
        if isinstance(stmt, ast.Assign):
            return self._parse_assign(stmt)
        elif isinstance(stmt, ast.AugAssign):
            return self._parse_augassign(stmt)
        elif isinstance(stmt, ast.If):
            return self._parse_if(stmt)
        elif isinstance(stmt, ast.While):
            return self._parse_while(stmt)
        elif isinstance(stmt, ast.Try):
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: try/except is not supported in the simplified compiler. "
                f"Use resiliency rules in .asya/config.yaml instead (see aint 7179)."
            )
        elif isinstance(stmt, ast.With | ast.AsyncWith):
            return self._parse_with(stmt)
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
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: 'raise' is not supported in the simplified compiler. "
                f"Use resiliency rules in .asya/config.yaml instead."
            )
        elif isinstance(stmt, ast.Expr):
            return self._parse_expr(stmt)
        else:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported statement type: {type(stmt).__name__}")

    def _parse_assign(self, stmt: ast.Assign) -> list[Operation]:
        if len(stmt.targets) != 1:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Multiple assignment targets not supported")

        target = stmt.targets[0]

        if isinstance(target, ast.Name) and target.id in ("p", "payload"):
            value = stmt.value
            if isinstance(value, ast.Await):
                value = value.value
            if isinstance(value, ast.Call):
                return [self._parse_actor_call(stmt)]
            else:
                raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Invalid assignment to 'p'")
        elif isinstance(target, ast.Subscript):
            base: ast.expr = target
            while isinstance(base, ast.Subscript):
                base = base.value
            if isinstance(base, ast.Name) and base.id == "p":
                value = stmt.value
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "list"
                    and len(value.args) == 1
                    and not value.keywords
                ):
                    value = value.args[0]
                if isinstance(value, ast.Await):
                    value = value.value
                if isinstance(value, ast.ListComp):
                    return [self._parse_fanout_comprehension(stmt, target, value)]
                elif isinstance(value, ast.List) and self._list_contains_actor_calls(value):
                    return [self._parse_fanout_literal(stmt, target, value)]
                elif isinstance(value, ast.Call) and self._is_asyncio_gather(value):
                    return [self._parse_fanout_gather(stmt, target, value)]
            code = ast.unparse(stmt)
            return [Mutation(lineno=stmt.lineno, code=code)]
        elif isinstance(target, ast.Name) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            is_class_call = isinstance(call.func, ast.Name) and call.func.id[0].isupper()

            if call.args or call.keywords:
                if is_class_call:
                    self._validate_class_instantiation(stmt)
                    return []
                else:
                    raise FlowCompileError(
                        f"{self.filename}:{stmt.lineno}: Unsupported assignment target. "
                        f"Handler results must be assigned to 'p', not '{target.id}'"
                    )
            else:
                if isinstance(call.func, ast.Name):
                    class_name = call.func.id
                elif isinstance(call.func, ast.Attribute):
                    class_name = ast.unparse(call.func)
                else:
                    raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported class instantiation")

                self.instances[target.id] = class_name
                return []
        else:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported assignment target")

    def _parse_augassign(self, stmt: ast.AugAssign) -> list[Operation]:
        code = ast.unparse(stmt)
        return [Mutation(lineno=stmt.lineno, code=code)]

    def _parse_actor_call(self, stmt: ast.Assign) -> ActorCall | Mutation:
        call = stmt.value
        is_await = isinstance(call, ast.Await)
        if is_await:
            assert isinstance(call, ast.Await)
            call = call.value
        if not isinstance(call, ast.Call):
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Expected function call")

        # Handle call-site wrappers: actor(handler)(p), inline(fn)(p)
        if isinstance(call.func, ast.Call):
            return self._parse_wrapper_call(stmt, call, is_await=is_await)

        if isinstance(call.func, ast.Name):
            actor_name = call.func.id
        elif isinstance(call.func, ast.Attribute):
            if isinstance(call.func.value, ast.Name) and call.func.value.id in self.instances:
                instance_var = call.func.value.id
                class_name = self.instances[instance_var]
                method_name = call.func.attr
                if self.module_path and "." not in class_name:
                    actor_name = f"{self.module_path}.{class_name}.{method_name}"
                else:
                    actor_name = f"{class_name}.{method_name}"
                self.class_methods.add(actor_name)
            else:
                actor_name = ast.unparse(call.func)
        else:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported call type")

        if len(call.args) != 1:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Actor call must have exactly one argument (p)")

        # Inline comment directive takes priority
        directive = self._directives.get(stmt.lineno)
        if directive is not None:
            if directive.treat_as not in _VALID_DIRECTIVES:
                raise FlowCompileError(
                    f"{self.filename}:{stmt.lineno}: Unknown directive '{directive.treat_as}'. "
                    f"Supported: {', '.join(sorted(_VALID_DIRECTIVES))}"
                )
            if directive.treat_as == "inline":
                self._inline_funcs.add(actor_name)
                return Mutation(lineno=stmt.lineno, code=ast.unparse(stmt))
            elif directive.treat_as == "actor":
                self._actors.append(actor_name)
                return ActorCall(lineno=stmt.lineno, name=actor_name)
            elif directive.treat_as in ("flow", "unfold", "config"):
                raise FlowCompileError(
                    f"{self.filename}:{stmt.lineno}: Directive '{directive.treat_as}' is not yet implemented"
                )

        # Definition-site decorator (lower priority)
        if actor_name in self._decorator_index and self._decorator_index[actor_name] == "inline":
            self._inline_funcs.add(actor_name)
            return Mutation(lineno=stmt.lineno, code=ast.unparse(stmt))

        # Rule engine classification (lowest priority)
        if self._rule_engine is not None:
            from asya_lab.compiler.rules import TreatAs

            qualified_name = self.import_map.get(actor_name, actor_name)
            treat_as = self._rule_engine.classify(qualified_name, module_path=self.module_path or None)
            if treat_as is not None and treat_as in (TreatAs.INLINE, TreatAs.CONFIG):
                self._inline_funcs.add(actor_name)
                return Mutation(lineno=stmt.lineno, code=ast.unparse(stmt))

        self._actors.append(actor_name)
        return ActorCall(lineno=stmt.lineno, name=actor_name)

    def _parse_wrapper_call(
        self, stmt: ast.Assign, outer_call: ast.Call, *, is_await: bool = False
    ) -> ActorCall | Mutation:
        """Parse call-site wrapper patterns: actor(handler)(p), inline(fn)(p)."""
        inner_call = outer_call.func
        if not isinstance(inner_call, ast.Call):
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported call type")

        # Extract wrapper name
        if not isinstance(inner_call.func, ast.Name):
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Unsupported call type")
        wrapper_name = inner_call.func.id

        if wrapper_name not in self._known_wrappers:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Unknown call-site wrapper '{wrapper_name}'. "
                f"Supported: {', '.join(sorted(self._known_wrappers))}"
            )

        # Extract inner argument (the actual function name)
        if len(inner_call.args) != 1:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Call-site wrapper must have exactly one argument")
        inner_arg = inner_call.args[0]
        if isinstance(inner_arg, ast.Name):
            actor_name = inner_arg.id
        elif isinstance(inner_arg, ast.Attribute):
            actor_name = ast.unparse(inner_arg)
        else:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Call-site wrapper argument must be a name or attribute"
            )

        # Inline comment directive overrides call-site wrapper
        directive = self._directives.get(stmt.lineno)
        if directive is not None and directive.treat_as == "inline":
            return Mutation(lineno=stmt.lineno, code=ast.unparse(stmt))

        # Determine wrapper type from name suffix
        if wrapper_name.endswith("inline"):
            # Unwrap: inline(fn)(p) → fn(p). The wrapper is a no-op identity.
            call_node: ast.expr = ast.Call(func=inner_arg, args=outer_call.args, keywords=outer_call.keywords)
            if is_await:
                call_node = ast.Await(value=call_node)
            unwrapped = ast.unparse(ast.Assign(targets=stmt.targets, value=call_node, lineno=stmt.lineno))
            self._inline_funcs.add(actor_name)
            return Mutation(lineno=stmt.lineno, code=unwrapped)
        elif wrapper_name.endswith("flow") or wrapper_name.endswith("unfold"):
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: Wrapper '{wrapper_name}' is not yet implemented")

        # Default: actor wrapper
        self._actors.append(actor_name)
        return ActorCall(lineno=stmt.lineno, name=actor_name)

    def _parse_if(self, stmt: ast.If) -> list[Operation]:
        test = ast.unparse(stmt.test)
        true_branch = self._parse_body(stmt.body)
        false_branch = self._parse_body(stmt.orelse) if stmt.orelse else []
        return [Conditional(lineno=stmt.lineno, test=test, true_branch=true_branch, false_branch=false_branch)]

    def _parse_while(self, stmt: ast.While) -> list[Operation]:
        if stmt.orelse:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: 'else' clause on 'while' loops is not supported")

        test: str | None = None
        if not (isinstance(stmt.test, ast.Constant) and stmt.test.value is True):
            test = ast.unparse(stmt.test)

        self._loop_depth += 1
        try:
            body = self._parse_body(stmt.body)
        finally:
            self._loop_depth -= 1

        return [Loop(lineno=stmt.lineno, test=test, body=body)]

    def _parse_with(self, stmt: ast.With | ast.AsyncWith) -> list[Operation]:
        symbols: list[str] = []
        for item in stmt.items:
            symbols.append(self._resolve_ctx_symbol(item.context_expr))

        rules = [self.rules.lookup(sym) for sym in symbols]

        for sym, rule in zip(symbols, rules, strict=True):
            if rule is None:
                raise FlowCompileError(
                    f"{self.filename}:{stmt.lineno}: Unsupported context manager: {sym!r}. "
                    f"No compiler rule found. Add a rule for this symbol in .asya/config.yaml."
                )

        treat_as_values = {r.treat_as for r in rules}  # type: ignore[union-attr]
        if len(treat_as_values) > 1:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: mixed treat-as values in a single 'with' statement "
                f"are not supported: {sorted(treat_as_values)}. "
                f"Use separate 'with' statements for context managers with different treat-as."
            )

        treat_as = next(iter(treat_as_values))

        if treat_as == "config":
            for sym, item, rule in zip(symbols, stmt.items, rules, strict=True):
                if rule is None:
                    raise FlowCompileError(f"{self.filename}:{stmt.lineno}: internal error: rule for {sym!r} is None")
                extracted_args = self._extract_ctx_args(item.context_expr, rule)
                self.extracted_configs.append({"symbol": sym, "args": extracted_args})
            return self._parse_body(stmt.body)

        elif treat_as == "inline":
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Inline context managers are not supported in the simplified compiler. "
                f"Restructure to use treat_as='config' rules or extract the context manager to the handler."
            )

        else:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Unknown treat-as value {treat_as!r} for context manager"
            )

    def _resolve_ctx_symbol(self, ctx_expr: ast.expr) -> str:
        if isinstance(ctx_expr, ast.Call):
            return ast.unparse(ctx_expr.func)
        return ast.unparse(ctx_expr)

    def _extract_ctx_args(self, ctx_expr: ast.expr, rule: CompilerRule) -> dict[str, str]:
        if not isinstance(ctx_expr, ast.Call) or not rule.extract:
            return {}

        call = ctx_expr
        extracted: dict[str, str] = {}
        param_names = list(rule.extract.keys())

        for i, arg in enumerate(call.args):
            if i < len(param_names):
                param = param_names[i]
                extracted[param] = ast.unparse(arg)

        for kw in call.keywords:
            if kw.arg and kw.arg in rule.extract:
                extracted[kw.arg] = ast.unparse(kw.value)

        return extracted

    def _parse_expr(self, stmt: ast.Expr) -> list[Operation]:
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

    # -- Fan-out parsing helpers --

    def _extract_target_key(self, target: ast.Subscript) -> str:
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
        self._actors.append(actor_name)
        return (actor_name, payload_expr)

    def _parse_fanout_comprehension(self, stmt: ast.Assign, target: ast.Subscript, listcomp: ast.ListComp) -> FanOut:
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
        return FanOut(
            lineno=stmt.lineno,
            target_key=self._extract_target_key(target),
            pattern="comprehension",
            actor_calls=[(actor_name, payload_expr)],
            iter_var=iter_var,
            iterable=iterable,
        )

    def _is_actor_call_node(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Await):
            node = node.value
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):
            return True
        if isinstance(func, ast.Attribute):
            base: ast.expr = func.value
            while isinstance(base, ast.Subscript | ast.Attribute):
                base = base.value
            return not (isinstance(base, ast.Name) and base.id == "p")
        return False

    def _list_contains_actor_calls(self, lst: ast.List) -> bool:
        return any(self._is_actor_call_node(elt) for elt in lst.elts)

    def _parse_fanout_literal(self, stmt: ast.Assign, target: ast.Subscript, lst: ast.List) -> FanOut:
        actor_calls = [self._extract_fanout_actor_call(elt) for elt in lst.elts]
        return FanOut(
            lineno=stmt.lineno,
            target_key=self._extract_target_key(target),
            pattern="literal",
            actor_calls=actor_calls,
        )

    def _is_asyncio_gather(self, call: ast.Call) -> bool:
        return (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "gather"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "asyncio"
        )

    def _parse_fanout_gather(self, stmt: ast.Assign, target: ast.Subscript, call: ast.Call) -> FanOut:
        target_key = self._extract_target_key(target)
        if (
            len(call.args) == 1
            and isinstance(call.args[0], ast.Starred)
            and isinstance(call.args[0].value, ast.GeneratorExp | ast.ListComp)
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
            return FanOut(
                lineno=stmt.lineno,
                target_key=target_key,
                pattern="gather",
                actor_calls=[(actor_name, payload_expr)],
                iter_var=iter_var,
                iterable=iterable,
            )
        if not call.args:
            raise FlowCompileError(f"{self.filename}:{stmt.lineno}: asyncio.gather must have at least one argument")
        actor_calls = [self._extract_fanout_actor_call(arg) for arg in call.args]
        return FanOut(
            lineno=stmt.lineno,
            target_key=target_key,
            pattern="gather",
            actor_calls=actor_calls,
        )

    def _validate_class_instantiation(self, stmt: ast.Assign) -> None:
        call = stmt.value
        if not isinstance(call, ast.Call):
            return

        if call.args:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Class instantiation must use only default arguments. "
                f"Found {len(call.args)} positional arguments."
            )

        if call.keywords:
            raise FlowCompileError(
                f"{self.filename}:{stmt.lineno}: Class instantiation must use only default arguments. "
                f"Found keyword arguments: {', '.join(kw.arg for kw in call.keywords if kw.arg)}"
            )
