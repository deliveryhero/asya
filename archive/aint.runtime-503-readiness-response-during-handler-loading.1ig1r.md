---
title: "Runtime: 503 readiness response during handler loading"
status: rejected
priority: 2
dependencies:
  - 1iofo
tags:
  - pr:192
reason: "Late binding: HTTP server starts after handler load, so 503 guard is unnecessary. GET /healthz added for K8s probes instead."
---

Implement HTTP 503 Service Unavailable response when the runtime HTTP server is up but the handler is not yet loaded. With binary framing, the runtime blocks on socket accept until ready. With HTTP, the server starts immediately and must signal not-ready to the sidecar. Sidecar retries with backoff on 503.
