import textwrap  # Standard Python library for wrapping text
from pathlib import Path

# Assuming these classes are available from your provided context
from asya_cli.scene.ir import (
    Assignment,
    Break,
    Continue,
    HandlerCall,
    IfBlock,
    Operation,
    Return,
    SceneIR,
    WhileLoop,
)


class DiagramGenerator:
    """
    Generate flow diagrams in DOT format with execution contexts.

    Shows which router/actor executes which code using nested clusters.
    """

    def __init__(self, flow_ir: SceneIR, max_label_width: int = 30):
        """
        Initialize diagram generator.

        Args:
            flow_ir: Flow intermediate representation
        """
        self.flow_ir = flow_ir
        self.node_counter = 0
        self.cluster_counter = 0
        self.dot_lines: list[str] = []
        self.edges: list[str] = []
        self.max_label_width = max_label_width

    def _wrap_label(self, text: str) -> str:
        """Wrap a string to max_label_width using textwrap and prepare for DOT."""
        # Replace newlines with a space temporarily for clean wrapping, then wrap
        clean_text = text.replace("\n", " ")
        wrapped_text = textwrap.fill(clean_text, width=self.max_label_width)
        return wrapped_text

    # --- Core DOT Generation Methods ---

    def generate_dot(self) -> str:
        """
        Generate DOT language representation of the flow.

        Returns:
            DOT format string
        """
        self.dot_lines = []
        self.edges = []
        self.node_counter = 0
        self.cluster_counter = 0

        self.dot_lines.append("digraph flow {")
        self.dot_lines.append("  rankdir=TB;")
        self.dot_lines.append("  compound=true;")
        self.dot_lines.append("  node [shape=box, style=rounded];")
        self.dot_lines.append("")

        start_node = self._new_node()
        start_label = self._escape_label(self._wrap_label(self.flow_ir.name))
        self.dot_lines.append(
            f'  {start_node} [label="{start_label}", shape=ellipse, style=filled, fillcolor=lightgreen];'
        )

        end_node = self._new_node()
        self.dot_lines.append(f'  {end_node} [label="End", shape=ellipse, style=filled, fillcolor=lightcoral];')
        self.dot_lines.append("")

        last_nodes = self._process_operations(self.flow_ir.operations, [start_node], end_node, router_context=None)

        for last_node in last_nodes:
            self.edges.append(f"  {last_node} -> {end_node};")

        for edge in self.edges:
            self.dot_lines.append(edge)

        self.dot_lines.append("}")
        return "\n".join(self.dot_lines)

    def _new_node(self) -> str:
        """Generate unique node identifier."""
        node = f"n{self.node_counter}"
        self.node_counter += 1
        return node

    def _new_cluster(self) -> str:
        """Generate unique cluster identifier."""
        cluster = f"cluster_{self.cluster_counter}"
        self.cluster_counter += 1
        return cluster

    def _process_operations(
        self,
        operations: list[Operation],
        prev_nodes: list[str],
        end_node: str,
        router_context: str | None = None,
        loop_start_node: str | None = None,
        loop_end_node: str | None = None,
    ) -> list[str]:
        """
        Process a list of operations and generate DOT nodes/edges.
        """
        current_nodes = prev_nodes

        for op in operations:
            if isinstance(op, HandlerCall):
                handler_node = self._process_handler_call(op, current_nodes)
                current_nodes = [handler_node]

            elif isinstance(op, Assignment):
                assign_node = self._process_assignment(op, current_nodes, router_context)
                current_nodes = [assign_node]

            elif isinstance(op, IfBlock):
                current_nodes = self._process_if_block(op, current_nodes, end_node, loop_start_node, loop_end_node)

            elif isinstance(op, WhileLoop):
                current_nodes = self._process_while_loop(op, current_nodes, end_node)

            elif isinstance(op, Break) or isinstance(op, Continue):
                return current_nodes

            elif isinstance(op, Return):
                for node in current_nodes:
                    self.edges.append(f'  {node} -> {end_node} [label="return"];')
                return []

        return current_nodes

    def _process_handler_call(self, op: HandlerCall, prev_nodes: list[str]) -> str:
        """Process handler call operation as a cluster."""
        cluster_id = self._new_cluster()
        handler_node = self._new_node()

        handler_name = self._escape_label(self._wrap_label(op.func_name))
        actor_name = ""  # XXX: support mapping of handlers to actor names

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append("    style=filled;")
        self.dot_lines.append("    fillcolor=lightblue;")
        self.dot_lines.append(f'    label="{actor_name}";')
        self.dot_lines.append("")
        self.dot_lines.append(
            f'    {handler_node} [label="{handler_name}", shape=box, style="rounded,filled", fillcolor=white, width=2, height=0.5];'
        )
        self.dot_lines.append("  }")
        self.dot_lines.append("")

        for prev_node in prev_nodes:
            self.edges.append(f"  {prev_node} -> {handler_node};")

        return handler_node

    def _process_assignment(self, op: Assignment, prev_nodes: list[str], router_context: str | None) -> str:
        """Process assignment operation."""
        assign_node = self._new_node()

        full_label = f'p["{op.key}"] = ...' if op.key else f"{op.target} = ..."
        label = self._escape_label(self._wrap_label(full_label))

        self.dot_lines.append(f'  {assign_node} [label="{label}", shape=note, style=filled, fillcolor=lightyellow];')
        for prev_node in prev_nodes:
            self.edges.append(f"  {prev_node} -> {assign_node};")
        return assign_node

    def _process_if_block(
        self,
        op: IfBlock,
        prev_nodes: list[str],
        end_node: str,
        loop_start_node: str | None,
        loop_end_node: str | None,
    ) -> list[str]:
        """Process if/elif/else block as a router cluster."""
        cluster_id = self._new_cluster()
        router_name = op.router_id or "if_router"

        condition_nodes = []
        condition_node = self._new_node()
        condition_nodes.append(condition_node)

        condition_label = self._escape_label(self._wrap_label(op.condition_str))

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append("    style=filled;")
        self.dot_lines.append("    fillcolor=wheat;")
        self.dot_lines.append(f'    label="{router_name}";')
        self.dot_lines.append("")
        self.dot_lines.append(
            f'    {condition_node} [label="{condition_label}", shape=diamond, style=filled, fillcolor=white];'
        )

        for _elif_cond, elif_cond_str, _elif_ops in op.elif_blocks:
            elif_condition = self._new_node()
            condition_nodes.append(elif_condition)
            elif_label = self._escape_label(self._wrap_label(elif_cond_str))
            self.dot_lines.append(
                f'    {elif_condition} [label="{elif_label}", shape=diamond, style=filled, fillcolor=white];'
            )

        for i in range(len(condition_nodes) - 1):
            self.dot_lines.append(
                f'    {condition_nodes[i]} -> {condition_nodes[i + 1]} [label="false", color=darkred];'
            )

        self.dot_lines.append("  }")
        self.dot_lines.append("")

        for prev_node in prev_nodes:
            self.edges.append(f"  {prev_node} -> {condition_node};")

        branch_endings = []

        if op.then_ops:
            num_edges_before = len(self.edges)
            then_last_nodes = self._process_operations(
                op.then_ops, [condition_node], end_node, router_name, loop_start_node, loop_end_node
            )
            if len(self.edges) > num_edges_before and "label=" not in self.edges[num_edges_before]:
                self.edges[num_edges_before] = (
                    self.edges[num_edges_before].rstrip(";") + ' [label="true", color=darkgreen];'
                )
            branch_endings.extend(then_last_nodes)
        else:
            branch_endings.append(condition_node)

        for i, (_elif_cond, _elif_cond_str, elif_ops) in enumerate(op.elif_blocks):
            elif_condition = condition_nodes[i + 1]
            if elif_ops:
                num_edges_before = len(self.edges)
                elif_last_nodes = self._process_operations(
                    elif_ops, [elif_condition], end_node, router_name, loop_start_node, loop_end_node
                )
                if len(self.edges) > num_edges_before and "label=" not in self.edges[num_edges_before]:
                    self.edges[num_edges_before] = (
                        self.edges[num_edges_before].rstrip(";") + ' [label="true", color=darkgreen];'
                    )
                branch_endings.extend(elif_last_nodes)
            else:
                branch_endings.append(elif_condition)

        last_condition = condition_nodes[-1]
        if op.else_ops:
            num_edges_before = len(self.edges)
            else_last_nodes = self._process_operations(
                op.else_ops, [last_condition], end_node, router_name, loop_start_node, loop_end_node
            )
            if len(self.edges) > num_edges_before and "label=" not in self.edges[num_edges_before]:
                self.edges[num_edges_before] = (
                    self.edges[num_edges_before].rstrip(";") + ' [label="false", color=darkred];'
                )
            branch_endings.extend(else_last_nodes)
        else:
            branch_endings.append(last_condition)

        return branch_endings

    def _process_while_loop(self, op: WhileLoop, prev_nodes: list[str], end_node: str) -> list[str]:
        """Process while loop as a router cluster (simplified as if-like structure)."""
        cluster_id = self._new_cluster()
        router_name = op.router_id or "while_router"

        condition_node = self._new_node()
        condition_label = self._escape_label(self._wrap_label(f"if {op.condition_str}"))

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append("    style=filled;")
        self.dot_lines.append("    fillcolor=wheat;")
        self.dot_lines.append(f'    label="{router_name}";')
        self.dot_lines.append("")
        self.dot_lines.append(
            f'    {condition_node} [label="{condition_label}", shape=diamond, style=filled, fillcolor=white];'
        )
        self.dot_lines.append("  }")
        self.dot_lines.append("")

        for prev_node in prev_nodes:
            self.edges.append(f"  {prev_node} -> {condition_node};")

        branch_endings = []

        if op.body_ops:
            num_edges_before = len(self.edges)
            body_last_nodes = self._process_operations(op.body_ops, [condition_node], end_node, router_name, None, None)
            if len(self.edges) > num_edges_before and "label=" not in self.edges[num_edges_before]:
                self.edges[num_edges_before] = (
                    self.edges[num_edges_before].rstrip(";") + ' [label="true", color=darkgreen];'
                )
            branch_endings.extend(body_last_nodes)

        branch_endings.append(condition_node)

        return branch_endings

    def _escape_label(self, text: str) -> str:
        """Escape special characters in DOT labels."""
        return text.replace('"', '\\"').replace("\n", "\\n")


