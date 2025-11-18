# Helm Charts

Asya🎭 provides Helm charts for deploying framework components.

## Available Charts

### asya-operator

Deploys Asya operator (CRD controller).

**Location**: `deploy/helm-charts/asya-operator/`

**Installation**:
```bash
kubectl apply -f src/asya-operator/config/crd/
helm install asya-operator deploy/helm-charts/asya-operator/ \
  -n asya-system --create-namespace \
  -f values.yaml
```

**Key values**:
```yaml
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
  rabbitmq:
    enabled: true
    type: rabbitmq
    config:
      host: rabbitmq.default.svc.cluster.local
      port: 5672
      username: guest
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

image:
  repository: asya-operator
  tag: latest

serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/operator-role
```

### asya-gateway

Deploys MCP HTTP gateway.

**Location**: `deploy/helm-charts/asya-gateway/`

**Installation**:
```bash
helm install asya-gateway deploy/helm-charts/asya-gateway/ \
  -f values.yaml
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

Deploys crew actors (`happy-end`, `error-end`).

**Location**: `deploy/helm-charts/asya-crew/`

**Installation**:
```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  -f values.yaml
```

**Key values**:
```yaml
storage: s3  # or minio
s3Bucket: asya-results
s3Region: us-east-1

# For MinIO
minioEndpoint: http://minio:9000
minioAccessKey: minioadmin
minioSecretKey: minioadmin
minioBucket: asya-results

gatewayUrl: http://asya-gateway:80

serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/actor-role
```

### asya-actor

Deploys user actors (batch deployment).

**Location**: `deploy/helm-charts/asya-actor/`

**Installation**:
```bash
helm install my-actors deploy/helm-charts/asya-actor/ \
  -f values.yaml
```

**Key values**:
```yaml
actors:
  - name: text-processor
    transport: sqs
    scaling:
      minReplicas: 0
      maxReplicas: 50
      queueLength: 5
    image: my-processor:v1
    handler: processor.TextProcessor.process
    env:
      - name: MODEL_PATH
        value: /models/v2

  - name: image-processor
    transport: sqs
    scaling:
      minReplicas: 0
      maxReplicas: 20
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

```yaml
# operator
transports:
  sqs:
    enabled: true
    config:
      region: us-east-1

# crew
storage: s3
s3Bucket: asya-results
s3Region: us-east-1

# actors
spec:
  transport: sqs
```

### Local with RabbitMQ + MinIO

```yaml
# operator
transports:
  rabbitmq:
    enabled: true
    config:
      host: rabbitmq.default.svc.cluster.local
      port: 5672
      username: guest
      password: guest

# crew
storage: minio
minioEndpoint: http://minio:9000
minioAccessKey: minioadmin
minioSecretKey: minioadmin
minioBucket: asya-results

# actors
spec:
  transport: rabbitmq
```

## Upgrading Charts

```bash
# Upgrade operator
helm upgrade asya-operator deploy/helm-charts/asya-operator/ \
  -n asya-system \
  -f values.yaml

# Upgrade gateway
helm upgrade asya-gateway deploy/helm-charts/asya-gateway/ \
  -f values.yaml

# Upgrade crew
helm upgrade asya-crew deploy/helm-charts/asya-crew/ \
  -f values.yaml
```

## Uninstalling

```bash
# Uninstall components
helm uninstall asya-gateway
helm uninstall asya-crew
helm uninstall asya-operator -n asya-system

# Remove CRDs (will delete all AsyncActors)
kubectl delete -f src/asya-operator/config/crd/
```
