---
description: "Role separation: data scientists write Python handlers, platform engineers configure infrastructure"
---

# Separation of Concerns

Asya enforces a clean boundary between application logic and infrastructure
configuration. Two files, two owners, zero overlap.

## Two files, two roles 🎭

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

## Actor Flavors: complexity hidden by platform

The full AsyncActor CRD has many fields — transport config, sidecar settings,
state proxy, KEDA triggers, resource limits. Platform engineers pre-configure
these as **flavors**: reusable templates that bundle infrastructure defaults.

```yaml
# What the data scientist sees (flavor = gpu-inference):
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-model
spec:
  flavor: gpu-inference    # platform-defined preset
  image: my-model:latest
  handler: model.predict
```

```yaml
# What the platform team defined in the flavor:
#   GPU node affinity, 0-10 scaling, 90s timeout,
#   retry with backoff, SQS transport, S3 state proxy
```

The flavor absorbs the complexity. The data scientist's YAML stays short and
readable — just name, image, handler, and flavor.

## What each side controls

**Data scientist**:
- Business logic (model inference, data transforms, LLM calls)
- Input/output contract (payload schema)
- Local testing with `pytest`
- Choosing a flavor (e.g., `gpu-inference`, `cpu-fast`, `agentic`)

**Platform team**:
- Defining flavors with sensible defaults
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
