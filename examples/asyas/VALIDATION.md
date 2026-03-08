# AsyncActor Examples Validation Report

**Date**: 2026-03-08
**Cluster**: `kind-asya-e2e-sqs-s3` (reused existing e2e cluster with SQS/LocalStack)
**Branch**: `examples/validation`

## Patches Applied to All Examples

All examples needed the following common changes to run on the SQS cluster:

| Change | Reason |
|--------|--------|
| `transport: rabbitmq` → `transport: sqs` | Only SQS configured in test cluster |
| Add `region: us-east-1` | Required for SQS transport |
| Add `providerConfigRef: localstack` | Required for SQS transport |
| `namespace: default/asya/production` → `asya-e2e` | Injector, secrets, and ConfigMaps are in `asya-e2e` |
| Remove `timeout:` blocks | Field does not exist in XRD (caused rejection before fix) |

## Results Per Example

### ✅ simple-actor.yaml

**Actor**: `hello-actor` | **Transport**: sqs

- XRD schema validation: passed
- Crossplane composition: Deployment + TriggerAuthentication created
- Sidecar injected: yes (`asya-runtime` + `asya-sidecar` containers present)
- Pod status: `CrashLoopBackOff` — expected, `echo_handler.process` module not in base `python:3.13-slim`
- **Verdict**: YAML correct. Pod crash is expected (placeholder handler; user must build own image).

---

### ✅ no-scaling-actor.yaml

**Actor**: `fixed-replicas-actor` | **Transport**: sqs | `scaling.enabled: false`

- XRD schema validation: passed
- Crossplane composition: Deployment created with `replicas: 3` (correct); no ScaledObject created (correct — `scaling.enabled: false`)
- Pod status: `CrashLoopBackOff` — expected, same reason as above
- **Verdict**: YAML correct. `scaling.enabled: false` with `replicas: 3` handled correctly by composition.

---

### ✅ fully-configured-actor.yaml

**Actor**: `fully-configured-actor` | **Transport**: sqs

- XRD schema validation: passed
- Crossplane composition: Deployment + TriggerAuthentication created
- Pod status: `ImagePullBackOff` — `my-custom-runtime:latest` is a placeholder image
- **Verdict**: YAML correct. Placeholder image name expected for a "full config" demo.

---

### ✅ custom-python-actor.yaml

**Actor**: `conda-ml-actor` | **Transport**: sqs | **Image**: `continuumio/miniconda3:latest`

- XRD schema validation: passed
- Crossplane composition: Deployment created
- Pod status: `CrashLoopBackOff` — image pulled successfully but `ml_model.predict` not found in it
- `ASYA_PYTHONEXECUTABLE` and `PYTHONPATH` env vars correctly propagated
- **Verdict**: YAML correct. Handler module doesn't exist in the stock conda image (expected for example).

---

### ✅ custom-sidecar-actor.yaml (1 fix applied)

**Actor**: `custom-sidecar-actor` | **Transport**: sqs

**Bug found**: `sidecar.image: ghcr.io/deliveryhero/asya-sidecar:v2.1.0` — tag does not exist in the registry.

**Fix**: Changed to `ghcr.io/deliveryhero/asya-sidecar:latest` with comment explaining to pin to an actual published tag.

- `timeout:` block removed (not in XRD)
- Sidecar override via `spec.sidecar.image` is correctly wired through the injector (webhook picked up the custom image from spec)
- Pod status: `ImagePullBackOff` on both the custom sidecar and `custom-runtime:latest`
- **Verdict**: YAML correct after fix. Sidecar image override mechanism works.

---

### ✅ multi-container-actor.yaml

**Actor**: `cached-actor` | **Transport**: sqs | Extra container: `redis:7-alpine`

- XRD schema validation: passed
- Crossplane composition: Deployment created
- Pod status: `ImagePullBackOff` on `my-app:latest`; `redis:7-alpine` started pulling
- Both `asya-sidecar` (injected) + `redis` containers counted alongside runtime
- **Verdict**: YAML correct. Multi-container pod template works; placeholder image expected.

---

### ✅ gpu-actor.yaml (1 fix applied)

**Actor**: `llm-actor` | **Transport**: sqs

**Bug found**: `timeout:` block present — not in XRD.
**Fix**: Removed `timeout:` block.

- XRD schema validation: passed after fix
- Crossplane composition: Deployment created with `nvidia.com/gpu: 1` resource request + `nodeSelector` + `tolerations`
- Pod status: `Pending` — no GPU node available in Kind (expected)
- **Verdict**: YAML correct after fix. GPU config is valid K8s; pods won't schedule in Kind (expected).

---

### ✅ advanced-scaling-actor.yaml

**Actor**: `advanced-scaling-actor` | **Transport**: sqs | `scaling.advanced` with formula

- XRD schema validation: passed — `scaling.advanced` fields (`formula`, `target`, `activationTarget`, `metricType`, `restoreToOriginalReplicaCount`) all accepted
- Crossplane composition: Deployment + TriggerAuthentication created
- ScaledObject: not yet created (blocked on SQS queue provisioning — see infrastructure note)
- Pod status: `CrashLoopBackOff` — `handlers.process` not in `python:3.13-slim`
- **Verdict**: YAML correct. `scaling.advanced` fields are properly supported by XRD.

---

### ✅ pipeline-preprocess.yaml

**Actor**: `preprocess` | **Transport**: sqs

