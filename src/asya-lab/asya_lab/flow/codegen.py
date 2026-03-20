"""Generate Python code for routers directly from parsed operations.

Replaces the old grouper.py + codegen.py two-stage pipeline with a single
module that walks the operation list and emits router functions directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from asya_lab.flow.parser import (
    ActorCall,
    Break,
    Conditional,
    Continue,
    FanOut,
    Loop,
    Mutation,
    Operation,
    ParseResult,
    Return,
)


ROUTER_PREFIXES = ("start_", "router_", "fanin_")


@dataclass
class _LoopCtx:
    """Context passed through recursion for break/continue resolution."""

    loop_name: str
    exit_chain: list[str]


@dataclass
class _RouterFunc:
    """A generated router function."""

    name: str
    code: str
    # For seq routers only — enables merging into start_
    seq_mutations: list[Mutation] | None = None
    seq_chain: list[str] | None = None


@dataclass
class CodegenMeta:
    """Metadata about generated code, used by manifest templater."""

    router_names: list[str]
    all_handler_names: set[str]
    router_refs: dict[str, list[str]]  # router_name -> list of referenced actor names
    single_actor: str | None  # set for single-actor flows


class CodeGenerator:
    def __init__(
        self,
        result: ParseResult,
        source_file: str,
        output_file: str | None = None,
    ):
        self.flow_name = result.flow_name
        self.result = result
        self.module_constants = result.constants
        self.inline_defs = result.inline_defs

        if output_file:
            try:
                output_path = Path(output_file).resolve()
                source_path = Path(source_file).resolve()
                relative_path = os.path.relpath(source_path, output_path.parent)
                self.source_file = relative_path
            except (ValueError, OSError):
                self.source_file = os.path.basename(source_file)
        else:
            self.source_file = os.path.basename(source_file)

        self._functions: list[_RouterFunc] = []
        self._has_fan_out = False
        self._all_handlers: set[str] = set()
        self._router_counter = 0

    def generate(self) -> str:
        if self._is_single_actor_flow():
            return self._generate_single_actor_flow()

        entry_chain = self._process_ops(self.result.operations)

        parts = []
        parts.append(self._generate_header())
        if self._has_fan_out:
            parts.append("import copy\n")
        if self.module_constants:
            parts.append("\n".join(self.module_constants) + "\n")
        if self.inline_defs:
            parts.append("\n\n".join(self.inline_defs) + "\n")

        parts.append(self._generate_routers_section(entry_chain))
        parts.append(self._generate_resolve_function())

        return "\n".join(parts)

    def get_meta(self) -> CodegenMeta:
        """Return metadata about the generated code."""
        if self._is_single_actor_flow():
            actor = next(op for op in self.result.operations if isinstance(op, ActorCall))
            return CodegenMeta(
                router_names=[],
                all_handler_names=set(),
                router_refs={},
                single_actor=actor.name,
            )

        start_name = f"start_{self.flow_name}"
        router_names = [start_name]
        for rf in self._functions:
            router_names.append(rf.name)

        all_handlers = set(self._all_handlers)
        # Conservative: each router gets refs to ALL handlers.
        # The resolve() function uses env-var lookup at runtime, so
        # each router pod needs all handler mappings available.
        router_refs = {rname: sorted(all_handlers) for rname in router_names}

        return CodegenMeta(
            router_names=router_names,
            all_handler_names=all_handlers,
            router_refs=router_refs,
            single_actor=None,
        )

    # -- Single-actor optimization --

    def _is_single_actor_flow(self) -> bool:
        ops = self.result.operations
        actor_calls = [op for op in ops if isinstance(op, ActorCall)]
        non_actor = [op for op in ops if not isinstance(op, ActorCall | Return)]
        return len(actor_calls) == 1 and len(non_actor) == 0

    def _generate_single_actor_flow(self) -> str:
        actor = next(op for op in self.result.operations if isinstance(op, ActorCall))
        parts = []
        parts.append(self._generate_header())
        parts.append(
            dedent(
                f"""\

            # ======================================================================
            # Single-Actor Flow: no router needed
            # The actor below IS the entrypoint; label it in your AsyncActor spec:
            #   asya.sh/flow: {self.flow_name}
            #   asya.sh/flow-role: entry
            # ======================================================================

            FLOW_METADATA = {{
                "flow_name": "{self.flow_name}",
                "type": "single-actor",
                "actor": {actor.name!r},
                "labels": {{
                    "asya.sh/flow": "{self.flow_name}",
                    "asya.sh/flow-role": "entry",
                }},
            }}
            """
            )
        )
        return "\n".join(parts)

    # -- Core operation processing --

    def _process_ops(
        self,
        ops: list[Operation],
        loop_ctx: _LoopCtx | None = None,
        continuation: list[str] | None = None,
    ) -> list[str]:
        """Walk operations and return the entry chain (names to prepend).

        Args:
            ops: Operations to process.
            loop_ctx: Enclosing loop context (for break/continue).
            continuation: Actors that execute after all ops complete. Used by
                Loop to compute exit_chain for break, and propagated through
                Conditional branches so nested Loops can access it.

        Side effect: generates router functions appended to self._functions.
        """
        cont = continuation or []

        if not ops:
            return []

        # Collect leading mutations
        mutations: list[Mutation] = []
        i = 0
        while i < len(ops) and isinstance(ops[i], Mutation):
            mutations.append(ops[i])  # type: ignore[arg-type]
            i += 1

        if i >= len(ops):
            # Only mutations remain: need a seq router
            name = self._router_name("seq", mutations[0].lineno)
            self._emit_seq_router(name, mutations, [])
            return [name]

        op = ops[i]
        rest = ops[i + 1 :]

        if isinstance(op, ActorCall):
            rest_chain = self._process_ops(rest, loop_ctx, continuation)
            chain = [op.name, *rest_chain]
            self._all_handlers.add(op.name)
            if mutations:
                name = self._router_name("seq", mutations[0].lineno)
                self._emit_seq_router(name, mutations, chain)
                return [name]
            return chain

        elif isinstance(op, Conditional):
            rest_chain = self._process_ops(rest, loop_ctx, continuation)

            true_terminal = self._is_terminal(op.true_branch)
            false_terminal = self._is_terminal(op.false_branch)

            # Pass full continuation to branches so nested Loops know the exit path
            branch_cont = rest_chain + cont
            true_inner = self._process_ops(op.true_branch, loop_ctx, branch_cont)
            false_inner = self._process_ops(op.false_branch, loop_ctx, branch_cont)

            true_chain = true_inner if true_terminal else true_inner + rest_chain
            false_chain = false_inner if false_terminal else false_inner + rest_chain

            true_exit = self._is_exit_terminal(op.true_branch, loop_ctx)
            false_exit = self._is_exit_terminal(op.false_branch, loop_ctx)

            name = self._router_name("if", op.lineno)
            self._emit_conditional_router(
                name,
                op.test,
                mutations,
                true_chain,
                false_chain,
                true_exit=true_exit,
                false_exit=false_exit,
            )
            return [name]

        elif isinstance(op, Loop):
            rest_chain = self._process_ops(rest, loop_ctx, continuation)
            exit_chain = rest_chain + cont
            loop_name = self._router_name("while", op.lineno)
            lctx = _LoopCtx(loop_name=loop_name, exit_chain=exit_chain)
            body_chain = self._process_ops(op.body, lctx)

            # Mutations before a loop run once (in seq router), NOT on every iteration
            self._emit_loop_router(loop_name, op.test, [], body_chain, exit_chain)

            if mutations:
                seq_name = self._router_name("seq", mutations[0].lineno)
                self._emit_seq_router(seq_name, mutations, [loop_name])
                return [seq_name]
            return [loop_name]

        elif isinstance(op, FanOut):
            self._has_fan_out = True
            rest_chain = self._process_ops(rest, loop_ctx, continuation)
            name = self._router_name("fanout", op.lineno)
            self._emit_fanout_router(name, op, rest_chain)
            if mutations:
                seq_name = self._router_name("seq", mutations[0].lineno)
                self._emit_seq_router(seq_name, mutations, [name])
                return [seq_name]
            return [name]

        elif isinstance(op, Break):
            if not loop_ctx:
                raise RuntimeError("Break outside loop context")
            if mutations:
                name = self._router_name("seq", mutations[0].lineno)
                self._emit_exit_seq_router(name, mutations, loop_ctx.exit_chain)
                return [name]
            return loop_ctx.exit_chain

        elif isinstance(op, Continue):
            if not loop_ctx:
                raise RuntimeError("Continue outside loop context")
            if mutations:
                name = self._router_name("seq", mutations[0].lineno)
                self._emit_seq_router(name, mutations, [loop_ctx.loop_name])
                return [name]
            return [loop_ctx.loop_name]

        elif isinstance(op, Return):
            if mutations:
                name = self._router_name("seq", mutations[0].lineno)
                self._emit_exit_seq_router(name, mutations, [])
                return [name]
            return []

        else:
            raise FlowCompileError(f"Unknown operation type: {type(op).__name__}")

    # -- Terminal detection --

    def _is_terminal(self, ops: list[Operation]) -> bool:
        """True if the last operation in this branch is Break, Continue, or Return."""
        if not ops:
            return False
        last = ops[-1]
        if isinstance(last, Break | Continue | Return):
            return True
        if isinstance(last, Conditional):
            return self._is_terminal(last.true_branch) and self._is_terminal(last.false_branch)
        return False

    def _is_exit_terminal(self, ops: list[Operation], loop_ctx: _LoopCtx | None) -> bool:
        """True if the branch should use SET (overwrite) instead of prepend."""
        if not ops:
            return False
        last = ops[-1]
        if isinstance(last, Break | Return):
            return True
        if isinstance(last, Conditional):
            return self._is_exit_terminal(last.true_branch, loop_ctx) and self._is_exit_terminal(
                last.false_branch, loop_ctx
            )
        return False

    # -- Router name generation --

    def _router_name(self, kind: str, lineno: int) -> str:
        self._router_counter += 1
        return f"router_{self.flow_name}_line_{lineno}_{kind}_{self._router_counter}"

    # -- Router function generation --

    def _emit_seq_router(self, name: str, mutations: list[Mutation], chain: list[str]) -> None:
        rf = self._build_seq_router(name, mutations, chain)
        self._functions.append(rf)

    def _build_seq_router(self, name: str, mutations: list[Mutation], chain: list[str]) -> _RouterFunc:
        lines = []
        lines.append(f"async def {name}(payload: dict):")
        lines.append('    """Router for control flow and payload mutations"""')
        lines.append("    p = payload")
        lines.append("    _next = []")

        for m in mutations:
            lines.append(f"    {m.code}")

        for actor in chain:
            self._all_handlers.add(actor)
            lines.append(f'    _next.append(resolve("{actor}"))')

        lines.append("")
        lines.append('    yield "SET", ".route.next[:0]", _next')
        lines.append("    yield payload")
        lines.append("")

        return _RouterFunc(name=name, code="\n".join(lines), seq_mutations=mutations, seq_chain=chain)

    def _emit_exit_seq_router(self, name: str, mutations: list[Mutation], chain: list[str]) -> None:
        """Seq router that uses SET (overwrite) for exit paths (break/return)."""
        lines = []
        lines.append(f"async def {name}(payload: dict):")
        lines.append('    """Router for control flow and payload mutations"""')
        lines.append("    p = payload")

        for m in mutations:
            lines.append(f"    {m.code}")

        if chain:
            resolved = ", ".join(f'resolve("{a}")' for a in chain)
            self._all_handlers.update(chain)
            lines.append(f'    yield "SET", ".route.next", [{resolved}]')

        lines.append("    yield p")
        lines.append("")

        self._functions.append(_RouterFunc(name=name, code="\n".join(lines)))

    def _emit_conditional_router(
        self,
        name: str,
        test: str,
        mutations: list[Mutation],
        true_chain: list[str],
        false_chain: list[str],
        true_exit: bool = False,
        false_exit: bool = False,
    ) -> None:
        lines = []
        lines.append(f"async def {name}(payload: dict):")
        lines.append('    """Router for control flow and payload mutations"""')
        lines.append("    p = payload")
        lines.append("    _next = []")

        for m in mutations:
            lines.append(f"    {m.code}")

        lines.append(f"    if {test}:")
        self._emit_branch_body(true_chain, true_exit, "        ", lines)

        lines.append("    else:")
        self._emit_branch_body(false_chain, false_exit, "        ", lines)

        lines.append("")
        lines.append('    yield "SET", ".route.next[:0]", _next')
        lines.append("    yield payload")
        lines.append("")

        self._functions.append(_RouterFunc(name=name, code="\n".join(lines)))

    def _emit_branch_body(
        self,
        chain: list[str],
        is_exit: bool,
        indent: str,
        lines: list[str],
    ) -> None:
        if is_exit:
            if chain:
                resolved = ", ".join(f'resolve("{a}")' for a in chain)
                self._all_handlers.update(chain)
                lines.append(f'{indent}yield "SET", ".route.next", [{resolved}]')
            lines.append(f"{indent}yield p")
            lines.append(f"{indent}return")
        elif chain:
            for actor in chain:
                self._all_handlers.add(actor)
                lines.append(f'{indent}_next.append(resolve("{actor}"))')
        else:
            lines.append(f"{indent}pass")

    def _emit_loop_router(
        self,
        name: str,
        test: str | None,
        mutations: list[Mutation],
        body_chain: list[str],
        exit_chain: list[str],
    ) -> None:
        lines = []
        lines.append(f"async def {name}(payload: dict):")
        lines.append('    """Router for control flow and payload mutations"""')
        lines.append("    p = payload")
        lines.append("    _next = []")

        for m in mutations:
            lines.append(f"    {m.code}")

        if test is not None:
            lines.append(f"    if {test}:")
            for actor in body_chain:
                self._all_handlers.add(actor)
                lines.append(f'        _next.append(resolve("{actor}"))')
            self._all_handlers.add(name)
            lines.append(f'        _next.append(resolve("{name}"))')

            lines.append("    else:")
            if exit_chain:
                resolved = ", ".join(f'resolve("{a}")' for a in exit_chain)
                self._all_handlers.update(exit_chain)
                lines.append(f'        yield "SET", ".route.next", [{resolved}]')
            lines.append("        yield p")
            lines.append("        return")
        else:
            # while True: always enter body
            for actor in body_chain:
                self._all_handlers.add(actor)
                lines.append(f'    _next.append(resolve("{actor}"))')
            self._all_handlers.add(name)
            lines.append(f'    _next.append(resolve("{name}"))')

        lines.append("")
        lines.append('    yield "SET", ".route.next[:0]", _next')
        lines.append("    yield payload")
        lines.append("")

        self._functions.append(_RouterFunc(name=name, code="\n".join(lines)))

    def _emit_fanout_router(self, name: str, fan_out: FanOut, rest_chain: list[str]) -> None:
        # Aggregator name
        agg_name = f"fanin_{self.flow_name}_line_{fan_out.lineno}"
        self._all_handlers.add(agg_name)
        for actor_name, _ in fan_out.actor_calls:
            self._all_handlers.add(actor_name)

        lines = []
        lines.append(f"async def {name}(payload: dict):")
        lines.append(f'    """Fan-out router: dispatches to sub-agents and aggregator (line {fan_out.lineno})"""')
        lines.append("    p = payload")
        lines.append("")
        lines.append('    origin_id = yield "GET", ".id"')
        lines.append('    _next_tail = yield "GET", ".route.next"')
        lines.append("")
        lines.append(f'    _agg = resolve("{agg_name}")')
        lines.append("")
        lines.append("    _slices = []")

        if fan_out.pattern == "comprehension" or (fan_out.pattern == "gather" and fan_out.iter_var is not None):
            iter_var = fan_out.iter_var
            iterable = fan_out.iterable
            actor_name, payload_expr = fan_out.actor_calls[0]
            lines.append(f"    for {iter_var} in {iterable}:")
            lines.append(f'        _slices.append((resolve("{actor_name}"), {payload_expr}))')
        else:
            for actor_name, payload_expr in fan_out.actor_calls:
                lines.append(f'    _slices.append((resolve("{actor_name}"), {payload_expr}))')

        lines.append("")
        lines.append("    _n = len(_slices) + 1")
        lines.append("    _fan_in = {")
        lines.append('        "actor": _agg,')
        lines.append('        "origin_id": origin_id,')
        lines.append('        "slice_count": _n,')
        lines.append(f'        "aggregation_key": "{fan_out.target_key}",')
        lines.append("    }")
        lines.append("")

        # Index 0: parent payload to aggregator
        after_agg = rest_chain
        if after_agg:
            after_items = ", ".join(["_agg", *[f'resolve("{a}")' for a in after_agg]])
            self._all_handlers.update(after_agg)
        else:
            after_items = "_agg"
        lines.append("    # Index 0: parent payload forwarded to aggregator")
        lines.append(f'    yield "SET", ".route.next", [{after_items}] + _next_tail')
        lines.append('    yield "SET", ".headers.x-asya-fan-in", {**_fan_in, "slice_index": 0}')
        lines.append("    yield copy.deepcopy(p)")
        lines.append("")

        # Indices 1..N: sub-agent slices
        lines.append("    for _i, (_actor, _payload) in enumerate(_slices):")
        lines.append('        yield "SET", ".route.next", [_actor, _agg]')
        lines.append('        yield "SET", ".headers.x-asya-fan-in", {**_fan_in, "slice_index": _i + 1}')
        lines.append("        yield _payload")
        lines.append("")

        self._functions.append(_RouterFunc(name=name, code="\n".join(lines)))

    # -- Assembly --

    def _generate_routers_section(self, entry_chain: list[str]) -> str:
        lines = []
        lines.append("\n# " + "=" * 70)
        lines.append("# Generated Routers (for kubernetes deployment)")
        lines.append("# " + "=" * 70)
        lines.append("")

        # Try to merge start_ with the first seq router if it's the only entry
        merged_seq = None
        if len(entry_chain) == 1:
            for rf in self._functions:
                if rf.name == entry_chain[0] and rf.seq_mutations is not None:
                    merged_seq = rf
                    break

        if merged_seq:
            lines.append(self._generate_start_router(merged_seq.seq_chain or [], merged_seq.seq_mutations))
            for rf in self._functions:
                if rf is not merged_seq:
                    lines.append(rf.code)
        else:
            lines.append(self._generate_start_router(entry_chain))
            for rf in self._functions:
                lines.append(rf.code)

        return "\n".join(lines)

    def _generate_start_router(self, entry_chain: list[str], mutations: list[Mutation] | None = None) -> str:
        name = f"start_{self.flow_name}"
        lines = []
        lines.append(f"async def {name}(payload: dict):")
        lines.append(f'    """Entrypoint for flow \'{self.flow_name}\'"""')

        if mutations:
            lines.append("    p = payload")
        lines.append("    _next = []")

        if mutations:
            for m in mutations:
                lines.append(f"    {m.code}")

        for actor in entry_chain:
            self._all_handlers.add(actor)
            lines.append(f'    _next.append(resolve("{actor}"))')

        lines.append('    yield "SET", ".route.next[:0]", _next')
        lines.append("    yield payload")
        lines.append("")

        return "\n".join(lines)

    def _generate_header(self) -> str:
        return dedent(
            f'''\
            # fmt: off
            # ruff: noqa
            """
            Auto-generated by asya flow compiler
            Source: {self.source_file}

            DO NOT EDIT THIS FILE MANUALLY
            Regenerate by running: asya flow compile {self.source_file}
            """
            '''
        )

    def _generate_resolve_function(self) -> str:
        return dedent(
            '''
            # ======================================================================
            # Handler Resolution
            # ======================================================================

            import os
            import logging

            _HANDLER_TO_ACTOR: dict[str, str] = {}
            _SUFFIX_TO_HANDLERS: dict[str, list[str]] = {}

            for _env_var, _handler_name in os.environ.items():
                if _env_var.startswith('ASYA_HANDLER_'):
                    _actor_name = _env_var[len('ASYA_HANDLER_'):].lower().replace('_', '-')
                    _HANDLER_TO_ACTOR[_handler_name] = _actor_name

                    # Index all suffixes (e.g., "a.b.c" -> ["c", "b.c", "a.b.c"])
                    _parts = _handler_name.split('.')
                    for _i in range(len(_parts)):
                        _suffix = '.'.join(_parts[_i:])
                        if _suffix not in _SUFFIX_TO_HANDLERS:
                            _SUFFIX_TO_HANDLERS[_suffix] = []
                        _SUFFIX_TO_HANDLERS[_suffix].append(_handler_name)

            logging.info(f"Loaded {len(_HANDLER_TO_ACTOR)} handler-to-actor mappings")


            def resolve(handler_full_name: str) -> str:
                """
                Resolve handler name to actor name using suffix-based matching.

                Looks up handler in environment variables:
                - ASYA_HANDLER_<ACTOR_NAME>="full.module.path.ClassName.method"

                Supports flexible suffix matching - any suffix of the full path can be used if unambiguous:
                - "method" (shortest)
                - "ClassName.method" (class + method)
                - "module.ClassName.method" (partial path)
                - "full.module.path.ClassName.method" (full path)

                Args:
                    handler_full_name: Any suffix of the full handler path

                Returns:
                    Actor name for routing (kebab-case, lowercase)

                Raises:
                    ValueError: If handler suffix not found or is ambiguous

                Examples:
                    # Environment: ASYA_HANDLER_MY_ACTOR="class_instantiation.DataPreprocessor.clean"

                    # All of these work (if unambiguous):
                    resolve("clean")  # shortest suffix
                    resolve("DataPreprocessor.clean")  # class + method
                    resolve("class_instantiation.DataPreprocessor.clean")  # full path

                    # Ambiguous suffix
                    # Env: ASYA_HANDLER_A="module1.clean", ASYA_HANDLER_B="module2.clean"
                    resolve("clean")  # raises ValueError: ambiguous, use longer suffix
                """
                if handler_full_name in _SUFFIX_TO_HANDLERS:
                    candidates = _SUFFIX_TO_HANDLERS[handler_full_name]
                    if len(candidates) == 1:
                        return _HANDLER_TO_ACTOR[candidates[0]]
                    else:
                        raise ValueError(
                            f"Handler suffix '{handler_full_name}' is ambiguous. "
                            f"Found multiple matches: {candidates}. "
                            f"Use a longer suffix to disambiguate."
                        )

                raise ValueError(
                    f"Handler '{handler_full_name}' not found in environment variables. "
                    f'No handler ends with suffix "{handler_full_name}". '
                    f"Available handlers: {list(_HANDLER_TO_ACTOR.keys())}"
                )
            '''
        )


# Import here to avoid circular import at module level
from asya_lab.flow.errors import FlowCompileError  # noqa: E402
