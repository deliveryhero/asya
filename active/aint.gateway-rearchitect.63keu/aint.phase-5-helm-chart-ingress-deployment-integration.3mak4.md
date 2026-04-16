---
title: "Phase 5: Helm chart + Ingress + deployment integration"
status: open
priority: 1 # high
dependencies:
  - cjrxo
  - i7ys2
  - iq8gi
---

Helm chart for asya-gateway deployment with all containers + Ingress config.

Deployment (single pod, multiple containers):
- mesh-api (:8080 ext, :8081 int)
- mcp-adapter (:8082, optional)
- a2a-adapter (:8083, optional)
- state-proxy-mesh (PG connector, Unix socket)
- state-proxy-envelopes (S3 connector, optional, Unix socket)

Helm values:
- mesh.enabled: true (always)
- mcp.enabled: true/false
- a2a.enabled: true/false
- stateProxy.mesh.type: pg (default)
- stateProxy.envelopes.type: s3 (optional)
- database.host, database.port, etc.
- ingress.external.enabled, ingress.internal.enabled
- ingress.external.annotations (JWT auth, rate limit)

nginx Ingress:
- External Ingress (asya-gateway-create): /api/v1/mesh/ Exact, round-robin
- External Ingress (asya-gateway-sticky): /api/v1/mesh/ Prefix + /mcp/ + /a2a/, hash by X-Asya-Envelope-ID
- Internal Ingress (asya-gateway-internal): /api/v1/mesh/ Prefix, hash, NetworkPolicy

Crossplane composition update:
- Remove ASYA_GATEWAY_URL from actor pod env (x-asya-gateway-url in envelope)

Testing:
- E2E: Kind cluster, full deployment, test MCP + A2A + direct /mesh/ + sidecar flow
- Test rolling update (PDB, graceful shutdown, SSE reconnect)
- Test asya expose --as mcp|a2a (ConfigMap creation + hot-reload)

Documentation:
- docs/setup/guide-gateway.md (installation/configuration)
- docs/usage/guide-gateway.md (MCP vs A2A, when to use what, examples)
- Update AGENTS.md gateway section

Depends on: cjrxo (MCP), i7ys2 (A2A), iq8gi (sidecar)
