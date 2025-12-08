"""
Router optimizer for Scene DSL.

Splits flat operation sequences into optimal router groupings.

Input: Flat list of operations from parser
Output: Grouped routers with clear boundaries

Splitting Rules:
1. Flush before `while` loops - ensures clean entry point for goto/continue
2. Flush before scene-level actor calls - scene-level actors are separate steps
3. Split at ActorCall when followed by mutations - ensures mutations operate on actor result
4. Each router should have clear single responsibility
"""

from asya_cli.scene.ir import (
    ActorCall,
    ClassInstantiation,
    ConditionalGoto,
    Goto,
    Label,
    PayloadMutation,
    Router,
)


class RouterOptimizer:
    """Optimize operation sequences into router groupings."""

    def __init__(self, scene_name: str):
        self.scene_name = scene_name
        self.router_counter = 0

    def _new_router_id(self, flow_type: str, line: int) -> str:
        """Generate unique router ID."""
        return f"router_{self.scene_name}_line_{line}_{flow_type}"

    def _detect_router_type(
        self, operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]
    ) -> str:
        """Detect primary control flow type from operations."""
        # Build label map to check for backward jumps
        label_positions = {}
        for idx, op in enumerate(operations):
            if isinstance(op, Label):
                label_positions[op.name] = idx

        # Look for backward jumps (while loops)
        for idx, op in enumerate(operations):
            if isinstance(op, Goto):
                target_pos = label_positions.get(op.target)
                if target_pos is not None and target_pos < idx:
                    return "while"

        # Check for ConditionalGoto (if statement)
        for op in operations:
            if isinstance(op, ConditionalGoto):
                return "if"

        # No control flow found
        return "mutations"

    def optimize(
        self, operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]
    ) -> list[Router]:
        """
        Split operations into optimal router groupings.

        Splitting happens at ActorCall boundaries when followed by non-control-flow operations.
        This ensures mutations after actor calls operate on the actor's result.

        Returns:
            List of routers with ActorCalls linked to their continuation routers
        """
        if not operations:
            return []

        routers = []
        modified_ops, continuation_routers = self._split_at_actor_calls(operations)

        if modified_ops:
            # Create main router
            flow_type = self._detect_router_type(modified_ops)
            router_line = modified_ops[0].line if modified_ops else 0
            main_router = Router(
                line=router_line,
                col=0,
                router_id=self._new_router_id(flow_type, router_line),
                operations=modified_ops,
            )
            routers.append(main_router)

        # Add continuation routers
        routers.extend(continuation_routers)

        # Resolve goto targets to router IDs
        self._resolve_goto_targets(routers)

        return routers

    def _resolve_goto_targets(self, routers: list[Router]) -> None:
        """
        Resolve Goto target labels to router IDs.

        Builds a map of label → router_id, then updates all Goto operations
        with their target_router_id.
        """
        # Build label → router_id map
        label_to_router = {}
        for router in routers:
            for op in router.operations:
                if isinstance(op, Label):
                    label_to_router[op.name] = router.router_id

        # Resolve goto targets
        for router in routers:
            for op in router.operations:
                if isinstance(op, Goto) and op.target != "scene_exit":
                    # Resolve label to router ID
                    if op.target in label_to_router:
                        op.target_router_id = label_to_router[op.target]

    def _split_at_actor_calls(
        self, operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]
    ) -> tuple[list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall], list[Router]]:
        """
        Split operations at ActorCall boundaries when followed by non-control-flow operations.

        Logic:
        - When we encounter ActorCall followed by mutations/operations (before next Label/Goto/ConditionalGoto)
        - Extract those operations into a continuation router
        - Link the ActorCall to the continuation router via continuation_router_id
        - This ensures mutations operate on actor result, not original payload

        Returns:
            (modified_operations, continuation_routers)
        """
        if not operations:
            return (operations, [])

        continuation_routers = []
        result_ops = []
        i = 0

        while i < len(operations):
            op = operations[i]

            if isinstance(op, ActorCall):
                # Collect all operations after this ActorCall
                continuation_ops = []
                j = i + 1
                while j < len(operations):
                    next_op = operations[j]
                    continuation_ops.append(next_op)
                    j += 1

                if continuation_ops:
                    # Create continuation router for operations after this actor
                    flow_type = self._detect_router_type(continuation_ops)
                    cont_line = continuation_ops[0].line
                    cont_router_id = self._new_router_id(flow_type, cont_line)

                    # Recursively optimize continuation operations
                    # (they might have nested actor calls)
                    cont_routers = self.optimize(continuation_ops)

                    if cont_routers:
                        # Link actor call to first continuation router
                        op.continuation_router_id = cont_routers[0].router_id
                        continuation_routers.extend(cont_routers)

                    # Skip continuation operations (already processed)
                    i = j
                else:
                    i += 1

                result_ops.append(op)
            else:
                result_ops.append(op)
                i += 1

        return (result_ops, continuation_routers)
