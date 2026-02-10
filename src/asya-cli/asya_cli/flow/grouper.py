"""Group IR operations into execution units (actors/routers)."""

from __future__ import annotations

from dataclasses import dataclass, field

from asya_cli.flow.ir import ActorCall, Break, Condition, Continue, IROperation, Mutation, Return, WhileLoop


@dataclass
class Router:
    name: str
    lineno: int
    mutations: list[Mutation] = field(default_factory=list)
    condition: Condition | None = None
    true_branch_actors: list[str] = field(default_factory=list)
    false_branch_actors: list[str] = field(default_factory=list)
    is_loop_back: bool = False


class OperationGrouper:
    def __init__(self, flow_name: str, operations: list[IROperation]):
        self.flow_name = flow_name
        self.operations = operations
        self.routers: list[Router] = []
        self.convergence_counter = 0
        self.convergence_map: dict[str, list[str]] = {}
        self._loop_counter = 0

    def group(self) -> list[Router]:
        self.routers = []
        self.convergence_counter = 0
        self.convergence_map = {}
        self._loop_counter = 0

        start_actors = self._process_operations(self.operations, [], is_top_level=True)

        start_router = Router(name=f"start_{self.flow_name}", lineno=0, true_branch_actors=start_actors)
        self.routers.insert(0, start_router)

        end_router = Router(name=f"end_{self.flow_name}", lineno=999999)
        self.routers.append(end_router)

        self._resolve_convergence_labels()

        return self.routers

    def _process_operations(
        self,
        operations: list[IROperation],
        convergence_stack: list[str],
        is_top_level: bool = False,
        loop_back_label: str | None = None,
        loop_exit_label: str | None = None,
    ) -> list[str]:
        if not operations:
            if convergence_stack:
                return [convergence_stack[-1]]
            if is_top_level:
                return [f"end_{self.flow_name}"]
            return []

        result: list[str] = []
        i = 0

        while i < len(operations):
            op = operations[i]

            if isinstance(op, Mutation):
                mutations = [op]
                i += 1

                while i < len(operations):
                    next_op = operations[i]
                    if isinstance(next_op, Mutation):
                        mutations.append(next_op)
                        i += 1
                    else:
                        break

                if i < len(operations):
                    next_op = operations[i]
                    if isinstance(next_op, ActorCall):
                        i += 1

                        continuation = self._process_operations(
                            operations[i:],
                            convergence_stack,
                            is_top_level=is_top_level,
                            loop_back_label=loop_back_label,
                            loop_exit_label=loop_exit_label,
                        )

                        router = Router(
                            name=f"router_{self.flow_name}_line_{mutations[0].lineno}_seq",
                            lineno=mutations[0].lineno,
                            mutations=mutations,
                            true_branch_actors=[next_op.name, *continuation],
                        )
                        self.routers.append(router)
                        return [*result, router.name]

                    elif isinstance(next_op, Condition):
                        i += 1

                        convergence_label = f"CONVERGENCE_{self.convergence_counter}"
                        self.convergence_counter += 1

                        new_stack = [*convergence_stack, convergence_label]

                        true_actors = self._process_operations(
                            next_op.true_branch,
                            new_stack,
                            loop_back_label=loop_back_label,
                            loop_exit_label=loop_exit_label,
                        )
                        false_actors = self._process_operations(
                            next_op.false_branch,
                            new_stack,
                            loop_back_label=loop_back_label,
                            loop_exit_label=loop_exit_label,
                        )

                        continuation_actors = self._process_operations(
                            operations[i:],
                            convergence_stack,
                            is_top_level=is_top_level,
                            loop_back_label=loop_back_label,
                            loop_exit_label=loop_exit_label,
                        )

                        self.convergence_map[convergence_label] = continuation_actors

                        router = Router(
                            name=f"router_{self.flow_name}_line_{next_op.lineno}_if",
                            lineno=next_op.lineno,
                            mutations=mutations,
                            condition=next_op,
                            true_branch_actors=true_actors,
                            false_branch_actors=false_actors,
                        )
                        self.routers.append(router)
                        return [*result, router.name]

                    elif isinstance(next_op, WhileLoop):
                        i += 1

                        continuation = self._process_operations(
                            operations[i:],
                            convergence_stack,
                            is_top_level=is_top_level,
                            loop_back_label=loop_back_label,
                            loop_exit_label=loop_exit_label,
                        )

                        loop_actors = self._process_while_loop(next_op, mutations, continuation)
                        return [*result, *loop_actors]

                continuation = self._process_operations(
                    operations[i:],
                    convergence_stack,
                    is_top_level=is_top_level,
                    loop_back_label=loop_back_label,
                    loop_exit_label=loop_exit_label,
                )
                router = Router(
                    name=f"router_{self.flow_name}_line_{mutations[0].lineno}_seq",
                    lineno=mutations[0].lineno,
                    mutations=mutations,
                    true_branch_actors=continuation,
                )
                self.routers.append(router)
                return [*result, router.name]

            elif isinstance(op, ActorCall):
                result.append(op.name)
                i += 1

            elif isinstance(op, Condition):
                convergence_label = f"CONVERGENCE_{self.convergence_counter}"
                self.convergence_counter += 1

                new_stack = [*convergence_stack, convergence_label]

                true_actors = self._process_operations(
                    op.true_branch,
                    new_stack,
                    loop_back_label=loop_back_label,
                    loop_exit_label=loop_exit_label,
                )
                false_actors = self._process_operations(
                    op.false_branch,
                    new_stack,
                    loop_back_label=loop_back_label,
                    loop_exit_label=loop_exit_label,
                )

                continuation_actors = self._process_operations(
                    operations[i + 1 :],
                    convergence_stack,
                    is_top_level=is_top_level,
                    loop_back_label=loop_back_label,
                    loop_exit_label=loop_exit_label,
                )

                self.convergence_map[convergence_label] = continuation_actors

                router = Router(
                    name=f"router_{self.flow_name}_line_{op.lineno}_if",
                    lineno=op.lineno,
                    condition=op,
                    true_branch_actors=true_actors,
                    false_branch_actors=false_actors,
                )
                self.routers.append(router)
                return [*result, router.name]

            elif isinstance(op, WhileLoop):
                i += 1

                continuation = self._process_operations(
                    operations[i:],
                    convergence_stack,
                    is_top_level=is_top_level,
                    loop_back_label=loop_back_label,
                    loop_exit_label=loop_exit_label,
                )

                loop_actors = self._process_while_loop(op, [], continuation)
                return [*result, *loop_actors]

            elif isinstance(op, Break):
                if loop_exit_label:
                    return [*result, loop_exit_label]
                return [*result, f"end_{self.flow_name}"]

            elif isinstance(op, Continue):
                if loop_back_label:
                    return [*result, loop_back_label]
                return result

            elif isinstance(op, Return):
                return [*result, f"end_{self.flow_name}"]

            else:
                i += 1

        if result:
            continuation = self._process_operations(
                operations[i:],
                convergence_stack,
                is_top_level=is_top_level,
                loop_back_label=loop_back_label,
                loop_exit_label=loop_exit_label,
            )
            return result + continuation

        if convergence_stack:
            return [convergence_stack[-1]]

        if is_top_level:
            return [f"end_{self.flow_name}"]

        return []

    def _process_while_loop(
        self,
        loop: WhileLoop,
        pre_mutations: list[Mutation],
        continuation: list[str],
    ) -> list[str]:
        """Process a WhileLoop IR node into router(s).

        For `while True:` (no condition):
            loop_back_router (re-inserts loop body into route)
            Body is processed with loop_back pointing to loop_back_router

        For `while condition:` (conditional):
            loop_condition_router (checks condition, true -> body, false -> continuation)
            loop_back_router (re-inserts condition_router into route)
        """
        loop_id = self._loop_counter
        self._loop_counter += 1

        loop_back_name = f"router_{self.flow_name}_line_{loop.lineno}_loop_back_{loop_id}"
        loop_exit_label = f"LOOP_EXIT_{loop_id}"
        loop_back_label = f"LOOP_BACK_{loop_id}"

        # Register the exit label so break can reference it
        self.convergence_map[loop_exit_label] = continuation

        if loop.test is None:
            # `while True:` — no condition router needed
            # The loop-back router re-inserts the body actors

            # Process loop body with loop context
            body_actors = self._process_operations(
                loop.body,
                [],
                loop_back_label=loop_back_label,
                loop_exit_label=loop_exit_label,
            )

            # Create loop-back router: re-inserts body actors + itself
            loop_back_router = Router(
                name=loop_back_name,
                lineno=loop.lineno,
                mutations=pre_mutations,
                true_branch_actors=[*body_actors, loop_back_name],
                is_loop_back=True,
            )
            self.routers.append(loop_back_router)

            # Register the loop_back_label so continue resolves to loop_back_router
            self.convergence_map[loop_back_label] = [loop_back_name]

            return [loop_back_name]

        else:
            # `while condition:` — need a condition router
            condition_name = f"router_{self.flow_name}_line_{loop.lineno}_while_{loop_id}"

            # Process loop body with loop context
            body_actors = self._process_operations(
                loop.body,
                [],
                loop_back_label=loop_back_label,
                loop_exit_label=loop_exit_label,
            )

            # Create loop-back router: re-inserts condition_router into route
            loop_back_router = Router(
                name=loop_back_name,
                lineno=loop.lineno,
                true_branch_actors=[condition_name],
                is_loop_back=True,
            )
            self.routers.append(loop_back_router)

            # Register the loop_back_label so continue resolves to loop_back_router
            self.convergence_map[loop_back_label] = [loop_back_name]

            # Create the condition-check router
            condition_ir = Condition(
                lineno=loop.lineno,
                test=loop.test,
                true_branch=[],
                false_branch=[],
            )

            condition_router = Router(
                name=condition_name,
                lineno=loop.lineno,
                mutations=pre_mutations,
                condition=condition_ir,
                true_branch_actors=[*body_actors, loop_back_name],
                false_branch_actors=[loop_exit_label],
            )
            self.routers.append(condition_router)

            return [condition_name]

    def _process_branch(self, branch: list[IROperation], convergence_stack: list[str]) -> list[str]:
        return self._process_operations(branch, convergence_stack)

    def _resolve_convergence_labels(self):
        for router in self.routers:
            router.true_branch_actors = self._resolve_actors(router.true_branch_actors)
            router.false_branch_actors = self._resolve_actors(router.false_branch_actors)

    def _resolve_actors(self, actors: list[str]) -> list[str]:
        resolved = []
        for actor in actors:
            if actor.startswith("CONVERGENCE_") or actor.startswith("LOOP_EXIT_") or actor.startswith("LOOP_BACK_"):
                replacement = self.convergence_map.get(actor, [])
                if replacement:
                    resolved.extend(self._resolve_actors(replacement))
            else:
                resolved.append(actor)
        return resolved
