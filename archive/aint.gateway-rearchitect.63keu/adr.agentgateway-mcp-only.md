---
title: "ADR: nginx + Custom Adapters (agentgateway Phase 2)"
status: accepted
date: 2026-04-16
supersedes: "ADR: agentgateway for MCP, Common Proxy for All"
---

# ADR: nginx + Custom Adapters, agentgateway in Phase 2

## Context

We evaluated agentgateway (Linux Foundation, Rust) as a facade for MCP/A2A.
Research found:
- MCP support is deep and valuable (tool federation, CEL RBAC, sessions)
- A2A support is pure passthrough (~100 LOC Rust, empty policy struct)
- agentgateway CANNOT handle two-step async backends (tools/call makes one
  synchronous HTTP call, MCP Tasks explicitly rejected: InvalidMethod)
- The ecosystem has no mature A2A gateway

We also evaluated the effort of custom adapters:
- MCP adapter: ~300-500 LOC Go (mark3labs/mcp-go library)
- A2A adapter: ~500-800 LOC Go (a2aproject/a2a-go v2 library)
- Total: ~800-1300 LOC -- comparable to learning agentgateway's config model

## Decision

**Phase 1: nginx Ingress + custom protocol adapters.** No agentgateway.

nginx Ingress provides: JWT auth (annotation), rate limiting (annotation),
TLS termination, consistent hash routing (upstream-hash-by). All via
annotations, zero custom code.

Custom adapters provide: MCP Streamable HTTP, A2A JSON-RPC. Both call
/mesh/ API as HTTP clients. Both read config from ConfigMaps with
polling watcher hot-reload.

**Phase 2 (when needed): add agentgateway** for MCP tool federation
(aggregate tools from multiple Asya meshes + external MCP servers). The
MCP adapter becomes an MCP upstream for agentgateway. No adapter code changes.

## Consequences

- No new infrastructure in Phase 1 (nginx already deployed)
- Full control over protocol handling (add new protocols instantly)
- No dependency on agentgateway release cycle or maturity
- Phase 2 path is clean: agentgateway wraps the MCP adapter
- Custom adapters are small (~800-1300 LOC total) using mature libraries
