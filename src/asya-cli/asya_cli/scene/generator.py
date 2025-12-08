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

        first_actors = self._collect_actors_from_steps(self.scene_ir.steps)
        if first_actors:
            actors_list = ", ".join(self._format_actor(a) for a in first_actors)
            lines.append(f"    r['actors'][c+1:c+1] = [{actors_list}]")
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
        lines.append("    _next_actors = []")
        lines.append("")

        # Generate code from router operations
        operation_lines = self._generate_router_operations(router.operations, indent=1, router_id=router_id)
        lines.extend(operation_lines)

        lines.append("")
        lines.append("    # Assign accumulated actors to route")
        lines.append("    r['actors'][c+1:c+1] = _next_actors")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((router_id, docstring, code))

    def _generate_router_operations(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        indent: int = 0,
        router_id: str | None = None,
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
                lines.append(f"{base_indent}_next_actors.append({self._format_actor(op.qualified_name)})")
                i += 1

            elif isinstance(op, Label):
                # Labels become comments
                lines.append(f"{base_indent}# Label: {op.name}")
                i += 1

            elif isinstance(op, ConditionalGoto):
                # Generate if/else structure
                if_lines, next_i = self._generate_conditional_block(operations, i, indent, router_id, loop_info)
                lines.extend(if_lines)
                i = next_i

            elif isinstance(op, Goto):
                # Handle different goto targets
                if op.target == "scene_exit":
                    # Early return: assign accumulated actors + end, then return
                    scene_name = self.scene_ir.name
                    end_actor = f"end_{scene_name}"
                    lines.append(f"{base_indent}# return: assign accumulated actors + end, skip remaining")
                    lines.append(f"{base_indent}r['actors'][c+1:] = _next_actors + [{self._format_actor(end_actor)}]")
                    lines.append(f"{base_indent}return envelope")
                elif loop_info and router_id:
                    # Generate route rewriting for loop control (continue/break)
                    if op.target == loop_info["start_label"]:
                        # Continue: re-add this router to route
                        lines.append(f"{base_indent}# continue: re-queue loop router")
                        lines.append(f"{base_indent}_next_actors.append({self._format_actor(router_id)})")
                    elif op.target == loop_info["exit_label"]:
                        # Break: do nothing (fall through)
                        lines.append(f"{base_indent}# break: exit loop")
                        lines.append(f"{base_indent}pass")
                    else:
                        # Other goto
                        lines.append(f"{base_indent}# Goto: {op.target}")
                else:
                    # Not in a loop, just comment
                    lines.append(f"{base_indent}# Goto: {op.target}")
                i += 1

            else:
                lines.append(f"{base_indent}# Unknown operation: {op.__class__.__name__}")
                i += 1

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
    ) -> tuple[list[str], int]:
        """
        Generate if/else block from ConditionalGoto pattern.

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

        # Generate true branch (process range in-place, no slicing)
        if true_start != -1:
            true_end = self._find_branch_end(operations, true_start + 1, label_map)
            branch_lines = self._generate_operations_range(
                operations, true_start + 1, true_end, indent + 1, label_map, None, router_id, loop_info
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
                operations, false_start + 1, false_end, indent + 1, label_map, None, router_id, loop_info
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
                lines.append(f"{base_indent}_next_actors.append({self._format_actor(op.qualified_name)})")
                i += 1

            elif isinstance(op, Label):
                # Skip labels (they're just markers)
                i += 1

            elif isinstance(op, ConditionalGoto):
                # Recursively generate nested if/else
                if_lines, next_i = self._generate_conditional_block_with_map(
                    operations, i, indent, label_map, visited, router_id, loop_info
                )
                lines.extend(if_lines)
                i = next_i

            elif isinstance(op, Goto):
                # Handle different goto targets
                if op.target == "scene_exit":
                    # Early return: assign accumulated actors + end, then return
                    scene_name = self.scene_ir.name
                    end_actor = f"end_{scene_name}"
                    lines.append(f"{base_indent}# return: assign accumulated actors + end, skip remaining")
                    lines.append(f"{base_indent}r['actors'][c+1:] = _next_actors + [{self._format_actor(end_actor)}]")
                    lines.append(f"{base_indent}return envelope")
                elif loop_info and router_id:
                    # Generate route rewriting for loop control (continue/break)
                    if op.target == loop_info["start_label"]:
                        # Continue: re-add this router to route
                        lines.append(f"{base_indent}# continue: re-queue loop router")
                        lines.append(f"{base_indent}_next_actors.append({self._format_actor(router_id)})")
                    elif op.target == loop_info["exit_label"]:
                        # Break: do nothing (fall through)
                        lines.append(f"{base_indent}# break: exit loop")
                        lines.append(f"{base_indent}pass")
                    else:
                        # Other goto - just skip
                        pass
                # Gotos mark end of branch, always advance
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
                operations, true_start + 1, true_end, indent + 1, label_map, visited, router_id, loop_info
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
                operations, false_start + 1, false_end, indent + 1, label_map, visited, router_id, loop_info
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
        """Collect all actors from scene steps, including end router."""
        actors = []
        for step in steps:
            if isinstance(step, ActorCall):
                actors.append(step.qualified_name)
            elif isinstance(step, Router):
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
