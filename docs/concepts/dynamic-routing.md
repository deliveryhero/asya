# Dynamic Routing

In static pipeline frameworks like Airflow or Argo Workflows, the execution
graph is fixed at compile time. In Asya, routes are data embedded in each
message, and actors can rewrite the future at runtime.

## Routes are data, not infrastructure

Every envelope carries a `route` object with three fields:

- `prev` — actors already visited (read-only)
- `curr` — the actor currently processing this message (read-only)
- `next` — the actors still to visit (writable)

Because the route is inside the message, different messages can follow different
paths through the same set of actors.

## Actors can change the future

A generator handler can insert actors at the front of `route.next` using the
slice notation `.route.next[:0]`. This **prepends** without losing the remaining
route:

```python
def handler(payload: dict):
    confidence = payload["score"]
    if confidence < 0.7:
        # Insert human-review before whatever comes next
        yield "SET", ".route.next[:0]", ["human-review"]
    else:
        yield "SET", ".route.next[:0]", ["auto-approve"]
    yield payload
```

> **Avoid** overwriting `.route.next` entirely (e.g., `yield "SET", ".route.next", [...]`).
> This discards the remaining route and breaks downstream actors that expect to
> receive the envelope. Use `.route.next[:0]` to prepend safely.

Only `.route.next` is writable. `.route.prev` and `.route.curr` are read-only,
enforcing a forward-only execution model — actors cannot rewrite history.

## What this enables

- **LLM judges** — a model evaluates quality and routes to different downstream
  actors based on the result
- **Confidence-based branching** — low-confidence predictions go to human review
- **Agentic loops** — an actor routes back to itself (via next) for iterative
  refinement
- **Human-in-the-loop** — route to `x-pause` to checkpoint and wait for human
  input, then resume with `x-resume`

## Contrast with static DAGs

| Property | Static DAG (Airflow, Argo) | Asya dynamic routing |
|----------|---------------------------|---------------------|
| Graph | Fixed at deploy time | Rewritten per message |
| Branching | Declared in DAG definition | Decided by actor code |
| Loops | Not supported or limited | Actor routes back to itself |
| New paths | Requires redeployment | Just change `route.next` |

## Further reading

- [ABI Protocol](../reference/specs/abi-protocol.md) — full yield protocol for
  GET/SET/FLY operations
- [Agentic Patterns](../usage/guide-agentic-patterns.md) — routing patterns for
  AI agent workflows
- [Pause/Resume](../usage/guide-pause-resume.md) — human-in-the-loop via
  `x-pause` and `x-resume`
