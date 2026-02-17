---
title: Auto-detect runtime container instead of requiring asya-runtime name
status: open
priority: 2 # medium
type: task
dependencies:
  - 1cph/1cto
---

## Problem

The injector currently requires the runtime container to be named exactly `asya-runtime`. This is too strict — users must rename their containers to match Asya's convention, which is invasive for workloadRef use cases where the user brings their own Deployment.

## Proposed Detection Logic (in injector)

When looking for the runtime container in a pod:

1. Filter out `asya-sidecar` from the container list
2. If exactly 1 remaining container → treat it as the runtime
3. If multiple remaining → pick the one with `ASYA_HANDLER` env var defined
4. If 0 or 2+ containers match → reject the pod with a clear error message

This replaces the current hard-coded name check at inject.go:160-168.

## workloadRef Controls via Annotations

For workloadRef, allow specifying Asya controls (handler, handler-mode, etc.) via pod template annotations instead of requiring env vars:

- `asya.sh/handler` → injected as ASYA_HANDLER env var
- `asya.sh/handler-mode` → injected as ASYA_HANDLER_MODE env var

Use annotations (not labels) because:
- Labels are limited to 63 chars and restricted charset
- Handler paths can contain dots, underscores, etc.
- Annotations have no length/charset restrictions
- Semantically, this is configuration metadata (annotation), not selection criteria (label)

For explicit opt-in when auto-detection is ambiguous, a label `asya.sh/runtime: "true"` on the container could be supported — but containers don't have labels in k8s, so this would need to be an env var marker or annotation referencing the container name.

## Validation Location

Detection and validation should happen in the **injector** (mutating webhook), not Crossplane XRD:
- The injector sees the actual pod spec at admission time
- For workloadRef, the pod template is in the referenced resource, not the AsyncActor CRD
- The XRD can only validate AsyncActor spec fields, not external workload contents

## Backward Compatibility

A container named `asya-runtime` would still work (case 2: single container after filtering sidecar, or case 3: only one with ASYA_HANDLER). No breaking change.


---
_Migrated from beads `asya-9u8`_
