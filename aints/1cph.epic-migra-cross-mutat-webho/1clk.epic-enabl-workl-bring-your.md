---
title: "(EPIC) Enable workloadRef: Bring Your Own Deployment"
status: open
priority: 3 # low
type: task
tags:
  - type:feature
---


## Overview

Enable users to reference an existing Deployment/StatefulSet instead of having Asya create one. The user provides their own workload (via workloadRef in AsyncActor spec), and Asya's injector handles sidecar injection and runtime configuration at pod admission time.

This is the "bring your own workload" model — essential for teams with existing ML inference services, custom Helm charts, or complex pod templates that don't fit the current AsyncActor template model.

## Design Principles

1. **Minimal invasion** — Asya should modify the user's workload as little as possible
2. **Fail clearly** — Ambiguous configurations should be rejected with actionable error messages
3. **Convention over configuration** — Sensible defaults, explicit overrides only when needed
4. **Annotations for metadata** — Use pod annotations (not labels) for Asya-specific configuration that the injector reads

## Edge Cases & Design Decisions

### 1. Runtime Container Command (DECIDED)

**Rule**: Command is ALWAYS set by the injector to `[pythonExec, /opt/asya/asya_runtime.py]`.
Any user-defined `command` on the runtime container is overwritten. This is intentional — the runtime script must be the entrypoint.

Python executable resolution: `ASYA_PYTHONEXECUTABLE` env var → `python3` (PATH). See asya-8y5.

### 2. Runtime Container Detection (TRACKED: asya-9u8)

**Rule**: Auto-detect which container is the runtime:
1. Filter out `asya-sidecar`
2. Single remaining container → runtime
3. Multiple → pick the one with `ASYA_HANDLER` env var
4. Ambiguous → reject

### 3. Metadata Delivery for workloadRef

**Problem**: Currently, handler/handlerMode come from the AsyncActor spec (`spec.workload.handler`, `spec.workload.handlerMode`). For workloadRef, there's no workload template in the spec.

**Proposed solution — annotations on the pod template**:
- `asya.sh/handler` → injected as `ASYA_HANDLER` env var (if not already set)
- `asya.sh/handler-mode` → injected as `ASYA_HANDLER_MODE` env var (if not already set)

**Why annotations, not labels**:
- Labels: 63 char limit, restricted charset `[a-zA-Z0-9._-]`
- Annotations: no restrictions, semantically correct for configuration metadata
- Handler paths like `my_module.MyClass.process` fit annotations but are fine for labels too — however, the principle of using the right primitive matters

**Priority chain**: Pod env var > Pod annotation > AsyncActor spec field > default.

**Fields that stay in AsyncActor spec** (not moved to annotations):
- `spec.transport` — operator/Crossplane needs this for queue provisioning
- `spec.scaling.*` — KEDA ScaledObject configuration
- `spec.timeout.*` — sidecar/pod-level config
- `spec.sidecar.*` — sidecar image/resources
- `spec.region` — transport config

### 4. Volume Conflicts

**Problem**: Injector adds volumes named `socket-dir`, `tmp`, `asya-runtime`. What if user's workload already has volumes with these names?

**Current behavior**: `appendVolumeIfNotExists` skips if name already exists. This means user-defined volumes with conflicting names would NOT be replaced — but the injector expects specific volume sources (EmptyDir, ConfigMap).

**Decision needed**: Should the injector:
- (a) Warn and skip (current behavior) — risks runtime failure if volume source is wrong
- (b) Override user volumes with same names — risks breaking user's setup
- (c) Use unique prefixed names like `asya-socket-dir` — avoids conflicts entirely

**Recommendation**: (c) — use `asya-` prefixed volume names to avoid collisions.

### 5. Probe Handling (CURRENT: safe)

**Current behavior**: Injector adds probes only if not already set (`if runtime.StartupProbe == nil`). This is safe — user-defined probes are preserved. No change needed.

### 6. Ownership & Lifecycle

**Problem**: For workloadRef, who owns the Deployment?

**Rules**:
- Asya does NOT own the referenced workload — no owner references
- Deleting the AsyncActor should NOT delete the user's Deployment
- Asya should only manage the sidecar injection (via mutating webhook) and the ScaledObject (if scaling enabled)
- Queue lifecycle: Crossplane creates/deletes queues based on AsyncActor — this works regardless of workloadRef

### 7. KEDA Scaling with workloadRef

**Problem**: KEDA ScaledObject targets a specific Deployment by name. For workloadRef, it must target the user's Deployment.

**Solution**: ScaledObject's `scaleTargetRef` must use the workloadRef name/kind instead of the generated one. The Crossplane composition or injector needs to pass this through.

### 8. Queue URL Delivery

**Problem**: The sidecar needs `ASYA_QUEUE_URL`. Currently this comes from `status.queueUrl` on the AsyncActor, read by the injector via `extractActorConfig()`.

**For workloadRef**: Same mechanism works — the injector reads the AsyncActor CR to get the queue URL. No change needed as long as Crossplane populates `status.queueUrl`.

### 9. Transport Credentials

**Problem**: Sidecar needs transport credentials (AWS keys for SQS, RabbitMQ password).

**Current mechanism**: Injector reads `AWSCredsSecret` from its own config and injects `envFrom` with the secret reference. This is injector-level config, not per-actor.

**For workloadRef**: Same mechanism works — credentials come from injector config, not from the AsyncActor spec.

### 10. Existing Container Env Vars

**Rule**: The injector should NEVER overwrite user-defined env vars. Current `appendEnvIfNotExists` behavior is correct — injector-added vars like `ASYA_SOCKET_DIR` are skipped if the user already defined them.

For annotation-based injection (asya.sh/handler → ASYA_HANDLER), same rule: skip if env var already exists on the container.

## Sub-tasks (to be created as individual beads)

1. asya-9u8 (exists): Auto-detect runtime container
2. Annotation-based metadata injection (asya.sh/handler, asya.sh/handler-mode)
3. Volume name prefixing to avoid conflicts
4. workloadRef field in AsyncActor spec + Crossplane XRD
5. KEDA ScaledObject targeting for workloadRef
6. Ownership model (no owner refs for workloadRef)
7. Documentation: workloadRef user guide for Data Scientists


---
_Migrated from beads `asya-f9dd`_
