---
title: "RFC: Replace asya-gateway with asya-mesh-api + protocol adapters"
status: merged
priority: 1
tags:
  - architecture
  - rfc
---

Replace asya-gateway (~7,150 LOC) with asya-mesh-api + MCP/A2A adapters.

See [rfc.md](rfc.md) for full design. ADRs:
- [adr.mesh-universal-api.md](adr.mesh-universal-api.md) — /mesh/ as universal API, unified /events
- [adr.mcp-a2a-siblings.md](adr.mcp-a2a-siblings.md) — MCP/A2A are siblings, one protocol per flow
- [adr.agentgateway-mcp-only.md](adr.agentgateway-mcp-only.md) — nginx + custom adapters, agentgateway Phase 2
- [adr.protocol-adapters-as-sidecars.md](adr.protocol-adapters-as-sidecars.md) — adapters as sidecar containers
- [adr.two-step-dispatch.md](adr.two-step-dispatch.md) — two-step create/subscribe for hash routing
- [adr.envelope-gateway-url.md](adr.envelope-gateway-url.md) — gateway URL in envelope, eliminates env var
- [adr.db-metadata-only.md](adr.db-metadata-only.md) — PG state-proxy as document store
