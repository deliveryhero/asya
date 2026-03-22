# NATS KV

NATS JetStream Key-Value connector for state proxy.

**Status**: Not yet implemented. The planned connector is `nats-kv-buffered-cas`.

## Overview

The NATS KV connector will provide cloud-native key-value storage for state proxy
using NATS JetStream's built-in KV store. It will implement the
`StateProxyConnector` interface with CAS support via revision-based conditional
updates.

Per the RFC, the connector naming convention is `{backend}-{buffering}-{consistency}`.
The planned connector name is `nats-kv-buffered-cas`.

NATS KV offers:

- Distributed key-value storage with pub/sub foundation
- Strong consistency with Raft consensus
- Revision-based CAS (each key mutation increments a revision number)
- TTL and history management
- Low latency for co-located workloads

## Planned Variant

| Image Suffix | Consistency | Write Mode | Use Case |
|--------------|-------------|------------|----------|
| `nats-kv-buffered-cas` | Compare-And-Set (revision) | Buffered | Small objects with strong consistency |

## Planned Configuration

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `NATS_URL` | Yes | NATS server URL (e.g. `nats://nats:4222`) | -- |
| `NATS_KV_BUCKET` | Yes | JetStream KV bucket name | -- |
| `STATE_PREFIX` | No | Key prefix inside KV bucket | `""` (root) |
| `NATS_CREDS_FILE` | No | Path to NATS credentials file | -- |

### AsyncActor Example

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: cache-actor
  namespace: prod
spec:
  actor: cache-actor
  stateProxy:
    - name: cache
      mount:
        path: /state/cache
      writeMode: buffered
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-nats-kv-buffered-cas:v1.0.0
        env:
          - name: NATS_URL
            value: nats://nats.default.svc.cluster.local:4222
          - name: NATS_KV_BUCKET
            value: actor-state
          - name: STATE_PREFIX
            value: cache-actor
        resources:
          requests:
            cpu: 20m
            memory: 32Mi
```

## Key Patterns

Handler path `/state/cache/user_123.json` maps to NATS KV key:

- **Without prefix**: `user_123.json`
- **With prefix** (`STATE_PREFIX=cache-actor`): `cache-actor.user_123.json`

## JetStream Bucket Setup

**Pre-create the KV bucket** before deploying actors:

```bash
nats kv add actor-state \
  --replicas=3 \
  --ttl=24h \
  --max-value-size=1048576
```

**Recommended bucket settings**:

- **Replicas**: 3 for high availability (Raft consensus)
- **TTL**: Optional, for ephemeral data
- **Max value size**: 1 MB (NATS KV optimized for small values)
- **Storage**: File-based for persistence

## Consistency Model

NATS KV provides strong consistency via Raft consensus. Writes are linearizable
when the bucket has `replicas > 1`.

The planned CAS behavior uses NATS KV's built-in revision numbers. On `read()`,
the connector caches the key's revision. On `write()`, the connector passes the
cached revision for conditional update. If the key was modified externally, the
update fails, which the connector maps to `FileExistsError` (HTTP 409).

On a CAS conflict (`FileExistsError`), the sidecar requeues the message with
exponential backoff, and the handler runs again from scratch with a fresh read.

### Extended Attributes

The connector will expose the `version` attribute (NATS KV revision number) as a
read-only extended attribute via `os.getxattr(path, "user.asya.version")`.

## Authentication

NATS supports multiple authentication mechanisms:

- **Token-based**: Include token in `NATS_URL` (`nats://token@host:port`)
- **Credentials file**: Mount `.creds` file and set `NATS_CREDS_FILE`
- **NKey**: Public/private key authentication
- **None**: For local testing

## Use Cases

**Best for**:

- Cloud-native stacks already using NATS for messaging
- Low-latency key-value storage co-located with NATS infrastructure
- Small objects (< 1 MB) with strong consistency requirements
- Reactive patterns (watch/subscribe to key changes)

**Not recommended for**:

- Large files (> 1 MB) — use S3/GCS instead
- High write throughput (> 10k ops/s) — NATS KV optimized for reads
- Long-term archival — use object storage

## Related Documentation

- [State Proxy Architecture](../components/core-state-proxy.md)
- [Redis Connector](redis.md)
- [S3 Connector](s3.md)
- [NATS JetStream KV Documentation](https://docs.nats.io/nats-concepts/jetstream/key-value-store)
