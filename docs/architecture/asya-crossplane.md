# Crossplane Compositions

## Overview

The Crossplane integration provides an alternative deployment model for AsyncActor resources using Crossplane compositions instead of the native Kubernetes operator. Crossplane manages the entire infrastructure lifecycle declaratively, from SQS queues to Deployments to KEDA autoscaling.

## Architecture

AsyncActor resources are implemented as Crossplane Composite Resources:

```
AsyncActor Claim (asya.sh/v1alpha1)
         │
         ▼
    XAsyncActor (XRD)
         │
         ▼
    Composition (SQS)
         │
    ┌────┼────────────────────────┐
    ▼    ▼            ▼           ▼
  SQS  Service-  ScaledObject  Deployment
 Queue Account   (KEDA)
 (AWS)  (IRSA)
```

**Key components**:
- **XRD** (`xasyncactors.asya.sh`): Defines the AsyncActor composite resource schema
- **Composition** (`asyncactor-sqs`): Orchestrates creation of managed resources
- **Managed Resources**: SQS Queue, ServiceAccount, TriggerAuthentication, ScaledObject, Deployment

## How AsyncActor Claims Work

1. **User creates AsyncActor claim** in their namespace
2. **Crossplane creates XAsyncActor XR** (composite resource) from the claim
3. **Composition pipeline executes**:
   - Renders SQS Queue resource with `asya-{namespace}-{actor}` naming
   - Creates ServiceAccount with IRSA annotation (if enabled)
   - Creates KEDA TriggerAuthentication for queue metrics
   - Waits for queue URL from SQS status
   - Creates KEDA ScaledObject with queue URL
   - Creates Deployment with pod labels for injection
4. **Crossplane providers reconcile** each managed resource
5. **Status aggregation**: Composition patches XR status with infrastructure state

## SQS Composition Pipeline

The `asyncactor-sqs` composition uses function-go-templating to render resources dynamically.

**Pipeline steps**:

1. **render-sqs-queue**: Creates SQS Queue
   - Name: `asya-{namespace}-{actor}`
   - Visibility timeout: 30s
   - Message retention: 4 days
   - Receive wait time: 20s (long polling)
   - Tags: `asya.sh/namespace`, `asya.sh/actor`

2. **render-serviceaccount**: Creates ServiceAccount with IRSA annotation (if `irsa.enabled=true`)
   - Name: Configured via `irsa.serviceAccountName` (shared per namespace)
   - Annotation: `eks.amazonaws.com/role-arn` from `irsa.roleArn` or pattern

3. **render-triggerauthentication**: Creates KEDA TriggerAuthentication
   - Auth provider: `podIdentity` or `secret` (configured via `keda.authProvider`)
   - Enables KEDA to read SQS queue metrics

4. **render-scaledobject**: Creates KEDA ScaledObject (if `scaling.enabled=true`)
   - Waits for queue URL from SQS Queue status
   - References TriggerAuthentication for AWS credentials
   - Configures autoscaling policies (scale-up aggressive, scale-down gradual)
   - Min replicas: `spec.scaling.minReplicas` (default: 0)
   - Max replicas: `spec.scaling.maxReplicas` (default: 10)
   - Queue length target: `spec.scaling.queueLength` (default: 5 messages/replica)

5. **render-deployment**: Creates Deployment
   - Workload template from `spec.workload.template`
   - Injects labels: `asya.sh/inject=true`, `asya.sh/actor={name}`
   - ServiceAccount: Uses IRSA ServiceAccount if enabled
   - Replicas: From `spec.workload.replicas` if scaling disabled, otherwise managed by KEDA

6. **patch-status-and-derive-phase**: Aggregates status from managed resources
   - Reads queue URL, queue ARN from SQS Queue status
   - Checks Ready conditions on Queue, ScaledObject, Deployment
   - Calculates phase: `Creating`, `Ready`, or `Napping`

