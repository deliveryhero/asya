---
title: Support handler-driven retry delay (Retry-After from handler)
status: open
priority: 2
---

## Context

Referenced in error-handling RFC as deferred work (legacy ref `asya-0gsw`). When a handler calls a rate-limited API (e.g. OpenAI returns 429 with Retry-After: 30), the handler knows the optimal retry delay but has no way to communicate it to the sidecar.

## Problem

Currently the sidecar computes retry delay from its static config (exponential/constant backoff). The handler has no mechanism to override this. For LLM API rate limits, the API itself tells you exactly when to retry — ignoring this wastes retries or waits too long.

## Proposed Solution

Extend the error response to include a `retry_after` field:

```json
{
  "error": "processing_error",
  "details": {
    "type": "openai.RateLimitError",
    "message": "Rate limit exceeded",
    "retry_after": 30
  }
}
```

Sidecar uses `max(computed_backoff, retry_after)` as the actual delay.

### Runtime Changes

Runtime `_error_response()` inspects the exception for a `retry_after` attribute (common in HTTP client libraries) and includes it in the response.

### Sidecar Changes

Router checks `error.retry_after` before computing backoff. If present, uses it as floor for the delay.

## Dependencies

- Requires runtime protocol extension (error response format)
- Sidecar must parse and respect the field
- XRD doesn't need changes (this is per-message, not per-actor config)
