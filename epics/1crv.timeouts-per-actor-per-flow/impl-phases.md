# Implementation Phases: Timeouts Per-Actor and Per-Flow

**Epic**: 1crv
**RFC**: `rfc.md` (in this directory)
**Design**: `docs/plans/2026-02-25-timeouts-design.md`

## Dependency Graph

```
Wave 1                   Wave 2                     Wave 3        Wave 4
───────                  ───────                    ───────       ───────

[1kjf7f]                 [1k1pjy]                                [1k8024]     [1kow6k]
DeadlineAt ──────────┬──> effectiveTimeout ──┬──> (depends) ──┬──> Integration ──> E2E
  field              │    + SLA pre-check    │                │     tests         tests
                     │         │             │                │
[1kbup4]             │    [1kqf0j]           │                │
CallRuntime ─────────┘    Component ─────────┘                │
  refactor                  tests                             │
                                                              │
                     [1kz8ww]                                 │
                     Gateway ─────────────────────────────────┘
                       deadline stamping
                       (parallel with Wave 2)
```

---

## Wave 1: Sidecar Foundation

**PR scope**: Message protocol + runtime client refactor. No behavior change for
existing messages (no deadline = no SLA check).

**Why first**: Everything else depends on the `DeadlineAt` field existing and
`CallRuntime` accepting per-message timeouts.

| Ref | Task | Files |
|-----|------|-------|
| `1crv/1kjf7f` | Add `DeadlineAt` to message `Status` struct + `ParseDeadline()` helper | `src/asya-sidecar/pkg/messages/message.go` |
| `1crv/1kbup4` | Refactor `CallRuntime` to accept per-call timeout; update visibility timeout formula to `max(actor, runtime) * 2` | `src/asya-sidecar/internal/runtime/client.go`, `internal/router/router.go`, `cmd/sidecar/main.go` |

**Merge criteria**:
- All existing unit tests pass (no behavior change)
- New unit tests for `ParseDeadline` (valid, empty, malformed)
- New unit tests for visibility timeout formula
- `CallRuntime` callers updated to pass `r.cfg.Timeout`

---

## Wave 2: Sidecar SLA Enforcement

**PR scope**: Core feature — wire up `ActorTimeout` (currently dead scaffolding),
add SLA pre-check, route expired messages to x-sink. This is the main behavior change.

**Why second**: Needs the `DeadlineAt` field and per-call timeout from Wave 1.

| Ref | Task | Files |
|-----|------|-------|
| `1crv/1k1pjy` | Add `effectiveTimeout()` method + SLA pre-check before `CallRuntime` | `src/asya-sidecar/internal/router/router.go` |
| `1crv/1kqf0j` | Component tests: expired message to x-sink, tight SLA reduces timeout | `testing/component/sidecar/` |

**Merge criteria**:
- `effectiveTimeout` unit tests: all precedence combos (runtime-only, actor < runtime, SLA < actor, no deadline)
- SLA pre-check unit tests: expired skips runtime, valid calls runtime
- Component test: expired message acked + routed to x-sink, runtime never called
- Component test: tight SLA → runtime receives reduced timeout

---

## Wave 3: Gateway Deadline Alignment

**PR scope**: Fix the protocol mismatch — gateway currently stamps deadline as a
top-level `ActorMessage.Deadline` field, but sidecar reads `status.deadline_at`.
Move the field.

**Why parallel with Wave 2**: Gateway and sidecar are separate components. This wave
can be developed and reviewed alongside Wave 2. Both must merge before Wave 4.

| Ref | Task | Files |
|-----|------|-------|
| `1crv/1kz8ww` | Stamp `status.deadline_at` in message protocol; add `ASYA_GATEWAY_DEFAULT_TIMEOUT` env var | `src/asya-gateway/internal/queue/queue.go`, `rabbitmq.go`, `sqs.go` |

**Merge criteria**:
- Published messages have `status.deadline_at` (not top-level `Deadline`)
- `ASYA_GATEWAY_DEFAULT_TIMEOUT` env var honored (default 5m)
- `timeout_seconds=0` in tool config → no deadline stamped
- Unit tests for all cases
- Existing gateway tests updated

---

## Wave 4: Cross-Component Validation

**PR scope**: Integration and E2E tests that validate the full timeout pipeline
end-to-end: gateway stamps deadline, sidecar enforces it, retries respect SLA,
backstop timer handles queue delays.

**Why last**: Requires both sidecar (Waves 1+2) and gateway (Wave 3) changes merged.

| Ref | Task | Files |
|-----|------|-------|
| `1crv/1k8024` | Integration tests: SLA across sidecar+runtime, retry+SLA interaction, gateway backstop | `testing/integration/sidecar-runtime/`, `gateway-actors/` |
| `1crv/1kow6k` | E2E tests: full pipeline SLA, slow actor crash, gateway backstop race | `testing/e2e/tests/` |

**Merge criteria**:
- Integration: expired mid-pipeline → x-sink
- Integration: retries stop on SLA expiry (not max_attempts)
- Integration: gateway backstop fires independently of sidecar
- E2E: pipeline completes within SLA
- E2E: slow actor → pod crash + task failed
- E2E: backstop race → first-write-wins, second report ignored

---

## Parallelism

```
Time ──────────────────────────────────────────────>

Wave 1  ██████████████
Wave 2                 ██████████████████
Wave 3                 ████████████████         (parallel with Wave 2)
Wave 4                                   ██████████████████
```

Waves 2 and 3 are independent and can be developed on separate branches
simultaneously. Wave 4 requires both to be merged.

## Risk Notes

- **Clock skew**: Negligible within K8s cluster (NTP-synced). No mitigation needed.
- **Crash-on-timeout**: Preserved by design. No graceful cancellation.
- **Backward compatibility**: Messages without `deadline_at` skip SLA check entirely.
  Per-actor timeout still applies. Zero behavior change for existing deployments
  until gateway starts stamping deadlines.
