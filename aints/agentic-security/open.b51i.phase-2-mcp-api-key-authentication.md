---
title: "Phase 2: MCP API key authentication"
priority: 2 # medium
---

Simple Bearer token auth for MCP endpoints. Reuse existing Authenticator interface from A2A auth. See rfc.md section 7, Phase 2.

## Scope

- Add MCPAuthMiddleware using existing Authenticator interface
- ASYA_MCP_API_KEY env var
- Apply to /mcp, /mcp/sse, /mcp/tools/call
- 401 response with WWW-Authenticate header when key missing/invalid
- Unit tests for MCP auth middleware

## Not in Scope

- OAuth 2.1 (Phase 3)
- MCP metadata discovery endpoints (Phase 3)

## Acceptance Criteria

- When ASYA_MCP_API_KEY is set, /mcp/* routes require Authorization: Bearer <key>
- When ASYA_MCP_API_KEY is empty, MCP auth is disabled (dev mode)
- Invalid/missing token returns 401
- Unit tests cover valid, invalid, missing, and disabled cases
