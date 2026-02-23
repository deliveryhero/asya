# Quickstart for Platform Engineers

Deploy and manage Asya🎭 infrastructure.

## What You'll Learn

- Install and configure Crossplane with Asya compositions and injector webhook
- Deploy gateway and crew actors for pipeline completion
- Support data science teams with templates and IAM configuration
- Set up monitoring with Prometheus and troubleshoot common issues
- Optimize scaling and costs for production workloads

## Overview

As platform engineer, you:

- Deploy Crossplane compositions and asya-injector webhook
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

### 2. Install Crossplane

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace
```

### 3. Install Asya Compositions and Injector

```bash
# Install Asya XRDs and Compositions
kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crossplane.yaml

# Install asya-injector webhook
helm install asya-injector deploy/helm-charts/asya-injector/ \
  -n asya-system --create-namespace
```

### 4. Configure Transports

**For AWS (SQS)**: Configure transport in AsyncActor resources
**For self-hosted (RabbitMQ)**: Configure transport in AsyncActor resources

Transport configuration is now managed per-actor in AsyncActor CRs, not centrally.

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
helm install asya-gateway deploy/helm-charts/asya-gateway/ -f gateway-values.yaml
```

### 6. Install Crew Actors

```yaml
# crew-values.yaml
x-sink:
  enabled: true
  transport: sqs  # or rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: asya_crew.message_persistence.s3.checkpoint_handler
          - name: ASYA_S3_BUCKET
            value: asya-results
          # For MinIO:
          # - name: ASYA_S3_ENDPOINT
          #   value: http://minio:9000
          # - name: ASYA_S3_ACCESS_KEY
          #   value: minioadmin
          # - name: ASYA_S3_SECRET_KEY
          #   value: minioadmin

x-sump:
  enabled: true
  transport: sqs  # or rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: asya_crew.message_persistence.s3.checkpoint_handler
          - name: ASYA_S3_BUCKET
            value: asya-results
```

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ -f crew-values.yaml
```

### 7. Verify Installation

```bash
# Check Crossplane
kubectl get pods -n crossplane-system

# Check injector webhook
kubectl get pods -n asya-system

# Check KEDA
kubectl get pods -n keda

# Check XRDs
kubectl get xrd | grep asya

# Check crew actors
kubectl get asyncactor
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
    enabled: true
    minReplicas: 0
    maxReplicas: 50
    queueLength: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: YOUR_IMAGE:TAG
          env:
          - name: ASYA_HANDLER
            value: "module.function"
            # For class handlers: "module.Class.method"
          resources:
            requests:
              memory: "1Gi"
              cpu: "500m"
            limits:
              memory: "2Gi"
```

**Key fields to explain**:
- `spec.transport`: Which transport to use (ask platform team)
- `spec.scaling.enabled`: Enable KEDA autoscaling (default: false)
- `spec.scaling.minReplicas`: Minimum pods (0 for scale-to-zero)
- `spec.scaling.maxReplicas`: Maximum pods
- `spec.scaling.queueLength`: Messages per replica target
- `spec.workload.kind`: Deployment
- `env.ASYA_HANDLER`: Handler path (`module.function` or `module.Class.method`)

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

**AWS (IRSA)**: Configure IAM role annotation in AsyncActor
```yaml
metadata:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/asya-actor-role
```

**AWS (Pod Identity)**: Create pod identity association
```bash
aws eks create-pod-identity-association \
  --cluster-name my-cluster \
  --namespace default \
  --service-account asya-my-actor \
  --role-arn arn:aws:iam::ACCOUNT:role/asya-actor-role
```

**RabbitMQ**: Provide credentials
```bash
kubectl create secret generic rabbitmq-secret \
  --from-literal=password=YOUR_PASSWORD
```

## Monitoring

### Prometheus Metrics

**Important**: The injector webhook does NOT automatically create ServiceMonitors. You must configure Prometheus scraping.

**Key sidecar metrics** (namespace: `asya_actor`):

- `asya_actor_processing_duration_seconds{queue}` - Processing time
- `asya_actor_messages_processed_total{queue, status}` - Messages processed
- `asya_actor_messages_failed_total{queue, reason}` - Failed messages
- `asya_actor_runtime_errors_total{queue, error_type}` - Runtime errors

**Key Crossplane metrics**:

- `crossplane_composition_reconcile_total` - Composition reconciliations
- `crossplane_composition_reconcile_errors_total` - Composition errors

**KEDA metrics**:

- `keda_scaler_active{scaledObject}` - Active scalers
- `keda_scaler_metrics_value{scaledObject}` - Queue depth

### Prometheus Configuration

**ServiceMonitor** (Prometheus Operator):
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: asya-actors
spec:
  selector:
    matchLabels:
      asya.sh/actor: "*"
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
```

**Scrape config** (standard Prometheus):
```yaml
scrape_configs:
- job_name: asya-actors
  kubernetes_sd_configs:
  - role: pod
  relabel_configs:
  - source_labels: [__meta_kubernetes_pod_label_asya_sh_actor]
    action: keep
    regex: .+
  - source_labels: [__meta_kubernetes_pod_container_name]
    action: keep
    regex: asya-sidecar
  - source_labels: [__address__]
    action: replace
    regex: ([^:]+)(?::\d+)?
    replacement: $1:8080
    target_label: __address__
```

### Grafana Dashboards

**Example queries**:

**Actor throughput**:
```promql
rate(asya_actor_messages_processed_total{queue="asya-my-actor"}[5m])
```

**Queue depth**:
```promql
keda_scaler_metrics_value{scaledObject="my-actor"}
```

**Error rate**:
```promql
rate(asya_actor_messages_failed_total{queue="asya-my-actor"}[5m])
```

