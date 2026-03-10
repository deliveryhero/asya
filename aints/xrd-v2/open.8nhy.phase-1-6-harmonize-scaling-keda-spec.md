---
title: "Phase 1.6: Harmonize AsyncActor scaling spec with KEDA ScaledObject"
priority: 2 # medium
dependencies:
  - af25
---

## Goal

Fully align `AsyncActor.spec.scaling` field names and structure with the KEDA
ScaledObject spec (keda.sh/docs/2.19/reference/scaledobject-spec/).
Breaking changes — no backward compatibility.

## Changes

### XRD (`xrd-asyncactor.yaml`)

Rename fields to match KEDA exactly:
- `scaling.minReplicas` → `scaling.minReplicaCount`
- `scaling.maxReplicas` → `scaling.maxReplicaCount`

Add new optional field:
- `scaling.additionalTriggers` — array of raw KEDA trigger objects appended
  after the auto-generated primary queue trigger (one per transport). Named
  `additionalTriggers` (not `triggers`) because the composition always owns the
  primary queue trigger; users only supply extras.

Keep as-is (already match KEDA or are Asya-specific shortcuts):
- `scaling.pollingInterval` — matches KEDA
- `scaling.cooldownPeriod` — matches KEDA
- `scaling.queueLength` — shortcut for the primary queue trigger threshold
- `scaling.enabled` — Asya-specific guard
- `scaling.advanced` — maps to KEDA `advanced` block

### Compositions (sqs, rabbitmq, pubsub — all three)

- Update Go template variable reads:
  `$scaling.minReplicas` → `$scaling.minReplicaCount`
  `$scaling.maxReplicas` → `$scaling.maxReplicaCount`
- After the primary queue trigger block, append `additionalTriggers` verbatim:
  ```
  {{`{{- range $scaling.additionalTriggers | default list }}`}}
  - {{`{{ . | toYaml | nindent 6 }}`}}
  {{`{{- end }}`}}
  ```

### Files to touch

- `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml`
- `examples/asyas/` — update any manifests using `minReplicas`/`maxReplicas`
- E2E test assertions on ScaledObject fields or AsyncActor spec validation

## Resulting user-facing syntax

```yaml
spec:
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 20
    pollingInterval: 30
    cooldownPeriod: 300
    queueLength: 5
    additionalTriggers:
      - type: cpu
        metricType: Utilization
        metadata:
          type: Utilization
          value: "80"
```
