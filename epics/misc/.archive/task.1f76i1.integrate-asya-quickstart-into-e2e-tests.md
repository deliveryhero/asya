---
title: Integrate asya-quickstart into E2E tests
status: wont_do
reason: overkill
priority: 2 # medium
type: task
---




---
## Notes

Replace individual chart deployments with asya-quickstart in E2E tests.

Implementation tasks:
1. Update testing/e2e/charts/helmfile.yaml.gotmpl:
   - Replace individual releases (operator, gateway, crew, localstack, etc.) 
     with single asya-quickstart release
   - Configure asya-quickstart with profile-specific values
   - Update needs/dependencies to reference asya-quickstart

2. Update profile values (testing/e2e/profiles/*.yaml):
   - Move operator/crew/gateway values under asya.quickstart structure
   - Configure sample infrastructure enable/disable flags

3. Add kube-prometheus-stack for monitoring:
   - Add prometheus-community Helm repo
   - Install kube-prometheus-stack in monitoring namespace
   - Document Grafana access for E2E test debugging

4. Remove deprecated infrastructure charts:
   - Delete testing/e2e/charts/{postgres,rabbitmq,minio,sqs,s3}
   - Keep only asya-test-actors and asya-test-flows

5. Verify E2E tests:
   - Test SQS-S3 profile
   - Test RabbitMQ-MinIO profile
   - Ensure all pytest tests pass

Dependencies:
- Requires PR #122 (asya-quickstart chart) to be merged
- Requires Phase 2 CI workflow updates to be merged

Benefits:
- Simplified E2E test setup
- Consistent with production quickstart usage
- Better monitoring with kube-prometheus-stack
- Easier maintenance with fewer local charts


---
_Migrated from beads `asya-dag`_
