# Configuring State Proxy

This guide covers state proxy configuration at the infrastructure level — how to enable persistent state for actors, configure storage backends, and manage credentials.

## Overview

The state proxy gives actors persistent state access via standard file operations. Handlers read and write to paths like `/state/checkpoints/model.pt`, and the runtime transparently forwards those operations to a storage backend (S3, Redis, NATS KV, GCS).

From an infrastructure perspective, enabling state proxy involves:

1. Adding `stateProxy` entries to the AsyncActor spec
2. Configuring storage backend credentials (IAM roles, secrets)
3. Choosing a connector image (S3, Redis, etc.)
4. Setting consistency guarantees (LWW vs CAS)

The Crossplane composition renders connector sidecar containers into the actor pod based on the `stateProxy` configuration.

## Enabling State Proxy

State proxy is configured in the AsyncActor spec under `spec.stateProxy`. Each entry defines a mount with a unique name, a path in the runtime container, and a connector configuration.

### Basic Example

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: ml-inference
  namespace: prod
spec:
  actor: ml-inference
  image: my-org/ml-inference:latest
  handler: inference.handle

  stateProxy:
  - name: weights
    mount:
      path: /state/weights
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
      env:
      - name: STATE_BUCKET
        value: ml-model-weights
      - name: AWS_REGION
        value: us-east-1