def generate_diagram(
    flow_ir: SceneIR, output_dot: str | None = None, output_png: str | None = None
) -> tuple[str, str | None]:
    """
    Generate flow diagram.

    Args:
        flow_ir: Flow intermediate representation
        output_dot: Optional path to save DOT file
        output_png: Optional path to save PNG file (requires graphviz Python package)

    Returns:
        Tuple of (dot_content, png_path)
        png_path is None if PNG generation was skipped or failed

    Raises:
        ImportError: If graphviz Python package not installed (only when output_png specified)
    """
    generator = DiagramGenerator(flow_ir)
    dot_content = generator.generate_dot()

    if output_dot:
        Path(output_dot).write_text(dot_content)

    png_path = None
    if output_png:
        try:
            import graphviz
        except ImportError:
            raise ImportError(
                "graphviz Python package not installed. Install it to generate PNG diagrams:\n"
                "  pip install asya-cli[diagram]\n"
                "  or: pip install graphviz\n"
                "  Or skip PNG generation and use only DOT output."
            ) from None

        try:
            src = graphviz.Source(dot_content)
            src.format = "png"
            output_path = Path(output_png)
            src.render(str(output_path.with_suffix("")), cleanup=True)
            png_path = output_png
        except Exception as e:
            raise RuntimeError(
                f"Failed to generate PNG diagram: {e}\n"
                "The graphviz Python package requires system graphviz executables.\n"
                "Install system graphviz:\n"
                "  Ubuntu/Debian: sudo apt-get install graphviz\n"
                "  macOS: brew install graphviz"
            ) from e

    return dot_content, png_path
