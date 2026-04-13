---
title: "fix(sidecar): strip trailing slash from gatewayURL in NewReporter"
status: open
priority: 3
---

## Problem

\`progress.Reporter\` stores \`gatewayURL\` verbatim. If the value has a trailing slash,
all path construction silently produces double-slash or double-segment URLs:

| gatewayURL value | Resulting /final URL |
|---|---|
| \`http://host\` | \`http://host/mesh/id/final\` ✅ |
| \`http://host/\` | \`http://host//mesh/id/final\` ❌ |
| \`http://host/mesh\` | \`http://host/mesh/mesh/id/final\` ❌ |

This is easy to introduce via Helm (\`sidecar.gatewayURL: "http://host/"\`) and fails
silently — the HTTP request goes to the wrong URL, gateway returns 404, sidecar logs
a warning but carries on.

Discovered during GKE demo cluster setup when \`sidecar.gatewayURL\` was accidentally
set with the \`/mesh\` suffix, causing x-sink's final callback to hit
\`http://asya-gateway-mesh.ns.svc.cluster.local/mesh/mesh/{id}/final\` (404).

## Root Cause

\`src/asya-sidecar/internal/progress/reporter.go:33\` — \`NewReporter\` stores the URL
without normalization. All five path constructions (\`/health\`, \`/mesh\`,
\`/mesh/{id}/progress\`, \`/mesh/{id}/fly\`, \`/mesh/{id}/final\`) use raw
\`fmt.Sprintf("%s/...", r.gatewayURL)\`.

## Fix

One line in \`NewReporter\`:

\`\`\`go
func NewReporter(gatewayURL, actorName string) *Reporter {
    return &Reporter{
        gatewayURL: strings.TrimRight(gatewayURL, "/"),
        ...
    }
}
\`\`\`

Add a unit test: construct \`Reporter\` with trailing slash, assert \`GetGatewayURL()\`
returns the trimmed form and path construction produces correct URLs.

## Files

- \`src/asya-sidecar/internal/progress/reporter.go\` — \`NewReporter\`, line 33
