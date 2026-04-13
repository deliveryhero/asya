---
title: "Phase 4: Enterprise auth (OAuth2 + OIDC for both protocols)"
status: open
priority: 3
---

OAuth2 and OIDC support for both A2A and MCP protocols. See rfc.md section 7, Phase 4.

## Scope

- A2A: OAuth2SecurityScheme support (Client Credentials flow)
- A2A: OpenIdConnectSecurityScheme support
- MCP: Client Credentials grant type (machine-to-machine, no user interaction)
- Scope-based access control for A2A (agent:invoke, agent:read)
- Agent Card dynamically reflects all configured auth schemes
- Audit logging for auth events (successful/failed auth attempts)

## Dependencies

- Phase 1 (dual-deployment split)
- Phase 3 (MCP OAuth 2.1 — token infrastructure)

## Acceptance Criteria

- A2A clients can authenticate via OAuth2 Client Credentials flow
- A2A clients can authenticate via OIDC (external IdP)
- MCP machine-to-machine clients can use Client Credentials grant
- Scopes restrict A2A operations
- Agent Card security section reflects all configured schemes dynamically
- Auth events are logged with timestamp, scheme, result, client identity
