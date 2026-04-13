---
title: API Key authentication middleware
status: merged
priority: 2
parent: emmc5
---

## Objective

Implement API Key authentication middleware for all `{base}/a2a/*` routes.

## Scope

### 1. Auth middleware

```go
func A2AAuthMiddleware(config AuthConfig) func(http.Handler) http.Handler
```

- Reads `ASYA_A2A_API_KEY` env var
- Validates `X-API-Key` header on all `{base}/a2a/*` routes
- Returns A2A-formatted JSON-RPC error (-32005) on auth failure
- Does NOT apply to `/mesh/*` or MCP routes

### 2. Agent Card security declaration

```json
{
  "securitySchemes": {
    "apiKey": {
      "apiKeySecurityScheme": {
        "location": "header",
        "name": "X-API-Key"
      }
    }
  },
  "securityRequirements": [{"schemes": {"apiKey": []}}]
}
```

### 3. Wire middleware

Apply middleware to A2A route group only when `ASYA_A2A_API_KEY` is set.

## References

- RFC section 12 (Phase 2: API Key), middleware architecture
- RFC section 15.2 test matrix, section 15.4 E2E tests

## Acceptance Criteria

- 401 for unauthenticated requests to A2A endpoints
- 200 for authenticated requests with valid API key
- No auth enforced on `/mesh/*` or MCP endpoints
- Agent Card includes `securitySchemes` when API key is configured
- Unit tests for middleware