```

**What happens**:

1. Crossplane adds a `state-sockets` emptyDir volume to the pod
2. Crossplane adds a `asya-state-proxy-weights` sidecar container with the specified image and env vars
3. Crossplane sets `ASYA_STATE_PROXY_MOUNTS=weights:/state/weights:write=buffered` on the runtime container
4. Runtime patches Python builtins to intercept file operations on `/state/weights/*`
5. Handler code can use `open("/state/weights/model.pt", "rb")` and the runtime forwards it to the connector over Unix socket

## Storage Backends

### S3 / MinIO

Three S3 connector variants are available:

| Image suffix | Write mode | Consistency | Use case |
|--------------|------------|-------------|----------|
| `s3-buffered-lww` | buffered | Last-Write-Wins | Single-writer state (checkpoints, configs) |
| `s3-buffered-cas` | buffered | Check-And-Set (ETag) | Multi-writer state with conflict detection |
| `s3-passthrough` | passthrough | Last-Write-Wins | Large files (streaming writes) |

#### s3-buffered-lww

**Consistency**: Last-Write-Wins — no conflict detection. Writes always overwrite.

**Configuration**:

```yaml
stateProxy:
- name: checkpoints
  mount:
    path: /state/checkpoints
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
    env:
    - name: STATE_BUCKET
      value: ml-checkpoints
    - name: STATE_PREFIX
      value: inference-v2/  # Optional: key prefix within bucket
    - name: AWS_REGION
      value: us-east-1
    - name: AWS_ENDPOINT_URL  # Optional: for MinIO or LocalStack
      value: http://minio.default.svc.cluster.local:9000
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 100m
        memory: 128Mi
```

**When to use**: State written by a single actor instance (model weights, checkpoints, configs).

#### s3-buffered-cas

**Consistency**: Check-And-Set with ETag-based conflict detection. Write fails if the object was modified since the last read.

**Configuration**:

```yaml
stateProxy:
- name: shared-state
  mount:
    path: /state/shared
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-cas:v1.0.0
    env:
    - name: STATE_BUCKET
      value: shared-state
    - name: AWS_REGION
      value: us-east-1
```

**When to use**: State written by multiple actor replicas where conflicts must be detected (e.g., distributed locking, counters).

**Error handling**: Handler code receives `FileExistsError` on CAS conflict — application must retry or resolve the conflict.

#### s3-passthrough

**Consistency**: Last-Write-Wins — no conflict detection.

**Write mode**: Streaming — each `write()` call sends an HTTP chunk. No buffering in memory.

**Configuration**:

```yaml
stateProxy:
- name: large-files
  mount:
    path: /state/large
  writeMode: passthrough  # Required for passthrough connector
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-passthrough:v1.0.0
    env:
    - name: STATE_BUCKET
      value: large-files
    - name: AWS_REGION
      value: us-east-1
```

**When to use**: Writing large files (>100 MB) where buffering in memory is not feasible.

**Limitations**: Does not support `seek()` or `tell()` on write file handles.

### Redis

**Consistency**: Check-And-Set with WATCH/MULTI/EXEC optimistic locking.

**Configuration**:

```yaml
stateProxy:
- name: cache
  mount:
    path: /state/cache
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-redis-buffered-cas:v1.0.0
    env:
    - name: REDIS_URL
      value: redis://redis.default.svc.cluster.local:6379/0
    - name: STATE_PREFIX
      value: actor-cache:  # Optional: key prefix
```

**When to use**: Low-latency state access with TTL support (session data, ephemeral state).

**TTL**: Redis does not currently support per-key TTL via the state proxy interface. Set TTLs using Redis server configuration or post-write Lua scripts.

### NATS KV

Not yet implemented. Planned connector: `nats-buffered-cas`.

### GCS

Not yet implemented. Planned connector: `gcs-buffered-lww`.

## IAM and Credentials

State proxy connectors use the same credential mechanisms as actors: **IRSA** (IAM Roles for Service Accounts) or Kubernetes Secrets.

### IRSA (Recommended for AWS)

IRSA injects AWS credentials into pods via the ServiceAccount. No secrets to manage.

**Setup**:

1. Create an IAM role with S3 permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::ml-checkpoints/*",
        "arn:aws:s3:::ml-checkpoints"
      ]
    }
  ]
}
```

2. Configure the trust relationship to allow the ServiceAccount:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/oidc.eks.REGION.amazonaws.com/id/OIDC_ID"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.REGION.amazonaws.com/id/OIDC_ID:sub": "system:serviceaccount:prod:asya-actors"
        }
      }
    }
  ]
}
```

3. Enable IRSA in the Crossplane chart:

```yaml
# deploy/helm-charts/asya-crossplane/values.yaml
irsa:
  enabled: true
  serviceAccountName: asya-actors
  roleArn: arn:aws:iam::ACCOUNT_ID:role/asya-actors-prod
```

4. The Crossplane composition automatically injects the ServiceAccount annotation:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: asya-actors
  namespace: prod
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/asya-actors-prod
```

**Result**: All connector containers in the actor pod inherit AWS credentials from the ServiceAccount.

### Kubernetes Secrets

For Redis or non-AWS backends, use Kubernetes Secrets.

**Example** — Redis password:

1. Create a secret:

```bash
kubectl create secret generic redis-creds \
  --from-literal=password=my-redis-password \
  -n prod
```

2. Reference the secret in the connector env:

```yaml
stateProxy:
- name: cache
  mount:
    path: /state/cache
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-redis-buffered-cas:v1.0.0
    env:
    - name: REDIS_URL
      value: redis://:$(REDIS_PASSWORD)@redis.default.svc.cluster.local:6379/0
    - name: REDIS_PASSWORD
      valueFrom:
        secretKeyRef:
          name: redis-creds
          key: password
```

**Alternative** — use `secretRefs` at the actor level to inject secrets:

```yaml
spec:
  secretRefs:
  - secretName: redis-creds
    keys:
    - key: password
      envVar: REDIS_PASSWORD

  stateProxy:
  - name: cache
    connector:
      env:
      - name: REDIS_URL
        value: redis://:$(REDIS_PASSWORD)@redis.default.svc.cluster.local:6379/0
```

## Key Patterns and Namespace Isolation

State proxy connectors use flat key-value storage. Paths like `/state/checkpoints/v2/model.pt` are stored as the key `v2/model.pt` (relative to the mount).

### Key prefix

Use `STATE_PREFIX` to isolate keys within a shared bucket:

```yaml
stateProxy:
- name: checkpoints
  connector:
    env:
    - name: STATE_BUCKET
      value: shared-ml-state
    - name: STATE_PREFIX
      value: team-nlp/inference-v2/  # Keys scoped to this prefix
```

**Example**:

- Handler writes to `/state/checkpoints/model.pt`
- Connector stores to S3 key: `team-nlp/inference-v2/model.pt`

### Namespace isolation

To isolate state by Kubernetes namespace, use a namespace-specific prefix:

```yaml
stateProxy:
- name: checkpoints
  connector:
    env:
    - name: STATE_BUCKET
      value: ml-state
    - name: STATE_PREFIX
      value: $(NAMESPACE)/  # Requires NAMESPACE env var
```

Inject the namespace via downward API:

```yaml
spec:
  env:
  - name: NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
```

**Result**: Actors in namespace `prod` write to `prod/model.pt`, actors in namespace `dev` write to `dev/model.pt`.

### Actor-level isolation

To isolate state per actor, include the actor name in the prefix:

```yaml
stateProxy:
- name: checkpoints
  connector:
    env:
    - name: STATE_PREFIX
      value: $(ACTOR)/
```

Inject the actor name via label:

```yaml
spec:
  env:
  - name: ACTOR
    valueFrom:
      fieldRef:
        fieldPath: metadata.labels['asya.sh/actor']
```

## Consistency Guarantees

| Connector | Consistency model | Conflict behavior |
|-----------|-------------------|-------------------|
| `s3-buffered-lww` | Last-Write-Wins | Overwrites silently |
| `s3-passthrough` | Last-Write-Wins | Overwrites silently |
| `s3-buffered-cas` | Check-And-Set (ETag) | Raises `FileExistsError` |
| `redis-buffered-cas` | Check-And-Set (WATCH/EXEC) | Raises `FileExistsError` |

### Last-Write-Wins (LWW)

**Semantics**: Writes always succeed. No conflict detection.

**Use case**: Single-writer state or state where the latest write is always correct (e.g., checkpoints, configs).

**Example**:

```
Actor A writes "version 1" to /state/cache/result.json
Actor B writes "version 2" to /state/cache/result.json
Result: "version 2" (last write wins)
```

### Check-And-Set (CAS)

**Semantics**: Write fails if the object was modified since the last read. Handler code must catch `FileExistsError` and retry.

**Use case**: Multi-writer state where conflicts must be detected (e.g., distributed counters, leader election).

**Example**:

```python
import json

# Read-modify-write with CAS
try:
    with open("/state/shared/counter.json", "r") as f:
        counter = json.load(f)
    counter["value"] += 1
    with open("/state/shared/counter.json", "w") as f:
        json.dump(counter, f)
except FileNotFoundError:
    # First write
    with open("/state/shared/counter.json", "w") as f:
        json.dump({"value": 1}, f)
except FileExistsError:
    # CAS conflict — another actor modified the counter
    # Retry or use a different strategy
    raise
```

**CAS granularity**:

- **S3 CAS**: ETag is checked per object. Reading `model.pt` and writing `config.json` does not cause a conflict.
- **Redis CAS**: WATCH is set per key. Same granularity as S3 CAS.

## Multiple Mounts

Actors can have multiple `stateProxy` entries. Each entry becomes a separate connector sidecar and a separate mount path in the runtime container.

**Example**:

```yaml
stateProxy:
- name: weights
  mount:
    path: /state/weights
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
    env:
    - name: STATE_BUCKET
      value: ml-weights

- name: cache
  mount:
    path: /state/cache
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-redis-buffered-cas:v1.0.0
    env:
    - name: REDIS_URL
      value: redis://redis.default.svc.cluster.local:6379/0

- name: checkpoints
  mount:
    path: /state/checkpoints
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
    env:
    - name: STATE_BUCKET
      value: ml-checkpoints
```

**Result**:

- Handler writes to `/state/weights/model.pt` → S3 bucket `ml-weights`
- Handler writes to `/state/cache/result.json` → Redis key `result.json`
- Handler writes to `/state/checkpoints/epoch-10.pt` → S3 bucket `ml-checkpoints`

**Pod layout**:

```
Pod
├── asya-runtime                 (runtime container)
│   ├── /var/run/asya/state/    ← shared volume
│   ├── /state/weights/         ← logical mount (no real FS)
│   ├── /state/cache/           ← logical mount
│   └── /state/checkpoints/     ← logical mount
├── asya-state-proxy-weights    (connector sidecar)
│   └── /var/run/asya/state/weights.sock
├── asya-state-proxy-cache      (connector sidecar)
│   └── /var/run/asya/state/cache.sock
└── asya-state-proxy-checkpoints (connector sidecar)
    └── /var/run/asya/state/checkpoints.sock
```

## Resource Limits

Each connector sidecar can have its own resource requests and limits.

**Example**:

```yaml
stateProxy:
- name: checkpoints
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 256Mi
```

**Tuning**:

- **CPU**: Connectors are I/O-bound. 50m is usually sufficient.
- **Memory**: Buffered connectors hold data in memory before flushing. Set limits based on expected file sizes.
  - Small files (<1 MB): 64 Mi
  - Medium files (1-10 MB): 128 Mi
  - Large files (10-100 MB): 256 Mi or more
- **Passthrough connectors**: Use minimal memory (no buffering). 64 Mi is sufficient.

## Connector Environment Variables

| Variable | Connectors | Required | Description |
|----------|-----------|----------|-------------|
| `CONNECTOR_SOCKET` | all | ✅ | Unix socket path (set by Crossplane, do not override) |
| `STATE_BUCKET` | s3-* | ✅ | S3 bucket name |
| `STATE_PREFIX` | s3-*, redis | ❌ | Key prefix within bucket or namespace |
| `AWS_REGION` | s3-* | ❌ | AWS region (default: `us-east-1`) |
| `AWS_ENDPOINT_URL` | s3-* | ❌ | Custom endpoint for MinIO/LocalStack |
| `REDIS_URL` | redis-* | ✅ | Redis connection URL (e.g., `redis://localhost:6379/0`) |

**Note**: `CONNECTOR_SOCKET` is set by the Crossplane composition to `/var/run/asya/state/{name}.sock` and should never be overridden.

## Debugging State Proxy

### Check connector logs

```bash
kubectl logs -n prod ml-inference-abc123 -c asya-state-proxy-weights
```

### Verify socket exists

```bash
kubectl exec -n prod ml-inference-abc123 -c asya-runtime -- ls -lh /var/run/asya/state/
```

Expected output:

```
srw-rw-rw- 1 root root 0 Jan 1 12:00 weights.sock
srw-rw-rw- 1 root root 0 Jan 1 12:00 cache.sock
```

### Test connector directly

```bash
# From the runtime container
kubectl exec -n prod ml-inference-abc123 -c asya-runtime -- \
  curl --unix-socket /var/run/asya/state/weights.sock http://localhost/healthz
```

Expected output:

```json
{"status": "ready"}
```

### Check runtime environment

```bash
kubectl exec -n prod ml-inference-abc123 -c asya-runtime -- env | grep ASYA_STATE_PROXY_MOUNTS
```

Expected output:

```
ASYA_STATE_PROXY_MOUNTS=weights:/state/weights:write=buffered;cache:/state/cache:write=buffered
```

## Best Practices

1. **Use IRSA for S3** — avoid managing AWS credentials in secrets; use IAM roles with IRSA.

2. **Set STATE_PREFIX per-namespace or per-actor** — isolate state to prevent accidental overwrites across tenants.

3. **Use CAS for multi-writer state** — if multiple replicas write to the same key, use `s3-buffered-cas` or `redis-buffered-cas` to detect conflicts.

4. **Use passthrough for large files** — if writing files >100 MB, use `s3-passthrough` to avoid memory pressure.

5. **Set resource limits on connectors** — prevent runaway memory usage; tune based on expected file sizes.

6. **Monitor connector errors** — check connector logs for HTTP errors (403 Forbidden, 404 Not Found, 409 Conflict).

---

**Using state proxy**: To read/write state in your actor handlers, see [usage/guide-state-proxy.md](../usage/guide-state-proxy.md).
