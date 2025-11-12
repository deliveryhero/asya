# KEDA Integration

## Overview

Asya🎭 uses KEDA (Kubernetes Event-Driven Autoscaling) to provide event-driven autoscaling for AsyncActor workloads. The operator automatically creates and manages KEDA ScaledObjects based on AsyncActor CRD configurations.

## ScaledObject Reconciliation

### Ownership Management

The operator uses Kubernetes owner references to manage ScaledObject lifecycle. When reconciling a ScaledObject, the operator follows this logic:

#### Scenario 1: ScaledObject Doesn't Exist

When no ScaledObject exists for an AsyncActor:
1. Operator builds KEDA triggers based on transport type (RabbitMQ, SQS)
2. Creates ScaledObject with owner reference pointing to the AsyncActor
3. Sets `asya.sh/source-generation` annotation to track AsyncActor generation

#### Scenario 2: ScaledObject Exists with Correct Ownership

When a ScaledObject exists and has the correct owner reference (matching AsyncActor UID):
1. Operator checks `asya.sh/source-generation` annotation
2. If generation matches current AsyncActor generation → skip reconciliation
3. If generation differs → rebuild triggers and update ScaledObject

#### Scenario 3: ScaledObject Exists with Incorrect Ownership

**Problem**: Old ScaledObjects from previous deployments can block the operator from managing scaling. This happens when:
- AsyncActor was deleted and recreated with same name (different UID)
- ScaledObject was manually created without proper owner reference
- Old deployment left orphaned ScaledObjects

**Solution** (src/asya-operator/internal/controller/keda.go:83-109):
1. Operator detects ScaledObject exists but owner reference doesn't match current AsyncActor UID
2. Deletes the old ScaledObject to clear the conflict
3. Logs the action: `"Found existing ScaledObject with incorrect ownership, deleting to recreate"`
4. Allows CreateOrUpdate to recreate ScaledObject with correct ownership

This prevents KEDA admission webhook from rejecting ownership changes and ensures the operator can always manage scaling.

### Generation Tracking

The operator tracks AsyncActor generation using the `asya.sh/source-generation` annotation on ScaledObjects. This optimization prevents unnecessary trigger rebuilding when:
- AsyncActor spec hasn't changed (generation unchanged)
- ScaledObject already matches desired configuration

## Transport-Specific Triggers

### RabbitMQ

KEDA trigger metadata:
- `queueName`: `asya-{actor-name}`
- `mode`: `QueueLength`
- `value`: Queue length threshold (default: 5)
- `protocol`: `amqp`
- `host`: Connection string with or without credentials

Authentication:
- Inline credentials: `amqp://username@host:port`
- TriggerAuthentication: Used when `passwordSecretRef` is configured

### SQS

KEDA trigger metadata:
- `queueName` or `queueURL`: Queue identifier
- `queueLength`: Queue length threshold (default: 5)
- `awsRegion`: AWS region
- `awsEndpoint`: Custom endpoint (LocalStack, etc.)

Authentication:
- Pod identity (IRSA): Default when no credentials configured
- TriggerAuthentication: Used when `credentials.accessKeyIdSecretRef` or `secretAccessKeySecretRef` configured

## HPA Behavior

The operator configures KEDA ScaledObjects with HPA behavior to prevent scaling thrashing:

### Scale Down
- Stabilization window: 300 seconds
- Policy: Remove max 1 pod per 60 seconds
- Select policy: Max (use maximum value from policies)

### Scale Up
- Stabilization window: 0 seconds (immediate scale up)
- Policies:
  - Add max 10 pods per 60 seconds
  - Add max 100% (double) pods per 60 seconds
- Select policy: Max (use maximum value from policies)

## Error Handling

### KEDA CRDs Not Installed
- Error: `"KEDA CRDs not installed"`
- Condition: `ScalingReady=False`, Reason: `ReconcileError`
- Resolution: Install KEDA before enabling scaling

### Transport Configuration Invalid
- Error: `"failed to build KEDA triggers: {details}"`
- Condition: `ScalingReady=False`, Reason: `ReconcileError`
- Resolution: Fix transport configuration in operator values

### Ownership Conflict
- Automatically resolved by deleting old ScaledObject
- Logs: `"Found existing ScaledObject with incorrect ownership, deleting to recreate"`
- No manual intervention required

## Status Updates

After successful ScaledObject reconciliation:
1. `asya.Status.ScaledObjectRef` set to ScaledObject name/namespace
2. `ScalingReady` condition set to `True`, Reason: `ScaledObjectCreated`
3. Operator fetches desired replicas from HPA and updates `asya.Status.DesiredReplicas`

## Testing

See `src/asya-operator/internal/controller/keda_test.go` for comprehensive tests covering:
- Trigger building for different transports
- ScaledObject reconciliation with ownership handling
- HPA behavior configuration
- Generation tracking optimization
