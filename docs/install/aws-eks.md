# AWS EKS Installation

Production deployment of Asya🎭 on Amazon EKS.

## Prerequisites

- AWS CLI configured
- kubectl 1.24+
- Helm 3.0+
- eksctl (optional, for cluster creation)
- EKS cluster 1.24+

## Required Components

### 1. VPC and Networking

**Requirements**:

- VPC with public and private subnets
- NAT gateway for private subnet internet access
- Security groups allowing pod-to-pod communication

**See**: [AWS VPC Best Practices](https://docs.aws.amazon.com/eks/latest/userguide/network_reqs.html)

### 2. IAM Roles and Permissions

**EKS Pod Identity** (recommended):

**Operator role** (`asya-operator-role`):
```json
{
  "Effect": "Allow",
  "Action": [
    "sqs:CreateQueue",
    "sqs:DeleteQueue",
    "sqs:GetQueueAttributes",
    "sqs:SetQueueAttributes",
    "sqs:TagQueue",
    "sqs:GetQueueUrl"
  ],
  "Resource": "arn:aws:sqs:*:*:asya-*"
}
```

**Actor role** (`asya-actor-role`):
```json
{
  "Effect": "Allow",
  "Action": [
    "sqs:ReceiveMessage",
    "sqs:SendMessage",
    "sqs:DeleteMessage",
    "sqs:ChangeMessageVisibility",
    "sqs:GetQueueAttributes"
  ],
  "Resource": "arn:aws:sqs:*:*:asya-*"
},
{
  "Effect": "Allow",
  "Action": [
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:ListBucket"
  ],
  "Resource": [
    "arn:aws:s3:::asya-results",
    "arn:aws:s3:::asya-results/*"
  ]
}
```

**KEDA role** (`keda-operator-role`):
```json
{
  "Effect": "Allow",
  "Action": [
    "sqs:GetQueueAttributes",
    "sqs:GetQueueUrl",
    "sqs:ListQueues"
  ],
  "Resource": "arn:aws:sqs:*:*:asya-*"
}
```

### 3. EKS Addons

```bash
# Install Pod Identity Agent
eksctl create addon --cluster my-cluster \
  --name eks-pod-identity-agent

# Install VPC CNI
eksctl create addon --cluster my-cluster \
  --name vpc-cni --version v1.16.2
```

### 4. KEDA Operator

```bash
# Create namespace
kubectl create namespace keda

# Add Helm repo
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# Install KEDA
helm install keda kedacore/keda \
  --namespace keda \
  --version 2.15.1
```

**Configure Pod Identity** for KEDA:
```bash
aws eks create-pod-identity-association \
  --cluster-name my-cluster \
  --namespace keda \
  --service-account keda-operator \
  --role-arn arn:aws:iam::ACCOUNT:role/keda-operator-role
```

### 5. S3 Bucket for Results

```bash
aws s3 mb s3://asya-results --region us-east-1
```

## Optional Components

### GPU Node Group

For AI/ML workloads:

```bash
eksctl create nodegroup \
  --cluster my-cluster \
  --name gpu-nodes \
  --node-type g4dn.xlarge \
  --nodes-min 0 \
  --nodes-max 10 \
  --node-ami-family AmazonLinux2 \
  --node-taints nvidia.com/gpu=true:NoSchedule
```

**Install NVIDIA Device Plugin**:
```bash
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.0/deployments/static/nvidia-device-plugin.yml
```

### Cluster Autoscaler

For automatic node provisioning:

```bash
helm repo add autoscaler https://kubernetes.github.io/autoscaler
helm install cluster-autoscaler autoscaler/cluster-autoscaler \
  --namespace kube-system \
  --set autoDiscovery.clusterName=my-cluster \
  --set awsRegion=us-east-1
```

### Metrics Server

For resource metrics:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### CloudWatch Container Insights

For centralized logging:

```bash
eksctl create iamserviceaccount \
  --cluster my-cluster \
  --namespace amazon-cloudwatch \
  --name cloudwatch-agent \
  --attach-policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy \
  --approve

# Install CloudWatch agent
kubectl apply -f https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/quickstart/cwagent-fluentd-quickstart.yaml
```

## Asya🎭 Deployment

### 1. Install CRDs

```bash
kubectl apply -f src/asya-operator/config/crd/
```

### 2. Configure Operator Values

```yaml
# operator-values.yaml
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1

serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/asya-operator-role
```

### 3. Install Operator

```bash
helm install asya-operator deploy/helm-charts/asya-operator/ \
  -n asya-system --create-namespace \
  -f operator-values.yaml
```

### 4. Install Gateway (Optional)

```yaml
# gateway-values.yaml
config:
  sqsRegion: us-east-1
  s3Bucket: asya-results
  postgresHost: postgres.default.svc.cluster.local

serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/asya-gateway-role

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
  -n default \
  -f gateway-values.yaml
```

### 5. Install Crew Actors

```yaml
# crew-values.yaml
happy-end:
  enabled: true
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.happy_end_handler
          - name: ASYA_S3_BUCKET
            value: asya-results
          # AWS_REGION from IRSA

error-end:
  enabled: true
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.error_end_handler
          - name: ASYA_S3_BUCKET
            value: asya-results
```

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  -n default \
  -f crew-values.yaml
```

**Note**: IRSA annotation can be set per-actor in AsyncActor spec if needed.

### 6. Deploy Your Actors

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/asya-actor-role
spec:
  transport: sqs
  scaling:
    minReplicas: 0
    maxReplicas: 50
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-actor:v1
          env:
          - name: ASYA_HANDLER
            value: "handler.process"
```

```bash
kubectl apply -f my-actor.yaml
```

## Verification

```bash
# Check operator
kubectl get pods -n asya-system

# Check KEDA
kubectl get pods -n keda

# Check actor
kubectl get asya my-actor
kubectl get pods -l asya.sh/actor=my-actor

# Check queue created
aws sqs list-queues | grep asya-my-actor
```

## Cost Optimization

- Use Spot Instances for GPU nodes
- Enable cluster autoscaler scale-to-zero
- Use KEDA scale-to-zero (`minReplicas: 0`)
- Set appropriate `queueLength` for scaling efficiency
- Monitor SQS costs (first 1M requests free)

**See**: [AWS EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)
