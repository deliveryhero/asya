---
title: "Phase 4.4: Remove old asya-operator code"
status: merged
priority: 2
---

Delete the old asya-operator source code and Helm chart after all functionality has been migrated to Crossplane + asya-injector.

## Prerequisites (must be complete before starting)

- Transport credential Secret created by Crossplane Composition (asya-kp6)
- Credential env vars mounted by asya-injector (asya-k7n)
- Runtime ConfigMap provisioned without operator (asya-57z)
- E2E tests adapted and passing on Crossplane (asya-rl0)

## Tasks

1. Delete `src/asya-operator/` directory entirely:
   - Controller logic (reconciliation loop, status management)
   - Transport implementations (SQS, RabbitMQ queue management)
   - Runtime loader and ConfigMap creation
   - API types and CRD definitions
   - All unit tests
2. Delete `deploy/helm-charts/asya-operator/` Helm chart
3. Remove operator-related symlinks:
   - `src/asya-operator/internal/controller/runtime_symlink/asya_runtime.py`
   - `testing/integration/operator/testdata/runtime_symlink/asya_runtime.py`
4. Tag the commit before deletion for historical reference

## Acceptance Criteria

- `src/asya-operator/` directory completely removed
- `deploy/helm-charts/asya-operator/` completely removed
- Repository builds and tests pass without operator code
- Git tag marks the last commit with operator code

## Technical Notes

- This is a one-way door — ensure ALL migration is verified first
- The operator is ~16K LOC (Go) — significant code removal
- Keep git history intact for future reference
- Symlinks will break immediately — remove them in this step

## What's being deleted (not migrated)

- Reconciliation loop and controller logic → replaced by Crossplane
- CRD definitions → replaced by XRD
- Transport queue management (SQS/RabbitMQ create/delete) → replaced by Crossplane providers
- Finalizers and deletion handling → Crossplane handles resource lifecycle
- Label management → Composition + injector
- Pod health checking → native Kubernetes
- Periodic queue health checks → Crossplane drift detection
- Status determination logic → Crossplane status patching
- HPA/KEDA integration → Crossplane Composition
- Spec validation → XRD validation rules


_Migrated from beads `asya-pb5`_
