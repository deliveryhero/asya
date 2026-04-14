---
title: Add helm template validation to pre-commit hooks
status: open
priority: 3
---

Add 'helm template test' for all Helm charts as part of pre-commit hooks to catch template rendering errors early.

## Scope
- deploy/helm-charts/asya-crossplane
- deploy/helm-charts/asya-operator
- deploy/helm-charts/asya-gateway
- deploy/helm-charts/asya-crew
- deploy/helm-charts/asya-actor

## Acceptance Criteria
- Pre-commit hook runs helm template on all charts
- Fails fast if any chart has rendering errors
- Works with both default and LocalStack values files


_Migrated from beads `asya-dqe`_
