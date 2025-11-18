
# SQS Authentication Architecture (Shared Role)

## Overview

This document describes the authentication architecture for SQS transport in the Asya🎭 framework. The design uses:
- **Operator**: EKS Pod Identity for queue management
- **Actors**: Single shared IAM role with IRSA (IAM Roles for Service Accounts) for message handling
- **Gateway**: Separate IAM role with IRSA for minimal send-only permissions

## Design Decision

**Shared Role Approach**

- ✅ Single IAM role created manually (one-time setup)
- ✅ Operator creates per-actor ServiceAccounts pointing to shared role
- ✅ Operator has NO IAM management permissions (only SQS queue management)
- ✅ Simple implementation and maintenance
- ✅ Acceptable security tradeoff given framework's lateral routing design

### Security Tradeoff Analysis

**Framework design allows lateral message routing:** Any actor can send messages to any other actor (i.e. to any queue `asya-*`) via envelope routing. This means a compromised actor can poison downstream actors regardless of IAM boundaries.

**What shared role prevents:**
- Operators with compromised credentials cannot escalate to IAM role creation
- Clear separation: operator manages queues, external admin manages IAM

**What shared role does NOT prevent:**
- Compromised actor can eavesdrop on other actors' queues (read messages)
- Compromised actor can delete messages from other actors' queues (DoS)
- Compromised actor can poison messages to any actor (already possible by design)

**Mitigation:** Defense-in-depth at application layer (message validation, **envelope signing**, rate limiting, monitoring).

Yes we'll later implement mTLS-like signing of envelopes so that compromised actor cannot read envelopes sent to other actors.

## Architecture Components

### 1. Naming Conventions

**All actors names are exactly same as their queue name**

**All queues MUST use `asya-` prefix:**
- Queue name: `asya-{actor_name}`
- Example: Actor `ml-model` → Queue `asya-ml-model`

**IAM role naming:**
- Shared actor role: `asya-actor`
- Operator role: `asya-operator`
- Gateway role: `asya-gateway`

### 2. IAM Roles Required

**Role 1: Operator Role** (manages queues only)
- Purpose: Allows operator to create/delete SQS queues
- Permissions: `sqs:CreateQueue` (will need to add code to operator to create asya queues), `sqs:DeleteQueue` (delete empty queue for deleted actor), `sqs:GetQueueUrl`, etc. on `asya-*` queues
- NO IAM permissions

**Role 2: Shared Actor Role** (all actors use this)
- Purpose: Allows actors to send/receive messages
- Permissions: SQS access to receive/send/delete/change default timeout on messages in `asya-*` queues
- Used by ALL actor pods

**Role 3: Gateway Role** (gateway service uses this)
- Purpose: Allows gateway to send messages to actor queues
- Permissions: SQS access to send messages and get queue URLs for `asya-*` queues (minimal permissions)
- Used ONLY by gateway pod

### 3. Component Responsibilities

**Operator:**
- Creates SQS queue: `asya-{actor_name}` when AsyncActor is deployed
- Creates ServiceAccount: `asya-{actor_name}` in actor's namespace with IRSA annotation
- Annotates ServiceAccount with `eks.amazonaws.com/role-arn` pointing to shared actor role
- Sets Deployment's `serviceAccountName: asya-{actor_name}`
- Deletes queue and ServiceAccount when AsyncActor is deleted

**Actor Pods:**
- Use per-actor ServiceAccount (unique per actor)
- ServiceAccount annotated with shared IAM role ARN (IRSA)
- Sidecar uses IAM credentials from IRSA to access SQS

**Gateway Pod:**
- Uses `asya-gateway` ServiceAccount
- ServiceAccount annotated with gateway IAM role ARN (IRSA)
- Gateway uses IAM credentials from IRSA to send messages to actor queues

## Setup Instructions

### Prerequisites

- EKS cluster version 1.24+ (with Pod Identity support)
- AWS CLI access with IAM permissions
- Operator will be installed in namespace: `asya-system` (configurable)

