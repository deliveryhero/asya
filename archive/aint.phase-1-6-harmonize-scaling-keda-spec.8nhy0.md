---
title: "Phase 1.6: Harmonize AsyncActor scaling spec with KEDA ScaledObject"
status: merged
priority: 2
assignee: Artem Yushkovskiy
dependencies:
  - af25i
tags:
  - worktree:.worktrees/xrd-v2/8nhy.phase-1-6-harmonize-scaling-keda-spec
  - branch:xrd-v2/8nhy.phase-1-6-harmonize-scaling-keda-spec
---

## Goal

Fully align `AsyncActor.spec.scaling` field names and structure with the KEDA
ScaledObject spec (keda.sh/docs/2.19/reference/scaledobject-spec/).
Breaking changes — no backward compatibility.

## Naming rationale: `scaling` not `autoscaling`

Keep the XRD field as `spec.scaling`. The `autoscaling.keda.sh/paused` annotation
uses `autoscaling` as an API group namespace prefix, not as a naming convention for
CRD fields. Kubernetes itself uses `scaling` idiomatically (`kubectl scale`, Argo
Rollouts, etc.). The HPA API group is `autoscaling/v1` but HPA is a different resource.
`spec.scaling` is clear, concise, and consistent with Kubernetes conventions.

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

**Core XRD + compositions** (schema + rendering):
- `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml` — rename fields, add `additionalTriggers`
- `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml`

**Examples** (update field names in all AsyncActor manifests):
- `examples/asyas/` — grep for `minReplicas`/`maxReplicas` and rename

**Helm chart values and READMEs**:
- `deploy/helm-charts/asya-crossplane/values.yaml` — if scaling defaults are documented there
- `deploy/helm-charts/asya-actor/` — any references to scaling field names in values/templates
- `deploy/helm-charts/asya-playground/` — same
- `deploy/helm-charts/*/README.md` — update field name docs

**E2E tests**:
- `testing/e2e/tests/test_crossplane_e2e.py` — assertions on ScaledObject `spec.minReplicaCount`/`maxReplicaCount`
- `testing/e2e/tests/` — grep for `minReplicas`/`maxReplicas` in any test that creates/inspects AsyncActors
- `testing/e2e/charts/` — any AsyncActor manifests used as test fixtures

**Documentation**:
- `docs/` — grep for `minReplicas`/`maxReplicas`; update all `.md` files that document scaling
- `docs/architecture/`, `docs/install/`, `docs/quickstart/` — update AsyncActor spec examples
- `CONTRIBUTING.md` — if it mentions scaling fields
- `README.md` — if it has a scaling example

**Sweep command** (run after implementation to catch stragglers):
```bash
grep -r "minReplicas\|maxReplicas" --include="*.yaml" --include="*.md" --include="*.py" \
  --exclude-dir=".git" --exclude-dir=".aint" .
```

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
