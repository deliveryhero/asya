# Asya🎭 Crew Helm Chart

This Helm chart deploys system AsyncActors with reserved roles (happy-end, error-end) for the Asya framework.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- Asya Operator installed and running
- AsyncActor CRDs installed

## Version Compatibility

The crew chart validates version constraints when `operatorVersion` is set:

- **Crew version MUST match operator version** - Crew actors use the same runtime/sidecar as the operator

Set `operatorVersion` in values.yaml to enable validation:

```yaml
operatorVersion: "1.0.0"  # Must match deployed operator version
```

## Installing the Chart

```bash
helm install asya-crew deploy/helm-charts/asya-crew \
  --namespace asya \
  --set happy-end.transport=rabbitmq \
  --set error-end.transport=rabbitmq
```

## Configuration

### System Actors

- **happy-end**: Persists successful results to S3 and reports to gateway
- **error-end**: Handles retries with exponential backoff and DLQ

### Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `operatorVersion` | Operator version for validation (optional) | `""` |
| `happy-end.enabled` | Enable happy-end actor | `true` |
| `happy-end.transport` | Transport type (rabbitmq/sqs) | `""` (required) |
| `error-end.enabled` | Enable error-end actor | `true` |
| `error-end.transport` | Transport type (rabbitmq/sqs) | `""` (required) |

See `values.yaml` for complete configuration options.
