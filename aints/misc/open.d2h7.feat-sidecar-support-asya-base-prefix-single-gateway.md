---
title: "feat(sidecar): support ASYA_BASE_PREFIX for single-gateway deployments with URL prefix"
priority: 2 # medium
---

## Problem

The sidecar progress reporter hardcodes two different path hierarchies against a
single \`gatewayURL\` base:

- \`{gatewayURL}/health\` — health check (root-level; NOT affected by \`ASYA_BASE_PREFIX\`)
- \`{gatewayURL}/mesh/{id}/...\` — mesh callbacks (affected by \`ASYA_BASE_PREFIX\`)

From AGENTS.md: \`ASYA_BASE_PREFIX\` affects \`/a2a/\`, \`/mcp/\`, \`/mesh/\` but
\`/health\` always stays at root (unaffected).

If the gateway is deployed with \`ASYA_BASE_PREFIX=/api/v1\`, the correct paths are:
- \`http://gateway/health\` (root, no prefix) — works fine
- \`http://gateway/api/v1/mesh/{id}/final\` — currently broken; sidecar would call
  \`http://gateway/mesh/{id}/final\` (missing prefix)

## Current Workaround

The **split-gateway architecture** (used in production and the GKE demo) avoids this
entirely: \`asya-gateway-mesh\` is an internal ClusterIP service with no ingress, so
\`ASYA_BASE_PREFIX\` is never set on it. Sidecars point to the raw internal service.

This becomes a real bug only in **single-gateway deployments** where one gateway
instance handles both external (A2A/MCP) and internal (mesh) traffic, AND that
instance is placed behind an ingress with a URL prefix.

## Affected code

\`src/asya-sidecar/internal/progress/reporter.go\` — five path constructions:
- Line 66: \`%s/mesh/%s/progress\`
- Line 130: \`%s/health\`
- Line 176: \`%s/mesh\`
- Line 206: \`%s/mesh/%s/fly\`
- Line 242: \`%s/mesh/%s/final\`

## Design options

**Option A — Split fields** (cleanest):

Add \`meshGatewayURL\` alongside \`gatewayURL\` (health stays on base, mesh on mesh URL):

\`\`\`go
type Reporter struct {
    healthURL  string  // e.g. "http://gateway"           — for /health
    meshURL    string  // e.g. "http://gateway/api/v1"    — for /mesh/...
}
\`\`\`

Helm: add \`sidecar.gatewayHealthURL\` (optional, defaults to \`sidecar.gatewayURL\`).

**Option B — Mesh path prefix** (minimal change):

Keep \`gatewayURL\` as base. Add \`sidecar.gatewayMeshBasePath\` (default \`""\`):
- mesh paths: \`{gatewayURL}{meshBasePath}/mesh/{id}/...\`
- health: \`{gatewayURL}/health\` (unchanged)

For prefix deployments, set \`gatewayMeshBasePath=/api/v1\`.

**Option C — Env var passthrough**:

Read \`ASYA_BASE_PREFIX\` from env in the sidecar and automatically prepend it to
mesh paths. Gateway and sidecar share the same env var name — consistent but
tight coupling.

## Recommendation

Option B is minimal and consistent with how the helm chart already works. Only
needed if anyone deploys single-gateway+prefix topology. File as P2 but don't
block on it — split-gateway arch fully avoids this.

## Files

- \`src/asya-sidecar/internal/progress/reporter.go\`
- \`deploy/helm-charts/asya-crossplane/values.yaml\` — add \`sidecar.gatewayMeshBasePath\`
- \`deploy/helm-charts/asya-crossplane/templates/\` — sidecar env var injection