- XRD schema validation: passed
- Pod status: `ImagePullBackOff` on `text-preprocessor:latest` (placeholder image)
- **Verdict**: YAML correct. Part of 3-stage pipeline demo.

---

### ✅ pipeline-inference.yaml (1 fix applied)

**Actor**: `inference` | **Transport**: sqs | GPU

**Bug found**: `timeout:` block present — not in XRD.
**Fix**: Removed `timeout:` block.

- XRD schema validation: passed after fix
- Pod status: `Pending` — no GPU (`nvidia.com/gpu`) in Kind cluster (expected)
- **Verdict**: YAML correct after fix. GPU pipeline stage correct.

---

### ⚠️ pipeline-postprocess.yaml

**Actor**: `postprocess` | **Transport**: sqs

- XRD schema validation: passed
- Pod status: `Pending` — `Insufficient cpu` (cluster resource pressure from running all 14 example actors simultaneously on a single-node Kind cluster)
- **Verdict**: YAML correct. Pending due to test environment resource constraints, not a YAML issue.

---

### ⚠️ multi-region-actor.yaml

**Actors**: `text-processor-eu` + `text-processor-us` | Both `spec.actor: text-processor`

- XRD schema validation: passed for both
- Both actors created successfully
- **Issue**: Both actors share `spec.actor: text-processor` in the same namespace → Crossplane creates only ONE `text-processor` Deployment (second actor's Crossplane Object reconciliation conflicts with the first)
- NodeSelector (`topology.kubernetes.io/region: eu-central-1/us-east-1`) prevents pod scheduling in Kind (expected — these nodes don't exist)
- **Root cause**: This example is designed for multi-cluster deployment (same `spec.actor` across different K8s clusters). When applied to the same cluster+namespace, resource names collide.
- **Verdict**: YAML is correct for its intended use case (separate clusters). Should add a comment warning that applying both to the same cluster/namespace causes resource conflicts.

---

### ✅ actor-with-persistence-overlay.yaml

**Actor**: `data-processor` | **Transport**: sqs | `overlays: [asya-persistence-s3]`

- XRD schema validation: passed
- Crossplane composition: Deployment created
- Sidecar injection: default `asya-sidecar:latest` used correctly (overlay doesn't override sidecar image)
- Pod status: `ImagePullBackOff` on `my-data-processor:latest` (placeholder)
- `overlays: [asya-persistence-s3]` field accepted by XRD (the EnvironmentConfig `asya-persistence-s3` was not present in this cluster, but this didn't block the actor from applying)
- **Verdict**: YAML correct. Overlay field is properly handled by XRD.

---

## Infrastructure Note

During testing, the LocalStack SQS pod (`asya-system/sqs-*`) was in `CrashLoopBackOff` (29 restarts). This blocked SQS queue creation for all test actors, which in turn blocked ScaledObject creation (ScaledObjects need the queue URL from the provisioned queue). This is a pre-existing cluster stability issue, not caused by the examples.

**Impact**: All test actors stayed in `STATUS=Creating` because SQS queue was not provisioned. Deployments, TriggerAuthentications, and Crossplane composition processing all worked correctly.

## Summary

| File | Schema OK | Composition OK | Issues Found | Fixed |
|------|-----------|----------------|--------------|-------|
| simple-actor.yaml | ✅ | ✅ | None | - |
| no-scaling-actor.yaml | ✅ | ✅ | None | - |
| fully-configured-actor.yaml | ✅ | ✅ | None | - |
| custom-python-actor.yaml | ✅ | ✅ | None | - |
| custom-sidecar-actor.yaml | ✅ | ✅ | Sidecar image tag `v2.1.0` not found; `timeout:` not in XRD | ✅ Both fixed |
| multi-container-actor.yaml | ✅ | ✅ | None | - |
| gpu-actor.yaml | ✅ | ✅ | `timeout:` not in XRD | ✅ Fixed |
| advanced-scaling-actor.yaml | ✅ | ✅ | None | - |
| pipeline-preprocess.yaml | ✅ | ✅ | None | - |
| pipeline-inference.yaml | ✅ | ✅ | `timeout:` not in XRD | ✅ Fixed |
| pipeline-postprocess.yaml | ✅ | ✅ | None | - |
| multi-region-actor.yaml | ✅ | ⚠️ | Same `spec.actor` in same namespace causes resource conflict (by design for multi-cluster) | Comment needed |
| actor-with-persistence-overlay.yaml | ✅ | ✅ | None | - |

## Bugs Fixed

1. **`timeout:` field** (3 files: `custom-sidecar-actor.yaml`, `gpu-actor.yaml`, `pipeline-inference.yaml`)
   - Field does not exist in XRD spec — would cause `Invalid value` rejection
   - Fixed by removing the `timeout:` blocks

2. **`custom-sidecar-actor.yaml`**: sidecar image tag `v2.1.0` not found in GHCR
   - Fixed by changing to `:latest` with a clarifying comment

## Remaining Recommendations

- `multi-region-actor.yaml`: Add a comment that both actors must be deployed to **different clusters** (not the same cluster+namespace) to avoid Deployment name conflicts
- `simple-actor.yaml` / `no-scaling-actor.yaml`: `echo_handler.process` comment could clarify users need to provide their own image
- LocalStack SQS CrashLoopBackOff in `asya-system` namespace needs investigation (unrelated to examples)
