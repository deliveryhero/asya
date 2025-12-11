"""Generate DOT diagrams for scene visualization."""

from typing import Dict, List, Set

from asya_cli.scene.grouper import Router


class DotGenerator:
    def __init__(self, scene_name: str, routers: List[Router]):
        self.scene_name = scene_name
        self.routers = routers
        self.user_actors: Set[str] = set()
        self.router_map: Dict[str, Router] = {}

    def generate(self) -> str:
        self._collect_actors()

        parts = []
        parts.append("digraph scene {")
        parts.append("  rankdir=TB;")
        parts.append('  node [fontname="Arial"];')
        parts.append('  edge [fontname="Arial"];')
        parts.append("")

        for router in self.routers:
            parts.append(self._generate_actor_node(router))

        for actor in sorted(self.user_actors):
            parts.append(self._generate_user_actor_node(actor))

        parts.append("")

        for router in self.routers:
            edges = self._generate_edges(router)
            if edges:
                parts.append(edges)

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
        if router.name.startswith("start_"):
            color = "lightgreen"
        elif router.name.startswith("end_"):
            color = "lightgreen"
        else:
            color = "lightyellow"

        label_parts = []
        label_parts.append(f'<tr><td bgcolor="{color}" align="center"><b>{router.name}</b></td></tr>')

        handler_parts = []

        if router.mutations:
            mutations_html = "<br/>".join(self._escape_html(m.code) for m in router.mutations)
            handler_parts.append(f'<tr><td bgcolor="white" align="left">{mutations_html}</td></tr>')

        if router.condition:
            condition_html = self._escape_html(router.condition.test)
            handler_parts.append(f'<tr><td bgcolor="lightyellow" align="center"><b>if</b> {condition_html}</td></tr>')

            true_label = "TRUE" if router.true_branch_actors else "pass"
            false_label = "FALSE" if router.false_branch_actors else "pass"

            handler_parts.append(f'<tr><td><table border="0" cellspacing="0" cellpadding="4"><tr>')
            handler_parts.append(f'<td bgcolor="darkgreen" align="center"><font color="white">{true_label}</font></td>')
            handler_parts.append(f'<td bgcolor="darkred" align="center"><font color="white">{false_label}</font></td>')
            handler_parts.append(f"</tr></table></td></tr>")

        if handler_parts:
            label_parts.append(
                f'<tr><td><table border="1" cellspacing="0" cellpadding="4">{"".join(handler_parts)}</table></td></tr>'
            )

        label = f'<<table border="1" cellspacing="0" cellpadding="2">{"".join(label_parts)}</table>>'

        return f"  {self._node_id(router.name)} [shape=box, style=filled, fillcolor={color}, label={label}];"

    def _generate_user_actor_node(self, actor_name: str) -> str:
        label_parts = []
        label_parts.append(f'<tr><td bgcolor="lightgray" align="center"><b>{actor_name}</b></td></tr>')
        label_parts.append(
            f'<tr><td><table border="1" cellspacing="0" cellpadding="4"><tr><td bgcolor="white" align="center">user handler</td></tr></table></td></tr>'
        )

        label = f'<<table border="1" cellspacing="0" cellpadding="2">{"".join(label_parts)}</table>>'

        return f"  {self._node_id(actor_name)} [shape=box, style=filled, fillcolor=lightgray, label={label}];"

    def _generate_edges(self, router: Router) -> str:
        lines = []

        if router.condition:
            true_actors = router.true_branch_actors
            false_actors = router.false_branch_actors

            if true_actors:
                lines.append(
                    f'  {self._node_id(router.name)} -> {self._node_id(true_actors[0])} [color=darkgreen, label="true"];'
                )
                for i in range(len(true_actors) - 1):
                    lines.append(f"  {self._node_id(true_actors[i])} -> {self._node_id(true_actors[i + 1])};")

            if false_actors:
                lines.append(
                    f'  {self._node_id(router.name)} -> {self._node_id(false_actors[0])} [color=darkred, label="false"];'
                )
                for i in range(len(false_actors) - 1):
                    lines.append(f"  {self._node_id(false_actors[i])} -> {self._node_id(false_actors[i + 1])};")
        else:
            actors = router.true_branch_actors
            if actors:
                lines.append(f"  {self._node_id(router.name)} -> {self._node_id(actors[0])};")
                for i in range(len(actors) - 1):
                    lines.append(f"  {self._node_id(actors[i])} -> {self._node_id(actors[i + 1])};")

        return "\n".join(lines) if lines else ""

    def _node_id(self, name: str) -> str:
        return name.replace("-", "_")

    def _escape_html(self, text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