## Status Model

The XAsyncActor status aggregates infrastructure readiness:

**Phase values**:
- **Creating**: Initial state, infrastructure provisioning in progress
- **Ready**: All infrastructure ready and workload has replicas > 0
- **Napping**: KEDA scaled to zero (no messages in queue)

**Status fields**:
```yaml
status:
  phase: Ready
  queueUrl: https://sqs.us-east-1.amazonaws.com/123456789/asya-prod-text-processor
  queueIdentifier: arn:aws:sqs:us-east-1:123456789:asya-prod-text-processor
  infrastructure:
    queue:
      ready: true
      message: ""
    keda:
      ready: true
      message: ""
    workload:
      ready: true
      replicas: 5
      readyReplicas: 5
```

**Phase calculation logic**:
- `Creating`: Default state when any infrastructure not ready
- `Ready`: Queue ready AND KEDA ready AND Workload ready AND replicas > 0
- `Napping`: All ready conditions met but replicas = 0 (KEDA scaled down)

## Queue Management

All message queues are automatically managed by Crossplane AWS Provider.

**Queue naming**: `asya-{namespace}-{actor_name}`
- Example: Actor `text-analyzer` in namespace `prod` → Queue `asya-prod-text-analyzer`
- Example: Actor `image-processor` in namespace `dev` → Queue `asya-dev-image-processor`
- System actors: `asya-{namespace}-x-sink`, `asya-{namespace}-x-sump`

**Queue lifecycle**:
- ✅ Created when AsyncActor claim reconciled by Crossplane
- ✅ Deleted when AsyncActor claim deleted (cascade via Crossplane)
- ✅ Preserved when AsyncActor claim updated (immutable resource)

**Queue properties** (SQS):
- Visibility timeout: 30 seconds
- Message retention: 345600 seconds (4 days)
- Receive wait time: 20 seconds (long polling)
- Deletion policy: Delete (queue removed with AsyncActor)

## Credential Management

Crossplane separates credentials by scope for security and namespace isolation.

**Crossplane AWS Provider credentials** (in `crossplane-system` namespace):
- Used by: Crossplane AWS Provider for queue management (create/delete/configure)
- Secret: Configured in `awsProviderConfig.secretRef` (e.g., `aws-creds`)
- Permissions: Admin-level queue operations
- Alternative: IRSA via `credentialsSource: InjectedIdentity`

