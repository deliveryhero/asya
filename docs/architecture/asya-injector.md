# Sidecar Injector Webhook

## Overview

The asya-injector is a Kubernetes mutating admission webhook that automatically injects the asya-sidecar container and related configuration into actor pods. It runs as a standalone service and integrates with the Crossplane-based AsyncActor deployment model.

## Architecture

```
Pod CREATE Request
         │
         ▼
    API Server
         │
         ▼
Mutating Webhook (asya-injector)
         │
    ┌────┼─────────────┐
    │    ▼             ▼
    │  Query      Perform
    │  AsyncActor  Injection
    │  XR         (JSON Patch)
    │    │             │
    │    ▼             ▼
    │  Extract    Add Sidecar
    │  Config     Add Volumes
    │             Modify Runtime
    │
    ▼
JSON Patch Response
         │
         ▼
    API Server (applies patch)
```

## How It Works

**Trigger**: Pod with labels `asya.sh/inject=true` and `asya.sh/actor={name}`

**Webhook flow**:

1. **Admission request received** - API server sends Pod CREATE request
2. **Label check** - Webhook checks for `asya.sh/inject=true` label
3. **Actor name extraction** - Reads actor name from `asya.sh/actor` label
4. **AsyncActor query** - Queries AsyncActor XR in pod's namespace via dynamic client
5. **Readiness check** - Validates AsyncActor has `Ready=True` or `Synced=True` condition
6. **Config extraction** - Extracts transport, queueURL, region, sidecar overrides from AsyncActor spec/status
7. **Injection** - Mutates pod to add sidecar, volumes, and modify runtime container
8. **JSON patch** - Creates RFC 6902 JSON Patch describing the mutation
9. **Response** - Returns patch to API server, which applies it before persisting pod

**Rejection scenarios**:
- Pod missing `asya.sh/actor` label
- AsyncActor not found in namespace
- AsyncActor infrastructure not ready (Crossplane still provisioning)
- Runtime container `asya-runtime` not found in pod spec

## What Gets Injected

### Sidecar Container

The webhook adds `asya-sidecar` container to the pod:

```yaml
containers:
  - name: asya-sidecar
    image: ghcr.io/deliveryhero/asya-sidecar:latest
    imagePullPolicy: IfNotPresent
    env:
      - name: ASYA_LOG_LEVEL
        value: info
      - name: ASYA_SOCKET_DIR
        value: /var/run/asya
      - name: ASYA_ACTOR_NAME
        value: text-processor
      - name: ASYA_NAMESPACE
        value: asya-e2e
      - name: ASYA_ACTOR_SINK
        value: x-sink
      - name: ASYA_ACTOR_SUMP
        value: x-sump
      - name: ASYA_TRANSPORT
        value: sqs
      - name: ASYA_AWS_REGION
        value: us-east-1
      - name: ASYA_QUEUE_URL
        value: https://sqs.us-east-1.amazonaws.com/.../asya-asya-e2e-text-processor
      - name: ASYA_IS_END_ACTOR
        value: "true"  # Only for x-sink and x-sump actors
    envFrom:
      - secretRef:
          name: aws-creds  # Optional, only if config.awsCredsSecret set
    volumeMounts:
      - name: socket-dir
        mountPath: /var/run/asya
      - name: tmp
        mountPath: /tmp
```

**Sidecar image override**:
- Global: `config.sidecarImage` (injector Helm values)
- Per-actor: `spec.sidecar.image` (AsyncActor spec)

**Additional sidecar env vars**:
- Custom env from `spec.sidecar.env` merged into sidecar container
- Gateway URL from `config.gatewayURL` (if configured)
- SQS endpoint override from `config.sqsEndpoint` (for LocalStack)

### Environment Variables

**Transport-specific** (SQS):
- `ASYA_AWS_REGION`: From `spec.region` or extracted AsyncActor config
- `ASYA_QUEUE_URL`: From AsyncActor status (set by Crossplane)
- `ASYA_SQS_ENDPOINT`: Custom endpoint for LocalStack (optional)

**End actor detection**:
- `ASYA_IS_END_ACTOR=true`: Automatically set for `x-sink` and `x-sump` actors

### Volumes

The webhook adds three volumes to the pod:

```yaml
volumes:
  # Unix socket for sidecar-runtime communication
  - name: socket-dir
    emptyDir: {}

  # Temporary directory
  - name: tmp
    emptyDir: {}

  # Runtime script ConfigMap
  - name: asya-runtime
    configMap:
      name: asya-runtime
      defaultMode: 0755
```

**ConfigMap source**: The `asya-runtime` ConfigMap must exist in the actor's namespace, containing `asya_runtime.py`. This is typically created by the Crossplane composition or manually deployed.

## Runtime Container Modification

The webhook modifies the existing `asya-runtime` container in the pod:

### Command Override

```yaml
containers:
  - name: asya-runtime
    image: my-handler:latest
    command:
      - python3  # Or from ASYA_PYTHONEXECUTABLE env var
      - /opt/asya/asya_runtime.py
```

