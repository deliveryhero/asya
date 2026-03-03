---
title: "Rename Gateway REST API: /envelope/* → /runs/*"
priority: 2 # medium
---




Rename Gateway REST API endpoints for better alignment with standards:
- /envelope/{id}/status → /runs/{id}/status
- /envelope/{id}/stream → /runs/{id}/stream
- Any other /envelope/* endpoints

Update:
- Go route handlers
- OpenAPI/Swagger specs if any
- CLI tools (asya mcp status, asya mcp stream)
- Documentation
- Integration and E2E tests

This aligns with A2A (Agent-to-Agent) and A2UI patterns where 'runs' is standard terminology.


---
**Close reason**: Completed as part of the envelope→message/task rename PR


---
_Migrated from beads `asya-w4j`_
