---
title: "ADR: Protocol Adapters as Sidecar Containers"
status: accepted
date: 2026-04-16
---

# ADR: Protocol Adapters as Sidecar Containers

## Context

MCP and A2A protocol support must be added to the mesh API. Three options:
1. Protocol handlers built into mesh-api binary (optional modules)
2. Protocol adapters as separate deployments
3. Protocol adapters as sidecar containers in the mesh-api pod

## Decision

**Protocol adapters (MCP, A2A) run as sidecar containers in the mesh-api pod.**
One Go module (`src/asya-gateway/`), three binaries (`asya-mesh-api`,
`asya-mcp-adapter`, `asya-a2a-adapter`).

Each adapter is a stateless HTTP translator:
- Reads protocol-specific config from its own ConfigMap
- Translates protocol calls -> /mesh/ HTTP calls
- Create calls go to localhost:8080 (same pod, mesh-api)
- Subscribe calls go via External Ingress (hash-routed for correct pod)
- Hot-reloads config via polling watcher (shared Go code)

Libraries:
- MCP: mark3labs/mcp-go (MCP Streamable HTTP server)
- A2A: a2aproject/a2a-go v2 (A2A JSON-RPC server + task store interface)

The a2a-adapter additionally mounts a state-proxy-s3 sidecar for reading
task history from S3 (hydration for tasks/get, SHOULD not MUST per A2A spec).

## Consequences

- mesh-api core has zero protocol knowledge (no MCP, no A2A imports)
- Adapters are optional: don't need MCP? Don't deploy the sidecar.
- Adapters scale with mesh-api (same pod, same replica count)
- Shared Go module: adapters import mesh types from pkg/types/
- Create calls are local (same pod, no network hop)
- Subscribe calls are hash-routed via Ingress (correct pod for SSE)
- Hot-reload: each adapter watches its own ConfigMap independently

## Alternatives Considered

- **Built into mesh-api**: mesh-api grows, mixed concerns, protocol code
  runs even when not needed.
- **Separate deployments**: three Deployments instead of one, more infra
  to manage, network hops for create calls.
