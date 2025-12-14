"""Group IR operations into execution units (actors/routers)."""

from __future__ import annotations

from dataclasses import dataclass, field

from asya_cli.flow.ir import ActorCall, Condition, IROperation, Mutation, Return


@dataclass
class Router:
    name: str
    lineno: int
    mutations: list[Mutation] = field(default_factory=list)
    condition: Condition | None = None
    true_branch_actors: list[str] = field(default_factory=list)
    false_branch_actors: list[str] = field(default_factory=list)


class OperationGrouper:
    def __init__(self, flow_name: str, operations: list[IROperation]):
        self.flow_name = flow_name
        self.operations = operations
        self.routers: list[Router] = []
        self.convergence_counter = 0
        self.convergence_map: dict[str, list[str]] = {}

    def group(self) -> list[Router]:
        self.routers = []
        self.convergence_counter = 0
        self.convergence_map = {}

        start_actors = self._process_operations(self.operations, [], is_top_level=True)

        start_router = Router(name=f"start_{self.flow_name}", lineno=0, true_branch_actors=start_actors)
        self.routers.insert(0, start_router)

        end_router = Router(name=f"end_{self.flow_name}", lineno=999999)
        self.routers.append(end_router)

        self._resolve_convergence_labels()

        return self.routers

    def _process_operations(
        self, operations: list[IROperation], convergence_stack: list[str], is_top_level: bool = False
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
                            operations[i:], convergence_stack, is_top_level=is_top_level
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

                        true_actors = self._process_operations(next_op.true_branch, new_stack)
                        false_actors = self._process_operations(next_op.false_branch, new_stack)

                        continuation_actors = self._process_operations(
                            operations[i:], convergence_stack, is_top_level=is_top_level
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

                continuation = self._process_operations(operations[i:], convergence_stack, is_top_level=is_top_level)
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

                true_actors = self._process_operations(op.true_branch, new_stack)
                false_actors = self._process_operations(op.false_branch, new_stack)

                continuation_actors = self._process_operations(
                    operations[i + 1 :], convergence_stack, is_top_level=is_top_level
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

            elif isinstance(op, Return):
                return [*result, f"end_{self.flow_name}"]

            else:
                i += 1

        if result:
            continuation = self._process_operations(operations[i:], convergence_stack, is_top_level=is_top_level)
            return result + continuation

        if convergence_stack:
            return [convergence_stack[-1]]

        if is_top_level:
            return [f"end_{self.flow_name}"]

        return []

    def _process_branch(self, branch: list[IROperation], convergence_stack: list[str]) -> list[str]:
        return self._process_operations(branch, convergence_stack)

    def _resolve_convergence_labels(self):
        for router in self.routers:
            router.true_branch_actors = self._resolve_actors(router.true_branch_actors)
            router.false_branch_actors = self._resolve_actors(router.false_branch_actors)

    def _resolve_actors(self, actors: list[str]) -> list[str]:
        resolved = []
        for actor in actors:
            if actor.startswith("CONVERGENCE_"):
                replacement = self.convergence_map.get(actor, [])
                if replacement:
                    resolved.extend(self._resolve_actors(replacement))
            else:
                resolved.append(actor)
        return resolved
