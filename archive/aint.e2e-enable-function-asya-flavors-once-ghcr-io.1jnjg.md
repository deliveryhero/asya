---
title: "E2E: Enable function-asya-flavors once ghcr.io image is public"
status: merged
priority: 2
parent: 00001
---

## Context

Crossplane Functions use their own OCI puller, NOT containerd's image store.
`kind load docker-image` does NOT work for Function packages — only for regular
container images that kubelet pulls via `imagePullPolicy: Never`.

The `function-asya-flavors` image (`ghcr.io/deliveryhero/function-asya-flavors:0.5.1`)
has been pushed to ghcr.io but is currently private. Once admins make it publicly
accessible, the feature can be enabled in E2E.

## What was done in PR #197

All the code is ready. The feature is implemented but gated:

- `EnvironmentConfig` fixtures deployed by `testing/e2e/charts/asya-test-actors/templates/environment-configs.yaml`:
  - `asya-test-actor` — provides `scaling` (min/maxReplicas, queueLength) + `asya-runtime` resource limits/requests
  - `asya-test-env-vars` — provides `FLAVOR_EXTRA_VAR=from-flavor` for multi-flavor override test
- 9 of 13 E2E test actors migrated to `spec.flavors: [asya-test-actor]`
- `actor-unicode` uses `spec.flavors: [asya-test-actor, asya-test-env-vars]` (multi-flavor)
- `actor-empty`, `actor-error`, `actor-slow-boundary` left unflavored (backward compat)
- `test_asyncactor_flavors_resolved` written in `testing/e2e/tests/test_crossplane_e2e.py`

## Steps to enable (3 changes)

### 1. `testing/e2e/profiles/sqs-s3.yaml`

```yaml
crossplane:
  functions:
    flavorsEnabled: true  # was: false
```

Remove the comment block explaining why it's disabled.

### 2. `testing/e2e/profiles/rabbitmq-minio.yaml`

```yaml
crossplane:
  functions:
    flavorsEnabled: true  # was: false
```

Remove the comment block explaining why it's disabled.

### 3. `testing/e2e/tests/test_crossplane_e2e.py`

Remove the `@pytest.mark.xfail` decorator from `test_asyncactor_flavors_resolved`
(currently at ~line 1550):

```python
# Remove these 3 lines:
@pytest.mark.xfail(
    reason="function-asya-flavors disabled in E2E until image is published to ghcr.io (functions.flavorsEnabled=false)"
)
```

## What test_asyncactor_flavors_resolved verifies

Three scenarios in one test:

1. **Single flavor**: actor with `spec.flavors: [asya-test-actor]` → Deployment gets
   `resources.limits.cpu: 500m` and `resources.requests.memory: 128Mi` injected from the flavor

2. **Multi-flavor + env override**: actor with `spec.flavors: [asya-test-actor, asya-test-env-vars]`
   plus inline `FLAVOR_EXTRA_VAR=from-actor` → inline value wins over flavor value (`from-flavor`)

3. **No flavor (backward compat)**: actor without `spec.flavors` → still reconciles correctly

## Key architecture note

Two separate image loading mechanisms in Kind:

- **containerd image store**: used by kubelet for Pod containers — `kind load docker-image` works,
  `imagePullPolicy: Never` works
- **Crossplane OCI puller**: used for Function/Provider packages — `kind load` does NOT work,
  image must be pullable from an OCI registry (ghcr.io)

This is why `functions.flavorsEnabled` is a toggle in both the Helm chart
(`deploy/helm-charts/asya-crossplane/values.yaml`) and the composition template
(`templates/composition-sqs.yaml`, `templates/composition-rabbitmq.yaml`).
