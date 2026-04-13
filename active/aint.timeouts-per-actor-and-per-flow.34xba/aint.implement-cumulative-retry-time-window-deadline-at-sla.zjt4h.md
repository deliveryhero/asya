---
title: Implement cumulative retry time window (deadline_at SLA enforcement)
status: open
priority: 2
parent: 34xba
---

## Problem

Asya supports 3 of 4 standard retry concepts but is missing cumulative time windows:

| Concept | Status | Config |
|---------|--------|--------|
| Max attempts | Implemented | `ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS` (default 3) |
| Backoff strategy | Implemented | `ASYA_RESILIENCY_RETRY_POLICY` + initial/max interval + coefficient + jitter |
| Exception filter | Implemented | `ASYA_RESILIENCY_NON_RETRYABLE_ERRORS` (blacklist with MRO matching) |
| Per-call timeout | Implemented | `ASYA_RESILIENCY_ACTOR_TIMEOUT` (scaffolded but dead - never read by router) |
| **Cumulative time window** | **Missing** | No config. RFC designed `status.deadline_at` but not implemented |

Without a cumulative window, a 5-actor pipeline with 3 retries * 5min timeout = 75 minutes
of wasted processing while the caller gave up after 30 seconds.

## What to implement

The timeout-handling RFC (`timeout-handling/rfc.md`) has a complete design:

1. **Message protocol**: Add `status.deadline_at` field (absolute timestamp, set once by gateway, never mutated)
2. **Sidecar SLA check**: Before calling runtime, check `now > deadline_at` -> route to x-sink (failed/Timeout), no retry
3. **Effective timeout**: `min(remaining_sla, actor_timeout, runtime_timeout)` - lowest wins
4. **Wire up ActorTimeout**: `cfg.Resiliency.ActorTimeout` is already parsed but never read by router
5. **Gateway deadline stamping**: `deadline_at = now + TimeoutSec` at message creation
6. **Gateway backstop timer**: Independent `time.AfterFunc` per task for messages stuck in queues
7. **Retry interaction**: `deadline_at` preserved across retries; SLA expiry stops retries regardless of `max_attempts`

## Key files

- **RFC**: `.aint/aints/timeout-handling/rfc.md` (full design with code samples)
- **Router (add SLA check)**: `src/asya-sidecar/internal/router/router.go`
- **Config (ActorTimeout already parsed)**: `src/asya-sidecar/internal/config/config.go`
- **Runtime client (per-call timeout)**: `src/asya-sidecar/internal/runtime/client.go`
- **Message types**: `src/asya-sidecar/internal/messages/message.go`
- **Gateway queue publish**: `src/asya-gateway/internal/queue/`
- **Gateway task types**: `src/asya-gateway/pkg/types/task.go`
- **XRD (actorTimeout field exists)**: `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`
- **Injector (already injects env var)**: `src/asya-injector/internal/injection/inject.go`

## Why this matters for decorator story

All major Python retry libraries support cumulative time windows:
- tenacity: `stop=stop_after_delay(30)`
- stamina: `timeout=45.0`
- backoff: `max_time=60`
- opnieuw: `retry_window_after_first_call_in_seconds=60`

Without this Asya concept implemented, the compiler cannot generate config for timeout-related
decorator arguments even if it can parse them. This is a prerequisite for the full decorator
extraction story in [1fmi].

## Testing

See RFC testing strategy section. Key tests:
- Unit: `effectiveTimeout` precedence, `ParseDeadline` parsing, expired message routing
- Integration: retries stop on SLA expiry, gateway backstop race
- E2E: full pipeline SLA enforcement
