---
title: Bearer/JWT authentication
priority: 2 # medium
dependencies:
  - tuw5
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

## References

- RFC section 12 (Phase 3: Bearer Token)

## Acceptance Criteria

- Valid JWT with correct issuer/audience passes authentication
- Invalid/expired JWT is rejected with JSON-RPC error
- JWKS endpoint is fetched and cached for key validation
- API Key and JWT can coexist (either is sufficient)
- Agent Card reflects configured security schemes
- Unit tests for JWT validation
