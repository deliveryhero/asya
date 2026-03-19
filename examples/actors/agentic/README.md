# ABI Actor Examples: Agentic Patterns

Generator actor examples for the three runtime agentic patterns that cannot
be expressed in the Flow DSL alone. These files are directly deployable actor
handlers — not compilable flows.

| File | Pattern | ABI verbs used |
|------|---------|----------------|
| `dynamic_routing.py` | LLM decides next actor at runtime | `SET .route.next` |
| `live_streaming.py` | Stream LLM tokens to UI token-by-token | `FLY` |
| `pause_for_human.py` | Suspend pipeline for human approval | `SET .route.next[:0]` |

For explanation and worked examples, see
[docs/tutorials/agentic-patterns.md](../../../docs/tutorials/agentic-patterns.md).

## How these differ from `examples/flows/agentic/`

`examples/flows/agentic/` contains **Flow DSL** definitions — Python files that
you compile with `asya flow compile` to generate router actors. Routing decisions
are baked in at compile time.

These files are **generator actor handlers** — functions with `yield` statements
that communicate with the Asya runtime via the ABI protocol at execution time.
You deploy them directly:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-router
spec:
  actor: my-router
  image: my-agentic-actors:latest
  handler: dynamic_routing.dispatcher
```

## Deployment

Each file's module docstring lists the `ASYA_HANDLER` value and required env
vars. Example for dynamic routing:

```yaml
env:
  - name: ASYA_HANDLER
    value: dynamic_routing.dispatcher
  - name: ASYA_HANDLER_BILLING
    value: asya-prod-billing-agent
  - name: ASYA_HANDLER_TECH
    value: asya-prod-tech-support
```

## Testing locally

The ABI protocol is pure Python — no Asya infrastructure needed for unit tests.
Collect all yields and filter by type:

```python
import asyncio

async def test_dispatcher():
    payload = {"query": "invoice question", "_transfer_to": "billing"}
    events = [e async for e in dynamic_routing.dispatcher(payload)]

    set_cmds = [e for e in events if isinstance(e, tuple) and e[0] == "SET"]
    assert set_cmds == [("SET", ".route.next", ["asya-prod-billing-agent"])]

    frames = [e for e in events if isinstance(e, dict)]
    assert "_transfer_to" not in frames[0]  # cleaned up

asyncio.run(test_dispatcher())
```
