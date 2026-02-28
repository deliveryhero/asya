---
title: "Streaming Protocol: Upstream Events to Gateway"
status: peeped
priority: 2 # medium
type: epic
---

Upstream event streaming from generator handlers to the gateway for real-time UI
updates (LLM token streaming, progress indicators). Upstream events are
transport-level — they flow directly from sidecar to gateway via HTTP, never
entering message queues.

## Status

All implementation tasks are **vibed** (done):
- Runtime async generator support (PR #203)
- Runtime SSE streaming for generators (PR #205)
- Sidecar SSE parser (PR #205)
- Sidecar→Gateway forwarding (PR #205)
- Integration test: full streaming path (PR #209)

One remaining task (compiler: reject async-for/yield-from) is **slopped** — see
task 1khyvl. This task's scope has narrowed: the Flow DSL now uses only `await`
(epic 1l04), so async-for/yield-from are already rejected by the parser. The
remaining work is ensuring the error messages are clear and reference the
streaming rationale.

## Architecture Decisions (Authoritative)

This epic established the foundational streaming architecture for Asya. The
design decisions in `rfc.md` remain authoritative:

1. **Transport-level, not payload-level** — streaming events bypass queues,
   flow direct from sidecar to gateway via HTTP
2. **No back-pressure across queue boundaries** — `GeneratorExit` cannot
   propagate across queues, so `async for event in actor(): yield event`
   is fundamentally impossible
3. **Best-effort delivery** — streaming events are ephemeral; if gateway is
   unreachable, events are dropped

## Evolution

### Handler-side interface (epic 1l01)

The original handler convention for marking upstream events:

```python
# Current: dict key convention
yield {"partial": True, "token": "hello"}
```

Is being replaced by the ABI `FLY` verb (epic 1l01):

```python
# Future: structural ABI instruction
yield "FLY", {"token": "hello"}
```

FLY separates control plane (tuple type) from data plane (dict contents). The
runtime dispatches on `type(yielded_value)` — no need to inspect dict keys for
control signals. See `../1l01.abi-instead-vfs/abi-protocol.md` Section 3.2.

### Wire protocol renaming (epic 1l02)

Epic 1l02 renames the downstream propagation to match:
- `ForwardPartial()` -> `ForwardStream()`
- `POST /tasks/{id}/partial` -> `POST /tasks/{id}/stream`
- `event: partial` -> `event: stream`
- `PartialPayload` -> `StreamPayload`

The runtime→sidecar wire format (`event: upstream`) is **unchanged** — it
already uses directional naming, not semantic naming.

## Dependencies

- Depends on: epic 1fbe (HTTP-over-Unix-socket protocol)
- Depended on by: epic 1l01 (ABI — FLY verb), epic 1l02 (rename partial→stream)
