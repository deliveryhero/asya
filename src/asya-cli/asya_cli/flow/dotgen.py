"""Generate DOT diagrams for flow visualization."""

from __future__ import annotations

from dataclasses import dataclass, field

from asya_cli.flow.grouper import Router


@dataclass
class _TryCluster:
    """Visualization info for a try-except block rendered as a dashed cluster."""

    cluster_name: str
    try_enter_name: str
    cluster_actors: set[str]
    anchor_node: str | None
    try_exit_name: str
    except_dispatch: Router | None
    finally_actors: list[str] = field(default_factory=list)


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
        self._hidden_routers: set[str] = set()
        self._redirect_map: dict[str, str] = {}
        self._try_clusters: list[_TryCluster] = []
        self._cluster_membership: dict[str, str] = {}
        self._color_error_control_flow = "snow4"
        self._color_true_branch = "darkseagreen4"
        self._color_false_branch = "indianred4"
        self._color_raise = "crimson"
        self._color_finally = "gray50"

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
        self._build_try_info()

        parts = []
        parts.append("digraph flow {")
        parts.append("  rankdir=TB;")
        if self._try_clusters:
            parts.append("  compound=true;")
        parts.append('  graph [fontname="Courier", fontsize=10];')
        parts.append('  node [fontname="Courier", fontsize=10, shape=box, style="filled,rounded", margin="0.2"];')
        parts.append('  edge [fontname="Courier", fontsize=10];')
        parts.append("")

        # Non-cluster, non-hidden router nodes
        for router in self.routers:
            if router.name in self._hidden_routers:
                continue
            if router.name in self._cluster_membership:
                continue
            parts.append(self._generate_actor_node(router))

        # Non-cluster user actor nodes
        for actor in sorted(self.user_actors):
            if actor in self._cluster_membership:
                continue
            parts.append(self._generate_user_actor_node(actor))

        # Try clusters (subgraph blocks with contained node definitions)
        for cluster in self._try_clusters:
            parts.extend(self._generate_try_cluster(cluster))

        parts.append("")

        # Edges
        all_edges = set()
        for router in self.routers:
            if router.name in self._hidden_routers:
                if router.is_try_enter:
                    all_edges.update(self._generate_try_block_edges(router))
                continue
            all_edges.update(self._generate_edges(router))

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
            for actor in router.finally_actors:
                if actor not in self.router_map:
                    self.user_actors.add(actor)
            for actor in router.continuation_actors:
                if actor not in self.router_map:
                    self.user_actors.add(actor)
            if router.exception_handlers:
                for handler in router.exception_handlers:
                    for actor in handler.actors:
                        if actor not in self.router_map:
                            self.user_actors.add(actor)

    def _build_try_info(self) -> None:
        """Build try cluster info, hidden routers set, and redirect map."""
        cluster_id = 0
        for router in self.routers:
            if not router.is_try_enter:
                continue

            # Derive try_exit name from naming convention
            try_exit_name = router.name.replace("_try_enter_", "_try_exit_")
            except_dispatch_name = router.except_dispatch_name
            except_dispatch = self.router_map.get(except_dispatch_name) if except_dispatch_name else None
            reraise_name = except_dispatch.reraise_name if except_dispatch else None

            # Collect actors inside the cluster (body chain, excluding infrastructure)
            exclude = {try_exit_name}
            if except_dispatch_name:
                exclude.add(except_dispatch_name)
            if reraise_name:
                exclude.add(reraise_name)
            cluster_actors = self._collect_cluster_actors(router.true_branch_actors, exclude)

            cluster_name = f"cluster_try_{cluster_id}"
            for actor in cluster_actors:
                self._cluster_membership[actor] = cluster_name

            # Pick anchor node (last actor in body chain inside the cluster for ltail edges)
            anchor = None
            for a in reversed(router.true_branch_actors):
                if a in cluster_actors:
                    anchor = a
                    break

            # Collect finally actors for cluster visualization
            try_exit_router = self.router_map.get(try_exit_name)
            finally_actors_list = try_exit_router.finally_actors if try_exit_router else []
            if finally_actors_list:
                finally_cluster_name = f"cluster_finally_{cluster_id}"
                for actor in finally_actors_list:
                    self._cluster_membership[actor] = finally_cluster_name

            self._try_clusters.append(
                _TryCluster(
                    cluster_name=cluster_name,
                    try_enter_name=router.name,
                    cluster_actors=cluster_actors,
                    anchor_node=anchor,
                    try_exit_name=try_exit_name,
                    except_dispatch=except_dispatch,
                    finally_actors=finally_actors_list,
                )
            )
            cluster_id += 1

            # Mark infrastructure routers as hidden
            self._hidden_routers.add(router.name)
            self._hidden_routers.add(try_exit_name)
            if except_dispatch_name:
                self._hidden_routers.add(except_dispatch_name)
            if reraise_name:
                self._hidden_routers.add(reraise_name)

            # Redirect map: try_enter → first body actor
            if router.true_branch_actors:
                first_body = router.true_branch_actors[0]
                if first_body != try_exit_name:
                    self._redirect_map[router.name] = first_body

            # Redirect map: try_exit → first continuation actor
            try_exit_router = self.router_map.get(try_exit_name)
            if try_exit_router:
                continuation = [*try_exit_router.finally_actors, *try_exit_router.continuation_actors]
                if continuation:
                    self._redirect_map[try_exit_name] = continuation[0]
                else:
                    # Fallback: find the actor after the try block in its parent chain
                    post_try = self._find_post_try_actor(router.name)
                    if post_try:
                        self._redirect_map[try_exit_name] = post_try

    def _collect_cluster_actors(self, body_actors: list[str], exclude: set[str]) -> set[str]:
        """Recursively collect all actors inside a try body cluster."""
        result: set[str] = set()
        to_visit = list(body_actors)
        while to_visit:
            actor = to_visit.pop()
            if actor in result or actor in exclude:
                continue
            result.add(actor)
            router = self.router_map.get(actor)
            if router:
                for a in router.true_branch_actors:
                    if a not in result and a not in exclude:
                        to_visit.append(a)
                for a in router.false_branch_actors:
                    if a not in result and a not in exclude:
                        to_visit.append(a)
        return result

    def _find_post_try_actor(self, try_enter_name: str) -> str | None:
        """Find the actor that follows the try block in its parent router's actor list.

        When a try-except is the last operation in a while loop body, the try-except's
        continuation is empty, but the loop_back router follows in the parent while
        condition's true_branch_actors. This method traces through wrapper routers
        (seq routers that contain the try_enter) to find that next actor.
        """
        for router in self.routers:
            for i, actor in enumerate(router.true_branch_actors):
                # Direct reference to try_enter
                if actor == try_enter_name and i + 1 < len(router.true_branch_actors):
                    return router.true_branch_actors[i + 1]
                # Through a wrapping seq_router (mutations before try create a wrapper)
                sub_router = self.router_map.get(actor)
                if (
                    sub_router
                    and not sub_router.condition
                    and try_enter_name in sub_router.true_branch_actors
                    and i + 1 < len(router.true_branch_actors)
                ):
                    return router.true_branch_actors[i + 1]
        return None

    def _resolve(self, name: str) -> str:
        """Resolve an actor name, replacing hidden try infrastructure routers."""
        return self._redirect_map.get(name, name)

    # ── Node generation ──────────────────────────────────────────────

    def _generate_actor_node(self, router: Router) -> str:
        if router.name.startswith("start_") or router.name.startswith("end_"):
            color = "lightgreen"
        else:
            color = "wheat"

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
                f'<td bgcolor="{self._color_true_branch}"><font color="white"><b>{true_label}</b></font></td>'
                f'<td bgcolor="{self._color_false_branch}"><font color="white"><b>{false_label}</b></font></td>'
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

    def _generate_try_cluster(self, cluster: _TryCluster) -> list[str]:
        """Generate DOT subgraph clusters for a try block and its finally block."""
        parts = []
        parts.append(f"  subgraph {cluster.cluster_name} {{")
        parts.append("    style=dashed;")
        parts.append(f'    color="{self._color_error_control_flow}";')
        parts.append('    fontname="Courier";')
        parts.append("    fontsize=10;")
        parts.append('    label="try";')
        for actor in sorted(cluster.cluster_actors):
            if actor in self.router_map:
                parts.append(f"  {self._generate_actor_node(self.router_map[actor])}")
            elif actor in self.user_actors:
                parts.append(f"  {self._generate_user_actor_node(actor)}")
        parts.append("  }")

        if cluster.finally_actors:
            finally_cluster_name = cluster.cluster_name.replace("cluster_try_", "cluster_finally_")
            parts.append(f"  subgraph {finally_cluster_name} {{")
            parts.append("    style=dashed;")
            parts.append(f'    color="{self._color_finally}";')
            parts.append('    fontname="Courier";')
            parts.append("    fontsize=10;")
            parts.append('    label="finally";')
            for actor in cluster.finally_actors:
                if actor in self.router_map:
                    parts.append(f"  {self._generate_actor_node(self.router_map[actor])}")
                elif actor in self.user_actors:
                    parts.append(f"  {self._generate_user_actor_node(actor)}")
            parts.append("  }")

        return parts

    # ── Edge generation ──────────────────────────────────────────────

    def _generate_try_block_edges(self, try_enter: Router) -> set[str]:
        """Generate all edges for a try-except block."""
        lines: set[str] = set()
        cluster = next(c for c in self._try_clusters if c.try_enter_name == try_enter.name)

        # Body sequential edges (with try_exit redirected to first continuation)
        resolved_body = [self._resolve(a) for a in try_enter.true_branch_actors]
        self._add_sequential_edges(resolved_body, lines)

        # Continuation sequential edges (finally + continuation after try)
        try_exit_router = self.router_map.get(cluster.try_exit_name)
        if try_exit_router:
            continuation = [*try_exit_router.finally_actors, *try_exit_router.continuation_actors]
            if continuation:
                self._add_sequential_edges(continuation, lines)

        # Error paths from cluster boundary to handler chains
        if cluster.except_dispatch and cluster.except_dispatch.exception_handlers:
            anchor = cluster.anchor_node
            if anchor:
                handler_continuation = [
                    *cluster.except_dispatch.finally_actors,
                    *cluster.except_dispatch.continuation_actors,
                ]

                # Fallback: if handler continuation is empty, use post-try actor
                if not handler_continuation:
                    post_try = self._find_post_try_actor(try_enter.name)
                    if post_try:
                        handler_continuation = [post_try]

                for handler in cluster.except_dispatch.exception_handlers:
                    if handler.actors:
                        if handler.is_raise:
                            label = self._format_raise_label(handler.error_types)
                            edge_color = self._color_raise
                        else:
                            label = self._format_except_label(handler.error_types)
                            edge_color = self._color_error_control_flow
                        lines.add(
                            f"  {self._node_id(anchor)} -> {self._node_id(handler.actors[0])}"
                            f" [ltail={cluster.cluster_name}, color={edge_color}, style=dashed,"
                            f' label="{self._escape_html(label)}"];'
                        )
                        self._add_sequential_edges(handler.actors, lines)

                        # Connect handler terminals → continuation (finally + post-try)
                        if handler_continuation:
                            for terminal in self._find_chain_terminals(handler.actors):
                                if not terminal.startswith("end_"):
                                    lines.add(
                                        f"  {self._node_id(terminal)} -> {self._node_id(handler_continuation[0])};"
                                    )
                            self._add_sequential_edges(handler_continuation, lines)

        return lines

    def _generate_edges(self, router: Router) -> set[str]:
        """Generate edges for non-try-infrastructure routers."""
        lines: set[str] = set()

        if router.is_loop_back:
            actors = [self._resolve(a) for a in router.true_branch_actors]
            if actors:
                lines.add(f"  {self._node_id(router.name)} -> {self._node_id(actors[0])} [constraint=false];")
                self._add_sequential_edges(actors, lines)
        elif router.condition:
            true_actors = [self._resolve(a) for a in router.true_branch_actors]
            false_actors = [self._resolve(a) for a in router.false_branch_actors]

            if true_actors:
                lines.add(
                    f"  {self._node_id(router.name)} -> {self._node_id(true_actors[0])}"
                    f" [color={self._color_true_branch}];"
                )
                self._add_sequential_edges(true_actors, lines)

            if false_actors:
                lines.add(
                    f"  {self._node_id(router.name)} -> {self._node_id(false_actors[0])}"
                    f" [color={self._color_false_branch}];"
                )
                self._add_sequential_edges(false_actors, lines)
        else:
            actors = [self._resolve(a) for a in router.true_branch_actors]
            if actors:
                lines.add(f"  {self._node_id(router.name)} -> {self._node_id(actors[0])};")
                self._add_sequential_edges(actors, lines)

        return lines

    def _add_sequential_edges(self, actors: list[str], lines: set[str]) -> None:
        """Add sequential edges between consecutive actors in a branch.

        Stops the chain when an actor is a router that generates its own
        outgoing edges (conditional, loop-back, or try-except routers),
        preventing duplicate edges in the graph.
        """
        for i in range(len(actors) - 1):
            source = actors[i]
            target = actors[i + 1]
            if source in self._hidden_routers or target in self._hidden_routers:
                continue
            # If the source is a router that owns its own outgoing edges, stop the chain
            source_router = self.router_map.get(source)
            if source_router and (
                source_router.condition
                or source_router.is_loop_back
                or source_router.is_try_enter
                or source_router.is_try_exit
                or source_router.is_except_dispatch
            ):
                break
            lines.add(f"  {self._node_id(source)} -> {self._node_id(target)};")

    # ── Helpers ──────────────────────────────────────────────────────

    def _format_except_label(self, error_types: list[str] | None) -> str:
        """Format exception types for handled-exception edge labels."""
        if error_types is None:
            return "except"
        if len(error_types) == 1:
            return f"except {error_types[0]}"
        return f"except ({', '.join(error_types)})"

    def _format_raise_label(self, error_types: list[str] | None) -> str:
        """Format exception types for re-raise edge labels."""
        if error_types is None:
            return "raise"
        if len(error_types) == 1:
            return f"raise {error_types[0]}"
        return f"raise ({', '.join(error_types)})"

    def _find_chain_terminals(self, actors: list[str]) -> list[str]:
        """Find all terminal actors in a sequential chain (actors with no further routing)."""
        if not actors:
            return []
        last = actors[-1]
        router = self.router_map.get(last)
        if router:
            if router.condition:
                terminals = []
                if router.true_branch_actors:
                    terminals.extend(self._find_chain_terminals(router.true_branch_actors))
                if router.false_branch_actors:
                    terminals.extend(self._find_chain_terminals(router.false_branch_actors))
                return terminals if terminals else [last]
            elif not router.is_loop_back and router.true_branch_actors:
                return self._find_chain_terminals(router.true_branch_actors)
        return [last]

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
