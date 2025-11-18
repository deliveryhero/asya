# Quickstart for Platform Engineers

Deploy and manage Asya🎭 infrastructure.

## Overview

As platform engineer, you:
- Deploy Asya operator and gateway
- Configure transports (SQS, RabbitMQ)
- Manage IAM roles and permissions
- Monitor system health
- Support data science teams

## Prerequisites

- Kubernetes cluster (EKS, GKE, Kind)
- kubectl and Helm configured
- Transport backend (SQS + S3 or RabbitMQ + MinIO)
- KEDA installed

## Quick Start

### 1. Install KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace
```

### 2. Install CRDs

```bash
kubectl apply -f src/asya-operator/config/crd/
```

### 3. Configure Transports

**For AWS (SQS)**:
```yaml
# operator-values.yaml
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1

serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/asya-operator-role
```

**For self-hosted (RabbitMQ)**:
```yaml
# operator-values.yaml
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

### 4. Install Operator

```bash
helm install asya-operator deploy/helm-charts/asya-operator/ \
  -n asya-system --create-namespace \
  -f operator-values.yaml
```

### 5. Install Gateway (Optional)

```yaml
# gateway-values.yaml
config:
  sqsRegion: us-east-1  # or skip for RabbitMQ
  postgresHost: postgres.default.svc.cluster.local
  postgresDatabase: asya_gateway

routes:
  tools:
  - name: example
    description: Example tool
    parameters:
      text:
        type: string
        required: true
    route: [example-actor]
```

```bash
helm install asya-gateway deploy/helm-charts/asya-gateway/ \
  -f gateway-values.yaml
```

### 6. Install Crew Actors

```yaml
# crew-values.yaml
storage: s3  # or minio
s3Bucket: asya-results
s3Region: us-east-1

gatewayUrl: http://asya-gateway:80
```

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  -f crew-values.yaml
```

### 7. Verify Installation

```bash
# Check operator
kubectl get pods -n asya-system

# Check KEDA
kubectl get pods -n keda

# Check CRDs
kubectl get crd | grep asya
```

## Supporting Data Science Teams

### Provide Template

Share AsyncActor template with DS teams:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  transport: sqs  # or rabbitmq
  scaling:
    minReplicas: 0
    maxReplicas: 50
    queueLength: 5
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: YOUR_IMAGE:TAG
          env:
          - name: ASYA_HANDLER
            value: "module.function"
          resources:
            requests:
              memory: "1Gi"
              cpu: "500m"
            limits:
              memory: "2Gi"
```

### Configure Gateway Tools

Add tools for DS teams to call:

```yaml
# gateway-values.yaml
routes:
  tools:
  - name: text-processor
    description: Process text with ML model
    parameters:
      text:
        type: string
        required: true
      model:
        type: string
        default: "default"
    route: [text-preprocess, text-infer, text-postprocess]
```

### Grant Access

**AWS**: Create IAM roles for actors
```bash
aws eks create-pod-identity-association \
  --cluster-name my-cluster \
  --namespace default \
  --service-account my-actor \
  --role-arn arn:aws:iam::ACCOUNT:role/asya-actor-role
```

**RabbitMQ**: Provide credentials
```bash
kubectl create secret generic rabbitmq-secret \
  --from-literal=password=YOUR_PASSWORD
```

## Monitoring

### Prometheus Metrics

**ServiceMonitors** created automatically by operator.

**Key metrics**:
- `asya_sidecar_processing_duration_seconds`
- `asya_operator_reconcile_total`
- `keda_scaler_active`

### Grafana Dashboards

**Example queries**:

**Actor throughput**:
```promql
rate(asya_sidecar_messages_processed_total[5m])
```

**Queue depth**:
```promql
keda_scaler_metrics_value{scaledObject="my-actor"}
```

**Error rate**:
```promql
rate(asya_sidecar_errors_total[5m])
```

### Logging

**View operator logs**:
```bash
kubectl logs -n asya-system deploy/asya-operator -f
```

**View actor logs**:
```bash
kubectl logs -l asya.sh/actor=my-actor -c asya-sidecar -f
```

## Troubleshooting

### Queue Not Created

```bash
# Check operator logs
kubectl logs -n asya-system deploy/asya-operator

# Check AsyncActor status
kubectl describe asya my-actor
```

### Actor Not Scaling

```bash
# Check KEDA
kubectl get scaledobject my-actor -o yaml
kubectl describe scaledobject my-actor

# Check HPA
kubectl get hpa
```

### Sidecar Connection Errors

```bash
# Check sidecar logs
kubectl logs deploy/my-actor -c asya-sidecar

# Common issues:
# - Wrong transport config
# - Missing IAM permissions
# - Queue doesn't exist
```

### Runtime Errors

```bash
# Check runtime logs
kubectl logs deploy/my-actor -c asya-runtime

# Common issues:
# - Handler not found (wrong ASYA_HANDLER)
# - Missing dependencies
# - OOM errors
```

## Scaling Configuration

### CPU-based Autoscaling

```yaml
spec:
  scaling:
    minReplicas: 1
    maxReplicas: 50
    queueLength: 5
    cpuThreshold: 80  # Future: combine with queue-based
```

### GPU Workloads

```yaml
spec:
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          resources:
            limits:
              nvidia.com/gpu: 1
        nodeSelector:
          nvidia.com/gpu: "true"
        tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

## Cost Optimization

**Enable scale-to-zero**:
```yaml
spec:
  scaling:
    minReplicas: 0  # Scale to 0 when idle
```

**Set appropriate queueLength**:
- Higher = fewer pods, slower processing
- Lower = more pods, faster processing

**Example**: `queueLength: 10` means 100 messages → 10 pods

**Use Spot Instances** (AWS):
```bash
eksctl create nodegroup \
  --cluster my-cluster \
  --spot \
  --instance-types g4dn.xlarge
```

## Upgrades

```bash
# Upgrade operator
helm upgrade asya-operator deploy/helm-charts/asya-operator/ \
  -n asya-system \
  -f operator-values.yaml

# Upgrade gateway
helm upgrade asya-gateway deploy/helm-charts/asya-gateway/ \
  -f gateway-values.yaml

# Upgrade crew
helm upgrade asya-crew deploy/helm-charts/asya-crew/ \
  -f crew-values.yaml
```

**See**: [../operate/upgrades.md](../operate/upgrades.md) for version compatibility.

## Next Steps

- Read [Architecture Overview](../architecture/)
- Configure [Monitoring](../operate/monitoring.md)
- Review [AWS Installation Guide](../install/aws-eks.md)
