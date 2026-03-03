---
title: Add transport credential Secret to Crossplane Composition
priority: 2 # medium
dependencies:
  - 1cph/1fm4wm
---





Add a composed Secret resource to the SQS Composition that creates transport credentials in the actor's namespace.

## Context

Currently the operator creates `{actor-name}-transport-creds` Secret in the actor namespace by copying credentials from the central secret in `asya-system`. With Crossplane replacing the operator, the Composition must handle this.

## Tasks

1. Add a `kubernetes.crossplane.io/v1alpha2/Object` resource to `composition-sqs.yaml` that creates a Secret
2. Secret should be named `{actor-name}-transport-creds` in the actor's namespace
3. Secret should contain `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
4. Credentials source: reference a central secret (e.g., via ProviderConfig or Helm values)
5. Add owner reference or Crossplane management so cleanup happens on AsyncActor deletion

## Acceptance Criteria

- SQS Composition creates credential Secret alongside queue, deployment, etc.
- Secret is accessible by sidecar pods in the actor namespace
- Secret is cleaned up when AsyncActor XR is deleted
- Manual testing confirms sidecar can authenticate to SQS using the created secret

## Technical Notes

- See operator's `reconcileTransportCredentials()` in `asya_controller.go:675-803` for current logic
- Consider using Crossplane's `kubernetes` provider to create the Secret (same pattern as ServiceAccount, TriggerAuth)
- Credential keys must match what the injector will reference: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

## Reference

Operator source: src/asya-operator/internal/controller/asya_controller.go
Composition: deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml


---
**Close reason**: Per-actor secrets not needed in Crossplane model. Shared aws-creds secret referenced via injector config.awsCredsSecret. Validated end-to-end in Kind cluster.


---
_Migrated from beads `asya-kp6`_
