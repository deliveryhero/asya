"""
Scene DSL diagram generator.

Generates DOT language diagrams from Scene IR.
"""

import subprocess
from pathlib import Path

from asya_cli.scene.ir import ActorCall, Router, SceneIR


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

        self.dot_lines.append("digraph Scene {")
        self.dot_lines.append("  rankdir=TB;")
        self.dot_lines.append("  node [shape=box, style=rounded];")
        self.dot_lines.append("")

        prev_node = "start"
        self.dot_lines.append(f'  {prev_node} [label="Start", shape=circle, fillcolor=lightgreen, style=filled];')

        for step in self.scene_ir.steps:
            if isinstance(step, ActorCall):
                step_node = self._process_actor_call(step)
                self.dot_lines.append(f"  {prev_node} -> {step_node};")
                prev_node = step_node
            elif isinstance(step, Router):
                step_node = self._process_router(step)
                self.dot_lines.append(f"  {prev_node} -> {step_node};")
                prev_node = step_node

        end_node = "end"
        self.dot_lines.append(f'  {end_node} [label="End", shape=circle, fillcolor=lightcoral, style=filled];')
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

    def _process_actor_call(self, actor: ActorCall) -> str:
        """Process ActorCall step."""
        node_id = self._new_node()
        cluster_id = f"cluster_{node_id}"

        actor_name = self._escape_label(actor.display_name)

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append(f'    label="{actor_name}";')
        self.dot_lines.append(
            f'    {node_id} [label="", shape=box, style="rounded,filled", fillcolor=white, width=2, height=0.5];'
        )
        self.dot_lines.append("  }")

        return node_id

    def _process_router(self, router: Router) -> str:
        """Process Router step."""
        node_id = self._new_node()
        cluster_id = f"cluster_{node_id}"

        router_label = self._escape_label(router.router_id)

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append(f'    label="{router_label}";')
        self.dot_lines.append('    style="rounded,dashed";')
        self.dot_lines.append("    color=blue;")

        # For now, just show the router as a single node
        # We could expand this to show internal control flow later
        self.dot_lines.append(
            f'    {node_id} [label="Control Flow\\n& Mutations", shape=box, style="rounded,filled", fillcolor=lightblue, width=2, height=1];'
        )
        self.dot_lines.append("  }")

        return node_id