**Python executable detection**:
- Checks for `ASYA_PYTHONEXECUTABLE` env var in runtime container
- Falls back to `python3` if not set
- Allows custom Python paths (e.g., `/opt/conda/bin/python`)

### Environment Variables

Added to runtime container:

```yaml
env:
  - name: ASYA_SOCKET_DIR
    value: /var/run/asya
  - name: ASYA_ENABLE_VALIDATION
    value: "false"  # Only for x-sink and x-sump actors
```

**Validation disable**: End actors (`x-sink`, `x-sump`) have validation disabled to allow arbitrary payloads without route validation.

### Volume Mounts

Added to runtime container:

```yaml
volumeMounts:
  # Socket directory for sidecar communication
  - name: socket-dir
    mountPath: /var/run/asya

  # Temporary directory
  - name: tmp
    mountPath: /tmp

  # Runtime script
  - name: asya-runtime
    mountPath: /opt/asya/asya_runtime.py
    subPath: asya_runtime.py
    readOnly: true
```

### Probes

The webhook adds startup, liveness, and readiness probes to the runtime container (if not already defined):

**Probe command**:
```bash
sh -c "test -S /var/run/asya/asya-runtime.sock && test -f /var/run/asya/runtime-ready"
```

**Probe configuration**:

- **Startup probe**:
  - Initial delay: 3 seconds
  - Period: 2 seconds
  - Timeout: 3 seconds
  - Failure threshold: 150 (allows 5 minutes for startup)

- **Liveness probe**:
  - Initial delay: 0 seconds
  - Period: 30 seconds
  - Timeout: 5 seconds
  - Failure threshold: 3

- **Readiness probe**:
  - Initial delay: 0 seconds
  - Period: 10 seconds
  - Timeout: 3 seconds
  - Failure threshold: 3

**Probe logic**: Checks for Unix socket existence and runtime ready marker file, ensuring both runtime server and sidecar are operational.

## AsyncActor Readiness Gating

The webhook queries the AsyncActor XR to validate infrastructure readiness before injection.

**Readiness conditions checked**:
- ✅ `Ready=True`: Crossplane standard Ready condition
- ✅ `Synced=True`: Crossplane Synced condition (alternative)

**Why gating matters**:
- Prevents pod creation before queue exists
- Ensures sidecar has valid queue URL
- Avoids pod CrashLoopBackOff during infrastructure provisioning

**Failure behavior**: If AsyncActor not ready, webhook rejects pod creation with error:
```
failed to get AsyncActor text-processor: AsyncActor text-processor is not ready (infrastructure provisioning may be in progress)
```

Deployment controller retries pod creation until AsyncActor becomes ready.

## Configuration via Helm Values

```yaml
config:
  logLevel: "info"

  # Sidecar image to inject
  sidecarImage: "ghcr.io/deliveryhero/asya-sidecar:latest"
  sidecarImagePullPolicy: "IfNotPresent"

  # Runtime ConfigMap name
  runtimeConfigMap: "asya-runtime"

  # Socket directory path
  socketDir: "/var/run/asya"

  # Runtime script mount path
  runtimeMountPath: "/opt/asya/asya_runtime.py"

  # Gateway URL for progress reporting
  gatewayURL: ""

  # Custom SQS endpoint (for LocalStack)
  sqsEndpoint: ""

  # AWS credentials secret name (for non-IRSA environments)
  awsCredsSecret: ""
```

**Per-actor overrides**: AsyncActor spec can override:
- `spec.sidecar.image`: Custom sidecar image
- `spec.sidecar.imagePullPolicy`: Custom pull policy
- `spec.sidecar.env`: Additional environment variables

## Webhook Configuration

```yaml
webhook:
  port: 8443

  # Namespaces to target for injection
  namespaceSelector:
    matchExpressions:
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values:
          - kube-system
          - kube-public
          - kube-node-lease
          - asya-system

  # Pod label that triggers injection
  objectSelector:
    matchLabels:
      asya.sh/inject: "true"

  # Failure policy
  failurePolicy: Fail

  # Timeout for webhook calls
  timeoutSeconds: 10
```

**Failure policy**: `Fail` ensures pods without sidecar are never created (safer than `Ignore`).

**Namespace exclusions**: System namespaces excluded to prevent accidental injection into cluster components.

## cert-manager TLS Certificate Management

The webhook requires TLS certificates for secure communication with the API server. cert-manager automates certificate lifecycle.

**Certificate configuration**:

```yaml
certManager:
  enabled: true
  duration: 8760h  # 1 year
  renewBefore: 720h  # 30 days
  issuer:
    create: true  # Creates self-signed issuer
    name: ""
    kind: Issuer
```

**How it works**:
1. Helm chart creates `Issuer` (self-signed) in injector namespace
2. Helm chart creates `Certificate` resource
3. cert-manager generates TLS certificate and stores in Secret
4. Injector deployment mounts Secret as TLS cert/key
5. MutatingWebhookConfiguration references CA bundle
6. cert-manager auto-renews before expiration

