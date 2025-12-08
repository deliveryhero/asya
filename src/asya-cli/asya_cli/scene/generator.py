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
        self._generate_entrypoint_router()
        self._generate_routers_from_steps(self.scene_ir.steps)
        return self.routers

    def _generate_entrypoint_router(self):
        """Generate entrypoint router for the scene."""
        entrypoint_id = self.scene_ir.name
        lines = []

        lines.append(f"def {entrypoint_id}(envelope: dict) -> dict:")

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
        self.routers.append((entrypoint_id, docstring, code))

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
        lines.append("")

        # Generate code from router operations
        operation_lines = self._generate_router_operations(router.operations, indent=1)
        lines.extend(operation_lines)

        lines.append("")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((router_id, docstring, code))

    def _generate_router_operations(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        indent: int = 0,
    ) -> list[str]:
        """
        Generate code from router operations.

        Converts Label/ConditionalGoto/Goto back to structured Python code.
        """
        lines = []
        param_name = self.scene_ir.param_name
        base_indent = "    " * indent

        i = 0
        while i < len(operations):
            op = operations[i]

            if isinstance(op, PayloadMutation):
                lines.append(f"{base_indent}    {param_name}['{op.key}'] = {op.value_str}")
                i += 1

            elif isinstance(op, ClassInstantiation):
                args_str = ", ".join(self._format_class_arg(arg) for arg in op.args)
                if op.kwargs:
                    kwargs_str = ", ".join(f"{k}={self._format_class_arg(v)}" for k, v in op.kwargs.items())
                    if args_str:
                        args_str = f"{args_str}, {kwargs_str}"
                    else:
                        args_str = kwargs_str
                lines.append(f"{base_indent}    {op.var_name} = {op.class_name}({args_str})")
                i += 1

            elif isinstance(op, ActorCall):
                lines.append(f"{base_indent}    r['actors'][c+1:c+1] = [{self._format_actor(op.qualified_name)}]")
                i += 1

            elif isinstance(op, Label):
                # Labels become comments
                lines.append(f"{base_indent}    # Label: {op.name}")
                i += 1

            elif isinstance(op, ConditionalGoto):
                # Generate if/else structure
                if_lines, next_i = self._generate_conditional_block(operations, i, indent)
                lines.extend(if_lines)
                i = next_i

            elif isinstance(op, Goto):
                # Gotos become comments (or could be continue/break in loops)
                lines.append(f"{base_indent}    # Goto: {op.target}")
                i += 1

            else:
                lines.append(f"{base_indent}    # Unknown operation: {op.__class__.__name__}")
                i += 1

        return lines

    def _generate_conditional_block(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        start_idx: int,
        indent: int,
    ) -> tuple[list[str], int]:
        """
        Generate if/else block from ConditionalGoto pattern.

        Returns (lines, next_index_to_process)
        """
        cond_goto = operations[start_idx]
        assert isinstance(cond_goto, ConditionalGoto)

        base_indent = "    " * indent
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
        lines.append(f"{base_indent}    if {cond_goto.condition_str}:")

        # Generate true branch
        if true_start != -1:
            true_end = self._find_branch_end(operations, true_start + 1, label_map)
            true_ops = operations[true_start + 1 : true_end]
            true_lines = self._generate_router_operations(true_ops, indent + 1)
            if true_lines:
                lines.extend(true_lines)
            else:
                lines.append(f"{base_indent}        pass")

        # Generate false branch
        if false_start != -1:
            lines.append(f"{base_indent}    else:")
            false_end = self._find_branch_end(operations, false_start + 1, label_map)
            false_ops = operations[false_start + 1 : false_end]
            false_lines = self._generate_router_operations(false_ops, indent + 1)
            if false_lines:
                lines.extend(false_lines)
            else:
                lines.append(f"{base_indent}        pass")

        # Find after_if label to skip to
        next_idx = max(true_end if true_start != -1 else start_idx, false_end if false_start != -1 else start_idx)

        # Skip the after_if label if present
        if next_idx < len(operations) and isinstance(operations[next_idx], Label):
            next_idx += 1

        return lines, next_idx

    def _find_branch_end(
        self,
        operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall],
        start_idx: int,
        label_map: dict[str, int],
    ) -> int:
        """Find the end of a branch (before Goto or Label)."""
        for idx in range(start_idx, len(operations)):
            op = operations[idx]
            if isinstance(op, Goto | Label):
                return idx
        return len(operations)

    def _collect_actors_from_steps(self, steps: list[ActorCall | Router]) -> list[str]:
        """Collect all actors from scene steps."""
        actors = []
        for step in steps:
            if isinstance(step, ActorCall):
                actors.append(step.qualified_name)
            elif isinstance(step, Router):
                actors.append(step.router_id)
        return actors

    def _format_actor(self, actor: str) -> str:
        """Format actor for code generation."""
        if actor.startswith("router_"):
            return actor
        else:
            return f'resolve("{actor}")'

    def _format_class_arg(self, arg) -> str:
        """Format class constructor argument."""
        import ast

        return ast.unparse(arg)
