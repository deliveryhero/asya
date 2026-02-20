---
title: Implement authentication middleware
status: open
priority: 2 # medium
type: task
---


Add authentication support for A2A endpoints.

## Requirements
- Support multiple auth schemes as declared in Agent Card
- Bearer token (JWT) validation
- OAuth2 client credentials flow
- API key authentication (header or query param)

## Auth Schemes

### 1. Bearer Token (JWT)
- Header: Authorization: Bearer <token>
- Validate against JWKS endpoint
- Extract claims for authorization

### 2. OAuth2 Client Credentials
- Token endpoint for machine-to-machine auth
- Scope-based access control (agent:invoke, agent:read)

### 3. API Key
- Header: X-API-Key: <key>
- Or query: ?api_key=<key>
- Simple validation against configured keys

## Implementation
- Add auth middleware in internal/auth/middleware.go
- Configure via environment variables:
  - ASYA_AUTH_ENABLED=true
  - ASYA_JWKS_URL=https://auth.example.com/.well-known/jwks.json
  - ASYA_API_KEYS=key1,key2,key3
- Apply to all A2A endpoints
- Skip auth for /.well-known/a2a/agent-card (public)
- Skip auth for /health

## Error Responses
- 401 Unauthorized - Missing or invalid credentials
- 403 Forbidden - Valid credentials but insufficient scope

## Testing
- Unit test for each auth scheme
- Integration test for protected endpoints
- Test public endpoints without auth


---
_Migrated from beads `asya-wir`_
