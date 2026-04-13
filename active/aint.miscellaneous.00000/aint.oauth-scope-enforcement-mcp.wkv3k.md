---
title: OAuth 2.1 scope enforcement per MCP endpoint (post-v0)
status: open
priority: 3
parent: 00000
---

OAuth tokens carry mcp:invoke / mcp:read scope claims but MCPAuthMiddleware does
not validate scope per operation — any valid token passes regardless of scope.

## Problem

OAuthBearerAuthenticator.Authenticate() returns bool. MCPAuthMiddleware calls
this and either allows or denies the request. There is no mechanism to:
- Extract claims from the validated token
- Check that the scope claim satisfies the required operation

A mcp:read token can currently invoke tools (POST /mcp with tools/call).

## Required Change

1. Extend the Authenticator interface (or add a separate Claims extractor)
   to return the validated token claims alongside the bool result.

2. Add per-route scope guards in MCPAuthMiddleware or at the handler level:
   - POST /tools/call, POST /mcp (tool invocations) → require mcp:invoke
   - GET /mcp/sse, listing operations → require mcp:read (or mcp:invoke)

3. Return 403 Forbidden (not 401) when token is valid but scope is insufficient.

4. Add integration test covering: mcp:read token rejected for tool invocation,
   mcp:invoke token accepted for tool invocation.

## Dependencies

- agentic-security/rcvm (OAuth 2.1 infrastructure, merged)

## Acceptance Criteria

- mcp:read-only token: GET /mcp/sse succeeds, POST /tools/call returns 403
- mcp:invoke token: POST /tools/call succeeds
- Full-scope token: all MCP endpoints accessible
- Component test covers all three cases
