# EKS Cluster Requirements for GPU-Powered AI Workloads

## Overview

Infrastructure requirements for deploying Asya🎭 framework on Amazon EKS with GPU support for AI/ML workloads.

## Component Categories

- **Critical:** Required for Asya🎭 to function
- **Standard Kubernetes:** Default EKS components, not Asya🎭-specific
- **Optional:** Enhancements for specific use cases


## Critical Components

### 1. EKS Pod Identity Agent

**Purpose:** IAM authentication for AWS services (operator SQS queue management, actors SQS/S3 access)

**Requirements:**
- Kubernetes 1.24+
- EKS addon: `eks-pod-identity-agent`

### 2. VPC CNI Plugin

**Purpose:** Pod networking for SQS and S3 connectivity

**Requirements:**
- Version 1.16.2+
- EKS addon: `vpc-cni`

### 3. NVIDIA Device Plugin

**Purpose:** GPU resource allocation and scheduling

**Requirements:**
- DaemonSet: `nvcr.io/nvidia/k8s-device-plugin:v0.17.0`
- Deployed to namespace `kube-system`
- Tolerates `nvidia.com/gpu` taint

### 4. KEDA Operator

**Purpose:** Event-driven autoscaling based on SQS queue depth, scale-to-zero

**Requirements:**
- Helm chart: `kedacore/keda` v2.15.1+
- Namespace: `keda`
- IAM role for KEDA operator service account:
  - Trust policy: Pod Identity (`pods.eks.amazonaws.com`)
  - Permissions: `sqs:GetQueueAttributes`, `sqs:GetQueueUrl`, `sqs:ListQueues` on `asya-*`
  - Pod Identity association: namespace `keda`, service account `keda-operator`

### 5. Cluster Autoscaler

**Purpose:** Automatic GPU node provisioning based on pending pod demand

**Requirements:**
- Helm chart: `kubernetes/autoscaler` v9.37.0+
- Namespace: `kube-system`
- IAM role for autoscaler service account:
  - Trust policy: Pod Identity (`pods.eks.amazonaws.com`)
  - Permissions: ASG describe/modify, EC2 describe, EKS describe
  - Pod Identity association: namespace `kube-system`, service account `cluster-autoscaler`
- Auto-discovery tags on node groups:
  - `k8s.io/cluster-autoscaler/<cluster-name>=owned`
  - `k8s.io/cluster-autoscaler/enabled=true`

### 6. GPU Node Group

**Requirements:**
- Instance types: g4dn.xlarge, g5.xlarge, p3.2xlarge, p4d.24xlarge
- AMI: `AL2_x86_64_GPU` (AL2 deprecated after Nov 26, 2025 - migrate to Bottlerocket)
- Node taint: `nvidia.com/gpu=true:NoSchedule`
- IAM policies: `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy`, `AmazonEC2ContainerRegistryReadOnly`
- Scale-to-zero: `min_size=0`, `max_size=10`

### 7. OIDC Provider

**Purpose:** Required for EKS Pod Identity and IRSA

**Requirements:**
- Client ID: `sts.amazonaws.com`
- Thumbprint from EKS cluster OIDC issuer

### 8. IAM Roles for Asya🎭

**asya-operator:**
- Trust policy: Pod Identity (`pods.eks.amazonaws.com`)
- Permissions: SQS queue management on `asya-*` (`CreateQueue`, `DeleteQueue`, `GetQueueAttributes`, `SetQueueAttributes`, `TagQueue`)
- Pod Identity association: namespace `asya-system`, service account `asya-operator`

**asya-actor (shared):**
- Trust policy: Pod Identity (`pods.eks.amazonaws.com`)
- Permissions:
  - SQS: `ChangeMessageVisibility`, `DeleteMessage`, `GetQueueAttributes`, `ReceiveMessage`, `SendMessage` on `asya-*`
  - S3: `GetObject`, `PutObject`, `DeleteObject`, `ListBucket` on results bucket
  - Additional permissions needed by application code
- Pod Identity associations: created per-actor by operator

**asya-gateway:**
- Trust policy: Pod Identity (`pods.eks.amazonaws.com`)
- Permissions: `sqs:SendMessage`, `sqs:GetQueueUrl` on `asya-*` (sends messages to first actor in route)
- Pod Identity association: namespace where actors are deployed (e.g., `asya-prod`, `asya-e2e`), service account `asya-gateway`
- Note: Gateway is deployed in the same namespace as actors, NOT in `asya-system` with the operator

### 9. S3 Bucket

**Purpose:** Storage for actor processing results (happy-end writes here)

**Requirements:**
- Encryption: AES256 or KMS
- Versioning: Enabled
- Lifecycle policy: 90-day expiration, 30-day noncurrent version retention

## Standard Kubernetes Components

### CoreDNS

**Purpose:** In-cluster DNS resolution

**Required for Asya🎭?** No. Actors communicate with external AWS services, not internal K8s services.

**Included because:** Standard K8s component, may be needed for monitoring/logging.

### kube-proxy

**Purpose:** Kubernetes Service networking (iptables/IPVS)

**Required for Asya🎭?** No. Actors use SQS queues, not K8s Services.

**Included because:** Fundamental K8s networking component.

## Optional Components

### AWS EBS CSI Driver

**When needed:**
- Stateful actors requiring persistent storage
- Fast local disk for model caching
- POSIX filesystem semantics

**Not needed for:** Stateless GPU inference (models loaded from S3 to GPU memory)

### Metrics Server

**When needed:**
- Resource usage monitoring (`kubectl top`)
- HPA in addition to KEDA
- Debugging resource constraints