**P95 latency**:
```promql
histogram_quantile(0.95, rate(asya_actor_processing_duration_seconds_bucket{queue="asya-my-actor"}[5m]))
```

**See**: [../operate/monitoring.md](../operate/monitoring.md) for complete metrics and alerts.

### Logging

**View Crossplane logs**:
```bash
kubectl logs -n crossplane-system deploy/crossplane -f
```

**View injector webhook logs**:
```bash
kubectl logs -n asya-system deploy/asya-injector -f
```

**View actor logs**:
```bash
# Runtime logs (handler output)
kubectl logs -l asya.sh/actor=my-actor -c asya-runtime -f

# Sidecar logs (routing, transport)
kubectl logs -l asya.sh/actor=my-actor -c asya-sidecar -f
```

## Troubleshooting

### Queue Not Created

```bash
# Check Crossplane logs
kubectl logs -n crossplane-system deploy/crossplane

# Check AsyncActor status
kubectl describe asyncactor my-actor

# Check conditions
kubectl get asyncactor my-actor -o jsonpath='{.status.conditions}'
```

**Common causes**:
- Transport not configured in AsyncActor spec
- Missing IAM permissions (SQS)
- RabbitMQ connection failure
- AWS SQS 60-second cooldown after queue deletion

### Actor Not Scaling

```bash
# Check ScaledObject
kubectl get scaledobject my-actor -o yaml
kubectl describe scaledobject my-actor

# Check HPA created by KEDA
kubectl get hpa

# Check KEDA operator logs
kubectl logs -n keda deploy/keda-operator
```

**Common causes**:
- `spec.scaling.enabled` not set to `true`
- KEDA not installed
- Queue doesn't exist
- Missing IAM permissions for KEDA to read queue metrics

### Sidecar Connection Errors

```bash
# Check sidecar logs
kubectl logs deploy/my-actor -c asya-sidecar

# Check transport config
kubectl get asya my-actor -o jsonpath='{.spec.transport}'
```

**Common issues**:
- Wrong transport configured in AsyncActor spec
- Missing IAM permissions (SQS)
- RabbitMQ credentials incorrect
- Queue doesn't exist
- Network connectivity issues

### Runtime Errors

```bash
# Check runtime logs
kubectl logs deploy/my-actor -c asya-runtime

# Check handler config
kubectl get asya my-actor -o jsonpath='{.spec.workload.template.spec.containers[?(@.name=="asya-runtime")].env}'
```

**Common issues**:
- Wrong `ASYA_HANDLER` value (handler not found)
- Missing Python dependencies in image
- Class handler `__init__` parameters missing defaults
- OOM errors (insufficient memory)
- CUDA OOM (GPU memory exhausted)

### Pod Status Issues

Check AsyncActor status for detailed error information:

```bash
kubectl get asya my-actor
```

**Status values**:
- `Running` - Healthy
- `Napping` - Scaled to zero (normal with minReplicas=0)
- `Creating` - Initial deployment
- `RuntimeError` - Runtime container crashing
- `SidecarError` - Sidecar container crashing
- `ImagePullError` - Cannot pull image
- `TransportError` - Queue/transport issues

## Scaling Configuration

### Queue-based Autoscaling (KEDA)

```yaml
spec:
  scaling:
    enabled: true
    minReplicas: 0          # Scale to zero when idle
    maxReplicas: 50         # Max replicas
    queueLength: 5          # Target: 5 messages per replica
    pollingInterval: 10     # Check queue every 10s
    cooldownPeriod: 60      # Wait 60s before scaling down
```

**Formula**: `desiredReplicas = ceil(queueDepth / queueLength)`

**Example**: 100 messages, queueLength=5 → 20 replicas

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

**Note**: Ensure GPU node group exists and NVIDIA device plugin is installed.

## Cost Optimization

**Enable scale-to-zero**:
```yaml
spec:
  scaling:
    enabled: true
    minReplicas: 0  # $0 when idle
```

**Set appropriate queueLength**:
- Higher = fewer pods, slower processing, lower cost
- Lower = more pods, faster processing, higher cost

**Examples**:
- `queueLength: 5` → 100 messages = 20 pods
- `queueLength: 10` → 100 messages = 10 pods
- `queueLength: 20` → 100 messages = 5 pods

**Use Spot Instances** (AWS):
```bash
eksctl create nodegroup \
  --cluster my-cluster \
  --spot \
  --instance-types g4dn.xlarge \
  --nodes-min 0 \
  --nodes-max 10
```

**SQS cost optimization**:
- First 1M requests/month free
- $0.40 per million requests after
- No idle costs (pay per use)
- Scale to zero = $0

## Upgrades

```bash
# Upgrade Crossplane
helm upgrade crossplane crossplane-stable/crossplane \
  -n crossplane-system

# Upgrade Asya compositions
kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crossplane.yaml

# Upgrade injector webhook
helm upgrade asya-injector deploy/helm-charts/asya-injector/ \
  -n asya-system

# Upgrade gateway
helm upgrade asya-gateway deploy/helm-charts/asya-gateway/ \
  -f gateway-values.yaml

# Upgrade crew
helm upgrade asya-crew deploy/helm-charts/asya-crew/ \
  -f crew-values.yaml
```

**Important**: Always upgrade Crossplane and compositions before upgrading actors. AsyncActors may need to be reconciled after composition upgrade.

## Next Steps

- Read [Architecture Overview](../architecture/README.md)
- Configure [Monitoring](../operate/monitoring.md)
- Review [AWS Installation Guide](../install/aws-eks.md)
- Review [Local Kind Installation](../install/local-kind.md)
