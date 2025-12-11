"""Group IR operations into execution units (actors/routers)."""

from dataclasses import dataclass, field
from typing import List, Optional

from asya_cli.scene.ir import ActorCall, Condition, IROperation, Mutation


@dataclass
class Router:
    name: str
    lineno: int
    mutations: List[Mutation] = field(default_factory=list)
    actors: List[str] = field(default_factory=list)
    condition: Optional[Condition] = None
    true_branch_actors: List[str] = field(default_factory=list)
    false_branch_actors: List[str] = field(default_factory=list)
    continuation_actors: List[str] = field(default_factory=list)


class OperationGrouper:
    def __init__(self, scene_name: str, operations: List[IROperation]):
        self.scene_name = scene_name
        self.operations = operations
        self.routers: List[Router] = []

    def group(self) -> List[Router]:
        self.routers = []

        initial_actors, rest_ops = self._extract_initial_actors(self.operations)

        start_router = Router(
            name=f"start_{self.scene_name}",
            lineno=0,
            actors=initial_actors
        )

        self._process_operations(rest_ops)

        if self.routers and initial_actors:
            start_router.actors.append(self.routers[0].name)

        self.routers.insert(0, start_router)
        self.routers.append(Router(name=f"end_{self.scene_name}", lineno=999999))

        return self.routers

    def _extract_initial_actors(self, operations: List[IROperation]):
        actors = []
        i = 0
        while i < len(operations):
            if isinstance(operations[i], ActorCall):
                actors.append(operations[i].name)
                i += 1
            else:
                break
        return actors, operations[i:]

    def _process_operations(self, operations: List[IROperation]):
        i = 0
        while i < len(operations):
            op = operations[i]

            if isinstance(op, Mutation):
                router, consumed = self._process_mutation_block(operations[i:])
                if router:
                    self.routers.append(router)
                    continuation_consumed = len(router.continuation_actors)
                    i += consumed + continuation_consumed
                else:
                    i += consumed

            elif isinstance(op, ActorCall):
                actors, consumed = self._collect_actors(operations[i:])
                if actors:
                    router = Router(
                        name=f"router_{self.scene_name}_line_{op.lineno}_seq",
                        lineno=op.lineno,
                        actors=actors
                    )
                    self.routers.append(router)
                i += consumed

            elif isinstance(op, Condition):
                router = self._process_condition(op, operations[i+1:])
                if router:
                    self.routers.append(router)
                    continuation_consumed = len(router.continuation_actors)
                    i += 1 + continuation_consumed
                else:
                    i += 1

            else:
                i += 1

    def _process_mutation_block(self, operations: List[IROperation]):
        mutations = []
        i = 0
        while i < len(operations) and isinstance(operations[i], Mutation):
            mutations.append(operations[i])
            i += 1

        if i < len(operations) and isinstance(operations[i], Condition):
            router = self._process_condition(operations[i], operations[i+1:], mutations)
            return router, i + 1

        if mutations:
            router = Router(
                name=f"router_{self.scene_name}_line_{mutations[0].lineno}_seq",
                lineno=mutations[0].lineno,
                mutations=mutations
            )
            return router, i

        return None, i

    def _collect_actors(self, operations: List[IROperation]):
        actors = []
        i = 0
        while i < len(operations) and isinstance(operations[i], ActorCall):
            actors.append(operations[i].name)
            i += 1
        return actors, i

    def _process_condition(self, cond: Condition, remaining_ops: List[IROperation], prefix_mutations: List[Mutation] = None):
        continuation_actors, _ = self._extract_initial_actors(remaining_ops)

        true_actors = self._extract_actors_from_branch(cond.true_branch)
        false_actors = self._extract_actors_from_branch(cond.false_branch)

        router = Router(
            name=f"router_{self.scene_name}_line_{cond.lineno}_if",
            lineno=cond.lineno,
            mutations=prefix_mutations or [],
            condition=cond,
            true_branch_actors=true_actors + continuation_actors,
            false_branch_actors=false_actors + continuation_actors,
            continuation_actors=continuation_actors
        )

        return router

    def _extract_actors_from_branch(self, branch: List[IROperation]):
        actors = []
        for op in branch:
            if isinstance(op, ActorCall):
                actors.append(op.name)
        return actors
