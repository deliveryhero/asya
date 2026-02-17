---
title: "Crossplane + Injector: resiliency config in XRD and ASYA_RESILIENCY_* env injection"
status: open
priority: 2 # medium
type: task
---

Update Crossplane XRD and compositions + injector to support resiliency configuration.

XRD changes (deploy/helm-charts/asya-crossplane/):
- Add spec.resiliency section to AsyncActor XRD with retry, nonRetryableErrors, slaTimeout fields
- Composition: flatten hierarchical resiliency config into ASYA_RESILIENCY_* env vars
- Create _sink queue alongside actor queue (asya-{ns}-_sink)
- Configure transport-level DLQ (SQS RedrivePolicy with maxReceiveCount)

Injector changes (src/asya-injector/):
- Pass ASYA_RESILIENCY_* env vars from pod annotations/labels to sidecar container
- Replace ASYA_ACTOR_HAPPY_END/ASYA_ACTOR_ERROR_END with ASYA_ACTOR_SINK=_sink
- Keep backward compatibility during migration

Future: EnvironmentConfig flavors for reusable resiliency profiles.

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md (Resiliency Configuration section)


---
**Close reason**: Closed


---
_Migrated from beads `asya-ii5y`_
