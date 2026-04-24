---
description: "Helm charts config: gateway, crew, crossplane chart values, image tags, resource limits"
---

# Helm Charts

Asya🎭 provides Helm charts for deploying framework components.

## Available Charts

### asya-gateway

Deploys MCP HTTP gateway.

**Location**: `deploy/helm-charts/asya-gateway/`

**Installation**:
```bash
helm install asya-gateway deploy/helm-charts/asya-gateway/ -f values.yaml
```

**Key values**:
```yaml
config:
  sqsRegion: <your-aws-region>
  postgresHost: postgres.default.svc.cluster.local
  postgresDatabase: asya_gateway
  postgresUsername: postgres
  postgresPasswordSecretRef:
    name: postgres-secret
    key: password

routes:
  tools:
  - name: text-processor
    description: Process text
    parameters:
      text:
        type: string
        required: true
    route: [preprocess, infer, postprocess]

serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/gateway-role

service:
  type: LoadBalancer
  port: 80
```

### asya-crew

Deploys crew actors (`x-sink`, `x-sump`) as AsyncActor CRDs.

**Location**: `deploy/helm-charts/asya-crew/`

**Installation**:
```bash
helm install asya-crew deploy/helm-charts/asya-crew/ --namespace asya-e2e -f values.yaml
```

**Key values**:
```yaml
x-sink:
  enabled: true
  scaling:
    enabled: true
    minReplicaCount: 1
    maxReplicaCount: 10
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints

x-sump:
  enabled: true
  scaling:
    enabled: true
    minReplicaCount: 1
    maxReplicaCount: 10
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints
```

### asya-crossplane

Deploys Crossplane XRDs and Compositions for AsyncActor management.

**Location**: `deploy/helm-charts/asya-crossplane/`

**Installation**:
```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ -n crossplane-system
```

**Key values**:
```yaml
providers:
  aws:
    sqsVersion: "v1.19.0"
  kubernetes:
    version: "v0.17.0"

awsProviderConfig:
  name: default
  credentialsSource: Secret
  secretRef:
    namespace: crossplane-system
    name: aws-creds
    key: credentials

awsRegion: <your-aws-region>
actorNamespace: asya

# Pin sidecar to a specific release (tag defaults to Chart.AppVersion)
sidecar:
  image:
    repository: ghcr.io/deliveryhero/asya-sidecar
    tag: v0.5.12
```

**Minimal example**:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  actor: my-actor
  image: my-handler:latest
  handler: my_module.process
```

## Common Patterns

### AWS with SQS + S3

**Crossplane** (`crossplane-values.yaml`):
```yaml
awsRegion: <your-aws-region>
awsProviderConfig:
  name: default
  credentialsSource: Secret
  secretRef:
    namespace: crossplane-system
    name: aws-creds
    key: credentials
```

**Crew** (`crew-values.yaml`):
```yaml
x-sink:
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints

x-sump:
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints
```

**Actors**:
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
spec:
  actor: my-actor
  image: my-actor:v1
  handler: handler.process
```

### Local with RabbitMQ + MinIO

**Crossplane** (`crossplane-values.yaml`):
```yaml
awsRegion: <your-aws-region>
actorNamespace: asya
# Use LocalStack or RabbitMQ for local development
```

**Crew** (`crew-values.yaml`):
```yaml
x-sink:
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints

x-sump:
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints
```

**Actors**:
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
spec:
  actor: my-actor
  image: my-actor:v1
  handler: handler.process
```

## Upgrading Charts

```bash
# Upgrade crossplane
helm upgrade asya-crossplane deploy/helm-charts/asya-crossplane/ -n crossplane-system -f values.yaml

# Upgrade gateway
helm upgrade asya-gateway deploy/helm-charts/asya-gateway/ -f values.yaml

# Upgrade crew
helm upgrade asya-crew deploy/helm-charts/asya-crew/ -f values.yaml
```

## Uninstalling

```bash
# Uninstall components
helm uninstall asya-gateway
helm uninstall asya-crew
helm uninstall asya-crossplane -n crossplane-system

# Remove XRDs (will delete all AsyncActors)
kubectl delete xrd asyncactors.asya.sh
```
