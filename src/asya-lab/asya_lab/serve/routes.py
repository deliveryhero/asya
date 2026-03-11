"""REST API routes for asya serve."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from asya_lab.config.project import AsyaProject


log = logging.getLogger(__name__)


def _resolve_flows_dir(project: AsyaProject) -> Path:
    """Resolve flows output directory from config, with fallback."""
    try:
        return project.resolve_path("compiler.flows")
    except KeyError:
        return project.root / ".asya" / "flows"


def _resolve_manifests_dir(project: AsyaProject) -> Path:
    """Resolve manifests output directory from config, with fallback."""
    try:
        return project.resolve_path("compiler.manifests")
    except KeyError:
        return project.root / ".asya" / "manifests"


def _resolve_gateway_url(project: AsyaProject) -> str | None:
    """Resolve gateway URL from the active context config."""
    contexts = project.cfg.get("contexts", {})
    if contexts:
        for _ctx_name, ctx_cfg in contexts.items():
            gw = ctx_cfg.get("gateway")
            if gw:
                return str(gw)
    return None


def create_router(project: AsyaProject) -> APIRouter:
    router = APIRouter()

    @router.get("/config")
    def get_config():
        from omegaconf import OmegaConf

        return OmegaConf.to_container(project.cfg, resolve=True)

    @router.get("/flows")
    def list_flows():
        flows_dir = _resolve_flows_dir(project)
        if not flows_dir.is_dir():
            return []
        return [d.name for d in sorted(flows_dir.iterdir()) if d.is_dir() and (d / "graph.json").exists()]

    @router.get("/flows/{flow_name}/graph")
    def get_flow_graph(flow_name: str):
        graph_file = _resolve_flows_dir(project) / flow_name / "graph.json"
        if not graph_file.exists():
            raise HTTPException(404, f"Flow '{flow_name}' not found or not compiled")
        return json.loads(graph_file.read_text())

    @router.get("/flows/{flow_name}/manifests")
    def get_flow_manifests(flow_name: str):
        manifests_dir = _resolve_manifests_dir(project) / flow_name
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
        source_candidates = list(project.root.rglob(f"**/{flow_name}.py"))
        if not source_candidates:
            raise HTTPException(404, f"Flow source '{flow_name}.py' not found")
        source_file = source_candidates[0]
        output_dir = _resolve_flows_dir(project) / flow_name

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
        gateway_url = _resolve_gateway_url(project)
        if not gateway_url:
            raise HTTPException(404, "No gateway configured in any context")
        contexts = project.cfg.get("contexts", {})
        for ctx_name, ctx_cfg in contexts.items():
            if ctx_cfg.get("gateway"):
                return {"context": ctx_name, "gateway": gateway_url}
        raise HTTPException(404, "No gateway configured in any context")

    @router.post("/gateway/call")
    async def gateway_call(request: Request):
        """Proxy a request to the configured gateway (MCP tools/call)."""
        import httpx

        gateway_url = _resolve_gateway_url(project)
        if not gateway_url:
            raise HTTPException(404, "No gateway configured in any context")
        body = await request.json()
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{gateway_url}/mcp/tools/call",
                    json=body,
                    timeout=30.0,
                )
                return resp.json()
            except httpx.ConnectError as e:
                raise HTTPException(502, f"Cannot reach gateway at {gateway_url}: {e}") from e
            except httpx.TimeoutException as e:
                raise HTTPException(504, f"Gateway timeout: {e}") from e

    @router.get("/gateway/stream/{task_id}")
    async def gateway_stream(task_id: str):
        """Proxy SSE from the configured gateway for task progress."""
        import httpx

        gateway_url = _resolve_gateway_url(project)
        if not gateway_url:
            raise HTTPException(404, "No gateway configured in any context")

        async def _proxy_sse():
            async with httpx.AsyncClient() as client:
                try:
                    async with client.stream(
                        "GET",
                        f"{gateway_url}/a2a/tasks/{task_id}/subscribe",
                        timeout=None,
                    ) as resp:
                        async for line in resp.aiter_lines():
                            yield line + "\n"
                except httpx.ConnectError:
                    log.warning("[!] Cannot reach gateway at %s", gateway_url)
                except httpx.TimeoutException:
                    log.warning("[!] Gateway SSE stream timeout for task %s", task_id)

        return StreamingResponse(_proxy_sse(), media_type="text/event-stream")

    @router.get("/actors/{actor_name}/logs")
    async def actor_logs(actor_name: str):
        """Stream actor logs via SSE. Deferred: needs kubernetes Python client."""
        raise HTTPException(501, "Actor logs streaming not yet implemented")

    return router
