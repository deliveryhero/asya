---
title: "Phase 1.1: Install Crossplane and providers in Kind cluster"
status: done
priority: 1 # high
type: task
---



Set up Crossplane infrastructure in the Kind test cluster for development and testing.

## Tasks

1. Add Crossplane Helm chart to testing/e2e/manifests or Helm deployment
2. Install Crossplane controller in asya-system namespace
3. Install provider-aws (Upbound official provider)
4. Install provider-kubernetes
5. Configure ProviderConfig for AWS (using LocalStack for testing)
6. Configure ProviderConfig for Kubernetes (in-cluster)
7. Verify providers are healthy with `kubectl get providers`

## Acceptance Criteria

- Crossplane controller running in Kind cluster
- Both providers installed and showing Ready status
- ProviderConfigs created for AWS (LocalStack) and Kubernetes
- Can create a test SQS queue via Crossplane and see it in LocalStack

## Technical Notes

- Use LocalStack for AWS resources in E2E tests (already configured)
- provider-aws should use static credentials pointing to LocalStack endpoint
- provider-kubernetes should use in-cluster config

## Reference

See docs/rfc/rfc-crossplane.md Section 9 (Phase 1)


---
**Close reason**: Phase 1 Foundation complete: Crossplane v2.1 installed with providers, XRD created, SQS Composition working with LocalStack


---
_Migrated from beads `asya-sd1`_
