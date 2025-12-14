"""Generate DOT diagrams for flow visualization."""

from __future__ import annotations

from asya_cli.flow.grouper import Router


class DotGenerator:
    def __init__(
        self, flow_name: str, routers: list[Router], step_width: int = 50, class_methods: set[str] | None = None
    ):
        self.flow_name = flow_name
        self.routers = routers
        self.step_width = step_width
        self.user_actors: set[str] = set()
        self.router_map: dict[str, Router] = {}
        self.class_methods = class_methods or set()

    @staticmethod
    def _sanitize_node_id(name: str) -> str:
        """Sanitize node name for DOT syntax (replace dots with underscores)."""
        return name.replace(".", "_")

    def _get_display_name(self, full_name: str) -> str:
        """Extract readable display name from full module path.

        Examples:
            "class_instantiation.DataPreprocessor.clean" -> "DataPreprocessor.clean"
            "my_module.process_data" -> "process_data"
            "module.submodule.function" -> "function"
            "start_flow_name" -> "start_flow_name"
        """
        parts = full_name.split(".")
        if len(parts) >= 2:
            # Check if this is a known class method
            if full_name in self.class_methods:
                # Class method: show ClassName.method
                return f"{parts[-2]}.{parts[-1]}"
            else:
                # Module function: show just function name
                return parts[-1]
        # Function or special router: show as-is
        return full_name

    def _truncate_display_name(self, display_name: str) -> str:
        """Truncate display name if it exceeds step_width."""
        full_text = f"p = {display_name}(p)"
        if len(full_text) <= self.step_width:
            return full_text
        # Truncate with ellipsis
        cut = "…"
        max_len = self.step_width - len("p = (p)") - len(cut)
        if max_len > 0:
            return f"p = {display_name[:max_len]}{cut}(p)"
        return full_text

    def generate(self) -> str:
        self._collect_actors()

        parts = []
        parts.append("digraph flow {")
        parts.append("  rankdir=TB;")
        parts.append('  graph [fontname="Courier", fontsize=10];')
        parts.append('  node [fontname="Courier", fontsize=10, shape=box, style="filled,rounded", margin="0.2"];')
        parts.append('  edge [fontname="Courier", fontsize=10];')
        parts.append("")

        for router in self.routers:
            parts.append(self._generate_actor_node(router))

        for actor in sorted(self.user_actors):
            parts.append(self._generate_user_actor_node(actor))

        parts.append("")

        all_edges = set()
        for router in self.routers:
            edges = self._generate_edges(router)
            all_edges.update(edges)

        if all_edges:
            for edge in sorted(all_edges):
                parts.append(edge)

        parts.append("}")

        return "\n".join(parts)

    def _collect_actors(self) -> None:
        for router in self.routers:
            self.router_map[router.name] = router

        for router in self.routers:
            for actor in router.true_branch_actors:
                if actor not in self.router_map:
                    self.user_actors.add(actor)
            for actor in router.false_branch_actors:
                if actor not in self.router_map:
                    self.user_actors.add(actor)

    def _generate_actor_node(self, router: Router) -> str:
        color = "lightgreen" if router.name.startswith("start_") or router.name.startswith("end_") else "wheat"

        rows = []
        display_name = self._get_display_name(router.name)
        truncated_name = self._truncate_display_name(display_name)
        rows.append(f'<tr><td bgcolor="white" align="center"><i>{self._escape_html(truncated_name)}</i></td></tr>')

        if router.mutations:
            for mutation in router.mutations:
                truncated_code = self._truncate_text(mutation.code)
                rows.append(f'<tr><td bgcolor="white" align="left">{self._escape_html(truncated_code)}</td></tr>')

        if router.condition:
            truncated_test = self._truncate_text(router.condition.test)
            rows.append(f'<tr><td bgcolor="lightyellow"><b>if</b> {self._escape_html(truncated_test)}</td></tr>')

            true_label = "TRUE" if router.true_branch_actors else "pass"
            false_label = "FALSE" if router.false_branch_actors else "pass"

            rows.append(
                f'<tr><td><table border="0" cellspacing="0" cellpadding="4"><tr>'
                f'<td bgcolor="darkgreen"><font color="white"><b>{true_label}</b></font></td>'
                f'<td bgcolor="darkred"><font color="white"><b>{false_label}</b></font></td>'
                f"</tr></table></td></tr>"
            )

        label = f'<<table border="0" cellspacing="0" cellpadding="6" cellborder="1">{"".join(rows)}</table>>'

        return f'  {self._node_id(router.name)} [fillcolor="{color}", label={label}];'

    def _generate_user_actor_node(self, actor_name: str) -> str:
        display_name = self._get_display_name(actor_name)
        truncated_name = self._truncate_display_name(display_name)
        label = (
            f'<<table border="0" cellspacing="0" cellpadding="6" cellborder="1">'
            f'<tr><td bgcolor="white" align="center">'
            f"<i>{self._escape_html(truncated_name)}</i></td></tr>"
            f"</table>>"
        )

        return f'  {self._node_id(actor_name)} [fillcolor="lightblue", label={label}];'

    def _generate_edges(self, router: Router) -> set[str]:
        lines = set()

        if router.condition:
            true_actors = router.true_branch_actors
            false_actors = router.false_branch_actors

            if true_actors:
                lines.add(f"  {self._node_id(router.name)} -> {self._node_id(true_actors[0])} [color=darkgreen];")
                for i in range(len(true_actors) - 1):
                    lines.add(f"  {self._node_id(true_actors[i])} -> {self._node_id(true_actors[i + 1])};")

            if false_actors:
                lines.add(f"  {self._node_id(router.name)} -> {self._node_id(false_actors[0])} [color=darkred];")
                for i in range(len(false_actors) - 1):
                    lines.add(f"  {self._node_id(false_actors[i])} -> {self._node_id(false_actors[i + 1])};")
        else:
            actors = router.true_branch_actors
            if actors:
                lines.add(f"  {self._node_id(router.name)} -> {self._node_id(actors[0])};")
                for i in range(len(actors) - 1):
                    lines.add(f"  {self._node_id(actors[i])} -> {self._node_id(actors[i + 1])};")

        return lines

    def _node_id(self, name: str) -> str:
        return name.replace("-", "_").replace(".", "_")

    def _escape_html(self, text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def _truncate_text(self, text: str) -> str:
        if len(text) <= self.step_width:
            return text
        postfix_len = 12  # approx to have 'line_XX' included
        cut = "…"
        prefix_len = self.step_width - postfix_len - len(cut)
        return f"{text[:prefix_len]}{cut}{text[-postfix_len:]}"
