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

## AsyncActor Spec

The AsyncActor XRD uses a flat spec — all fields live directly under `spec` with no nesting.
The Crossplane composition renders the full pod spec (runtime container + sidecar) from these fields.

### Minimal actor (3 required fields)

```yaml
spec:
  image: my-handler:latest
  handler: my_module.process
  transport: sqs
```

### Full spec

```yaml
spec:
  image: my-handler:latest
  imagePullPolicy: IfNotPresent
  handler: my_module.process
  transport: sqs
  actor: text-processor          # queue naming; defaults to metadata.name

  env:
  - name: MODEL_PATH
    value: /models/default

  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi

  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: 10
    queueLength: 5

  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule

  nodeSelector:
    gpu-type: a100

  flavors: [gpu-a100]
```

### XRD Schema Validation

The XRD validates fields at Kubernetes admission time using OpenAPI constraints:

| Error | Cause | Fix |
|-------|-------|-----|
| `transport in body should be one of [sqs rabbitmq pubsub]` | Invalid transport | Use one of the listed values |
| `handler in body should be at least 1 chars long` | Empty handler | Set a non-empty handler dotted path |
| `imagePullPolicy in body should be one of [Always IfNotPresent Never]` | Invalid pull policy | Use one of the listed values |

## Example AsyncActor Claim

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
  namespace: asya
spec:
  actor: text-processor
  transport: sqs

  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: 10
    queueLength: 5

  image: my-processor:v1
  handler: processor.TextProcessor.process
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

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
