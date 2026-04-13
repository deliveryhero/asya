---
title: "RFC: Replace asya-gateway with agentgateway + asya-dispatcher"
status: open
priority: 1
parent: 63keu
tags:
  - architecture
  - rfc
---

# RFC: agentgateway + asya-dispatcher

Replace `asya-gateway` (~7,150 LOC Go monolith) with:

1. **agentgateway** (LF, Rust) -- MCP server, A2A proxy, auth, rate limiting
2. **asya-dispatcher** (new, Go, ~2,000 LOC) -- two-port HTTP service:
   - Port 8080 (external): `/dispatch`, `/stream/{id}`, `/tasks/{id}`, `/a2a/*`
   - Port 8081 (internal): `/mesh/{id}/*` (sidecar callbacks)

## Key Design Decisions

- **Two-step API**: `POST /dispatch` (round-robin, generates ID) +
  `GET /stream/{id}` (hash-routed, holds SSE). Standard REST pattern,
  maps to A2A `tasks/send` + `tasks/subscribe`.
- **Consistent hash via Ingress**: `upstream-hash-by: $http_x_asya_envelope_id`.
  Two Ingresses: external (client-facing) and internal (sidecar-facing).
  ID generation is application concern (dispatcher), routing is networking
  concern (Ingress).
- **`x-asya-gateway-url` in envelope**: sidecar reads gateway URL from
  envelope headers, eliminating `ASYA_GATEWAY_URL` env var.
- **`X-Asya-Envelope-ID` header**: sidecar sets this on every POST for
  consistent hash routing. Always present on sidecar requests.
- **DB for metadata only**: lightweight task status table, async writes.
  No pub/sub, no pg_notify, no JSONB payload/result columns.
- **SSE + mesh in same process**: Go channels for real-time delivery,
  no cross-process sync needed.

## Eliminates

- pg_notify (8KB limit, dedicated conn, feedback loops)
- api/mesh gateway split (ASYA_GATEWAY_MODE)
- ASYA_GATEWAY_URL env var in sidecars
- MCP server code (~1,868 LOC) -> agentgateway
- Auth/OAuth code (~755 LOC) -> agentgateway
- PG as pub/sub bus
- task_updates table

## Full RFC

See [rfc.md](rfc.md) for complete design including:
- agentgateway research findings and capabilities
- asya-gateway code audit by bucket (~7,150 LOC breakdown)
- Ingress configuration (nginx consistent hash)
- Two-step dispatch flow diagrams
- A2A/MCP protocol mapping
- Sidecar changes (header + envelope URL)
- DB schema (metadata only)
- Code impact analysis (~72% reduction)
- Risks and open questions

## Sub-tasks

- [ ] Prototype asya-dispatcher with two-step API
- [ ] Prototype Ingress consistent hash routing (nginx)
- [ ] Sidecar: read gateway URL from envelope, set X-Asya-Envelope-ID header
- [ ] Evaluate agentgateway MCP federation with Asya flows
- [ ] Design simplified DB schema (metadata only)
- [ ] Migration plan from current architecture
