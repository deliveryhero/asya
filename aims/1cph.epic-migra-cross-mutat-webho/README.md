---
title: "Epic: Migrate to Crossplane + Mutating Webhook Architecture"
status: open
priority: 1 # high
type: epic
---

Replace the custom ~16K LOC asya-operator with a Crossplane-based declarative control plane and a lightweight mutating webhook for sidecar injection.

## Motivation

- **Maintenance burden**: Current operator requires ~400 LOC per transport, complex reconciliation logic
- **Instability**: Custom reconciliation loops prone to edge cases and race conditions
- **Drift ignorance**: Manual changes to cloud resources not automatically corrected

## Solution

1. **Crossplane Compositions**: Declarative infrastructure management (SQS queues, KEDA ScaledObjects, Deployments)
2. **Mutating Webhook (asya-injector)**: Lightweight Go webhook for sidecar injection at pod creation

## Scope

- AWS SQS transport (priority 1)
- Both workload (template) and workloadRef support
- KEDA autoscaling with scale-to-zero
- Pod health status via labels

## Out of Scope (future work)

- Other transports (RabbitMQ, Pub/Sub, Kafka, Azure Service Bus, NATS)
- Actor warm-up before scale-to-zero (see thoughts-actor-warm-up.md)
- Composition Functions for replica count status

## Reference

See docs/rfc/rfc-crossplane.md for complete design.


---
_Migrated from beads `asya-vab`_
