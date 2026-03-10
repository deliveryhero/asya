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
  sqsRegion: us-east-1
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
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicaCount: 1
    maxReplicaCount: 10
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-crew:latest
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints

x-sump:
  enabled: true
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicaCount: 1
    maxReplicaCount: 10
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-crew:latest
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints
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

awsRegion: us-east-1
actorNamespace: asya
```

**Workload Requirements**:

AsyncActor claims using Crossplane must follow these rules:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  actor: my-actor
  transport: sqs
  workload:
    kind: Deployment
    template:
      spec:
        containers:
          - name: asya-runtime  # Required: must be named 'asya-runtime'
            image: my-handler:latest
            # command: NOT ALLOWED (injected by composition)
            env:
              - name: ASYA_HANDLER
                value: my_module.process
```

**Validation Errors**:
- `workload must have exactly one container named 'asya-runtime'` - rename container
- `asya-runtime container must not define 'command'` - remove command field
- `workload is required` - specify workload with container spec

### asya-actor

Deploys user actors (batch deployment).

**Location**: `deploy/helm-charts/asya-actor/`

**Installation**:
```bash
helm install my-actors deploy/helm-charts/asya-actor/ -f values.yaml
```

**Key values**:
```yaml
actors:
  - name: text-processor
    transport: sqs
    scaling:
      minReplicaCount: 0
      maxReplicaCount: 50
      queueLength: 5
    image: my-processor:v1
    handler: processor.TextProcessor.process
    env:
      - name: MODEL_PATH
        value: /models/v2

  - name: image-processor
    transport: sqs
    scaling:
      minReplicaCount: 0
      maxReplicaCount: 20
    image: my-image:v1
    handler: image.process
    resources:
      requests:
        nvidia.com/gpu: 1

serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/actor-role
```

## Common Patterns

### AWS with SQS + S3

**Crossplane** (`crossplane-values.yaml`):
```yaml
awsRegion: us-east-1
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
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints

x-sump:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints
```

**Actors**:
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
spec:
  transport: sqs
```

### Local with RabbitMQ + MinIO

**Crossplane** (`crossplane-values.yaml`):
```yaml
awsRegion: us-east-1
actorNamespace: asya
# Use LocalStack or RabbitMQ for local development
```

**Crew** (`crew-values.yaml`):
```yaml
x-sink:
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints

x-sump:
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints
```

**Actors**:
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
spec:
  transport: rabbitmq
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
