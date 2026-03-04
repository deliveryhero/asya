---
title: Bearer/JWT authentication
priority: 2 # medium
---


## Objective

Implement Bearer/JWT authentication for A2A endpoints, building on the API Key middleware from T12.

## Scope

### 1. JWT validation

Add JWT validation to the existing A2A auth middleware:

- `ASYA_A2A_JWT_ISSUER` — expected token issuer
- `ASYA_A2A_JWT_AUDIENCE` — expected token audience
- `ASYA_A2A_JWT_JWKS_URL` — JWKS endpoint for key validation

### 2. Agent Card security declaration

```json
{
  "securitySchemes": {
    "bearer": {
      "httpAuthSecurityScheme": {
        "scheme": "bearer",
        "bearerFormat": "JWT"
      }
    }
  }
}
```

### 3. Multi-scheme support

Support both API Key and JWT simultaneously — if either authenticates, request is allowed.

## Implementation Details

### Go libraries

- `github.com/golang-jwt/jwt/v5` — JWT parsing and standard claim validation
- `github.com/MicahParks/keyfunc/v3` — JWKS fetching, caching, and key rotation

### Middleware design

Refactor `auth.go` to support a chain of authenticators. A request passes if ANY
configured authenticator succeeds:

```go
type Authenticator interface {
    Authenticate(r *http.Request) bool
}

func A2AAuthMiddleware(authenticators ...Authenticator) func(http.Handler) http.Handler
```

Concrete implementations:
- `APIKeyAuthenticator` — existing X-API-Key header check (constant-time compare)
- `JWTAuthenticator` — parses `Authorization: Bearer <token>`, validates via JWKS

### Environment variables

All three required when JWT is enabled:
- `ASYA_A2A_JWT_JWKS_URL` — JWKS endpoint (e.g. `https://auth.example.com/.well-known/jwks.json`)
- `ASYA_A2A_JWT_ISSUER` — expected `iss` claim
- `ASYA_A2A_JWT_AUDIENCE` — expected `aud` claim

### Agent Card update

When JWT is configured, add both `apiKey` and `bearer` to `securitySchemes`.
Security requirements list both (OR semantics per A2A spec):

```json
{
  "security": [
    {"apiKey": {}},
    {"bearer": {}}
  ]
}
```

### a2a-go types used

- `a2alib.HTTPAuthSecurityScheme{Scheme: "bearer", BearerFormat: "JWT"}`
- `a2alib.SecuritySchemeName("bearer")`

### Error response

JSON-RPC error code `-32005` with HTTP 401, same as API Key rejection.
The `writeJSONRPCError` helper already exists.

### Agent card bypass

Exact path match `r.URL.Path == "/.well-known/agent.json"` (already implemented).

## References

- RFC section 12 (Phase 3: Bearer Token)
- a2a-go `a2a/auth.go` lines 170-183 (HTTPAuthSecurityScheme)

## Acceptance Criteria

- Valid JWT with correct issuer/audience passes authentication
- Invalid/expired JWT is rejected with JSON-RPC error (`-32005`)
- Expired JWT is rejected
- Missing/malformed `Authorization` header falls through to next authenticator
- JWKS endpoint is fetched and cached (auto-refresh on key rotation)
- API Key and JWT can coexist (either is sufficient)
- Agent Card `securitySchemes` reflects all configured auth methods
- Agent Card `security` lists schemes with OR semantics
- Unit tests for JWT validation (valid, expired, wrong issuer, wrong audience)
- Unit tests for multi-scheme auth chain
