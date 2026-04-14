---
title: Document gateway security model in docs/internal/
status: merged
priority: 2
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/agentic-security/4iga.gateway-security-internal-docs
  - branch:agentic-security/4iga.gateway-security-internal-docs
  - pr:275
---

Write clean, implementation-accurate internal documentation for the gateway security model.
The RFC and research docs are design-time artifacts; this task produces the canonical reference
used by contributors and operators.

## Source Material

- `.aint/aints/agentic-security/rfc.md` — design RFC (phases 1-3 all implemented)
- `.aint/aints/agentic-security/research-a2a-auth.md` — A2A spec research
- `.aint/aints/agentic-security/research-mcp-auth.md` — MCP auth spec research
- `src/asya-gateway/cmd/gateway/main.go` — route registration, env var wiring
- `src/asya-gateway/internal/oauth/server.go` — OAuth 2.1 server implementation
- `src/asya-gateway/internal/a2a/auth.go` — A2A auth middleware

## Known Inconsistencies to Resolve

Before writing docs, reconcile these gaps between the RFC/research and what's shipped:

1. **Missing env vars in RFC §7**: Add `ASYA_MCP_OAUTH_SECRET` and
   `ASYA_MCP_OAUTH_REGISTRATION_TOKEN` to the env var table.
2. **RFC §11 Open Questions**: Close all three with the implemented decisions:
   - Q1 (Helm): one chart, `mode` value in Helm values
   - Q2 (dev mode): `ASYA_GATEWAY_MODE=""` (empty) = all routes, no auth — backward compat
   - Q3 (OAuth storage): same PostgreSQL as task store
3. **A2A discovery path**: `research-a2a-auth.md §10` says `/.well-known/agent-card.json`;
   implementation uses `/.well-known/agent.json` (path from a2asrv library, older A2A draft).
   Document the actual path. Note the spec version difference.
4. **MCP scope names**: `research-mcp-auth.md` uses `mcp:tools`/`mcp:resources` (from MCP
   tutorial); implementation defines `mcp:invoke`/`mcp:read`. Document the Asya choices.
5. **RFC status**: Update rfc.md Status from "Draft" to "Implemented (Phases 1-3)".

## Output

Create `docs/internal/gateway-security.md` covering:

### Sections

1. **Deployment model** — `ASYA_GATEWAY_MODE`, api vs mesh deployments, shared resources
2. **Route groups** — A2A, MCP, mesh, health; which deployment serves each
3. **A2A authentication** — API key (`X-API-Key`) + JWT/Bearer; Agent Card declaration;
   public vs protected endpoints; `/.well-known/agent.json` path
4. **MCP authentication** — Phase 2 (API key) and Phase 3 (OAuth 2.1); mode selection;
   `ASYA_MCP_OAUTH_ENABLED` flag; all OAuth endpoints; scope model (`mcp:invoke`, `mcp:read`)
5. **Mesh security** — network isolation rationale; ClusterIP-only; NetworkPolicy example
6. **Complete env var reference** — all auth-related env vars with types, defaults, and when required
7. **OAuth 2.1 flow walkthrough** — step-by-step for client developers
8. **Development mode** — empty `ASYA_GATEWAY_MODE`, auth disabled, what to configure locally

### Cross-references

- Link to `docs/architecture/asya-gateway.md` (update that doc to mention security section)
- Link to Helm chart values for `mode` configuration

## Acceptance Criteria

- All env vars from `main.go` OAuth wiring are documented
- A2A and MCP auth modes are accurately described (no RFC-era "planned" language)
- No contradiction with `research-a2a-auth.md` or `research-mcp-auth.md` (differences noted)
- A contributor can configure MCP OAuth 2.1 locally using only this doc
- rfc.md status updated to reflect implementation reality
