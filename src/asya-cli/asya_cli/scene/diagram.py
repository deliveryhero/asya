"""
Scene DSL diagram generator.

Generates DOT language diagrams from Scene IR.
"""

import subprocess
from pathlib import Path

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


def generate_diagram(
    scene_ir: SceneIR, output_dot: str | None = None, output_png: str | None = None
) -> tuple[str, str | None]:
    """
    Generate DOT diagram from Scene IR.

    Args:
        scene_ir: Scene intermediate representation
        output_dot: Optional path to save DOT file
        output_png: Optional path to save PNG file (requires graphviz)

    Returns:
        Tuple of (dot_content, png_path)
        png_path is None if PNG generation was skipped or failed
    """
    generator = DiagramGenerator(scene_ir)
    dot_content = generator.generate()

    if output_dot:
        Path(output_dot).write_text(dot_content)

    png_path = None
    if output_png:
        try:
            result = subprocess.run(
                ["dot", "-Tpng", "-o", output_png],
                input=dot_content.encode(),
                capture_output=True,
                check=True,
            )
            png_path = output_png
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"Warning: Failed to generate PNG: {e}")

    return dot_content, png_path


class DiagramGenerator:
    """Generate DOT diagrams from Scene IR."""

    def __init__(self, scene_ir: SceneIR):
        self.scene_ir = scene_ir
        self.dot_lines: list[str] = []
        self.node_counter = 0

    def generate(self) -> str:
        """Generate DOT diagram."""
        self.dot_lines = []

        scene_name = self.scene_ir.name
        param_name = self.scene_ir.param_name

        self.dot_lines.append("digraph Scene {")
        self.dot_lines.append("  rankdir=TB;")
        self.dot_lines.append("  node [shape=box, style=rounded];")
        self.dot_lines.append("")

        # Entrypoint
        start_node = "start"
        self.dot_lines.append(f'  {start_node} [label="{scene_name}_start", shape=ellipse, fillcolor=lightgreen, style=filled];')

        prev_node = start_node
        for step in self.scene_ir.steps:
            if isinstance(step, ActorCall):
                step_node = self._process_actor_call(step, param_name)
                self.dot_lines.append(f"  {prev_node} -> {step_node};")
                prev_node = step_node
            elif isinstance(step, Router):
                step_node = self._process_router(step, param_name)
                self.dot_lines.append(f"  {prev_node} -> {step_node};")
                prev_node = step_node

        # Exit point
        end_node = "end"
        self.dot_lines.append(f'  {end_node} [label="{scene_name}_end", shape=ellipse, fillcolor=lightcoral, style=filled];')
        self.dot_lines.append(f"  {prev_node} -> {end_node};")

        self.dot_lines.append("}")
        return "\n".join(self.dot_lines)

    def _new_node(self) -> str:
        """Generate unique node ID."""
        self.node_counter += 1
        return f"n{self.node_counter}"

    def _escape_label(self, label: str) -> str:
        """Escape label for DOT."""
        return label.replace('"', '\\"')

    def _process_actor_call(self, actor: ActorCall, param_name: str) -> str:
        """Process ActorCall step - blue box with scene syntax label."""
        node_id = self._new_node()
        cluster_id = f"cluster_{node_id}"

        # Label: p = handler_name(p)
        step_label = f"{param_name} = {actor.display_name}({param_name})"
        step_label = self._escape_label(step_label)

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append('    label="";')
        self.dot_lines.append('    style="rounded,filled";')
        self.dot_lines.append('    color=blue;')
        self.dot_lines.append('    fillcolor=lightblue;')
        self.dot_lines.append(
            f'    {node_id} [label="{step_label}", shape=box, style="rounded", fillcolor=white, width=2, height=0.8];'
        )
        self.dot_lines.append("  }")

        return node_id

    def _process_router(self, router: Router, param_name: str) -> str:
        """Process Router step - brownish box with control flow graph."""
        cluster_id = f"cluster_router_{self.node_counter}"

        # Create invisible entry/exit nodes for connecting to scene flow
        router_entry = self._new_node()
        router_exit = self._new_node()

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append('    label="";')
        self.dot_lines.append('    style="rounded,filled";')
        self.dot_lines.append('    color="#8B4513";')
        self.dot_lines.append('    fillcolor="#DEB887";')

        # Invisible entry/exit points
        self.dot_lines.append(f'    {router_entry} [label="", shape=point, width=0.1];')
        self.dot_lines.append(f'    {router_exit} [label="", shape=point, width=0.1];')

        # Build label map
        label_map = {}
        for idx, op in enumerate(router.operations):
            if isinstance(op, Label):
                label_map[op.name] = idx

        # Generate nodes and edges for router operations
        self._generate_router_cfg(router.operations, param_name, label_map, router_entry, router_exit)

        self.dot_lines.append("  }")

        # Return a wrapper node for scene-level connections
        wrapper_node = self._new_node()
        self.dot_lines.append(f'  {wrapper_node} [label="", shape=point, width=0.01, style=invis];')
        self.dot_lines.append(f"  {wrapper_node} -> {router_entry} [style=invis];")
        self.dot_lines.append(f"  {router_exit} -> {wrapper_node} [style=invis];")

        return wrapper_node

    def _generate_router_cfg(
        self,
        operations: list,
        param_name: str,
        label_map: dict[str, int],
        entry_node: str,
        exit_node: str,
    ):
        """Generate control flow graph for router operations."""
        # Create nodes for operations
        op_nodes = {}
        for idx, op in enumerate(operations):
            if isinstance(op, Label):
                continue
            elif isinstance(op, Goto):
                continue
            elif isinstance(op, ConditionalGoto):
                # Decision point - invisible diamond
                node_id = self._new_node()
                self.dot_lines.append(f'    {node_id} [label="", shape=diamond, width=0.3, height=0.3, style=filled, fillcolor=white];')
                op_nodes[idx] = node_id
            elif isinstance(op, ActorCall):
                node_id = self._new_node()
                label = f"{param_name} = {str(op)}({param_name})"
                label = self._escape_label(label)
                self.dot_lines.append(f'    {node_id} [label="{label}", shape=box, style=rounded, fillcolor=white];')
                op_nodes[idx] = node_id
            elif isinstance(op, PayloadMutation):
                node_id = self._new_node()
                label = f'{param_name}["{op.key}"] = {str(op)}'
                label = self._escape_label(label)
                self.dot_lines.append(f'    {node_id} [label="{label}", shape=box, style=rounded, fillcolor=white];')
                op_nodes[idx] = node_id
            elif isinstance(op, ClassInstantiation):
                node_id = self._new_node()
                label = str(op)
                label = self._escape_label(label)
                self.dot_lines.append(f'    {node_id} [label="{label}", shape=box, style=rounded, fillcolor=white];')
                op_nodes[idx] = node_id

        # Connect entry to first operation
        first_op_idx = self._find_first_visible_op(operations, 0, op_nodes)
        if first_op_idx is not None:
            self.dot_lines.append(f"    {entry_node} -> {op_nodes[first_op_idx]};")

        # Generate edges based on control flow
        visited = set()
        self._connect_cfg_edges(operations, 0, label_map, op_nodes, entry_node, exit_node, visited)

    def _find_first_visible_op(self, operations: list, start_idx: int, op_nodes: dict) -> int | None:
        """Find first visible operation starting from start_idx."""
        for idx in range(start_idx, len(operations)):
            if idx in op_nodes:
                return idx
        return None

    def _connect_cfg_edges(
        self,
        operations: list,
        idx: int,
        label_map: dict[str, int],
        op_nodes: dict[int, str],
        entry_node: str,
        exit_node: str,
        visited: set[int],
    ):
        """Recursively connect CFG edges."""
        if idx >= len(operations) or idx in visited:
            return

        visited.add(idx)
        op = operations[idx]

        if isinstance(op, ConditionalGoto):
            # Decision node - ONLY follow goto targets, don't connect to next
            node_id = op_nodes[idx]

            # True branch (dark green)
            true_idx = label_map.get(op.true_target)
            if true_idx is not None:
                true_target_idx = self._find_first_visible_op(operations, true_idx + 1, op_nodes)
                if true_target_idx is not None:
                    self.dot_lines.append(f'    {node_id} -> {op_nodes[true_target_idx]} [color="darkgreen", label="true"];')
                    self._connect_cfg_edges(operations, true_target_idx, label_map, op_nodes, entry_node, exit_node, visited)
                else:
                    # True branch leads to exit
                    self.dot_lines.append(f'    {node_id} -> {exit_node} [color="darkgreen", label="true"];')

            # False branch (dark red)
            if op.false_target:
                false_idx = label_map.get(op.false_target)
                if false_idx is not None:
                    false_target_idx = self._find_first_visible_op(operations, false_idx + 1, op_nodes)
                    if false_target_idx is not None:
                        self.dot_lines.append(f'    {node_id} -> {op_nodes[false_target_idx]} [color="darkred", label="false"];')
                        self._connect_cfg_edges(operations, false_target_idx, label_map, op_nodes, entry_node, exit_node, visited)
                    else:
                        # False branch leads to exit
                        self.dot_lines.append(f'    {node_id} -> {exit_node} [color="darkred", label="false"];')

        elif isinstance(op, Goto):
            # Jump to target - find preceding operation to connect from
            prev_node = self._find_prev_visible_op(operations, idx, op_nodes)
            target_idx = label_map.get(op.target)

            if prev_node is not None and target_idx is not None:
                # Check for backward jump (loop)
                if target_idx <= idx:
                    # Backward jump - don't follow to avoid infinite loop
                    target_node_idx = self._find_first_visible_op(operations, target_idx + 1, op_nodes)
                    if target_node_idx is not None:
                        self.dot_lines.append(f'    {op_nodes[prev_node]} -> {op_nodes[target_node_idx]} [style=dashed, color=gray, label="loop"];')
                    else:
                        self.dot_lines.append(f'    {op_nodes[prev_node]} -> {exit_node} [style=dashed, color=gray, label="loop"];')
                else:
                    # Forward jump
                    target_node_idx = self._find_first_visible_op(operations, target_idx + 1, op_nodes)
                    if target_node_idx is not None:
                        self.dot_lines.append(f'    {op_nodes[prev_node]} -> {op_nodes[target_node_idx]};')
                        self._connect_cfg_edges(operations, target_node_idx, label_map, op_nodes, entry_node, exit_node, visited)
                    else:
                        self.dot_lines.append(f'    {op_nodes[prev_node]} -> {exit_node};')

        elif isinstance(op, Label):
            # Skip labels - they don't create nodes, continue traversal
            self._connect_cfg_edges(operations, idx + 1, label_map, op_nodes, entry_node, exit_node, visited)

        elif idx in op_nodes:
            # Regular operation - check what follows
            next_idx = idx + 1

            # Look ahead to see if next is Goto or end
            if next_idx < len(operations) and isinstance(operations[next_idx], Goto):
                # Goto follows - let Goto handler create the edge
                self._connect_cfg_edges(operations, next_idx, label_map, op_nodes, entry_node, exit_node, visited)
            else:
                # Connect to next visible operation or exit
                next_visible = self._find_first_visible_op(operations, next_idx, op_nodes)
                if next_visible is not None:
                    self.dot_lines.append(f"    {op_nodes[idx]} -> {op_nodes[next_visible]};")
                    self._connect_cfg_edges(operations, next_visible, label_map, op_nodes, entry_node, exit_node, visited)
                else:
                    # No more operations - connect to exit
                    self.dot_lines.append(f"    {op_nodes[idx]} -> {exit_node};")

    def _find_prev_visible_op(self, operations: list, idx: int, op_nodes: dict) -> int | None:
        """Find previous visible operation before idx."""
        for i in range(idx - 1, -1, -1):
            if i in op_nodes:
                return i
        return None
