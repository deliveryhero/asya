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
    RouterBoundary,
)


class RouterOptimizer:
    """Optimize operation sequences into router groupings."""

    def __init__(self, scene_name: str):
        self.scene_name = scene_name
        self.router_counter = 0

    def _new_router_id(self, flow_type: str, line: int) -> str:
        """Generate router ID based on line and flow type."""
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

        # No control flow found - sequential calls
        return "seq"

    def optimize(
        self, operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall | RouterBoundary]
    ) -> list[Router]:
        """
        Split operations into optimal router groupings.

        Splitting happens at:
        1. RouterBoundary markers (for nested loops)
        2. ActorCall boundaries (operations after actor calls in continuation routers)

        Returns:
            List of routers with ActorCalls linked to their continuation routers
        """
        if not operations:
            return []

        # First split at RouterBoundary markers
        boundary_chunks = self._split_at_boundaries(operations)

        # Then recursively optimize each chunk (splitting at ActorCalls)
        routers = []
        for chunk in boundary_chunks:
            chunk_routers = self._optimize_chunk(chunk)
            routers.extend(chunk_routers)

        # Resolve goto targets to router IDs
        self._resolve_goto_targets(routers)

        # Optimize away simple forwarding routers
        routers = self._inline_forwarding_routers(routers)

        return routers

    def _split_at_boundaries(
        self, operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall | RouterBoundary]
    ) -> list[list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]]:
        """Split operations at RouterBoundary markers."""
        chunks = []
        current_chunk = []

        for op in operations:
            if isinstance(op, RouterBoundary):
                # Flush current chunk
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = []
            else:
                current_chunk.append(op)

        # Flush final chunk
        if current_chunk:
            chunks.append(current_chunk)

        return chunks if chunks else [[]]

    def _optimize_chunk(
        self, operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]
    ) -> list[Router]:
        """Optimize a single chunk of operations (split at ActorCalls)."""
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

        return routers

    def _inline_forwarding_routers(self, routers: list[Router]) -> list[Router]:
        """
        Optimize away simple forwarding routers and empty routers.

        Forwarding router: only contains Label and Goto operations.
        Empty router: only contains Label operations (no actual work).

        These can be eliminated by redirecting references to them.
        """
        # Identify forwarding routers and their targets, and empty routers
        forwarding_map = {}  # router_id -> target_router_id
        empty_routers = set()  # router_ids with no operations

        for router in routers:
            non_label_ops = [op for op in router.operations if not isinstance(op, Label)]

            # If router only contains Labels (no actual operations), it's empty
            if len(non_label_ops) == 0:
                empty_routers.add(router.router_id)
            # If router only contains one Goto (and possibly Labels), it's a forwarder
            elif len(non_label_ops) == 1 and isinstance(non_label_ops[0], Goto):
                goto_op = non_label_ops[0]
                if goto_op.target_router_id:
                    forwarding_map[router.router_id] = goto_op.target_router_id

        # If no forwarders or empty routers found, return as-is
        if not forwarding_map and not empty_routers:
            return routers

        # Redirect all references to forwarders
        for router in routers:
            for op in router.operations:
                # Redirect ActorCall continuations
                if isinstance(op, ActorCall) and op.continuation_router_id:
                    while op.continuation_router_id in forwarding_map:
                        op.continuation_router_id = forwarding_map[op.continuation_router_id]
                # Redirect Goto targets
                elif isinstance(op, Goto) and op.target_router_id:
                    while op.target_router_id in forwarding_map:
                        op.target_router_id = forwarding_map[op.target_router_id]
                # Redirect ConditionalGoto targets
                elif isinstance(op, ConditionalGoto):
                    if op.true_target_router_id:
                        while op.true_target_router_id in forwarding_map:
                            op.true_target_router_id = forwarding_map[op.true_target_router_id]
                    if op.false_target_router_id:
                        while op.false_target_router_id in forwarding_map:
                            op.false_target_router_id = forwarding_map[op.false_target_router_id]

        # Redirect references to empty routers by removing them
        # (any references to empty routers should just be removed since they do nothing)
        for router in routers:
            for op in router.operations:
                # For ActorCall continuations pointing to empty routers, set to None
                if isinstance(op, ActorCall) and op.continuation_router_id in empty_routers:
                    op.continuation_router_id = None
                # For Goto/ConditionalGoto pointing to empty routers, this shouldn't happen
                # but if it does, it's a bug in the IR generation

        # Remove forwarding and empty routers from the list
        return [r for r in routers if r.router_id not in forwarding_map and r.router_id not in empty_routers]

    def _resolve_goto_targets(self, routers: list[Router]) -> None:
        """
        Resolve Goto and ConditionalGoto target labels to router IDs.

        Builds a map of label → router_id, then updates all Goto and ConditionalGoto operations
        with their target_router_id fields.
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
                elif isinstance(op, ConditionalGoto):
                    # Resolve true and false targets
                    if op.true_target in label_to_router:
                        op.true_target_router_id = label_to_router[op.true_target]
                    if op.false_target and op.false_target in label_to_router:
                        op.false_target_router_id = label_to_router[op.false_target]

    def _split_at_actor_calls(
        self, operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]
    ) -> tuple[list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall], list[Router]]:
        """
        Split operations at ActorCall boundaries when followed by non-control-flow operations.

        Logic:
        - When we encounter ActorCall followed by mutations/operations (before next control flow boundary)
        - Extract those operations into a continuation router
        - Link the ActorCall to the continuation router via continuation_router_id
        - This ensures mutations operate on actor result, not original payload

        Continuation boundary rules:
        - Stop at Labels (control flow convergence points)
        - Stop at ConditionalGoto (if/elif/else branches)
        - Stop at Goto (loop continue/break, explicit jumps)
        - Continue through mutations and class instantiations

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
                # Collect operations after ActorCall until next control flow boundary
                continuation_ops = []
                j = i + 1
                while j < len(operations):
                    next_op = operations[j]
                    # Stop at control flow boundaries and router boundaries
                    if isinstance(next_op, (Label, ConditionalGoto, Goto, RouterBoundary)):
                        break
                    # Continue with mutations and class instantiations
                    continuation_ops.append(next_op)
                    j += 1

                if continuation_ops:
                    # Create continuation router for operations after this actor
                    flow_type = self._detect_router_type(continuation_ops)
                    cont_line = continuation_ops[0].line
                    cont_router_id = self._new_router_id(flow_type, cont_line)

                    # Recursively optimize continuation operations
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
