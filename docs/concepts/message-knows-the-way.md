---
description: "Envelope routing: route embedded in message (prev/curr/next), no external router or coordinator"
---

# Message Knows the Way

In most pipeline frameworks, a central coordinator decides where each message
goes next. In Asya, the **envelope** carries its own route. There is no external
database for pipeline state and no shared memory between actors.

## The envelope is the core primitive

Every message in the mesh is wrapped in an envelope containing three sections:

| Section | Purpose |
|---------|---------|
| `route` | Where the message has been, where it is, and where it goes next |
| `payload` | The application data — a plain JSON object |
| `headers` | Cross-cutting metadata: trace IDs, deadlines, status |

The route is a triplet — `prev`, `curr`, `next` — that fully describes the
message's journey through the mesh.

## Example envelope

```json
{
  "id": "env-abc123",
  "route": {
    "prev": ["preprocess"],
    "curr": "infer",
    "next": ["postprocess", "store"]
  },
  "headers": { "trace_id": "t-42" },
  "payload": { "text": "Hello world", "cleaned": true }
}
```

This envelope has already passed through `preprocess`, is currently being handled
by `infer`, and will next visit `postprocess` then `store`.

## Route advancement

After each actor processes a message, the runtime shifts the route forward:

1. `curr` is appended to `prev`
2. The first element of `next` becomes the new `curr`
3. `next` shrinks by one

```
Before infer:   prev=[preprocess]       curr=infer       next=[postprocess, store]
After infer:    prev=[preprocess,infer] curr=postprocess  next=[store]
After postproc: prev=[..., postprocess] curr=store        next=[]
After store:    next is empty → routed to x-sink
```

When `next` is empty and the actor finishes, the sidecar routes the envelope to
`x-sink` for result persistence. No special "end" marker is needed.

## Actors are stateless

Because the route travels with the message, actors do not need to know about the
pipeline they belong to. An actor receives the payload, processes it,
and returns the result. The sidecar handles the envelope and routing.

```python
# The actor never sees the envelope — only the payload
def process(state: dict) -> dict:
    state["prediction"] = model.predict(state["text"])
    return state
```

This means actors can be reused across different pipelines without modification.
The same `process` function works whether the route is
`[preprocess, infer, store]` or `[infer, judge, human-review]`.

## Why this matters

- **No single point of failure** — no coordinator to crash or bottleneck
- **Inspectable** — read any envelope to see exactly where it has been and where
  it will go
- **Replayable** — re-inject an envelope into any queue to restart from that
  point
- **Dynamic** — actors can rewrite `route.next` at runtime (see
  [Dynamic Routing](dynamic-routing.md))

## Further reading

- [Envelope specification](../reference/specs/envelope.md) — full field
  reference, ID generation, status codes
- [Actor Mesh](actor-mesh.md) — the architecture that envelopes enable
- [ABI Protocol](../reference/specs/abi-protocol.md) — how handlers read and
  modify envelope fields
