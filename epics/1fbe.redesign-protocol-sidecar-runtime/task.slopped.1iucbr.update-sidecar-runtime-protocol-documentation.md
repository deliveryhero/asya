---
title: Update sidecar-runtime protocol documentation
priority: 3 # low
type: task
dependencies:
  - 1ia4/1in0hv
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
