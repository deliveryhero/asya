---
title: "Phase 2.5: Deploy webhook with cert-manager"
status: merged
priority: 1
dependencies:
  - 1fmq
---

Set up TLS certificates and deploy the webhook to Kubernetes.

## Tasks

1. Create cert-manager Certificate resource for webhook
2. Create MutatingWebhookConfiguration with caBundle injection
3. Create Deployment for asya-injector
4. Create Service for webhook endpoint
5. Create RBAC (ServiceAccount, ClusterRole, ClusterRoleBinding)
6. Create Helm chart (deploy/helm-charts/asya-injector/)
7. Test webhook deployment in Kind cluster
8. Verify TLS handshake works

## Acceptance Criteria

- Webhook deployed and running in asya-system namespace
- cert-manager provides valid TLS certificate
- MutatingWebhookConfiguration has correct caBundle
- Pod creation triggers webhook (visible in logs)

## Technical Notes

- Use cert-manager's CA injector for caBundle
- Webhook should fail-open initially (failurePolicy: Ignore) for safety
- Switch to fail-closed after testing
- Webhook listens on port 9443 (Kubernetes convention)

## Reference

See docs/rfc/rfc-crossplane.md Section 9 (Phase 2)


---
**Close reason**: Closed


---
_Migrated from beads `asya-4rb`_