**Not needed for:** Basic Asya🎭 operation with KEDA-only scaling

### CloudWatch Container Insights

**When needed:**
- Centralized logging beyond stdout/stderr
- AWS-native monitoring dashboards
- CloudWatch Alarms integration

## VPC and Networking

**Multi-AZ requirement:**
- EKS control plane requires 2+ AZs for high availability
- Node groups can span AZs for fault tolerance
- Single-AZ limitation: Reduced control plane availability, no node fault tolerance

**Subnet requirements:**
- Private subnets for node groups
- Public subnets for NAT gateways (if using private nodes)
- Subnet tags: `kubernetes.io/role/internal-elb=1` (private), `kubernetes.io/role/elb=1` (public)

## IAM Authentication Schemes

### EKS Pod Identity (Recommended)

**Advantages:**
- Simpler trust policy (always `pods.eks.amazonaws.com`)
- No per-cluster OIDC configuration in trust policy
- Cross-account role assumption support
- Centralized association management via EKS API

**Trust policy principal:** `Service: pods.eks.amazonaws.com`

**Required actions:** `sts:AssumeRole`, `sts:TagSession`

### IRSA (IAM Roles for Service Accounts)

**Legacy approach.** Use for:
- Kubernetes < 1.24 (Pod Identity unavailable)
- Compatibility with existing IRSA infrastructure

**Trust policy principal:** `Federated: <OIDC provider ARN>`

**Required action:** `sts:AssumeRoleWithWebIdentity`

**Conditions:** Match `<oidc-url>:sub` to `system:serviceaccount:<namespace>:<sa-name>`, `<oidc-url>:aud` to `sts.amazonaws.com`

**Service account annotation:** `eks.amazonaws.com/role-arn: <role-arn>`

## Cost Optimization

### GPU Node Scaling

- Node group: `min_size=0`, `desired_size=0`, `max_size=10`
- KEDA ScaledObject: `minReplicaCount=0`
- Cluster Autoscaler scales nodes based on pending pods
- Spot instances: `capacity_type=SPOT`, multiple instance types for flexibility

### SQS

- Long polling: `waitTimeSeconds=20` (reduces empty receives)
- Batch operations: Up to 10 messages per request
- Visibility timeout: Match actor processing time
- Dead-letter queues: Prevent infinite retries

### S3

- Lifecycle policies: Auto-delete old results (90 days)
- S3 Intelligent-Tiering: Automatic cost optimization
- Versioning retention: 30 days for noncurrent versions

## Security

### Network Policies

- Restrict actor egress to DNS (kube-system) and external services
- Block IMDS endpoint: `169.254.169.254/32`

### SQS Encryption

- KMS encryption with key rotation enabled
- Key reuse period: 300 seconds

### Pod Security Standards

- Namespace labels: `pod-security.kubernetes.io/enforce=restricted`

### IAM Policy Scoping

- All SQS policies: Scoped to `arn:aws:sqs:*:<account>:asya-*`
- S3 policies: Scoped to specific bucket ARN

## Deployment Checklist

**Infrastructure:**
- [ ] VPC with private/public subnets (2+ AZs)
- [ ] EKS cluster 1.24+
- [ ] OIDC provider
- [ ] GPU node group (AL2 GPU AMI)
- [ ] S3 bucket (encryption, lifecycle)

**Kubernetes:**
- [ ] VPC CNI addon
- [ ] EKS Pod Identity Agent addon
- [ ] CoreDNS addon
- [ ] kube-proxy addon
- [ ] NVIDIA device plugin DaemonSet

**Autoscaling:**
- [ ] Cluster Autoscaler (Helm + IAM role with Pod Identity association)
- [ ] KEDA operator (Helm + IAM role with Pod Identity association)

**IAM for Asya🎭:**
- [ ] asya-operator role + Pod Identity association
- [ ] asya-actor role (operator creates associations per-actor)
- [ ] asya-gateway role + Pod Identity association

**Security:**
- [ ] IAM policies scoped to `asya-*`
- [ ] Network policies
- [ ] Pod security standards

**Asya🎭:**
- [ ] Operator Helm chart
- [ ] Operator configured with SQS transport + actor role ARN

## Validation Commands

**Cluster components:**
```bash
kubectl get nodes -l nvidia.com/gpu=true
kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds
kubectl get pods -n kube-system -l app.kubernetes.io/name=cluster-autoscaler
kubectl get pods -n keda -l app.kubernetes.io/name=keda-operator
```

**IAM roles:**
```bash
aws iam get-role --role-name asya-operator
aws iam get-role --role-name asya-actor
aws iam get-role --role-name asya-gateway
```

**Pod Identity associations:**
```bash
aws eks list-pod-identity-associations --cluster-name <cluster-name>
```

**S3 bucket:**
```bash
aws s3 ls | grep asya-results
```

**GPU test pod:**
```bash
kubectl run gpu-test --image=nvidia/cuda:12.2.0-base-ubuntu22.04 \
  --limits=nvidia.com/gpu=1 --restart=Never --command -- nvidia-smi
kubectl logs gpu-test
```

## References

- [EKS User Guide](https://docs.aws.amazon.com/eks/latest/userguide/)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [KEDA AWS SQS Scaler](https://keda.sh/docs/2.14/scalers/aws-sqs/)
- [NVIDIA Device Plugin](https://github.com/NVIDIA/k8s-device-plugin)
- [Cluster Autoscaler on AWS](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/cloudprovider/aws/README.md)
- [Asya🎭 AWS Setup Guide](./aws-setup.md)
