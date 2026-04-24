---
description: "GCS connector: Google Cloud Storage config for state proxy, bucket setup, Workload Identity"
---

# GCS

Google Cloud Storage connector for state proxy.

## Available Variants

| Image Suffix | Consistency | Write Mode | Use Case |
|--------------|-------------|------------|----------|
| `gcs-buffered-lww` | Last-Write-Wins | Buffered | General-purpose, small-to-medium files |
| `gcs-buffered-cas` | Compare-And-Set | Buffered | Multi-process writes, conflict detection |

## Configuration

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `STATE_BUCKET` | ✅ | GCS bucket name | — |
| `STATE_PREFIX` | ❌ | Key prefix inside bucket | `""` (root) |
| `GCS_PROJECT` | ❌ | GCP project ID | Auto-detected from environment |
| `STORAGE_EMULATOR_HOST` | ❌ | Emulator endpoint for testing (e.g. `http://fake-gcs:4443`) | — |

**Service account authentication**: Connectors use the Google Cloud SDK's default credential chain (Workload Identity, service account key file via `GOOGLE_APPLICATION_CREDENTIALS`, or compute metadata).

### AsyncActor Example

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: model-inference
  namespace: prod
spec:
  actor: model-inference
  stateProxy:
    - name: weights
      mount:
        path: /state/weights
      writeMode: buffered
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-lww:v1.0.0
        env:
          - name: STATE_BUCKET
            value: my-model-weights
          - name: STATE_PREFIX
            value: models/v2
          - name: GCS_PROJECT
            value: my-gcp-project
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            memory: 128Mi
```

## Service Account Permissions

**Sidecar connector permissions** (via Workload Identity or service account key):

```json
{
  "bindings": [
    {
      "role": "roles/storage.objectUser",
      "members": [
        "serviceAccount:actor-sa@my-project.iam.gserviceaccount.com"
      ]
    }
  ]
}
```

**Required IAM permissions**:

- `storage.objects.get`
- `storage.objects.create`
- `storage.objects.delete`
- `storage.objects.list`

**For CAS variant**: no additional permissions needed — generation-based conflict detection uses standard GCS operations.

## Key Patterns

Handler path `/state/weights/model.bin` maps to GCS blob name:

- **Without prefix**: `model.bin`
- **With prefix** (`STATE_PREFIX=models/v2`): `models/v2/model.bin`

Directory semantics are simulated: `os.listdir("/state/weights/subdir/")` uses prefix-based listing with delimiter `/` to return entries under `subdir/`.

## Bucket Setup

**Pre-create the bucket** before deploying actors. The connector does not create buckets.

**Recommended bucket settings**:

- **Location**: Same region as GKE cluster for low latency
- **Storage class**: `STANDARD` for frequently accessed data, `NEARLINE` for infrequent access
- **Versioning**: Optional (connector does not use versions; beneficial for recovery)
- **Lifecycle policies**: Recommended for expired data cleanup
- **Encryption**: Default (Google-managed keys) or CMEK
- **Public access**: Blocked (actors use service account credentials)

## Consistency Guarantees

### gcs-buffered-lww

No conflict detection. Concurrent writes to the same blob result in the last write winning. Object generation changes are ignored.

**Safe for**: Single-writer per blob, or when the latest write is always correct.

### gcs-buffered-cas

Check-And-Set with generation-based conflict detection. On `read()`, the
connector caches the blob's generation number (an int64 that GCS increments on
every mutation). On `write()`, the connector passes `if_generation_match` with
the cached generation as a precondition. If the blob was modified externally
since the last read, GCS returns `PreconditionFailed` (412), which the connector
maps to `FileExistsError`.

For keys that have never been read (new key path), the write is unconditional.

For exclusive creates (atomic create-if-absent), the connector uses
`if_generation_match=0`, which means the object must not already exist.

On a CAS conflict (`FileExistsError`), the sidecar requeues the message with
exponential backoff, and the handler runs again from scratch with a fresh read.
The handler does not need explicit retry logic.

**Handler code**:

```python
import json

async def handler(payload):
    # Read (connector caches generation internally)
    with open("/state/cache/result.json") as f:
        data = json.load(f)

    data["count"] += 1

    # Write (connector uses cached generation for conditional write)
    with open("/state/cache/result.json", "w") as f:
        json.dump(data, f)

    return payload
```

If the blob was modified between read and write, the connector raises
`FileExistsError`. Per the ADR on CAS safety, this is safe even across pod
crashes: a crash before write leaves no state change, a crash during write is
atomic (succeeds or fails entirely), and a crash after write but before message
ack triggers a redelivery where CAS detects the version conflict.

## Write Mode

Both variants use **buffered** write mode: collects all writes into memory (spills to disk above 4 MiB via `tempfile.SpooledTemporaryFile`). On `close()`, sends a single upload to GCS.

**Advantages**: Supports `seek()` and `tell()`, known content length for GCS API.

**Limitations**: Memory overhead for large files.

**For large files** (> 100 MB): Use S3 passthrough connector or buffer manually in handler code.

## Workload Identity Setup

**Recommended for GKE deployments**: Use Workload Identity to bind Kubernetes service accounts to GCP service accounts.

```bash
# Create GCP service account
gcloud iam service-accounts create actor-sa \
  --project=my-project

