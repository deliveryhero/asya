---
title: "Phase 1: Dual-deployment gateway split"
priority: 1 # high
tags:
  - phase:1
---

Split gateway into two deployment modes (api + mesh) for network-level route
isolation. Wire existing A2A auth to the api mode. No new auth code.

See `rfc.md` section 7, Phase 1.

## Scope

- Add `ASYA_GATEWAY_MODE` env var (`api`, `mesh`, or empty for dev/all)
- Gate route registration in `main.go` based on mode
- Update Helm chart to support two releases with `mode` value
- Update sidecar `ASYA_GATEWAY_URL` to point to mesh service name
- Update integration/e2e tests for dual-deployment topology
- Existing A2A auth (API key + JWT, merged in 7fuy) works unchanged

## Not in Scope

- New auth middleware (Phase 2+)
- MCP auth (Phase 2+)
- NetworkPolicy (optional hardening, separate task)

## Acceptance Criteria

- `ASYA_GATEWAY_MODE=api` serves only /a2a/*, /mcp/*, /.well-known/*, /health
- `ASYA_GATEWAY_MODE=mesh` serves only /mesh/*, /health
- Empty mode serves all routes (backward compat)
- Sidecar can reach mesh service, external clients can reach api service
- A2A auth (API key + JWT) applies to /a2a/* on api deployment
- Helm chart produces two Deployments + two Services from one values file
