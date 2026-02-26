# AWS EKS Installation

Production deployment of 🎭 on Amazon EKS.

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

**Crossplane AWS provider role** (`crossplane-provider-aws-role`):
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

**Actor role** (`asya-actor-role`) - shared IAM role for all actor sidecars. Provides access to SQS queues and S3 bucket for persisting messages. This role is assigned via IRSA (or EKS Pod Identity) to a shared `asya-actors` ServiceAccount in each actor namespace — no static AWS credentials are stored in the cluster:

> **Note:** For local development with LocalStack, IRSA is unavailable. Use a static `aws-creds` Secret with `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` instead. See `docs/quickstart/README_CROSSPLANE.md` for the dev setup.
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
    "arn:aws:s3:::asya-results-bucket",
    "arn:aws:s3:::asya-results-bucket/*"
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

Create a sample S3 bucket for persisting result messages:

```bash
aws s3 mb s3://asya-results-bucket --region us-east-1
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

### 1. Install Crossplane

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace
```

### 2. Configure Crossplane Values

```yaml
# crossplane-values.yaml
awsRegion: us-east-1
awsProviderConfig:
  name: default
  credentialsSource: Secret
  secretRef:
    namespace: crossplane-system
    name: aws-creds
    key: credentials
```

### 3. Install Asya Crossplane Chart

```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ \
  -n crossplane-system \
  -f crossplane-values.yaml
```

### 4. Install Asya Injector

```bash
helm install asya-injector deploy/helm-charts/asya-injector/ \
  -n asya-system --create-namespace
```

### 5. Install Gateway (Optional)

```yaml
# gateway-values.yaml
config:
  sqsRegion: us-east-1
  s3Bucket: asya-results-bucket
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

### 6. Install Crew Actors

Crew actors are pre-defined system actors for handling common scenarios.
For example, actors `x-sink` and `x-sump` are the common flow finalizers and can persist messages to S3-compatible storage.

Suppose, we want to save all messages to the bucket `s3://asya-results-bucket`. Note that the bucket name should be globally unique.

```yaml
# crew-values.yaml
x-sink:
  enabled: true
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints

x-sump:
  enabled: true
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints
```

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  -n default \
  -f crew-values.yaml
```

**Note**: IRSA annotation can be set per-actor in AsyncActor spec if needed.

### 7. Deploy Your Actors

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
# Check Crossplane
kubectl get pods -n crossplane-system

# Check injector
kubectl get pods -n asya-system

# Check KEDA
kubectl get pods -n keda

# Check actor
kubectl get asyncactor my-actor
kubectl get pods -l asya.sh/actor=my-actor

# Check queue created
aws sqs list-queues | grep asya-my-actor
kubectl get sqsqueue
```

## Cost Optimization

- Use Spot Instances for GPU nodes
- Enable cluster autoscaler scale-to-zero
- Use KEDA scale-to-zero (`minReplicas: 0`)
- Set appropriate `queueLength` for scaling efficiency
- Monitor SQS costs (first 1M requests free)

**See**: [AWS EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)
