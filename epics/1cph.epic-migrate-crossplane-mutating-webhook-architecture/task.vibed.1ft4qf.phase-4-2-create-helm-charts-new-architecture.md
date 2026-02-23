---
title: "Phase 4.2: Create Helm charts for new architecture"
priority: 2 # medium
type: task
dependencies:
  - 1cph/1fm4wm
---





Create Helm charts for deploying the Crossplane-based Asya system.

## Tasks

1. Create deploy/helm-charts/asya-crossplane/:
   - Crossplane XRD definitions
   - Compositions (SQS initially)
   - ProviderConfigs (templates)
2. Create deploy/helm-charts/asya-injector/:
   - Webhook Deployment
   - Service
   - MutatingWebhookConfiguration
   - RBAC resources
   - cert-manager Certificate
3. Update deploy/helm-charts/asya-crew/ if needed
4. Update deploy/helm-charts/asya-gateway/ if needed
5. Create umbrella chart or deployment guide

## Acceptance Criteria

- `helm install asya-crossplane` deploys XRDs and Compositions
- `helm install asya-injector` deploys webhook
- All resources have proper labels and annotations
- Values.yaml allows customization

## Technical Notes

- Follow existing Helm chart patterns in repo
- Use consistent naming with asya.sh/ labels
- Document required values (AWS account, region, etc.)

## Reference

See docs/rfc/rfc-crossplane.md Section 9 (Phase 4)


---
**Close reason**: Both asya-crossplane and asya-injector Helm charts fully implemented with templates, values, labels, customization, and README docs


---
_Migrated from beads `asya-bs4`_
