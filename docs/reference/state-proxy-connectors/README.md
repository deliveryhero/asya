# State Proxy Connectors

State proxy connectors are pluggable storage backends that give actors persistent state access via standard Python file operations.

## Overview

The state proxy translates Python file I/O (`open`, `os.stat`, `os.listdir`, `os.remove`) into HTTP requests over Unix sockets to connector sidecar processes. Each connector adapts those HTTP requests to a specific storage backend.

Actors read and write state as if it were a local directory — no SDK, no special imports. The runtime patches Python builtins at startup to intercept file operations on configured mount paths.

See [core-state-proxy.md](../components/core-state-proxy.md) for architecture and runtime integration.

## Available Connectors

| Connector | Storage | Consistency | Use Case |
|-----------|---------|-------------|----------|
| [S3](s3.md) | AWS S3 / MinIO | LWW or CAS | General-purpose object storage, model weights, large files |
| [GCS](gcs.md) | Google Cloud Storage | LWW or CAS | GCP deployments, model weights, large files |
| [Redis](redis.md) | Redis | CAS with WATCH/EXEC | Fast key-value storage, small objects, TTL support |
| [NATS KV](nats-kv.md) | NATS JetStream KV | CAS with revision (not yet implemented) | Cloud-native deployments with NATS infrastructure |

## Consistency Models

### Last-Write-Wins (LWW)

Writes always overwrite the existing object. No conflict detection. Suitable for state written by a single actor instance or when the latest write is always correct.

**Connectors**: `s3-buffered-lww`, `s3-passthrough`, `gcs-buffered-lww`

### Compare-And-Set (CAS)

Writes include a condition that the object has not changed since it was last read.
If the object was modified externally, the write fails with `FileExistsError`.
Suitable for state that may be accessed by multiple processes. On a CAS conflict
(`FileExistsError`), the sidecar requeues the message with exponential backoff,
and the handler runs again from scratch with a fresh read.

The CAS primitive varies by backend: S3 uses ETags with conditional `PutObject`,
GCS uses generation numbers with `if_generation_match`, Redis uses
WATCH/MULTI/EXEC optimistic locking, and NATS KV uses revision-based conditional
updates.

**Connectors**: `s3-buffered-cas`, `gcs-buffered-cas`, `redis-buffered-cas`
(planned: `nats-kv-buffered-cas`)

## Write Modes

Configured per mount via `stateProxy[].writeMode` in the AsyncActor spec.

### buffered (default)

Collects all writes into memory (spills to disk above 4 MiB). On `close()`, sends a single PUT with `Content-Length`. Supports `seek()` and `tell()` before close.

Suitable for small-to-medium files where the full size is needed upfront.

### passthrough

Opens HTTP connection immediately, sends each `write()` call as an HTTP chunk using chunked transfer encoding. Does not buffer in memory — suitable for large files. Does not support `seek()` or `tell()`.

## Choosing a Connector

**For model weights and large files**: S3 (AWS) or GCS (GCP) with buffered-lww or passthrough.

**For fast key-value storage**: Redis with buffered-cas. Best for small objects (< 1 MB) that need low-latency access.

**For cloud-native stacks with NATS**: NATS KV (not yet implemented).

**For MinIO compatibility**: S3 connectors work with MinIO via `AWS_ENDPOINT_URL`.

## Configuration

State proxy is configured in the AsyncActor CRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: model-inference
spec:
  actor: model-inference
  stateProxy:
    - name: weights
      mount:
        path: /state/weights
      writeMode: buffered
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
        env:
          - name: STATE_BUCKET
            value: my-model-weights
          - name: AWS_REGION
            value: us-east-1
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
```

See individual connector pages for required environment variables and backend-specific setup.

## Common Environment Variables

All connectors support:

| Variable | Description | Required |
|----------|-------------|----------|
| `CONNECTOR_SOCKET` | Unix socket path (set automatically by Crossplane) | ✅ |
| `STATE_PREFIX` | Key prefix within bucket or namespace | ❌ |

Backend-specific variables are documented in each connector's reference page.

## Error Mapping

Connectors map storage backend errors to standard Python exceptions:

| Connector Error | Python Exception |
|-----------------|------------------|
| Object not found | `FileNotFoundError` |
| Permission denied | `PermissionError` |
| CAS conflict | `FileExistsError` |
| Payload too large | `OSError(errno.EFBIG, ...)` |
| Backend unavailable | `ConnectionError` |
| Timeout | `TimeoutError` |

Handler code can catch these exceptions directly — no SDK imports needed.

## Related Documentation

- [State Proxy Architecture](../components/core-state-proxy.md) — runtime hooks, pod layout, HTTP protocol
- [Crossplane](../components/core-crossplane.md) — Crossplane resource definition
