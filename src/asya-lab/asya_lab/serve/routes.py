"""REST API routes for asya serve."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from asya_lab.config.project import AsyaProject


def _project_root(project: AsyaProject) -> Path:
    """Get the project root (parent of nearest .asya/)."""
    return project._store.asya_dirs[-1].parent


def create_router(project: AsyaProject) -> APIRouter:
    router = APIRouter()
    root = _project_root(project)

    @router.get("/config")
    def get_config():
        from omegaconf import OmegaConf

        return OmegaConf.to_container(project.cfg, resolve=True)

    @router.get("/flows")
    def list_flows():
        flows_dir = root / ".asya" / "flows"
        if not flows_dir.is_dir():
            return []
        return [d.name for d in sorted(flows_dir.iterdir()) if d.is_dir() and (d / "graph.json").exists()]

    @router.get("/flows/{flow_name}/graph")
    def get_flow_graph(flow_name: str):
        graph_file = root / ".asya" / "flows" / flow_name / "graph.json"
        if not graph_file.exists():
            raise HTTPException(404, f"Flow '{flow_name}' not found or not compiled")
        return json.loads(graph_file.read_text())

    @router.get("/flows/{flow_name}/manifests")
    def get_flow_manifests(flow_name: str):
        manifests_dir = root / ".asya" / "manifests" / flow_name
        if not manifests_dir.is_dir():
            return []
        result = []
        import yaml

        for f in sorted(manifests_dir.rglob("*.yaml")):
            content = yaml.safe_load(f.read_text())
            result.append({"path": str(f.relative_to(manifests_dir)), "content": content})
        return result

    @router.post("/flows/{flow_name}/compile")
    def compile_flow(flow_name: str):
        readonly = bool(project.cfg.get("readonly", False))
        if readonly:
            raise HTTPException(403, "Project is read-only")
        source_candidates = list(root.rglob(f"**/{flow_name}.py"))
        if not source_candidates:
            raise HTTPException(404, f"Flow source '{flow_name}.py' not found")
        source_file = source_candidates[0]
        flows_dir = root / ".asya" / "flows"
        output_dir = flows_dir / flow_name

        from asya_lab.flow.compiler import FlowCompiler

        compiler = FlowCompiler()
        try:
            source_code = source_file.read_text()
            compiler.compile(source_code, str(source_file))
            graph = compiler.generate_graph()
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "graph.json").write_text(json.dumps(graph, indent=2))
            return {"status": "ok", "flow": flow_name}
        except (SyntaxError, ValueError, TypeError) as e:
            raise HTTPException(422, str(e)) from e

    @router.get("/gateway")
    def get_gateway():
        """Return gateway URL from active context config."""
        contexts = project.cfg.get("contexts", {})
        if contexts:
            for ctx_name, ctx_cfg in contexts.items():
                gw = ctx_cfg.get("gateway")
                if gw:
                    return {"context": ctx_name, "gateway": str(gw)}
        raise HTTPException(404, "No gateway configured in any context")

    @router.post("/gateway/call")
    async def gateway_call(request: Request):
        """Proxy MCP tools/call to the gateway. Deferred: needs gateway URL."""
        raise HTTPException(501, "Gateway proxy not yet implemented")

    @router.get("/gateway/stream/{task_id}")
    async def gateway_stream(task_id: str):
        """Proxy gateway SSE for task progress. Deferred: needs gateway URL."""
        raise HTTPException(501, "Gateway stream proxy not yet implemented")

    @router.get("/actors/{actor_name}/logs")
    async def actor_logs(actor_name: str):
        """Stream actor logs via SSE. Deferred: needs kubernetes Python client."""
        raise HTTPException(501, "Actor logs streaming not yet implemented")

    return router
