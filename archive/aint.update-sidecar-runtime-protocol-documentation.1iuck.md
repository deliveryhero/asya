---
title: Update sidecar-runtime protocol documentation
status: merged
priority: 3
parent: jp7cz
dependencies:
  - 1in0
tags:
  - pr:192
reason: docs/architecture/protocols/sidecar-runtime.md rewritten for HTTP POST /invoke + GET /healthz in this PR.
---

Update protocol documentation to reflect the new HTTP-over-Unix-socket design.

Scope:
- Rewrite docs/architecture/protocols/sidecar-runtime.md
- Document POST /invoke request format
- Document JSON response format (simple handlers)
- Document SSE response format (generator handlers)
- Document error responses (500) and abort (204)
- Document timeout strategy
- Remove binary framing documentation
- Add curl examples for debugging

Key files:
- docs/architecture/protocols/sidecar-runtime.md
