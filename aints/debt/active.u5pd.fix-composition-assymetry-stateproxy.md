---
title: Simplify flavor function and fix stateProxy asymmetry
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/.worktrees/debt/u5pd.fix-composition-assymetry-stateproxy
  - branch:debt/u5pd.fix-composition-assymetry-stateproxy
---


## Problem

The flavor pipeline (`function-asya-flavors`) has two architectural issues:

1. **Hardcoded field list**: `extractActorInlineSpec` only handles `scaling` and
   `workload`. Any other field (like `stateProxy`) is silently ignored. Adding a
   new flavor-mergeable field requires changing Go code.

2. **Context indirection**: The function writes to `asya/resolved-spec` context
   key. Every downstream Go template step must dual-read from context + XR spec
   with ~15 lines of boilerplate per step. The injector (which runs at Pod
   admission time) has no access to composition context at all, so `stateProxy`
   defined in a flavor is never injected.

3. **Over-engineered merge**: `merge.go` uses `strategicpatch` with full
   `corev1.PodSpec` struct tags (~95 lines) for Kubernetes-aware list merge.
   In practice, the only list that needs merge-by-key is `env` vars on
   containers. All other flavor fields are scalars, dicts, or whole arrays
   that replace (not merge).

## Root cause

The function was designed for arbitrary Kubernetes strategic merge, but the
actual use case is much simpler: deep merge dicts, replace arrays, with one
special case for env var lists.

## Chosen approach

**Simplify `function-asya-flavors` and write resolved spec back onto the XR.**

### Architecture

1. Fetch EnvironmentConfigs via Requirements API (unchanged)
2. Deep merge all fields with simple JSON merge (dicts recurse, scalars replace,
   arrays replace by default)
3. **One special case**: `workload.template.spec.containers[].env` and
   `sidecar.env` — merge by `name` key instead of replacing (~30 lines)
4. Apply actor inline spec as final override on **all** fields (no hardcoded
   list — iterate all spec keys except `actor`, `transport`, `flavors`)
5. Write resolved spec back onto XR via `SetDesiredCompositeResource`
   (not to `asya/resolved-spec` context key)

### What this fixes

- **stateProxy gap**: The injector reads `stateProxy` from XR spec. If a flavor
  sets it, the function writes it back to XR spec. Injector works unchanged.
- **Any future field**: No hardcoded field list. A flavor that sets `resiliency`,
  `sidecar`, `secretRefs`, or any other spec field works automatically.
- **Template boilerplate**: Downstream Go templates read from `$xr.spec.*`
  directly. Remove all `$resolvedSpec` dual-read logic from all 3 composition
  templates.

### What gets removed

- `merge.go` — replace `strategicpatch` + `ActorSpecSchema` + `corev1.PodSpec`
  with a simple ~30-line env-var-merge function
- `asya/resolved-spec` context key — no longer needed
- `extractActorInlineSpec` hardcoded field list — replaced with dynamic iteration
- All `$resolvedSpec` boilerplate in composition Go templates (~15 lines x N steps
  x 3 compositions)

### EnvironmentConfig syntax

Flavor EnvironmentConfigs use **standard K8s syntax**, identical to the XRD spec:

```yaml
data:
  stateProxy:
    - name: checkpoints
      mount: { path: /state/checkpoints }
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
        env:
          - name: STATE_BUCKET
            value: my-bucket
  scaling:
    minReplicas: 1
    maxReplicas: 5
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: OPENAI_API_KEY
            valueFrom:
              secretKeyRef: { name: openai-creds, key: api-key }
```

Env vars merge by `name` key across flavors (last wins for same name, different
names accumulate). All other fields use replace semantics.

### Limitations (accepted)

- Flavors are cluster-scoped only (EnvironmentConfigs are cluster-scoped).
  Namespace-scoped flavors via ConfigMaps tracked in [jgwn].
- Env var merge only applies to `workload.template.spec.containers[].env` and
  `sidecar.env`. Other list fields (e.g., `stateProxy` array) use replace
  semantics — a flavor owns the entire `stateProxy` config.

## Affected files

- `src/function-asya-flavors/fn.go` — rewrite merge + write-back logic
- `src/function-asya-flavors/merge.go` — replace with simple env-merge function
- `src/function-asya-flavors/fn_test.go` — update tests
- `src/function-asya-flavors/merge_test.go` — update tests
- `deploy/helm-charts/asya-crossplane/templates/composition-{sqs,rabbitmq,pubsub}.yaml`
  — remove `$resolvedSpec` dual-read boilerplate
- `deploy/helm-charts/asya-crew/templates/persistence-flavor.yaml` — already correct
- `deploy/helm-charts/asya-crew/templates/_helpers.tpl` — remove bypass comment
