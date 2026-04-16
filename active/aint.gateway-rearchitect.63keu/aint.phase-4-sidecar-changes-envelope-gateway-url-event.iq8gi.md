---
title: "Phase 4: Sidecar changes (envelope gateway URL + event POST + pre-flight check)"
status: open
priority: 1 # high
dependencies:
  - nacr7
---

Update asya-sidecar to work with the new mesh-api. Three changes:

1. Read gateway URL from envelope header x-asya-gateway-url (fall back to ASYA_GATEWAY_URL env var for backward compat):
   gatewayURL := envelope.Headers['x-asya-gateway-url']

2. Unified event POST (replaces separate progress/final/fly POSTs):
   POST {gatewayURL}/api/v1/mesh/{id}/events
   Header: X-Asya-Envelope-ID: {id}
   Body: {type: 'status', status: 'running', data: {actor: X, progress: 50}}
   Body: {type: 'fly', data: {text: 'token...'}}
   Body: {type: 'status', status: 'succeeded', data: {actor: X}}

3. Pre-flight check before processing:
   GET {gatewayURL}/api/v1/mesh/{id}
   If status == canceled|paused: ack message, route to x-sink, skip processing.

Implementation:
- Modify internal/router/router.go: replace separate progress/final/fly POSTs
- Modify internal/config/config.go: read gateway URL from envelope headers
- Modify internal/progress/reporter.go: unified event POST format
- Add pre-flight check in ProcessMessage before calling runtime
- Keep backward compat: if x-asya-gateway-url missing, use env var;
  if new /events endpoint 404s, fall back to old endpoints

Testing:
- Unit: header reading, event POST format, pre-flight logic
- Component: Docker Compose with new mesh-api, test full sidecar flow
- E2E: Kind cluster, test sidecar -> mesh-api -> SSE client flow
- Test backward compat: sidecar with old gateway, sidecar with new mesh-api

Can be parallelized with Phase 3 adapters (depends on nacr7 mesh-api only).
Depends on: nacr7 (mesh-api)
