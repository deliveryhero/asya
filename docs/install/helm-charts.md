# Helm Charts

Asya🎭 provides Helm charts for deploying framework components.

## Available Charts

### asya-operator

Deploys Asya operator (CRD controller).

**Location**: `deploy/helm-charts/asya-operator/`

**Installation**:
```bash
kubectl apply -f src/asya-operator/config/crd/
helm install asya-operator deploy/helm-charts/asya-operator/ -n asya-system --create-namespace -f values.yaml
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

Deploys crew actors (`happy-end`, `error-end`) as AsyncActor CRDs.

**Location**: `deploy/helm-charts/asya-crew/`

**Installation**:
```bash
helm install asya-crew deploy/helm-charts/asya-crew/ --namespace asya-e2e -f values.yaml
```

**Key values**:
```yaml
happy-end:
  enabled: true
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 10
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-crew:latest
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.happy_end_handler
          # Optional S3/MinIO persistence
          - name: ASYA_S3_BUCKET
            value: asya-results
          - name: ASYA_S3_ENDPOINT
            value: http://minio:9000
          - name: ASYA_S3_ACCESS_KEY
            value: minioadmin
          - name: ASYA_S3_SECRET_KEY
            value: minioadmin

error-end:
  enabled: true
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 10
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-crew:latest
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.error_end_handler
          # Optional S3/MinIO persistence
          - name: ASYA_S3_BUCKET
            value: asya-results
```

**Note**: Chart templates automatically inject `ASYA_HANDLER_MODE=envelope` and `ASYA_ENABLE_VALIDATION=false`.

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

**Operator** (`operator-values.yaml`):
```yaml
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
```

**Crew** (`crew-values.yaml`):
```yaml
happy-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_S3_BUCKET
            value: asya-results
          # AWS_REGION from IRSA or instance metadata

error-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_S3_BUCKET
            value: asya-results
```

**Actors**:
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
spec:
  transport: sqs
```

### Local with RabbitMQ + MinIO

**Operator** (`operator-values.yaml`):
```yaml
transports:
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
```

**Crew** (`crew-values.yaml`):
```yaml
happy-end:
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_S3_BUCKET
            value: asya-results
          - name: ASYA_S3_ENDPOINT
            value: http://minio.default.svc.cluster.local:9000
          - name: ASYA_S3_ACCESS_KEY
            value: minioadmin
          - name: ASYA_S3_SECRET_KEY
            value: minioadmin

error-end:
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_S3_BUCKET
            value: asya-results
          - name: ASYA_S3_ENDPOINT
            value: http://minio.default.svc.cluster.local:9000
          - name: ASYA_S3_ACCESS_KEY
            value: minioadmin
          - name: ASYA_S3_SECRET_KEY
            value: minioadmin
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
# Upgrade operator
helm upgrade asya-operator deploy/helm-charts/asya-operator/ -n asya-system -f values.yaml

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
helm uninstall asya-operator -n asya-system

# Remove CRDs (will delete all AsyncActors)
kubectl delete -f src/asya-operator/config/crd/
```
