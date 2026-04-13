---
title: Teach XRD to propagate user labels from AsyncActor down to owned resources
status: merged
priority: 2
parent: 00000
tags:
  - worktree:.worktrees/misc/1o9t98.xrd-propagate-labels
  - branch:misc/1o9t98.xrd-propagate-labels
---

# XRD Label Propagation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Propagate user-defined labels from AsyncActor claims to all composed resources (Deployment, ScaledObject, TriggerAuthentication, ServiceAccount) and reject reserved label prefixes at the composition level.

**Architecture:** Extract user labels from `$xr.metadata.labels` (filtering only `crossplane.io/` system labels) in each `function-go-templating` step and merge them into every composed resource's metadata.labels. Add a validation step early in the pipeline that emits a Fatal Result when reserved prefixes (`app.kubernetes.io/`) are detected. Update the E2E test to remove xfail and adjust reserved-prefix assertions to match Crossplane condition patterns.

**Tech Stack:** Crossplane Compositions (function-go-templating), Helm templates, pytest (E2E)

---

## Task 1: Add label validation step to both compositions

**Files:**
- Modify: `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml`
- Modify: `deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml`

Add a `validate-labels` pipeline step as the first step (before overlays) that:
1. Iterates `$xr.metadata.labels`
2. Checks for `app.kubernetes.io/` prefix
3. Emits `meta.gotemplating.fn.crossplane.io/v1alpha1 Result` with `severity: Fatal` if found

```yaml
- step: validate-labels
  functionRef:
    name: function-go-templating
  input:
    apiVersion: gotemplating.fn.crossplane.io/v1beta1
    kind: GoTemplate
    source: Inline
    inline:
      template: |
        {{`{{- $xr := .observed.composite.resource -}}`}}
        {{`{{- $reserved := list -}}`}}
        {{`{{- range $k, $v := $xr.metadata.labels -}}`}}
          {{`{{- if hasPrefix "app.kubernetes.io/" $k -}}`}}
            {{`{{- $reserved = append $reserved $k -}}`}}
          {{`{{- end -}}`}}
        {{`{{- end -}}`}}
        {{`{{- if gt (len $reserved) 0 -}}`}}
        apiVersion: meta.gotemplating.fn.crossplane.io/v1alpha1
        kind: Result
        severity: Fatal
        message: "Labels with reserved prefix 'app.kubernetes.io/' are not allowed: {{`{{ join ", " $reserved }}`}}"
        {{`{{- end -}}`}}
```

## Task 2: Add user label propagation to SQS composition

**File:** `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml`

In each render step (render-sqs-queue, render-serviceaccount, render-triggerauthentication, render-scaledobject, render-deployment), add user label extraction after the existing variable declarations:

```
{{- $userLabels := dict -}}
{{- range $k, $v := $xr.metadata.labels -}}
  {{- if not (hasPrefix "crossplane.io/" $k) -}}
    {{- $_ := set $userLabels $k $v -}}
  {{- end -}}
{{- end -}}
```

Then add `{{- range $k, $v := $userLabels }}` / `{{ $k }}: "{{ $v }}"` / `{{- end }}` BEFORE the hardcoded operator labels in each resource's metadata.labels section. Operator labels appear last so they always win on conflicts.

Resources to update:
- **ServiceAccount** — also add missing operator labels (currently has none)
- **TriggerAuthentication** — add user labels before existing operator labels
- **ScaledObject** — add user labels before existing operator labels
- **Deployment** metadata labels — add user labels before existing operator labels
- **Deployment** pod template labels — add user labels before existing pod labels
- **SQS Queue** — add user labels as AWS tags (optional, not tested)

## Task 3: Add user label propagation to RabbitMQ composition

**File:** `deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml`

Same pattern as Task 2 for:
- **TriggerAuthentication**
- **ScaledObject**
- **Deployment** metadata and pod template labels

## Task 4: Update E2E test — remove xfail and adjust assertions

**File:** `testing/e2e/tests/test_crossplane_e2e.py`

1. Remove `@pytest.mark.xfail(reason="...")` decorator from `test_asyncactor_label_propagation`
2. Adjust reserved-prefix rejection assertions (lines 929-938):
   - Crossplane doesn't set custom `WorkloadReady` conditions; a Fatal Result surfaces as a `Synced=False` condition or similar
   - Change assertion to check for any condition with `status: "False"` that mentions "reserved prefix" in message

```python
# Replace WorkloadReady-specific check with generic condition check
error_condition = next(
    (c for c in conditions
     if c.get("status") == "False"
     and "reserved prefix" in c.get("message", "").lower()),
    None,
)
assert error_condition is not None, (
    "Should have a False condition mentioning reserved prefix"
)
```

## Task 5: Commit, lint, and create PR

- Run `make lint` to fix formatting
- Commit with message: `feat(crossplane): propagate user labels from AsyncActor to composed resources`
- Push and create PR

## Related

- Closes aint `misc/1m1vbr` (fix test assertions) — subsumed by this work
