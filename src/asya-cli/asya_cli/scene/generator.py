"""
Router code generator for Scene DSL.

Generates router functions from Scene IR.
"""

from asya_cli.scene.ir import (
    ActorCall,
    ClassInstantiation,
    ConditionalGoto,
    Goto,
    Label,
    PayloadMutation,
    Router,
    SceneIR,
)


class RouterGenerator:
    """Generate router functions from Scene IR."""

    def __init__(self, scene_ir: SceneIR):
        self.scene_ir = scene_ir
        self.routers: list[tuple[str, str, str]] = []

    def generate(self) -> list[tuple[str, str, str]]:
        """
        Generate all router functions.

        Returns:
            List of (router_id, docstring, code) tuples
        """
        self._generate_start_router()
        self._generate_end_router()
        self._generate_routers_from_steps(self.scene_ir.steps)
        return self.routers

    def _generate_start_router(self):
        """Generate entrypoint router for the scene."""
        start_id = f"start_{self.scene_ir.name}"
        lines = []

        lines.append(f"def {start_id}(envelope: dict) -> dict:")

        docstring = f"Entrypoint for scene '{self.scene_ir.name}'"
        lines.append(f'    """{docstring}"""')

        lines.append("    r = envelope['route']")
        lines.append("    c = r['current']")
        lines.append("")

        # Low-level routing: set first step(s) (actor calls + next router)
        if self.scene_ir.steps:
            actors_to_route = []
            i = 0

            # Collect all initial ActorCalls
            while i < len(self.scene_ir.steps) and isinstance(self.scene_ir.steps[i], ActorCall):
                actors_to_route.append(self._format_actor(self.scene_ir.steps[i].qualified_name))
                i += 1

            # After ActorCalls, add the next router
            if i < len(self.scene_ir.steps):
                next_step = self.scene_ir.steps[i]
                if isinstance(next_step, Router):
                    actors_to_route.append(self._format_actor(next_step.router_id))
                else:
                    actors_to_route.append(self._format_actor(next_step.qualified_name))

            if actors_to_route:
                actors_list = ", ".join(actors_to_route)
                lines.append(f"    r['actors'][c+1:c+1] = [{actors_list}]")
            else:
                lines.append("    pass")
        else:
            lines.append("    pass")

        lines.append("")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((start_id, docstring, code))

    def _generate_end_router(self):
        """Generate exitpoint router for the scene."""
        end_id = f"end_{self.scene_ir.name}"
        lines = []

        lines.append(f"def {end_id}(envelope: dict) -> dict:")

        docstring = f"Exitpoint for scene '{self.scene_ir.name}'"
        lines.append(f'    """{docstring}"""')

        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((end_id, docstring, code))

    def _generate_routers_from_steps(self, steps: list[ActorCall | Router]):
        """Generate router functions for all Router steps."""
        for step in steps:
            if isinstance(step, Router):
                self._generate_router_function(step)

    def _generate_router_function(self, router: Router):
        """Generate router function from Router IR node."""
        router_id = router.router_id
        param_name = self.scene_ir.param_name
        lines = []

        lines.append(f"def {router_id}(envelope: dict) -> dict:")

        docstring = "Router for control flow and payload mutations"
        lines.append(f'    """{docstring}"""')

        lines.append(f"    {param_name} = envelope['payload']")
        lines.append("    r = envelope['route']")
        lines.append("    c = r['current']")
        lines.append("    _next = []")
        lines.append("")

        # Find the next step(s) in the sequential flow (for default routing)
        next_steps = self._find_next_steps(router_id)
        # For operations that need a single next_step, use the first one (the immediate next)
        next_step = next_steps[0] if next_steps else None

        # Generate code from router operations
        operation_lines = self._generate_router_operations(
            router.operations, indent=1, router_id=router_id, next_step=next_step, next_steps=next_steps
        )
        lines.extend(operation_lines)

        lines.append("")
        lines.append("    r['actors'][c+1:c+1] = _next")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((router_id, docstring, code))

    def _find_next_steps(self, router_id: str) -> list[str]:
        """
        Find the next step(s) after the given router in the sequential flow.

        If next step is an ActorCall, return [actor, step_after_actor].
        Otherwise return [next_router].
        """
        steps = self.scene_ir.steps
        for i, step in enumerate(steps):
            if isinstance(step, Router) and step.router_id == router_id:
                # Found current router, collect next steps
                next_steps = []
                j = i + 1

                # Collect all sequential ActorCalls
                while j < len(steps) and isinstance(steps[j], ActorCall):
                    next_steps.append(steps[j].qualified_name)
                    j += 1

                # After ActorCalls, add the next router (or end)
                if j < len(steps):
                    next_step = steps[j]
                    if isinstance(next_step, Router):
                        next_steps.append(next_step.router_id)
                    else:
                        next_steps.append(next_step.qualified_name)
                else:
                    # No more steps, route to end
                    next_steps.append(f"end_{self.scene_ir.name}")

                return next_steps
        return []


    def _generate_router_operations(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        indent: int = 0,
        router_id: str | None = None,
        next_step: str | None = None,
        next_steps: list[str] | None = None,
    ) -> list[str]:
        """
        Generate code from router operations.

        Converts Label/ConditionalGoto/Goto back to structured Python code.
        """
        lines = []
        param_name = self.scene_ir.param_name
        base_indent = "    " * indent

        # Build label map and detect loop structure
        label_map = self._build_label_map(operations)
        loop_info = self._detect_loop_labels(operations, label_map) if router_id else None

        i = 0
        while i < len(operations):
            op = operations[i]

            if isinstance(op, PayloadMutation):
                lines.append(f"{base_indent}{param_name}['{op.key}'] = {op.value_str}")
                i += 1

            elif isinstance(op, ClassInstantiation):
                args_str = ", ".join(self._format_class_arg(arg) for arg in op.args)
                if op.kwargs:
                    kwargs_str = ", ".join(f"{k}={self._format_class_arg(v)}" for k, v in op.kwargs.items())
                    if args_str:
                        args_str = f"{args_str}, {kwargs_str}"
                    else:
                        args_str = kwargs_str
                lines.append(f"{base_indent}{op.var_name} = {op.class_name}({args_str})")
                i += 1

            elif isinstance(op, ActorCall):
                # Route to actor
                lines.append(f"{base_indent}_next.append({self._format_actor(op.qualified_name)})")
                # If actor has continuation, route to continuation router after actor
                if op.continuation_router_id:
                    lines.append(f"{base_indent}_next.append({self._format_actor(op.continuation_router_id)})")
                i += 1

            elif isinstance(op, Label):
                # Skip labels (they're IR artifacts, not useful in generated code)
                i += 1

            elif isinstance(op, ConditionalGoto):
                # Generate if/else structure
                if_lines, next_i = self._generate_conditional_block(operations, i, indent, router_id, loop_info, next_step, next_steps)
                lines.extend(if_lines)
                i = next_i

            elif isinstance(op, Goto):
                if op.target == "scene_exit":
                    scene_name = self.scene_ir.name
                    end_actor = f"end_{scene_name}"
                    lines.append(f"{base_indent}_next.append({self._format_actor(end_actor)})")
                elif op.target_router_id:
                    # Determine comment based on target label name
                    comment = None
                    if "loop_start" in op.target:
                        comment = "continue loop"
                    elif "loop_exit" in op.target:
                        comment = "break loop"

                    if comment:
                        lines.append(f"{base_indent}# {comment}")
                    lines.append(f"{base_indent}_next.append({self._format_actor(op.target_router_id)})")
                else:
                    lines.append(f"{base_indent}# Unresolved goto: {op.target}")
                i += 1

            else:
                lines.append(f"{base_indent}# Unknown operation: {op.__class__.__name__}")
                i += 1

        # Low-level routing: if no control flow operations, route to next step(s)
        has_control_flow = any(isinstance(op, (ConditionalGoto, Goto, ActorCall)) for op in operations)
        if not has_control_flow and next_steps:
            # Route to all next steps (actor calls + next router)
            for step in next_steps:
                lines.append(f"{base_indent}_next.append({self._format_actor(step)})")

        return lines

    def _build_label_map(
        self, operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]
    ) -> dict[str, int]:
        """Build mapping of label names to their indices."""
        label_map = {}
        for idx, op in enumerate(operations):
            if isinstance(op, Label):
                label_map[op.name] = idx
        return label_map

    def _detect_loop_labels(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        label_map: dict[str, int],
    ) -> dict[str, str] | None:
        """
        Detect loop structure and return loop labels.

        Returns dict with 'start_label' and 'exit_label' if loop detected, None otherwise.
        """
        # Look for backward jumps (goto to earlier label)
        for idx, op in enumerate(operations):
            if isinstance(op, Goto):
                target_idx = label_map.get(op.target)
                if target_idx is not None and target_idx < idx:
                    # Backward jump found - this is a loop
                    start_label = op.target
                    # Find the exit label by looking for forward jumps from ConditionalGoto
                    for cond_op in operations:
                        if isinstance(cond_op, ConditionalGoto):
                            if cond_op.false_target and cond_op.false_target in label_map:
                                false_idx = label_map[cond_op.false_target]
                                if false_idx > target_idx:
                                    return {"start_label": start_label, "exit_label": cond_op.false_target}
        return None

    def _generate_conditional_block(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        start_idx: int,
        indent: int,
        router_id: str | None = None,
        loop_info: dict[str, str] | None = None,
        next_step: str | None = None,
        next_steps: list[str] | None = None,
    ) -> tuple[list[str], int]:
        """
        Generate if/else block from ConditionalGoto pattern with low-level routing.

        Returns (lines, next_index_to_process)
        """
        cond_goto = operations[start_idx]
        assert isinstance(cond_goto, ConditionalGoto)

        base_indent = "    " * indent
        param_name = self.scene_ir.param_name
        lines = []

        # Build label map
        label_map = {}
        for idx, op in enumerate(operations):
            if isinstance(op, Label):
                label_map[op.name] = idx

        # Find true and false branches
        true_start = label_map.get(cond_goto.true_target, -1)
        false_start = label_map.get(cond_goto.false_target, -1) if cond_goto.false_target else -1

        # Generate if statement
        lines.append(f"{base_indent}if {cond_goto.condition_str}:")

        # Generate true branch
        if true_start != -1:
            # True branch operations are in this router - execute inline
            true_end = self._find_branch_end(operations, true_start + 1, label_map)
            branch_lines = self._generate_operations_range(
                operations, true_start + 1, true_end, indent + 1, label_map, None, router_id, loop_info, next_step, next_steps
            )
            if branch_lines:
                lines.extend(branch_lines)
            else:
                lines.append(f"{base_indent}    pass")

            # After inline operations, route to next step if no Goto was encountered
            branch_ops = operations[true_start + 1:true_end]
            has_goto = any(isinstance(op, (Goto, ActorCall)) for op in branch_ops)
            if not has_goto and next_step:
                lines.append(f"{base_indent}    _next.append({self._format_actor(next_step)})")
        elif cond_goto.true_target_router_id and cond_goto.true_target_router_id != router_id:
            # True branch is in a different router - route to it
            lines.append(f"{base_indent}    _next.append({self._format_actor(cond_goto.true_target_router_id)})")

        # Generate false branch
        if false_start != -1:
            # False branch operations are in this router - execute inline
            lines.append(f"{base_indent}else:")
            false_end = self._find_branch_end(operations, false_start + 1, label_map)
            branch_lines = self._generate_operations_range(
                operations, false_start + 1, false_end, indent + 1, label_map, None, router_id, loop_info, next_step, next_steps
            )
            if branch_lines:
                lines.extend(branch_lines)
            else:
                lines.append(f"{base_indent}    pass")

            # After inline operations, route to appropriate step if no Goto was encountered
            branch_ops = operations[false_start + 1:false_end]
            has_goto = any(isinstance(op, (Goto, ActorCall)) for op in branch_ops)
            if not has_goto:
                # For false branch (loop exit), route to the step AFTER the loop
                # This requires finding what comes after the current router
                if next_step:
                    lines.append(f"{base_indent}    _next.append({self._format_actor(next_step)})")
        elif cond_goto.false_target_router_id and cond_goto.false_target_router_id != router_id:
            # False branch is in a different router - route to it
            lines.append(f"{base_indent}else:")
            lines.append(f"{base_indent}    _next.append({self._format_actor(cond_goto.false_target_router_id)})")
        elif cond_goto.false_target_router_id == router_id:
            # False target points to self (loop exit condition)
            lines.append(f"{base_indent}else:")
            # Find exit point: scan forward past all routers to first ActorCall or end
            exit_target = None
            steps = self.scene_ir.steps
            for i, step in enumerate(steps):
                if isinstance(step, Router) and step.router_id == router_id:
                    # Found current router, scan forward
                    j = i + 1
                    while j < len(steps) and isinstance(steps[j], Router):
                        j += 1
                    # Found first ActorCall or reached end
                    if j < len(steps):
                        if isinstance(steps[j], ActorCall):
                            exit_target = steps[j].qualified_name
                    else:
                        exit_target = f"end_{self.scene_ir.name}"
                    break
            if exit_target:
                lines.append(f"{base_indent}    _next.append({self._format_actor(exit_target)})")
        elif false_start == -1 and next_step:
            # No false branch operations in this router, route to next step (loop exit)
            lines.append(f"{base_indent}else:")
            lines.append(f"{base_indent}    _next.append({self._format_actor(next_step)})")

        # Find convergence point by looking for Goto in true branch
        convergence_label = None
        if true_start != -1:
            for idx in range(true_start + 1, true_end):
                if isinstance(operations[idx], Goto):
                    convergence_label = operations[idx].target
                    break

        # Find next_idx: skip past the convergence label
        if convergence_label and convergence_label in label_map:
            convergence_idx = label_map[convergence_label]
            # Check if this is a backward jump (loop)
            if convergence_idx <= start_idx:
                # Backward jump - this is a loop, use false branch end
                next_idx = false_end if false_start != -1 else true_end
                if next_idx < len(operations) and isinstance(operations[next_idx], Label):
                    next_idx += 1
            else:
                # Forward jump - normal convergence
                next_idx = convergence_idx + 1
        else:
            next_idx = max(true_end if true_start != -1 else start_idx, false_end if false_start != -1 else start_idx)
            if next_idx < len(operations) and isinstance(operations[next_idx], Label):
                next_idx += 1

        return lines, next_idx

    def _generate_operations_range(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        start_idx: int,
        end_idx: int,
        indent: int,
        label_map: dict[str, int],
        visited: set[int] | None = None,
        router_id: str | None = None,
        loop_info: dict[str, str] | None = None,
        next_step: str | None = None,
        next_steps: list[str] | None = None,
    ) -> list[str]:
        """
        Generate code for a range of operations without slicing.

        Uses the pre-built label_map to resolve labels correctly.
        Tracks visited indices to prevent infinite recursion on loops.
        """
        if visited is None:
            visited = set()

        lines = []
        param_name = self.scene_ir.param_name
        base_indent = "    " * indent

        i = start_idx
        while i < end_idx:
            if i in visited:
                i += 1
                continue
            visited.add(i)
            op = operations[i]

            if isinstance(op, PayloadMutation):
                lines.append(f"{base_indent}{param_name}['{op.key}'] = {op.value_str}")
                i += 1

            elif isinstance(op, ClassInstantiation):
                args_str = ", ".join(self._format_class_arg(arg) for arg in op.args)
                if op.kwargs:
                    kwargs_str = ", ".join(f"{k}={self._format_class_arg(v)}" for k, v in op.kwargs.items())
                    if args_str:
                        args_str = f"{args_str}, {kwargs_str}"
                    else:
                        args_str = kwargs_str
                lines.append(f"{base_indent}{op.var_name} = {op.class_name}({args_str})")
                i += 1

            elif isinstance(op, ActorCall):
                # Route to actor
                lines.append(f"{base_indent}_next.append({self._format_actor(op.qualified_name)})")
                # If actor has continuation, route to continuation router after actor
                if op.continuation_router_id:
                    lines.append(f"{base_indent}_next.append({self._format_actor(op.continuation_router_id)})")
                i += 1

            elif isinstance(op, Label):
                # Skip labels (they're just markers)
                i += 1

            elif isinstance(op, ConditionalGoto):
                # Recursively generate nested if/else
                if_lines, next_i = self._generate_conditional_block_with_map(
                    operations, i, indent, label_map, visited, router_id, loop_info, next_step, next_steps
                )
                lines.extend(if_lines)
                i = next_i

            elif isinstance(op, Goto):
                if op.target == "scene_exit":
                    scene_name = self.scene_ir.name
                    end_actor = f"end_{scene_name}"
                    lines.append(f"{base_indent}_next.append({self._format_actor(end_actor)})")
                elif op.target_router_id:
                    # Determine comment based on target label name
                    comment = None
                    if "loop_start" in op.target:
                        comment = "continue loop"
                    elif "loop_exit" in op.target:
                        comment = "break loop"

                    if comment:
                        lines.append(f"{base_indent}# {comment}")
                    lines.append(f"{base_indent}_next.append({self._format_actor(op.target_router_id)})")
                else:
                    lines.append(f"{base_indent}# Unresolved goto: {op.target}")
                i += 1

            else:
                lines.append(f"{base_indent}# Unknown operation: {op.__class__.__name__}")
                i += 1

        return lines

    def _generate_conditional_block_with_map(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        start_idx: int,
        indent: int,
        label_map: dict[str, int],
        visited: set[int] | None = None,
        router_id: str | None = None,
        loop_info: dict[str, str] | None = None,
        next_step: str | None = None,
        next_steps: list[str] | None = None,
    ) -> tuple[list[str], int]:
        """
        Generate if/else block using pre-built label_map.

        Returns (lines, next_index_to_process)
        """
        if visited is None:
            visited = set()

        cond_goto = operations[start_idx]
        assert isinstance(cond_goto, ConditionalGoto)

        base_indent = "    " * indent
        lines = []

        # Find true and false branches using pre-built label_map
        true_start = label_map.get(cond_goto.true_target, -1)
        false_start = label_map.get(cond_goto.false_target, -1) if cond_goto.false_target else -1

        # Generate if statement
        lines.append(f"{base_indent}if {cond_goto.condition_str}:")

        # Generate true branch
        if true_start != -1:
            true_end = self._find_branch_end(operations, true_start + 1, label_map)
            branch_lines = self._generate_operations_range(
                operations, true_start + 1, true_end, indent + 1, label_map, visited, router_id, loop_info, next_step
            )
            if branch_lines:
                lines.extend(branch_lines)
            else:
                lines.append(f"{base_indent}    pass")

        # Generate false branch
        if false_start != -1:
            lines.append(f"{base_indent}else:")
            false_end = self._find_branch_end(operations, false_start + 1, label_map)
            branch_lines = self._generate_operations_range(
                operations, false_start + 1, false_end, indent + 1, label_map, visited, router_id, loop_info, next_step, next_steps
            )
            if branch_lines:
                lines.extend(branch_lines)
            else:
                lines.append(f"{base_indent}    pass")

        # Find convergence point by looking for Goto in true branch
        convergence_label = None
        if true_start != -1:
            for idx in range(true_start + 1, true_end):
                if isinstance(operations[idx], Goto):
                    convergence_label = operations[idx].target
                    break

        # Find next_idx: skip past the convergence label
        if convergence_label and convergence_label in label_map:
            convergence_idx = label_map[convergence_label]
            # Check if this is a backward jump (loop)
            if convergence_idx <= start_idx:
                # Backward jump - this is a loop, use false branch end
                next_idx = false_end if false_start != -1 else true_end
                if next_idx < len(operations) and isinstance(operations[next_idx], Label):
                    next_idx += 1
            else:
                # Forward jump - normal convergence
                next_idx = convergence_idx + 1
        else:
            next_idx = max(true_end if true_start != -1 else start_idx, false_end if false_start != -1 else start_idx)
            if next_idx < len(operations) and isinstance(operations[next_idx], Label):
                next_idx += 1

        return lines, next_idx

    def _find_branch_end(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        start_idx: int,
        label_map: dict[str, int],
    ) -> int:
        """Find the end of a branch (including Goto or at convergence Label)."""
        conditional_targets = set()
        for op in operations:
            if isinstance(op, ConditionalGoto):
                conditional_targets.add(op.true_target)
                if op.false_target:
                    conditional_targets.add(op.false_target)

        for idx in range(start_idx, len(operations)):
            op = operations[idx]
            if isinstance(op, Goto):
                # Include the Goto operation so it can generate route rewriting
                return idx + 1
            if isinstance(op, Label) and op.name not in conditional_targets:
                return idx
        return len(operations)

    def _collect_actors_from_steps(self, steps: list[ActorCall | Router]) -> list[str]:
        """
        Collect only top-level actors from scene steps.

        Top-level routers are those in the initial execution path (first pass through the scene).
        Excludes:
        - Continuation routers (reachable via ActorCall.continuation_router_id)
        - Loop-back routers (contain only Goto/Label operations)
        - False-branch routers (reachable only via ConditionalGoto false_target)
        """
        # Identify routers to exclude
        continuation_routers = set()
        false_branch_routers = set()

        for step in steps:
            if isinstance(step, Router):
                for op in step.operations:
                    # Continuation routers
                    if isinstance(op, ActorCall) and op.continuation_router_id:
                        continuation_routers.add(op.continuation_router_id)
                    # False branch routers (loop exit paths)
                    elif isinstance(op, ConditionalGoto) and op.false_target_router_id:
                        false_branch_routers.add(op.false_target_router_id)

        # Identify loop-back routers (routers that only contain Goto back to loop start)
        loop_back_routers = set()
        for step in steps:
            if isinstance(step, Router):
                # Check if router only contains Label and Goto (no mutations, no actor calls, no conditions)
                has_only_labels_and_goto = all(
                    isinstance(op, (Label, Goto)) for op in step.operations
                )
                if has_only_labels_and_goto and len(step.operations) > 0:
                    loop_back_routers.add(step.router_id)

        # Collect top-level actors
        actors = []
        for step in steps:
            if isinstance(step, ActorCall):
                actors.append(step.qualified_name)
            elif isinstance(step, Router):
                # Exclude continuation, loop-back, and false-branch routers
                if (step.router_id not in continuation_routers and
                    step.router_id not in loop_back_routers and
                    step.router_id not in false_branch_routers):
                    actors.append(step.router_id)

        # Add end router as final step
        actors.append(f"end_{self.scene_ir.name}")
        return actors

    def _format_actor(self, actor: str) -> str:
        """Format actor for code generation."""
        return f'resolve("{actor}")'

    def _format_class_arg(self, arg) -> str:
        """Format class constructor argument."""
        import ast

        return ast.unparse(arg)
