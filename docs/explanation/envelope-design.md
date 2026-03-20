<!-- Type: Explanation -->

# Understanding the Envelope

The envelope is the fundamental data structure in Asya. Every message flowing
through the actor mesh is an envelope. This document explains the design
decisions behind its structure.

## The envelope at a glance

```json
{
  "id": "env-abc123",
  "parent_id": null,
  "route": {
    "prev": ["preprocess"],
    "curr": "inference",
    "next": ["postprocess"]
  },
  "headers": {
    "trace_id": "t-42"
  },
  "status": {
    "phase": "processing",
    "deadline_at": "2025-11-18T12:05:00Z"
  },
  "payload": {
    "text": "Hello world"
  }
}
```

**Reference**: [Actor-Actor Protocol](../architecture/protocols/actor-actor.md)
for the full field specification.

## Why route has prev / curr / next

The route is split into three parts rather than being a flat list with an
index pointer. Each part serves a distinct purpose.

### prev: audit trail

`route.prev` records which actors have already processed this envelope. It
grows as the envelope moves through the pipeline. This provides:

- **Traceability**: any actor can see who processed the envelope before it
- **Progress calculation**: `len(prev) / (len(prev) + 1 + len(next))` gives
  a natural progress percentage
- **Debugging**: when an envelope arrives in x-sump with an error, `prev`
  shows exactly which actors it passed through successfully

### curr: current actor identity

`route.curr` tells the actor which queue it was consumed from. This matters
for actors that serve multiple roles or for debugging. The sidecar uses `curr`
to validate that the envelope arrived at the correct destination.

### next: remaining pipeline (writable)

`route.next` is the only writable part of the route. Actors can modify it
to implement dynamic routing:

```python
# Conditional routing
if payload.get("needs_review"):
    yield "SET", ".route.next", ["reviewer", "notifier"]
else:
    yield "SET", ".route.next", ["notifier"]
```

Making `next` writable while `prev` and `curr` are read-only enforces a
forward-only model: actors can change the future, but they cannot rewrite
history.

### Route advancement

The runtime (not the sidecar) advances the route after the handler completes:

1. `curr` is appended to `prev`
2. The first element of `next` becomes the new `curr`
3. `next` shrinks by one

This happens inside the runtime so that any routing changes the handler makes
via `yield "SET", ".route.next", [...]` are reflected before advancement.

## Why envelope IDs are immutable

The `id` field is set when the envelope is created and never changes. This
enables:

- **Deduplication**: actors can detect redelivered messages by ID
- **Correlation**: the gateway tracks task progress by envelope ID
- **Lineage**: when fan-out creates multiple envelopes from one, all children
  carry `parent_id` pointing to the original

### Fan-out ID semantics

When a generator handler yields multiple payloads, the sidecar creates
separate envelopes:

- Index 0: retains the original `id` (for SSE streaming compatibility)
- Index 1+: receives suffixed IDs (`original-id-1`, `original-id-2`, ...)
- All children set `parent_id` to the original envelope ID

This means the first child can be tracked by the gateway as if it were the
original envelope, while subsequent children are traceable via `parent_id`.

## Why payload is opaque to the sidecar

The sidecar never reads, validates, or modifies the `payload` field. Only the
actor handler sees it. This separation has several benefits:

- **Actor autonomy**: actors define their own payload schema. There is no
  framework-imposed structure
- **Zero coupling**: the sidecar is a generic router. The same sidecar binary
  works for an LLM inference actor, a data preprocessor, or an image resizer
- **Payload enrichment**: actors append to the payload rather than replacing
  it, building up a processing record as the envelope moves through the
  pipeline

The enrichment pattern is the recommended approach:

```json
// After preprocess
{"product_id": "123", "product_name": "Ice-cream Bourgignon"}

// After inference (appended, not replaced)
{"product_id": "123", "product_name": "Ice-cream Bourgignon", "recipe": "..."}

// After judge (appended again)
{"product_id": "123", "product_name": "...", "recipe": "...", "recipe_eval": "INVALID"}
```

## Why x-sink and x-sump are automatic

Every envelope ends at one of two destinations: `x-sink` (success) or
`x-sump` (error). These are automatic -- you never include them in
`route.next`.

### Convention over configuration

The sidecar applies simple rules:

| Condition | Destination |
|-----------|-------------|
| `route.next` is empty (pipeline complete) | x-sink |
| Handler returned `None` (intentional abort) | x-sink |
| SLA deadline expired before calling runtime | x-sink (with `phase=failed`, `reason=Timeout`) |
| Handler raised an exception | x-sump |
| Runtime timed out | x-sump |

This means every pipeline has exactly two terminal states, regardless of how
many actors it has or how routing is modified. Operators know where to look
for results (x-sink) and errors (x-sump) without reading the pipeline
definition.

### Why not a configurable error handler?

Allowing per-actor error routing would make failure analysis harder: you would
need to know each actor's error configuration to find where a failed envelope
landed. With a single x-sump, monitoring is straightforward -- alert on
x-sump queue depth.

For retry scenarios, the `resiliency` configuration on the AsyncActor CRD
handles retries before routing to x-sump. The actor can define policies with
backoff, attempt limits, and even an `onExhausted` route for custom exhaustion
handling.

## Why headers exist separately from payload

Headers carry metadata that is meaningful to the infrastructure (trace IDs,
priorities) but not to the handler's business logic. Separating them from the
payload means:

- The sidecar can read headers (for logging, correlation) without parsing the
  payload
- Actors can set headers via the ABI (`yield "SET", ".headers.trace_id", "..."`)
  without touching the payload
- Headers propagate through the entire pipeline automatically

## The status field

The `status` field is optional and stamped by the gateway when it creates the
envelope:

- `phase`: lifecycle phase (`pending`, `processing`, `succeeded`, `failed`)
- `deadline_at`: absolute pipeline deadline in RFC 3339 UTC

The sidecar uses `deadline_at` for SLA pre-checks: if the deadline has passed
before calling the runtime, the envelope is routed to x-sink with
`phase=failed` and `reason=Timeout`. The runtime is never called -- no wasted
compute.

The deadline is an absolute timestamp (not a duration) so it is unambiguous
regardless of clock skew or processing delays across actors.

## Further reading

- [Actor-Actor Protocol](../architecture/protocols/actor-actor.md) -- full
  envelope specification
- [ABI Protocol Reference](../reference/abi-protocol.md) -- how handlers
  interact with envelope metadata
- [Why Choreography?](choreography-vs-orchestration.md) -- the coordination
  model that the envelope enables
