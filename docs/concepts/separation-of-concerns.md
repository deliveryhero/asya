# Separation of Concerns

Asya enforces a clean boundary between application logic and infrastructure
configuration. Two files, two owners, zero overlap.

## Two files, two roles

| File | Owner | Contains |
|------|-------|----------|
| `handler.py` | Data scientist / ML engineer | Pure Python: `dict -> dict` |
| `actor.yaml` | Platform / DevOps team | Scaling, transport, retries, timeouts, monitoring |

The data scientist writes a plain function. No SDK imports, no infrastructure
code, no queue client, no retry logic. The function receives a dictionary and
returns a dictionary.

```python
def handler(payload: dict) -> dict:
    result = my_model.predict(payload["input"])
    return {"prediction": result}
```

The platform team writes an `AsyncActor` manifest that configures everything
else: which queue to read from, how many replicas, what retry policy to apply,
which secrets to mount.

## No SDK lock-in

The handler has zero dependencies on Asya. It can be unit-tested with a plain
`assert handler({"input": "x"}) == {"prediction": "y"}`. No mocking of
framework internals, no test harness setup.

This also means the handler is portable. If the team moves away from Asya, the
business logic transfers without rewriting.

## Flow compiler extends this model

The [Flow Compiler](flow-compiler.md) lets data scientists describe multi-actor
pipelines as familiar Python — `if/else`, loops, `asyncio.gather`. The compiler
produces standard `AsyncActor` manifests. The data scientist never touches YAML;
the platform team never reads Python pipeline code.

## What each side controls

**Data scientist**:
- Business logic (model inference, data transforms, LLM calls)
- Input/output contract (payload schema)
- Local testing with `pytest`

**Platform team**:
- Transport backend (SQS, RabbitMQ, Pub/Sub)
- Autoscaling thresholds (KEDA)
- Retry policies, timeouts, SLA deadlines
- Secret injection, resource limits, node affinity

## Further reading

- [Your first actor](../usage/start-first-actor.md) — write a handler and deploy
  it
- [AsyncActor CRD](../reference/specs/asyncactor-crd.md) — full manifest
  reference
- [Handler Patterns](../usage/guide-handler-patterns.md) — function vs generator
  handlers
