---
title: "ADR: agentgateway for MCP Only"
status: accepted
date: 2026-04-14
---

# ADR: agentgateway for MCP Only

## Context

We evaluated agentgateway (Linux Foundation, Rust) as a facade for both MCP
and A2A. Research into the source code and ecosystem revealed:

**MCP support is deep and valuable:**
- Real MCP server with tool federation (merge tools from N backends)
- CEL-based per-tool RBAC
- Session management (encrypted cookies)
- Multiple upstream transports (stdio, SSE, streamablehttp, OpenAPI)
- failOpen/failClosed modes

**A2A support is negligible:**
- ~100 lines of Rust, pure passthrough proxy
- Empty policy struct: `pub struct A2aPolicy {}`
- No agent card aggregation (1:1 proxy)
- No task state management
- No RBAC for A2A
- Trend toward LESS A2A awareness (v1.0 removed A2A SDK dependency)

**The entire A2A gateway ecosystem is immature:**
- LiteLLM A2A: passthrough + logging (same as agentgateway)
- All other A2A gateway projects: 0-3 GitHub stars
- No mature project manages A2A task lifecycle at the gateway layer

## Decision

**Use agentgateway for MCP only.** Build A2A server in the dispatcher.

agentgateway handles MCP clients (tool federation, auth, RBAC, sessions).
A2A requests route through agentgateway for auth (JWT on all routes) but
agentgateway adds nothing A2A-specific.

## Consequences

- MCP: delete ~2,400 LOC (MCP server, auth, tool registry), replaced by agentgateway config
- A2A: keep/rewrite ~500 LOC (A2A adapter over /mesh/), no external dependency
- Auth: agentgateway provides JWT/OIDC for all routes (MCP and A2A)
- Risk: if a better A2A gateway appears, easy to adopt (A2A handler is thin adapter)

## Alternatives Considered

- **agentgateway for both MCP + A2A**: A2A support is empty, adds no value
- **LiteLLM as unified facade**: A2A support equally thin, plus LiteLLM is
  primarily an LLM proxy, not a protocol gateway
- **mcp-gateway-registry (585 stars)**: claims MCP + A2A, but unclear maturity
- **Build our own MCP server**: unnecessary, solved problem
- **No facade (expose dispatcher directly)**: loses MCP federation, auth, RBAC