**Manual certificate**: If `certManager.enabled=false`, provide your own TLS secret and configure webhook CA bundle manually.

## Deployment

**Prerequisites**:
- Kubernetes 1.19+
- cert-manager installed
- AsyncActor XRD installed (for querying AsyncActor resources)

**Installation**:

```bash
# Install injector webhook
helm install asya-injector deploy/helm-charts/asya-injector/ \
  --namespace asya-system --create-namespace \
  --set config.sidecarImage=ghcr.io/deliveryhero/asya-sidecar:latest \
  --set config.gatewayURL=http://asya-gateway.asya-system.svc.cluster.local
```

**Verification**:

```bash
# Check webhook is running
kubectl get pods -n asya-system -l app.kubernetes.io/name=asya-injector

# Check webhook configuration
kubectl get mutatingwebhookconfigurations asya-injector

# Check certificate
kubectl get certificate -n asya-system asya-injector-webhook-cert
```

## Example Pod Mutation

**Before injection** (pod created by Crossplane Deployment):

```yaml
apiVersion: v1
kind: Pod
metadata:
  labels:
    asya.sh/inject: "true"
    asya.sh/actor: text-processor
spec:
  containers:
    - name: asya-runtime
      image: my-handler:v1
      env:
        - name: ASYA_HANDLER
          value: processor.TextProcessor.process
```

**After injection** (pod created by API server with webhook patch):

```yaml
apiVersion: v1
kind: Pod
metadata:
  labels:
    asya.sh/inject: "true"
    asya.sh/actor: text-processor
spec:
  terminationGracePeriodSeconds: 30
  containers:
    - name: asya-runtime
      image: my-handler:v1
      command:
        - python3
        - /opt/asya/asya_runtime.py
      env:
        - name: ASYA_HANDLER
          value: processor.TextProcessor.process
        - name: ASYA_SOCKET_DIR
          value: /var/run/asya
      volumeMounts:
        - name: socket-dir
          mountPath: /var/run/asya
        - name: tmp
          mountPath: /tmp
        - name: asya-runtime
          mountPath: /opt/asya/asya_runtime.py
          subPath: asya_runtime.py
          readOnly: true
      startupProbe:
        exec:
          command:
            - sh
            - -c
            - test -S /var/run/asya/asya-runtime.sock && test -f /var/run/asya/runtime-ready
        initialDelaySeconds: 3
        periodSeconds: 2
        timeoutSeconds: 3
        failureThreshold: 150
      livenessProbe:
        exec:
          command:
            - sh
            - -c
            - test -S /var/run/asya/asya-runtime.sock && test -f /var/run/asya/runtime-ready
        periodSeconds: 30
        timeoutSeconds: 5
        failureThreshold: 3
      readinessProbe:
        exec:
          command:
            - sh
            - -c
            - test -S /var/run/asya/asya-runtime.sock && test -f /var/run/asya/runtime-ready
        periodSeconds: 10
        timeoutSeconds: 3
        failureThreshold: 3

    - name: asya-sidecar
      image: ghcr.io/deliveryhero/asya-sidecar:latest
      imagePullPolicy: IfNotPresent
      env:
        - name: ASYA_LOG_LEVEL
          value: info
        - name: ASYA_SOCKET_DIR
          value: /var/run/asya
        - name: ASYA_ACTOR_NAME
          value: text-processor
        - name: ASYA_NAMESPACE
          value: asya-e2e
        - name: ASYA_ACTOR_SINK
          value: x-sink
        - name: ASYA_ACTOR_SUMP
          value: x-sump
        - name: ASYA_TRANSPORT
          value: sqs
        - name: ASYA_AWS_REGION
          value: us-east-1
        - name: ASYA_QUEUE_URL
          value: https://sqs.us-east-1.amazonaws.com/.../asya-asya-e2e-text-processor
      volumeMounts:
        - name: socket-dir
          mountPath: /var/run/asya
        - name: tmp
          mountPath: /tmp

  volumes:
    - name: socket-dir
      emptyDir: {}
    - name: tmp
      emptyDir: {}
    - name: asya-runtime
      configMap:
        name: asya-runtime
        defaultMode: 0755
```

## Observability

**Logs**:
```bash
# View injector logs
kubectl logs -n asya-system deployment/asya-injector

# Watch injection events
kubectl logs -n asya-system deployment/asya-injector -f | grep "Injecting sidecar"
```

**Metrics**: The injector exposes Prometheus metrics (if configured):
- `asya_injector_requests_total` - Total webhook requests
- `asya_injector_errors_total` - Failed injections
- `asya_injector_duration_seconds` - Injection duration

**Debugging injection failures**:
1. Check injector logs for errors
2. Verify AsyncActor exists and is Ready
3. Verify pod has `asya.sh/inject=true` and `asya.sh/actor` labels
4. Check runtime ConfigMap exists in namespace
5. Verify webhook certificate is valid
