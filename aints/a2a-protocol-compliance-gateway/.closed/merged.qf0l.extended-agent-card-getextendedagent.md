---
title: Extended Agent Card (GetExtendedAgentCard)
priority: 3 # low
tags:
  - pr:262
---




## Objective

Implement `GetExtendedAgentCard` endpoint that returns an authenticated, extended version of the Agent Card with additional details not publicly visible.

## Scope

### 1. Endpoint

**Method**: `extendedAgentCard`
**HTTP**: `GET {base}/a2a/extendedAgentCard`

Returns an extended Agent Card with auth-gated details (e.g., internal skill metadata, configuration hints, extended capabilities).

### 2. Capability flag

Update the Agent Card to declare `capabilities.extended_agent_card: true` once this is implemented. Currently returns `a2a.ErrUnsupportedOperation`.

### 3. Auth requirement

This endpoint MUST require authentication (API Key or JWT). Unauthenticated requests get JSON-RPC error.

## References

- RFC section 7.8 (GetExtendedAgentCard), section 6.1 (endpoint layout)

## Acceptance Criteria

- Authenticated requests receive extended Agent Card
- Unauthenticated requests receive error
- Agent Card `capabilities.extended_agent_card` reflects availability
- Unit tests
