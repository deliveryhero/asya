# Multi-Tenant AI Pipeline Platform

## Use-Case

A platform team serves N internal teams (content moderation, customer support,
data enrichment, report generation). Teams define flows in Python; the platform
deploys and runs them as AsyncActor CRDs on a shared Kubernetes cluster.

## Why Asya

- **Actor isolation**: Each team's actors are separate pods with own resource
  quotas, secrets, and scaling policies. One team's bug can't crash another's.
- **Queue-per-actor**: Per-team backpressure. A spike in content moderation
  requests doesn't starve customer support.
- **State-in-message**: No shared database between teams. Each envelope carries
  its full processing context — complete tenant isolation.
- **Flow DSL**: Teams write Python control flow, compiler generates CRDs.
  Platform team manages infrastructure, not application code.
- **Gateway as API layer**: Each flow exposed as MCP tool or A2A agent.
  Consumers interact via standard protocols, unaware of pipeline internals.

## Architecture

```
Team A (Python flow) ──compile──> AsyncActor CRDs ──> Namespace A
Team B (Python flow) ──compile──> AsyncActor CRDs ──> Namespace B
                                                         |
                                 Gateway (shared) <──────+
                                    |
                        MCP / A2A / REST clients
```

## Key Asya Features Used

- Flow DSL compilation to CRDs
- Per-actor KEDA autoscaling (queue depth triggers)
- Namespace-level isolation
- Gateway flow-to-tool mapping via ConfigMap
- Resiliency policies per actor (retry, DLQ)

## Example Flow (Team: Content Moderation)

```python
@flow
async def moderate_content(p):
    p = await toxicity_classifier(p)
    if p["toxicity_score"] > 0.8:
        p = await human_review(p)  # pause/resume
    elif p["toxicity_score"] > 0.5:
        p = await auto_flag(p)
    else:
        p = await auto_approve(p)
    p = await audit_logger(p)
    return p
```
