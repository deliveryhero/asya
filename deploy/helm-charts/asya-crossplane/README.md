# Asya Crossplane Helm Chart

This Helm chart deploys Crossplane XRDs and Compositions for managing AsyncActor resources declaratively using Crossplane.

## Overview

The asya-crossplane chart provides an alternative deployment model using Crossplane instead of the native asya-operator. It:

- Defines XRD (CompositeResourceDefinition) for AsyncActor resources
- Creates Compositions that provision AWS SQS queues and Kubernetes Deployments
- Supports KEDA autoscaling integration
- Provides CEL validation for common misconfigurations

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- Crossplane installed with:
  - AWS Provider (for SQS)
  - Kubernetes Provider (for Deployments)
  - Function Go-Templating

## Installation

### Basic Installation

```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane \
  --namespace crossplane-system
```

### Installation with LocalStack

```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane \
  --namespace crossplane-system \
  -f deploy/helm-charts/asya-crossplane/values-localstack.yaml
```

## Configuration

### Provider Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `providers.aws.sqsVersion` | AWS SQS provider version | `v1.19.0` |
| `providers.kubernetes.version` | Kubernetes provider version | `v0.17.0` |

### AWS ProviderConfig

| Parameter | Description | Default |
|-----------|-------------|---------|
| `awsProviderConfig.name` | ProviderConfig name | `default` |
| `awsProviderConfig.credentialsSource` | Credentials source | `Secret` |
| `awsProviderConfig.secretRef.namespace` | Secret namespace | `crossplane-system` |
| `awsProviderConfig.secretRef.name` | Secret name | `aws-creds` |
| `awsProviderConfig.endpoint.enabled` | Enable custom endpoint | `false` |
| `awsProviderConfig.endpoint.url` | Custom endpoint URL | `""` |

### Kubernetes ProviderConfig

| Parameter | Description | Default |
|-----------|-------------|---------|
| `kubernetesProviderConfig.name` | ProviderConfig name | `in-cluster` |
| `kubernetesProviderConfig.credentialsSource` | Credentials source | `InjectedIdentity` |

## AsyncActor Workload Requirements

When creating AsyncActor claims, the workload specification must follow these rules:

### Required Container Name

The workload must contain exactly one container named `asya-runtime`:

```yaml
spec:
  workload:
    template:
      spec:
        containers:
          - name: asya-runtime  # Required name
            image: my-handler:latest
            env:
              - name: ASYA_HANDLER
                value: my_module.process
```

### Forbidden: Custom Command

The `asya-runtime` container must NOT define a `command` field. The command is injected by the operator/Crossplane composition:

```yaml
# INVALID - will be rejected by CEL validation
containers:
  - name: asya-runtime
    image: my-handler:latest
    command: ["/bin/sh", "-c", "custom script"]  # NOT ALLOWED
```

### Validation Errors

If you violate these rules, you'll see clear error messages at admission time:

| Error | Cause | Fix |
|-------|-------|-----|
| `workload must have template.spec.containers` | Missing container spec | Add `template.spec.containers` |
| `workload must have exactly one container named 'asya-runtime'` | Wrong container name | Rename container to `asya-runtime` |
| `asya-runtime container must not define 'command'` | Custom command defined | Remove `command` field |

## Example AsyncActor Claim

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
  namespace: asya
spec:
  transport: sqs
  region: us-east-1

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5

  workload:
    kind: Deployment
    template:
      spec:
        containers:
          - name: asya-runtime
            image: my-processor:v1
            env:
              - name: ASYA_HANDLER
                value: processor.TextProcessor.process
            resources:
              requests:
                cpu: 100m
                memory: 256Mi
              limits:
                cpu: 500m
                memory: 512Mi
```

## CEL Validation

The XRD includes CEL (Common Expression Language) validations that run at Kubernetes admission time:

1. **Container Structure**: `workload.template.spec.containers` must exist
2. **Container Name**: Exactly one container must be named `asya-runtime`
3. **No Custom Command**: The `asya-runtime` container cannot define `command`

These validations provide immediate feedback when creating invalid AsyncActor claims.

## Architecture

```
AsyncActor Claim (asya.sh/v1alpha1)
         │
         ▼
    XAsyncActor (XRD)
         │
         ▼
    Composition
         │
    ┌────┼────────────┐
    ▼    ▼            ▼
  SQS  ScaledObject  Deployment
 Queue  (KEDA)
 (AWS)
```

## Comparison with asya-operator

| Feature | asya-operator | asya-crossplane |
|---------|---------------|-----------------|
| Queue Management | Operator creates queues | Crossplane AWS Provider |
| Deployment | Operator creates Deployment | Crossplane K8s Provider |
| Sidecar Injection | Automatic | Via Composition |
| CEL Validation | In operator code | In XRD schema |
| GitOps | CRD-based | Crossplane claims |

## Uninstalling

```bash
helm uninstall asya-crossplane -n crossplane-system

# This will also delete any AsyncActor claims and their managed resources
```

## License

See main project license.
