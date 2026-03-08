---
title: "Phase 3: MCP OAuth 2.1 spec compliance"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - pr:271
---



Full MCP authorization spec compliance with OAuth 2.1 + PKCE. See rfc.md section 7, Phase 3.

## Scope

- Protected Resource Metadata endpoint (/.well-known/oauth-protected-resource, RFC 9728)
- Authorization Server Metadata endpoint (/.well-known/oauth-authorization-server, RFC 8414)
- Authorization endpoint (/oauth/authorize)
- Token endpoint (/oauth/token) with PKCE (S256) validation
- Dynamic Client Registration endpoint (/oauth/register, RFC 7591)
- PostgreSQL tables: oauth_clients, oauth_tokens, oauth_authorization_codes
- Scope-based access control (mcp:invoke, mcp:read)
- Token refresh and rotation
- MCPAuthMiddleware OAuth mode (validate self-issued JWTs)
- Integration tests with MCP client library

## Dependencies

- Phase 1 (dual-deployment split)
- Phase 2 (MCP API key — provides middleware foundation)

## Acceptance Criteria

- MCP client can discover auth requirements via /.well-known/oauth-protected-resource
- MCP client can register dynamically via /oauth/register
- MCP client can obtain token via Authorization Code + PKCE flow
- Bearer token grants access to /mcp/* endpoints
- Invalid/expired tokens return 401
- Scopes restrict access (mcp:invoke for tool calls, mcp:read for listing)
- Token refresh works without re-authorization
- Integration test exercises full OAuth flow