# Grant storage permissions
gcloud projects add-iam-policy-binding my-project \
  --member="serviceAccount:actor-sa@my-project.iam.gserviceaccount.com" \
  --role="roles/storage.objectUser"

# Bind to Kubernetes service account
gcloud iam service-accounts add-iam-policy-binding \
  actor-sa@my-project.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:my-project.svc.id.goog[prod/actor-service-account]"

# Annotate Kubernetes service account
kubectl annotate serviceaccount actor-service-account \
  -n prod \
  iam.gke.io/gcp-service-account=actor-sa@my-project.iam.gserviceaccount.com
```

**AsyncActor** must reference the annotated Kubernetes service account:

```yaml
spec:
  serviceAccountName: actor-service-account
```

## Performance Characteristics

- **Latency**: Typical GCS GET/PUT latency (10-100 ms in same region)
- **Throughput**: GCS supports high throughput for multi-regional buckets
- **Concurrency**: No connection pooling; one HTTP request per file operation
- **Caching**: None — every `open()` reads from GCS

**Optimization**: Minimize reads by caching in actor memory when possible.

## Storage Emulator (Testing)

For local testing, use [fake-gcs-server](https://github.com/fsouza/fake-gcs-server):

```bash
docker run -p 4443:4443 fsouza/fake-gcs-server -scheme http -port 4443
```

**Connector configuration**:

```yaml
env:
  - name: STATE_BUCKET
    value: test-bucket
  - name: STORAGE_EMULATOR_HOST
    value: http://fake-gcs:4443
```

**Create bucket** via HTTP API:

```bash
curl -X POST 'http://localhost:4443/storage/v1/b?project=test' \
  -H 'Content-Type: application/json' \
  -d '{"name": "test-bucket"}'
```

The `google-cloud-storage` Python SDK supports `STORAGE_EMULATOR_HOST` natively — when set, the client routes all requests to the emulator with no code changes. The emulator supports generation numbers and preconditions (`if_generation_match`), which enables CAS testing.

## Best Practices

- Use Workload Identity for pod-level GCP authentication (avoid service account keys)
- Set `STATE_PREFIX` to namespace models by environment or version
- Use lifecycle policies to delete expired data or transition to cheaper storage classes
- Monitor GCS request metrics via Cloud Monitoring
- Deploy buckets in the same region as GKE cluster to reduce latency and egress costs
- For large files (> 100 MB), buffer manually or use chunked writes in handler code

## Troubleshooting

**`FileNotFoundError` on read**: Verify bucket name, blob name, and IAM `storage.objects.get` permission.

**`PermissionError`**: Check service account has `storage.objects.create` / `storage.objects.delete` permissions.

**`ConnectionError`**: Verify Workload Identity binding is correct (pod service account → GCP service account).

**`FileExistsError` with gcs-buffered-cas**: Another process modified the blob since last read. Retry or merge changes.

**Slow writes**: Large payloads + buffered mode = memory spill to disk. Optimize by reducing payload size or using in-memory caching.

**Workload Identity not working**: Verify GKE cluster has Workload Identity enabled, pod runs with correct service account, and IAM binding exists.

## Analytics Queries via `/query`

`gcs-buffered-lww` and `gcs-buffered-cas` connectors expose `POST /query` for
Mango-style analytics over stored objects. The connector downloads blobs via the
Google Cloud Storage SDK (inheriting Workload Identity or ADC credentials) and
filters them locally with DuckDB.

### Request

```json
{
  "prefix": "runs/2024-01/",
  "filter": {"status": "done", "model": "gemma-7b"},
  "sort": ["-created_at"],
  "limit": 100,
  "offset": 0
}
```

### Per-call limits

Same environment variables as the S3 connector — see [S3 `/query` limits](s3.md#per-call-limits).

| Env var | Default | Effect |
|---------|---------|--------|
| `QUERY_MAX_KEYS` | 10 000 | `list()` guard — returns 400 if exceeded |
| `QUERY_MAX_FETCH_KEYS` | 1 000 | Max blobs downloaded per call |
| `QUERY_MAX_FETCH_BYTES` | 268 435 456 (256 MiB) | Total bytes downloaded; stops after crossing the limit |
| `QUERY_MAX_RESULT_ROWS` | 10 000 | SQL `LIMIT` cap on returned rows |

### Helm configuration

```yaml
persistence:
  config:
    query:
      maxFetchBytes: "67108864"   # 64 MiB
      maxFetchKeys: "500"
      maxKeys: "5000"
      maxResultRows: "1000"
```

## Related Documentation

- [State Proxy Architecture](../components/core-state-proxy.md)
- [S3 Connector](s3.md)
- [Redis Connector](redis.md)
- [GKE Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
