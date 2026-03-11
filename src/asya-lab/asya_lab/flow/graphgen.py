"""Generate graph JSON for interactive flow visualization.

Emits a JSON structure with nodes, edges, and groups suitable for
React Flow rendering. Schema matches rfc-ui-components.md section 3.2.
"""

from __future__ import annotations

from asya_lab.flow.grouper import Router


class GraphGenerator:
    def __init__(
        self,
        flow_name: str,
        routers: list[Router],
        class_methods: set[str] | None = None,
    ):
        self.flow_name = flow_name
        self.routers = routers
        self.class_methods = class_methods or set()
        self.router_map: dict[str, Router] = {}
        self.user_actors: set[str] = set()
        self.fanin_actors: set[str] = set()
        self._hidden_routers: set[str] = set()

    def generate(self) -> dict:
        self._collect()
        nodes = self._build_nodes()
        edges = self._build_edges()
        groups = self._build_groups()
        return {
            "flow": self.flow_name,
            "nodes": nodes,
            "edges": edges,
            "groups": groups,
        }

    def _collect(self) -> None:
        for router in self.routers:
            self.router_map[router.name] = router

        for router in self.routers:
            for actor_list in [
                router.true_branch_actors,
                router.false_branch_actors,
                router.finally_actors,
                router.continuation_actors,
            ]:
                for actor in actor_list:
                    if actor not in self.router_map:
                        self.user_actors.add(actor)
            if router.exception_handlers:
                for handler in router.exception_handlers:
                    for actor in handler.actors:
                        if actor not in self.router_map:
                            self.user_actors.add(actor)
            if router.is_fan_out and router.fan_out_op:
                for actor_name, _ in router.fan_out_op.actor_calls:
                    if actor_name not in self.router_map:
                        self.user_actors.add(actor_name)
                for actor in router.true_branch_actors:
                    if actor.startswith("fanin_"):
                        self.fanin_actors.add(actor)

        for router in self.routers:
            if router.is_try_enter:
                self._hidden_routers.add(router.name)
                try_exit = router.name.replace("_try_enter_", "_try_exit_")
                self._hidden_routers.add(try_exit)
                if router.except_dispatch_name:
                    self._hidden_routers.add(router.except_dispatch_name)
                    dispatch = self.router_map.get(router.except_dispatch_name)
                    if dispatch and dispatch.reraise_name:
                        self._hidden_routers.add(dispatch.reraise_name)

    def _classify_role(self, router: Router) -> str:
        if router.condition:
            return "conditional"
        if router.is_fan_out:
            return "fanout"
        if router.is_loop_back:
            return "loop"
        if router.mutations:
            return "mutation"
        if router.is_reraise:
            return "raise_exit"
        return "processor"

    def _is_entrypoint(self, name: str) -> bool:
        return name.startswith("start_")

    def _is_exitpoint(self, name: str) -> bool:
        return name.startswith("end_")

    def _get_display_label(self, name: str) -> str:
        parts = name.split(".")
        if len(parts) >= 2:
            if name in self.class_methods:
                return f"{parts[-2]}.{parts[-1]}"
            return parts[-1]
        return name

    def _build_nodes(self) -> list[dict]:
        nodes = []
        for router in self.routers:
            if router.name in self._hidden_routers:
                continue
            node: dict = {
                "id": router.name,
                "type": "router",
                "role": self._classify_role(router),
                "label": self._get_display_label(router.name),
            }
            if self._is_entrypoint(router.name):
                node["entrypoint"] = True
            if self._is_exitpoint(router.name):
                node["exitpoint"] = True
            if router.mutations:
                node["mutations"] = [m.code for m in router.mutations]
            if router.condition:
                node["condition"] = router.condition.test
            nodes.append(node)

        for actor in sorted(self.user_actors):
            node = {
                "id": actor,
                "type": "actor",
                "role": "fanin" if actor in self.fanin_actors else "processor",
                "label": self._get_display_label(actor),
            }
            nodes.append(node)

        return nodes

    def _resolve(self, name: str) -> str | None:
        """Resolve hidden infrastructure routers to first visible actor."""
        if name not in self._hidden_routers:
            return name
        router = self.router_map.get(name)
        if router and router.is_try_enter and router.true_branch_actors:
            for a in router.true_branch_actors:
                resolved = self._resolve(a)
                if resolved:
                    return resolved
        if router:
            try_exit = router.name.replace("_try_enter_", "_try_exit_")
            exit_router = self.router_map.get(try_exit)
            if exit_router:
                cont = [*exit_router.finally_actors, *exit_router.continuation_actors]
                if cont:
                    return self._resolve(cont[0])
        return None

    def _build_edges(self) -> list[dict]:
        edges = []
        seen = set()

        def add_edge(source: str, target: str, edge_type: str, label: str | None = None) -> None:
            key = (source, target, edge_type)
            if key in seen:
                return
            if source in self._hidden_routers or target in self._hidden_routers:
                return
            seen.add(key)
            edge: dict = {"source": source, "target": target, "type": edge_type}
            if label:
                edge["label"] = label
            edges.append(edge)

        for router in self.routers:
            if router.name in self._hidden_routers:
                if router.is_try_enter:
                    self._add_try_edges(router, add_edge)
                continue

            if router.is_fan_out and router.fan_out_op:
                self._add_fanout_edges(router, add_edge)
            elif router.condition:
                for actor in router.true_branch_actors:
                    resolved = self._resolve(actor)
                    if resolved:
                        add_edge(router.name, resolved, "true")
                        break
                for actor in router.false_branch_actors:
                    resolved = self._resolve(actor)
                    if resolved:
                        add_edge(router.name, resolved, "false")
                        break
                self._add_sequential_branch(router.true_branch_actors, add_edge)
                self._add_sequential_branch(router.false_branch_actors, add_edge)
            else:
                actors = [router.name, *router.true_branch_actors]
                self._add_sequential_branch(actors, add_edge)

        return edges

    def _add_sequential_branch(self, actors: list[str], add_edge) -> None:
        resolved = []
        for a in actors:
            r = self._resolve(a)
            if r and r not in self._hidden_routers:
                resolved.append(r)
        for i in range(len(resolved) - 1):
            add_edge(resolved[i], resolved[i + 1], "sequential")

    def _add_try_edges(self, try_enter: Router, add_edge) -> None:
        body = try_enter.true_branch_actors
        resolved_body = [self._resolve(a) for a in body if self._resolve(a)]
        for i in range(len(resolved_body) - 1):
            add_edge(resolved_body[i], resolved_body[i + 1], "sequential")

        except_dispatch = (
            self.router_map.get(try_enter.except_dispatch_name) if try_enter.except_dispatch_name else None
        )
        if except_dispatch and except_dispatch.exception_handlers:
            for handler in except_dispatch.exception_handlers:
                if handler.actors and not handler.is_raise:
                    label = "except"
                    if handler.error_types:
                        label = f"except {', '.join(handler.error_types)}"
                    for actor in handler.actors:
                        resolved = self._resolve(actor)
                        if resolved:
                            add_edge(resolved_body[-1] if resolved_body else try_enter.name, resolved, "except", label)
                            break

        try_exit_name = try_enter.name.replace("_try_enter_", "_try_exit_")
        try_exit = self.router_map.get(try_exit_name)
        if try_exit:
            cont = [*try_exit.finally_actors, *try_exit.continuation_actors]
            resolved_cont = [self._resolve(a) for a in cont if self._resolve(a)]
            if resolved_body and resolved_cont:
                add_edge(resolved_body[-1], resolved_cont[0], "sequential")
            for i in range(len(resolved_cont) - 1):
                add_edge(resolved_cont[i], resolved_cont[i + 1], "sequential")

    def _add_fanout_edges(self, router: Router, add_edge) -> None:
        fan_out = router.fan_out_op
        if fan_out is None:
            return
        for actor_name, _ in fan_out.actor_calls:
            add_edge(router.name, actor_name, "fanout")
        agg = [a for a in router.true_branch_actors if a.startswith("fanin_")]
        if agg:
            for actor_name, _ in fan_out.actor_calls:
                add_edge(actor_name, agg[0], "sequential")

    def _build_groups(self) -> list[dict]:
        groups = []
        cluster_id = 0
        for router in self.routers:
            if not router.is_try_enter:
                continue
            try_actors = []
            for a in router.true_branch_actors:
                if a not in self._hidden_routers and (a in self.user_actors or a in self.router_map):
                    try_actors.append(a)
            groups.append(
                {
                    "id": f"try-{cluster_id}",
                    "type": "try",
                    "nodes": try_actors,
                }
            )

            try_exit_name = router.name.replace("_try_enter_", "_try_exit_")
            try_exit = self.router_map.get(try_exit_name)
            if try_exit and try_exit.finally_actors:
                groups.append(
                    {
                        "id": f"finally-{cluster_id}",
                        "type": "finally",
                        "nodes": list(try_exit.finally_actors),
                    }
                )
            cluster_id += 1
        return groups
