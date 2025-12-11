"""Group IR operations into execution units (actors/routers)."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from asya_cli.scene.ir import ActorCall, Condition, IROperation, Mutation


@dataclass
class Router:
    name: str
    lineno: int
    mutations: List[Mutation] = field(default_factory=list)
    condition: Optional[Condition] = None
    true_branch_actors: List[str] = field(default_factory=list)
    false_branch_actors: List[str] = field(default_factory=list)


class OperationGrouper:
    def __init__(self, scene_name: str, operations: List[IROperation]):
        self.scene_name = scene_name
        self.operations = operations
        self.routers: List[Router] = []
        self.convergence_counter = 0
        self.convergence_map: Dict[str, List[str]] = {}

    def group(self) -> List[Router]:
        self.routers = []
        self.convergence_counter = 0
        self.convergence_map = {}

        start_actors = self._process_operations(self.operations, [])

        start_router = Router(
            name=f"start_{self.scene_name}",
            lineno=0,
            true_branch_actors=start_actors
        )
        self.routers.insert(0, start_router)

        end_router = Router(name=f"end_{self.scene_name}", lineno=999999)
        self.routers.append(end_router)

        self._resolve_convergence_labels()

        return self.routers

    def _process_operations(self, operations: List[IROperation], convergence_stack: List[str]) -> List[str]:
        if not operations:
            if convergence_stack:
                return [convergence_stack[-1]]
            return []

        i = 0
        mutations = []

        while i < len(operations):
            op = operations[i]

            if isinstance(op, Mutation):
                mutations.append(op)
                i += 1
            elif isinstance(op, ActorCall):
                actors = []
                while i < len(operations) and isinstance(operations[i], ActorCall):
                    actors.append(operations[i].name)
                    i += 1

                if mutations:
                    next_actors = actors + self._process_operations(operations[i:], convergence_stack)
                    router = Router(
                        name=f"router_{self.scene_name}_line_{mutations[0].lineno}_seq",
                        lineno=mutations[0].lineno,
                        mutations=mutations,
                        true_branch_actors=next_actors
                    )
                    self.routers.append(router)
                    return [router.name]
                else:
                    return actors + self._process_operations(operations[i:], convergence_stack)

            elif isinstance(op, Condition):
                convergence_label = f"CONVERGENCE_{self.convergence_counter}"
                self.convergence_counter += 1

                new_stack = convergence_stack + [convergence_label]

                true_actors = self._process_branch(op.true_branch, new_stack)
                false_actors = self._process_branch(op.false_branch, new_stack)

                continuation_actors = self._process_operations(operations[i+1:], convergence_stack)

                self.convergence_map[convergence_label] = continuation_actors

                router = Router(
                    name=f"router_{self.scene_name}_line_{op.lineno}_if",
                    lineno=op.lineno,
                    mutations=mutations,
                    condition=op,
                    true_branch_actors=true_actors,
                    false_branch_actors=false_actors
                )
                self.routers.append(router)
                return [router.name]
            else:
                i += 1

        if mutations:
            next_actors = self._process_operations(operations[i:], convergence_stack)
            router = Router(
                name=f"router_{self.scene_name}_line_{mutations[0].lineno}_seq",
                lineno=mutations[0].lineno,
                mutations=mutations,
                true_branch_actors=next_actors
            )
            self.routers.append(router)
            return [router.name]

        if convergence_stack:
            return [convergence_stack[-1]]

        return []

    def _process_branch(self, branch: List[IROperation], convergence_stack: List[str]) -> List[str]:
        return self._process_operations(branch, convergence_stack)

    def _resolve_convergence_labels(self):
        for router in self.routers:
            router.true_branch_actors = self._resolve_actors(router.true_branch_actors)
            router.false_branch_actors = self._resolve_actors(router.false_branch_actors)

    def _resolve_actors(self, actors: List[str]) -> List[str]:
        resolved = []
        for actor in actors:
            if actor.startswith("CONVERGENCE_"):
                replacement = self.convergence_map.get(actor, [])
                if replacement:
                    resolved.extend(self._resolve_actors(replacement))
                else:
                    resolved.append(actor)
            else:
                resolved.append(actor)
        return resolved