**Actor credentials** (in actor's namespace):
- Used by: Sidecar containers for message operations (send/receive/delete)
- Method: IRSA (IAM Roles for Service Accounts) via ServiceAccount annotation
- ServiceAccount: Created by composition with `eks.amazonaws.com/role-arn` annotation
- Permissions: Message-level operations only (SQS SendMessage, ReceiveMessage, DeleteMessage)

**IRSA flow**:
1. Composition creates ServiceAccount with IAM role ARN annotation
2. Deployment references ServiceAccount
3. EKS injects AWS credentials into pod via webhook
4. Sidecar uses ambient credentials for SQS operations

## Resource Ownership

Crossplane manages all resources via composite resource ownership:

**Managed Resources** (owned by XAsyncActor XR):
- ✅ **SQS Queue**: AWS queue via Crossplane AWS Provider
- ✅ **ServiceAccount**: IRSA-annotated ServiceAccount (if enabled)
- ✅ **TriggerAuthentication**: KEDA auth for queue metrics
- ✅ **ScaledObject**: KEDA autoscaling configuration (if scaling enabled)
- ✅ **Deployment**: Actor workload

**Deletion behavior**:
- Deleting AsyncActor claim triggers cascade deletion of XR
- Crossplane deletes all managed resources automatically
- SQS queue deleted via AWS Provider (respects `deletionPolicy: Delete`)

## Deployment

**Prerequisites**:
- Crossplane installed with AWS Provider (SQS) and Kubernetes Provider
- Function Go-Templating installed
- KEDA installed

**Installation**:

```bash
# Install Crossplane compositions and XRD
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ \
  --namespace crossplane-system \
  --set awsProviderConfig.credentialsSource=Secret \
  --set awsAccountId=123456789012 \
  --set actorNamespace=asya-e2e
```

**Configuration** (via `values.yaml`):
- `providers.aws.sqsVersion`: AWS SQS provider version
- `providers.kubernetes.version`: Kubernetes provider version
- `awsProviderConfig.credentialsSource`: `Secret`, `InjectedIdentity`, or `Upbound`
- `irsa.enabled`: Enable ServiceAccount creation with IRSA
- `keda.authProvider`: `podIdentity` or `secret`

## Example AsyncActor Claim

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
  namespace: asya
spec:
  transport: sqs
  region: us-east-1

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5
    pollingInterval: 30
    cooldownPeriod: 300

  workload:
    kind: Deployment
    template:
      spec:
        containers:
          - name: asya-runtime
            image: my-processor:v1
            env:
              - name: ASYA_HANDLER
                value: processor.TextProcessor.process
            resources:
              requests:
                cpu: 100m
                memory: 256Mi
```

**Important**: The `asya-runtime` container must NOT define `command` field - the Crossplane composition manages the entrypoint.

## CEL Validation

The XRD includes CEL (Common Expression Language) validations enforced at admission time:

1. ✅ **Container structure**: `workload.template.spec.containers` must exist
2. ✅ **Container name**: Exactly one container must be named `asya-runtime`
3. ❌ **No custom command**: The `asya-runtime` container cannot define `command` field

**Validation errors**:
- `workload must have template.spec.containers` - Missing container spec
- `workload must have exactly one container named 'asya-runtime'` - Wrong container name
- `asya-runtime container must not define 'command'` - Custom command not allowed

## Comparison with asya-operator

| Feature | asya-operator | asya-crossplane |
|---------|---------------|-----------------|
| Queue Management | Operator creates queues via SDK | Crossplane AWS Provider |
| Deployment | Operator creates Deployment | Crossplane Kubernetes Provider |
| Sidecar Injection | Operator injects directly | Crossplane composition renders inline |
| CEL Validation | In operator code | In XRD schema |
| Credential Management | Operator copies secrets | IRSA via ServiceAccount annotations |
| Status Model | Operator calculates status | Composition aggregates status |
| GitOps | CRD-based | Crossplane claims |

## Observability

**kubectl commands**:
```bash
# List AsyncActor claims
kubectl get asyncactors -n asya-e2e

# Get AsyncActor status
kubectl get asyncactor text-processor -n asya-e2e -o yaml

# List XAsyncActor composite resources
kubectl get xasyncactors

# Check managed resources
kubectl get managed -l crossplane.io/claim-name=text-processor
```

**Status columns**:
- `Actor`: Actor name from `asya.sh/actor` label
- `Status`: Current phase (Creating, Ready, Napping)
- `Ready`: Number of ready replicas
- `Replicas`: Total desired replicas
- `Transport`: Transport type (sqs, rabbitmq)
- `Queue`: Queue URL (priority 1, hidden by default)
- `Age`: Time since creation

## Configuration

Crossplane configuration via Helm values:

```yaml
# AWS ProviderConfig
awsProviderConfig:
  name: default
  credentialsSource: Secret  # or InjectedIdentity
  secretRef:
    namespace: crossplane-system
    name: aws-creds
    key: credentials

# IRSA configuration
irsa:
  enabled: true
  serviceAccountName: asya-actors
  roleArnPattern: "arn:aws:iam::ACCOUNT_ID:role/asya-actors-{namespace}"

# KEDA authentication
keda:
  authProvider: podIdentity  # or secret
```

**AsyncActor references transport by name**:
```yaml
spec:
  transport: sqs  # Just the name
```

Composition validates referenced transport exists in available compositions.
