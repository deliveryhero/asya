"""
Diagram generator for Flow DSL.

Generates DOT language diagrams from FlowIR showing execution contexts (routers and actors).
"""

from pathlib import Path

from asya_cli.flow.ir import (
    Assignment,
    Break,
    Continue,
    FlowIR,
    HandlerCall,
    IfBlock,
    Operation,
    Return,
    WhileLoop,
)


class DiagramGenerator:
    """
    Generate flow diagrams in DOT format with execution contexts.

    Shows which router/actor executes which code using nested clusters.
    """

    def __init__(self, flow_ir: FlowIR):
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
        self.dot_lines.append(
            f'  {start_node} [label="{self.flow_ir.name}", shape=ellipse, style=filled, fillcolor=lightgreen];'
        )

        end_node = self._new_node()
        self.dot_lines.append(f'  {end_node} [label="End", shape=ellipse, style=filled, fillcolor=lightcoral];')
        self.dot_lines.append("")

        entrypoint_exit = self._generate_entrypoint(start_node)

        last_node = self._process_operations(self.flow_ir.operations, entrypoint_exit, end_node, router_context=None)

        if last_node != end_node:
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

    def _generate_entrypoint(self, start_node: str) -> str:
        """
        Generate entrypoint cluster.

        Args:
            start_node: Starting node to connect from

        Returns:
            Exit node from entrypoint
        """
        cluster_id = self._new_cluster()
        entry_node = self._new_node()
        exit_node = self._new_node()

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append("    style=filled;")
        self.dot_lines.append("    fillcolor=lightgrey;")
        self.dot_lines.append(f'    label="{self.flow_ir.name}_entrypoint";')
        self.dot_lines.append("")
        self.dot_lines.append(f'    {entry_node} [label="Entry", shape=circle, width=0.5];')
        self.dot_lines.append(
            f'    {exit_node} [label="Setup route", shape=box, style="rounded,filled", fillcolor=white];'
        )
        self.dot_lines.append(f"    {entry_node} -> {exit_node};")
        self.dot_lines.append("  }")
        self.dot_lines.append("")

        self.edges.append(f"  {start_node} -> {entry_node};")

        return exit_node

    def _process_operations(
        self,
        operations: list[Operation],
        prev_node: str,
        end_node: str,
        router_context: str | None = None,
        loop_start_node: str | None = None,
        loop_end_node: str | None = None,
    ) -> str:
        """
        Process a list of operations and generate DOT nodes/edges.

        Args:
            operations: List of operations to process
            prev_node: Previous node to connect from
            end_node: Final end node for returns
            router_context: Current router context (cluster name)
            loop_start_node: Node to connect to for 'continue'
            loop_end_node: Node to connect to for 'break'

        Returns:
            Last node ID in the sequence
        """
        current_node = prev_node

        for op in operations:
            if isinstance(op, HandlerCall):
                current_node = self._process_handler_call(op, current_node)

            elif isinstance(op, Assignment):
                current_node = self._process_assignment(op, current_node, router_context)

            elif isinstance(op, IfBlock):
                current_node = self._process_if_block(op, current_node, end_node, loop_start_node, loop_end_node)

            elif isinstance(op, WhileLoop):
                current_node = self._process_while_loop(op, current_node, end_node)

            elif isinstance(op, Break):
                if loop_end_node:
                    self.edges.append(f'  {current_node} -> {loop_end_node} [label="break", color=red];')
                    return loop_end_node
                else:
                    break_node = self._new_node()
                    self.dot_lines.append(
                        f'  {break_node} [label="break", shape=diamond, style=filled, fillcolor=pink];'
                    )
                    self.edges.append(f"  {current_node} -> {break_node};")
                    return break_node

            elif isinstance(op, Continue):
                if loop_start_node:
                    self.edges.append(f'  {current_node} -> {loop_start_node} [label="continue", color=blue];')
                    return loop_start_node
                else:
                    continue_node = self._new_node()
                    self.dot_lines.append(
                        f'  {continue_node} [label="continue", shape=diamond, style=filled, fillcolor=lightblue];'
                    )
                    self.edges.append(f"  {current_node} -> {continue_node};")
                    return continue_node

            elif isinstance(op, Return):
                self.edges.append(f'  {current_node} -> {end_node} [label="return"];')
                return end_node

        return current_node

    def _process_handler_call(self, op: HandlerCall, prev_node: str) -> str:
        """Process handler call operation as a cluster."""
        cluster_id = self._new_cluster()
        entry_node = self._new_node()
        handler_node = self._new_node()
        exit_node = self._new_node()

        actor_name = self._escape_label(op.func_name)

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append("    style=filled;")
        self.dot_lines.append("    fillcolor=lightblue;")
        self.dot_lines.append(f'    label="{actor_name}";')
        self.dot_lines.append("")
        self.dot_lines.append(f'    {entry_node} [label="Entry", shape=circle, width=0.5];')
        self.dot_lines.append(
            f'    {handler_node} [label="Execute\\n{actor_name}", shape=box, style="rounded,filled", fillcolor=white];'
        )
        self.dot_lines.append(f'    {exit_node} [label="Exit", shape=circle, width=0.5];')
        self.dot_lines.append(f"    {entry_node} -> {handler_node} -> {exit_node};")
        self.dot_lines.append("  }")
        self.dot_lines.append("")

        self.edges.append(f"  {prev_node} -> {entry_node};")

        return exit_node

    def _process_assignment(self, op: Assignment, prev_node: str, router_context: str | None) -> str:
        """Process assignment operation."""
        assign_node = self._new_node()
        if op.key:
            label = self._escape_label(f'p["{op.key}"] = ...')
        else:
            label = self._escape_label(f"{op.target} = ...")

        self.dot_lines.append(f'  {assign_node} [label="{label}", shape=note, style=filled, fillcolor=lightyellow];')
        self.edges.append(f"  {prev_node} -> {assign_node};")
        return assign_node

    def _process_if_block(
        self,
        op: IfBlock,
        prev_node: str,
        end_node: str,
        loop_start_node: str | None,
        loop_end_node: str | None,
    ) -> str:
        """Process if/elif/else block as a router cluster."""
        cluster_id = self._new_cluster()
        router_name = op.router_id or "if_router"

        entry_node = self._new_node()
        condition_node = self._new_node()
        exit_node = self._new_node()

        condition_label = self._escape_label(op.condition_str)

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append("    style=filled;")
        self.dot_lines.append("    fillcolor=wheat;")
        self.dot_lines.append(f'    label="{router_name}";')
        self.dot_lines.append("")
        self.dot_lines.append(f'    {entry_node} [label="Entry", shape=circle, width=0.5];')
        self.dot_lines.append(
            f'    {condition_node} [label="Check:\\n{condition_label}", shape=diamond, style=filled, fillcolor=white];'
        )
        self.dot_lines.append(f"    {entry_node} -> {condition_node};")
        self.dot_lines.append("  }")
        self.dot_lines.append("")

        self.edges.append(f"  {prev_node} -> {entry_node};")

        if op.then_ops:
            branch_exit = self._new_node()
            self.dot_lines.append(f'  {branch_exit} [label="", shape=point, width=0.1];')
            self.edges.append(f'  {condition_node} -> {branch_exit} [label="true", color=green];')
            then_last = self._process_operations(
                op.then_ops, branch_exit, end_node, router_name, loop_start_node, loop_end_node
            )
            if then_last != end_node:
                self.edges.append(f"  {then_last} -> {exit_node};")
        else:
            self.edges.append(f'  {condition_node} -> {exit_node} [label="true", color=green];')

        prev_condition = condition_node
        for elif_cond, elif_cond_str, elif_ops in op.elif_blocks:
            elif_cluster = self._new_cluster()
            elif_entry = self._new_node()
            elif_condition = self._new_node()
            elif_label = self._escape_label(elif_cond_str)

            self.dot_lines.append(f"  subgraph {elif_cluster} {{")
            self.dot_lines.append("    style=filled;")
            self.dot_lines.append("    fillcolor=wheat;")
            self.dot_lines.append(f'    label="{router_name} elif";')
            self.dot_lines.append("")
            self.dot_lines.append(f'    {elif_entry} [label="Entry", shape=circle, width=0.5];')
            self.dot_lines.append(
                f'    {elif_condition} [label="Check:\\n{elif_label}", shape=diamond, style=filled, fillcolor=white];'
            )
            self.dot_lines.append(f"    {elif_entry} -> {elif_condition};")
            self.dot_lines.append("  }")
            self.dot_lines.append("")

            self.edges.append(f'  {prev_condition} -> {elif_entry} [label="false", color=red];')

            if elif_ops:
                branch_exit = self._new_node()
                self.dot_lines.append(f'  {branch_exit} [label="", shape=point, width=0.1];')
                self.edges.append(f'  {elif_condition} -> {branch_exit} [label="true", color=green];')
                elif_last = self._process_operations(
                    elif_ops, branch_exit, end_node, router_name, loop_start_node, loop_end_node
                )
                if elif_last != end_node:
                    self.edges.append(f"  {elif_last} -> {exit_node};")
            else:
                self.edges.append(f'  {elif_condition} -> {exit_node} [label="true", color=green];')

            prev_condition = elif_condition

        if op.else_ops:
            else_branch = self._new_node()
            self.dot_lines.append(f'  {else_branch} [label="", shape=point, width=0.1];')
            self.edges.append(f'  {prev_condition} -> {else_branch} [label="else", color=red];')
            else_last = self._process_operations(
                op.else_ops, else_branch, end_node, router_name, loop_start_node, loop_end_node
            )
            if else_last != end_node:
                self.edges.append(f"  {else_last} -> {exit_node};")
        else:
            self.edges.append(f'  {prev_condition} -> {exit_node} [label="false", color=red];')

        return exit_node

    def _process_while_loop(self, op: WhileLoop, prev_node: str, end_node: str) -> str:
        """Process while loop as a router cluster."""
        cluster_id = self._new_cluster()
        router_name = op.router_id or "while_router"

        entry_node = self._new_node()
        condition_node = self._new_node()
        exit_node = self._new_node()

        condition_label = self._escape_label(f"while {op.condition_str}")

        self.dot_lines.append(f"  subgraph {cluster_id} {{")
        self.dot_lines.append("    style=filled;")
        self.dot_lines.append("    fillcolor=wheat;")
        self.dot_lines.append(f'    label="{router_name}";')
        self.dot_lines.append("")
        self.dot_lines.append(f'    {entry_node} [label="Entry", shape=circle, width=0.5];')
        self.dot_lines.append(
            f'    {condition_node} [label="Check:\\n{condition_label}", shape=diamond, style=filled, fillcolor=white];'
        )
        self.dot_lines.append(f"    {entry_node} -> {condition_node};")
        self.dot_lines.append("  }")
        self.dot_lines.append("")

        self.edges.append(f"  {prev_node} -> {entry_node};")

        if op.body_ops:
            branch_exit = self._new_node()
            self.dot_lines.append(f'  {branch_exit} [label="", shape=point, width=0.1];')
            self.edges.append(f'  {condition_node} -> {branch_exit} [label="true", color=green];')
            body_last = self._process_operations(
                op.body_ops, branch_exit, end_node, router_name, condition_node, exit_node
            )
            if body_last != end_node and body_last != exit_node:
                self.edges.append(f'  {body_last} -> {condition_node} [label="loop", color=blue];')
        else:
            self.edges.append(f'  {condition_node} -> {condition_node} [label="true", color=green];')

        self.edges.append(f'  {condition_node} -> {exit_node} [label="false", color=red];')

        return exit_node

    def _escape_label(self, text: str) -> str:
        """Escape special characters in DOT labels."""
        return text.replace('"', '\\"').replace("\n", "\\n")


def generate_diagram(
    flow_ir: FlowIR, output_dot: str | None = None, output_png: str | None = None
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
            )

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
            )

    return dot_content, png_path