### Step 1: Set Environment Variables

```bash
export CLUSTER_NAME="my-cluster"
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "Cluster: $CLUSTER_NAME"
echo "Region: $AWS_REGION"
echo "Account ID: $AWS_ACCOUNT_ID"
```

### Step 2: Create Operator IAM Role
(add this to asya-operator's README as a prerequisite to installing asya framework)

**Trust policy for operator (EKS Pod Identity):**

```bash
cat > asya-operator-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Service": "pods.eks.amazonaws.com"
    },
    "Action": [
      "sts:AssumeRole",
      "sts:TagSession"
    ],
    "Sid": "AllowEksAuthToAssumeRoleForPodIdentity"
  }]
}
EOF
```

**Create operator role:**

```bash
aws iam create-role \
  --role-name asya-operator \
  --assume-role-policy-document file://asya-operator-trust-policy.json \
  --description "Asya🎭 operator role for SQS queue management"

export OPERATOR_ROLE_ARN=$(aws iam get-role --role-name asya-operator --query 'Role.Arn' --output text)
echo "Operator Role ARN: $OPERATOR_ROLE_ARN"
```

**Attach permissions policy:**

```bash
cat > asya-operator-permissions.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "ManageAsyaQueues",
    "Effect": "Allow",
    "Action": [
      "sqs:DeleteQueue",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:SetQueueAttributes",
      "sqs:TagQueue",
      "sqs:UntagQueue"
    ],
    "Resource": "arn:aws:sqs:*:${AWS_ACCOUNT_ID}:asya-*"
  }]
}
EOF

aws iam put-role-policy \
  --role-name asya-operator \
  --policy-name asya-sqs-queue-management \
  --policy-document file://asya-operator-permissions.json
```

**Create Pod Identity Association for operator:**

```bash
aws eks create-pod-identity-association \
  --cluster-name "$CLUSTER_NAME" \
  --namespace asya-system \
  --service-account asya-operator \
  --role-arn "$OPERATOR_ROLE_ARN"

echo "Pod Identity Association created for operator"
```

### Step 3: Create Shared Actor IAM Role
(also add this to asya-operator's README as a prerequisite to installing asya framework)

**Get OIDC provider ID:**

```bash
OIDC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query "cluster.identity.oidc.issuer" --output text | sed 's|https://oidc.eks.eu-central-1.amazonaws.com/id/||')
echo "OIDC ID: $OIDC_ID"
```

**Trust policy for actors (IRSA - IAM Roles for Service Accounts):**

```bash
cat > asya-actors-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowAssumeWebIdentityForAsyaServiceAccounts",
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/oidc.eks.eu-central-1.amazonaws.com/id/${OIDC_ID}"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringLike": {
        "oidc.eks.eu-central-1.amazonaws.com/id/${OIDC_ID}:sub": "system:serviceaccount:*:asya-*"
      }
    }
  }]
}
EOF
```

**Create shared actor role:**

```bash
aws iam create-role \
  --role-name asya-actor \
  --assume-role-policy-document file://asya-actors-trust-policy.json \
  --description "Shared IAM role for all Asya🎭 actors to access SQS"

export ACTORS_ROLE_ARN=$(aws iam get-role --role-name asya-actor --query 'Role.Arn' --output text)
echo "Actors Role ARN: $ACTORS_ROLE_ARN"
```

**Attach permissions policy:**

```bash
cat > asya-actors-permissions.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SQSAccess",
      "Effect": "Allow",
      "Action": [
        "sqs:ChangeMessageVisibility",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl",
        "sqs:ReceiveMessage",
        "sqs:SendMessage"
      ],
      "Resource": [
        "arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:asya-*",
        "arn:aws:sqs:eu-west-1:984138409301:sqs-client-ingestion-cimt-stg",
        "arn:aws:sqs:eu-west-1:004925411957:sqs-client-ingestion-cimt-prod"
      ]
    },
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:HeadObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::aimc-data-test",
        "arn:aws:s3:::aimc-data-test/*"
      ]
    },
    {
      "Sid": "SecretsManagerAcces",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": ["*"]
    },
    {
      "Sid": "AssumeRoleWebIdentityOIDC",
      "Effect": "Allow",
      "Action": ["sts:AssumeRoleWithWebIdentity"],
      "Resource": ["*"]
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name asya-actor \
  --policy-name asya-actor-policy \
  --policy-document file://asya-actors-permissions.json
```

**Note:** Actors use IRSA (IAM Roles for Service Accounts). Each actor's ServiceAccount will be annotated with `eks.amazonaws.com/role-arn` pointing to this shared role.

### Step 3.5: Create Gateway IAM Role (Optional)

If you plan to deploy the Asya🎭 Gateway (for MCP/API integration), create a separate role with minimal permissions:

**Trust policy for gateway:**

```bash
cat > asya-gateway-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/oidc.eks.eu-central-1.amazonaws.com/id/<OIDC_ID>"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "oidc.eks.eu-central-1.amazonaws.com/id/<OIDC_ID>:sub": "system:serviceaccount:asya-poc:asya-gateway"
      }
    },
    "Sid": "AllowAssumeWebIdentityForAsyaGateway"
  }]
}
EOF
```

Replace `<OIDC_ID>` with your cluster's OIDC provider ID:
```bash
OIDC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query "cluster.identity.oidc.issuer" --output text | sed 's|https://oidc.eks.eu-central-1.amazonaws.com/id/||')
echo "OIDC ID: $OIDC_ID"
```

**Create gateway role:**

```bash
aws iam create-role \
  --role-name asya-gateway \
  --assume-role-policy-document file://asya-gateway-trust-policy.json \
  --description "IAM role for Asya🎭 Gateway to send messages to actor queues"

export GATEWAY_ROLE_ARN=$(aws iam get-role --role-name asya-gateway --query 'Role.Arn' --output text)
echo "Gateway Role ARN: $GATEWAY_ROLE_ARN"
```

**Attach permissions policy (minimal - only send messages):**

```bash
cat > asya-gateway-permissions.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "SQSSendMessage",
    "Effect": "Allow",
    "Action": [
      "sqs:GetQueueUrl",
      "sqs:SendMessage"
    ],
    "Resource": "arn:aws:sqs:*:${AWS_ACCOUNT_ID}:asya-*"
  }]
}
EOF

aws iam put-role-policy \
  --role-name asya-gateway \
  --policy-name asya-gateway-sqs-send \
  --policy-document file://asya-gateway-permissions.json
```

**Configure gateway Helm values:**

```yaml
# gateway-values.yaml
serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::${AWS_ACCOUNT_ID}:role/asya-gateway"
```

### Step 4: Install Operator with IAM Configuration

**Create operator values file:**

```yaml
# operator-values.yaml
serviceAccount:
  create: true
  # Note: EKS Pod Identity does not use annotations
  # Association created via AWS API (see Step 2)

transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
      # Shared role ARN that all actors will use
      actorRoleArn: "arn:aws:iam::123456789012:role/asya-actor"
      visibilityTimeout: 300
      waitTimeSeconds: 20
```

**Install operator:**

```bash
helm install asya-operator deploy/helm-charts/asya-operator \
  --namespace asya-system \
  --create-namespace \
  -f operator-values.yaml
```

**Or using --set:**

```bash
helm install asya-operator deploy/helm-charts/asya-operator \
  --namespace asya-system \
  --create-namespace \
  --set transports.sqs.enabled=true \
  --set transports.sqs.config.region=us-east-1 \
  --set transports.sqs.config.actorRoleArn="$ACTORS_ROLE_ARN"
```

## Implementation Details

### Operator Changes Required

**File: `deploy/helm-charts/asya-operator/values.yaml`**

Add `actorRoleArn` to SQS transport config:

```yaml
transports:
  sqs:
    enabled: false
    # Note: you need to delete hard-coded list of queues to create from operator helm chart
    type: sqs
    config:
      region: us-east-1
      actorRoleArn: ""  # ARN of shared IAM role for actors
      visibilityTimeout: 300
      waitTimeSeconds: 20
```

**File: `src/asya-operator/internal/controller/transport_config.go`**

Add field to SQS config struct:

```go
type SQSTransportConfig struct {
    Region            string `json:"region"`
    ActorRoleArn      string `json:"actorRoleArn"`      // NEW: Shared role ARN
    VisibilityTimeout int32  `json:"visibilityTimeout"`
    WaitTimeSeconds   int32  `json:"waitTimeSeconds"`
}
```

**File: `src/asya-operator/internal/controller/asya_controller.go`**

Add new reconciliation functions:

```go
// In Reconcile(), before reconcileWorkload:
if asya.Spec.Transport == "sqs" {
    if err := r.reconcileSQSQueue(ctx, asya); err != nil {
        return ctrl.Result{}, err
    }
    if err := r.reconcileServiceAccount(ctx, asya); err != nil {
        return ctrl.Result{}, err
    }
}

// New function: Create SQS queue
func (r *AsyncActorReconciler) reconcileSQSQueue(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
    // Get SQS transport config
    transport, err := r.TransportRegistry.GetTransport("sqs")
    if err != nil {
        return err
    }

    sqsConfig := transport.Config.(SQSTransportConfig)
    queueName := fmt.Sprintf("asya-%s", asya.Name)

    // Create AWS SQS client using operator's IRSA credentials
    cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(sqsConfig.Region))
    if err != nil {
        return fmt.Errorf("failed to load AWS config: %w", err)
    }

    sqsClient := sqs.NewFromConfig(cfg)

    // CreateQueue is idempotent - safe to call on existing queues
    _, err = sqsClient.CreateQueue(ctx, &sqs.CreateQueueInput{
        QueueName: aws.String(queueName),
        Attributes: map[string]string{
            "VisibilityTimeout":       fmt.Sprintf("%d", sqsConfig.VisibilityTimeout),
            "MessageRetentionPeriod":  "345600", // 4 days
        },
        Tags: map[string]string{
            "asya.sh/actor":     asya.Name,
            "asya.sh/namespace": asya.Namespace,
        },
    })

    if err != nil {
        return fmt.Errorf("failed to create SQS queue %s: %w", queueName, err)
    }

    return nil
}

// New function: Create per-actor ServiceAccount and Pod Identity Association
func (r *AsyncActorReconciler) reconcileServiceAccount(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
    // Get transport config for actor role ARN
    transport, err := r.TransportRegistry.GetTransport("sqs")
    if err != nil {
        return err
    }

    sqsConfig := transport.Config.(SQSTransportConfig)

    if sqsConfig.ActorRoleArn == "" {
        return fmt.Errorf("actorRoleArn not configured in SQS transport")
    }

    saName := fmt.Sprintf("asya-%s", asya.Name)

    // Create ServiceAccount
    sa := &corev1.ServiceAccount{
        ObjectMeta: metav1.ObjectMeta{
            Name:      saName,
            Namespace: asya.Namespace,
        },
    }

    result, err := controllerutil.CreateOrUpdate(ctx, r.Client, sa, func() error {
        // Set owner reference for cleanup
        if err := controllerutil.SetControllerReference(asya, sa, r.Scheme); err != nil {
            return err
        }
        return nil
    })

    if err != nil {
        return fmt.Errorf("failed to reconcile ServiceAccount: %w", err)
    }

    logger := log.FromContext(ctx)
    logger.Info("ServiceAccount reconciled", "result", result, "name", saName)

    // Create Pod Identity Association
    if err := r.reconcilePodIdentityAssociation(ctx, asya, sqsConfig.ActorRoleArn); err != nil {
        return fmt.Errorf("failed to reconcile Pod Identity Association: %w", err)
    }

    return nil
}

// New function: Create Pod Identity Association
func (r *AsyncActorReconciler) reconcilePodIdentityAssociation(ctx context.Context, asya *asyav1alpha1.AsyncActor, roleArn string) error {
    transport, err := r.TransportRegistry.GetTransport("sqs")
    if err != nil {
        return err
    }

    sqsConfig := transport.Config.(SQSTransportConfig)
    saName := fmt.Sprintf("asya-%s", asya.Name)

    // Load AWS config
    cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(sqsConfig.Region))
    if err != nil {
        return fmt.Errorf("failed to load AWS config: %w", err)
    }

    eksClient := eks.NewFromConfig(cfg)

    // Check if association already exists
    listResp, err := eksClient.ListPodIdentityAssociations(ctx, &eks.ListPodIdentityAssociationsInput{
        ClusterName:    aws.String(r.ClusterName),
        Namespace:      aws.String(asya.Namespace),
        ServiceAccount: aws.String(saName),
    })

    if err != nil {
        return fmt.Errorf("failed to list Pod Identity Associations: %w", err)
    }

    // If association exists, we're done (idempotent)
    if len(listResp.Associations) > 0 {
        logger := log.FromContext(ctx)
        logger.Info("Pod Identity Association already exists", "serviceAccount", saName)
        return nil
    }

    // Create new association
    _, err = eksClient.CreatePodIdentityAssociation(ctx, &eks.CreatePodIdentityAssociationInput{
        ClusterName:    aws.String(r.ClusterName),
        Namespace:      aws.String(asya.Namespace),
        ServiceAccount: aws.String(saName),
        RoleArn:        aws.String(roleArn),
        Tags: map[string]string{
            "asya.sh/actor":     asya.Name,
            "asya.sh/namespace": asya.Namespace,
        },
    })

    if err != nil {
        return fmt.Errorf("failed to create Pod Identity Association: %w", err)
    }

    logger := log.FromContext(ctx)
    logger.Info("Pod Identity Association created", "serviceAccount", saName, "roleArn", roleArn)

    return nil
}
```

**File: `src/asya-operator/internal/controller/asya_controller.go` (injectSidecar)**

Update `reconcileDeployment` to set serviceAccountName:

```go
func (r *AsyncActorReconciler) reconcileDeployment(ctx context.Context, asya *asyav1alpha1.AsyncActor, podTemplate corev1.PodTemplateSpec) error {
    // ... existing code ...

    result, err := controllerutil.CreateOrUpdate(ctx, r.Client, deployment, func() error {
        // ... existing code ...

        // Set ServiceAccount for SQS transport
        if asya.Spec.Transport == "sqs" {
            podTemplate.Spec.ServiceAccountName = fmt.Sprintf("asya-%s", asya.Name)
        }

        deployment.Spec.Template = podTemplate

        return nil
    })

    // ... rest of function ...
}
```

**File: `src/asya-operator/internal/controller/asya_controller.go` (reconcileDelete)**

Add cleanup for SQS resources:

TODO: I think it's worth of adding a check that the queue is not empty - otherwise report error and not delete - to avoid data loss

```go
func (r *AsyncActorReconciler) reconcileDelete(ctx context.Context, asya *asyav1alpha1.AsyncActor) (ctrl.Result, error) {
    logger := log.FromContext(ctx)
    logger.Info("Deleting AsyncActor", "name", asya.Name)

    // Delete SQS resources if using SQS transport
    if asya.Spec.Transport == "sqs" {
        // Delete Pod Identity Association
        if err := r.deletePodIdentityAssociation(ctx, asya); err != nil {
            logger.Error(err, "Failed to delete Pod Identity Association, continuing with deletion")
        }

        // Delete SQS queue
        if err := r.deleteSQSQueue(ctx, asya); err != nil {
            logger.Error(err, "Failed to delete SQS queue, continuing with deletion")
        }
    }

    // Remove finalizer (ServiceAccount will be cleaned up by owner reference)
    controllerutil.RemoveFinalizer(asya, actorFinalizer)
    if err := r.Update(ctx, asya); err != nil {
        return ctrl.Result{}, err
    }

    return ctrl.Result{}, nil
}

func (r *AsyncActorReconciler) deleteSQSQueue(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
    transport, err := r.TransportRegistry.GetTransport("sqs")
    if err != nil {
        return err
    }

    sqsConfig := transport.Config.(SQSTransportConfig)
    queueName := fmt.Sprintf("asya-%s", asya.Name)

    cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(sqsConfig.Region))
    if err != nil {
        return fmt.Errorf("failed to load AWS config: %w", err)
    }

    sqsClient := sqs.NewFromConfig(cfg)

    // Get queue URL first
    urlResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
        QueueName: aws.String(queueName),
    })
    if err != nil {
        // Queue might not exist, that's okay
        return nil
    }

    // Delete queue
    _, err = sqsClient.DeleteQueue(ctx, &sqs.DeleteQueueInput{
        QueueUrl: urlResult.QueueUrl,
    })

    return err
}

func (r *AsyncActorReconciler) deletePodIdentityAssociation(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
    transport, err := r.TransportRegistry.GetTransport("sqs")
    if err != nil {
        return err
    }

    sqsConfig := transport.Config.(SQSTransportConfig)
    saName := fmt.Sprintf("asya-%s", asya.Name)

    // Load AWS config
    cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(sqsConfig.Region))
    if err != nil {
        return fmt.Errorf("failed to load AWS config: %w", err)
    }

    eksClient := eks.NewFromConfig(cfg)

    // List associations to find the ID
    listResp, err := eksClient.ListPodIdentityAssociations(ctx, &eks.ListPodIdentityAssociationsInput{
        ClusterName:    aws.String(r.ClusterName),
        Namespace:      aws.String(asya.Namespace),
        ServiceAccount: aws.String(saName),
    })

    if err != nil {
        return fmt.Errorf("failed to list Pod Identity Associations: %w", err)
    }

    // Delete all matching associations
    for _, assoc := range listResp.Associations {
        _, err := eksClient.DeletePodIdentityAssociation(ctx, &eks.DeletePodIdentityAssociationInput{
            ClusterName:   aws.String(r.ClusterName),
            AssociationId: assoc.AssociationId,
        })
        if err != nil {
            return fmt.Errorf("failed to delete Pod Identity Association %s: %w", *assoc.AssociationId, err)
        }

        logger := log.FromContext(ctx)
        logger.Info("Pod Identity Association deleted", "id", *assoc.AssociationId)
    }

    return nil
}
```

**File: `src/asya-operator/internal/controller/asya_controller.go` (RBAC)**

Add ServiceAccount permissions:

```go
// +kubebuilder:rbac:groups="",resources=serviceaccounts,verbs=get;list;watch;create;update;patch;delete
```

### RBAC Requirements

Operator needs permissions to manage ServiceAccounts:

```yaml
# Already covered by kubebuilder RBAC markers, but for reference:
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: asya-operator
rules:
- apiGroups: [""]
  resources: ["serviceaccounts"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

## User Workflow

### Deploy an Actor with SQS Transport

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: ml-model
  namespace: production
spec:
  transport: sqs
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: "my_module.process"
```

**What happens automatically:**

1. Operator validates SQS transport is enabled
2. Operator creates SQS queue: `asya-ml-model`
3. Operator creates ServiceAccount: `asya-ml-model` in namespace `production`
4. Operator creates Pod Identity Association linking ServiceAccount to shared role
5. Operator creates Deployment with `serviceAccountName: asya-ml-model`
6. Pod starts, EKS Pod Identity provides AWS credentials from shared role
7. Sidecar connects to SQS using Pod Identity credentials

### Verify Setup

```bash
# Check queue created
aws sqs list-queues --queue-name-prefix asya-

# Check ServiceAccount
kubectl get serviceaccount asya-ml-model -n production -o yaml

# Check Pod Identity Association
aws eks list-pod-identity-associations \
  --cluster-name "$CLUSTER_NAME" \
  --namespace production \
  --service-account asya-ml-model

# Check pod has correct SA
kubectl get pod -n production -l asya.sh/asya=ml-model -o jsonpath='{.items[0].spec.serviceAccountName}'

# Check Pod Identity credentials working
kubectl exec -n production deployment/ml-model -c asya-sidecar -- \
  env | grep AWS_
```

## Comparison with RabbitMQ

| Aspect | RabbitMQ | SQS |
|--------|----------|-----|
| Queue Creation | Sidecar auto-creates via `QueueDeclare` | Operator creates via AWS API |
| Authentication | Username/password (K8s Secret) | EKS Pod Identity |
| Per-Actor Isolation | Queue-level (same user) | Queue-level (same IAM role) |
| External Setup | Deploy RabbitMQ server | Create 2 IAM roles + Pod Identity Associations |
| Operator Permissions | None | SQS queue management + EKS Pod Identity management |

## Future Considerations

### Potential Enhancements

1. **Per-Actor IAM Roles:**
   - Operator creates IAM roles dynamically
   - Better isolation (actor can only read its own queue)
   - Requires operator to have `iam:CreateRole` permissions
   - More complex, see initial discussion for details

2. **Message Signing:**
   - Cryptographic envelope signing
   - Prevents message poisoning attacks
   - Independent of IAM boundaries

3. **Queue Policy:**
   - Add SQS queue policies for additional access control
   - Can restrict which roles can send to specific queues

4. **Cross-Account Support:**
   - Support actors in different AWS accounts
   - Requires cross-account IAM trust relationships

## Troubleshooting

### Common Issues

**Pod cannot assume IAM role:**
```
Error: failed to retrieve credentials
```

Solutions:
- Verify EKS cluster version is 1.24+ (Pod Identity support)
- Check Pod Identity Association exists for the ServiceAccount
- Verify IAM role trust policy allows `pods.eks.amazonaws.com`
- Check pod is using correct ServiceAccount
- List associations: `aws eks list-pod-identity-associations --cluster-name <name>`

**Operator cannot create queues:**
```
Error: AccessDenied: User is not authorized to perform sqs:CreateQueue
```

Solutions:
- Verify operator Pod Identity Association exists
- Check operator IAM role has SQS permissions
- Verify queue name uses `asya-` prefix (if policy is scoped)
- Check operator pod has credentials: `kubectl exec -n asya-system deployment/asya-operator -- env | grep AWS_`

**Actor cannot send/receive messages:**
```
Error: AccessDenied: Access to the resource is denied
```

Solutions:
- Verify actor Pod Identity Association exists
- Check shared actor role has permissions on `asya-*` queues
- Verify queue exists: `aws sqs get-queue-url --queue-name asya-{actor_name}`
- List associations: `aws eks list-pod-identity-associations --cluster-name <name> --namespace <ns>`

## Security Best Practices

1. **Least Privilege:** Scope operator role to `asya-*` queues only
2. **Application-Layer Security:** Implement message validation, schema enforcement
3. **Monitoring:** Track SQS API calls via CloudTrail
4. **Alerts:** Alert on unusual queue access patterns
5. **Network Policies:** Use K8s NetworkPolicies to restrict pod-to-pod communication
6. **Encryption:** Enable SQS encryption at rest (KMS)
7. **Audit:** Regular IAM role reviews, queue access audits

## References

- [EKS Pod Identity Documentation](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [EKS IRSA Documentation](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html) (older method)
- [SQS API Reference](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/)
- [AWS IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
