<!-- Type: Reference -->
# NATS KV State Connector

NATS JetStream Key-Value connector for state proxy.

⚠️ **Status**: Planned. This connector is not yet implemented.

## Overview

The NATS KV connector will provide cloud-native key-value storage for state proxy using NATS JetStream's built-in KV store.

NATS KV offers:

- Distributed key-value storage with pub/sub foundation
- Strong consistency with Raft consensus
- Watch/subscribe support for reactive updates
- TTL and history management
- Low latency for co-located workloads

## Planned Configuration

(Configuration details TBD)

### Environment Variables (Tentative)

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `NATS_URL` | ✅ | NATS server URL (e.g. `nats://nats:4222`) | — |
| `NATS_KV_BUCKET` | ✅ | JetStream KV bucket name | — |
| `STATE_PREFIX` | ❌ | Key prefix inside KV bucket | `""` (root) |
| `NATS_CREDS_FILE` | ❌ | Path to NATS credentials file | — |

### AsyncActor Example (Tentative)

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
        image: ghcr.io/deliveryhero/asya-state-proxy-nats-kv:v1.0.0
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

## Key Patterns (Tentative)

Handler path `/state/cache/user_123.json` would map to NATS KV key:

- **Without prefix**: `user_123.json`
- **With prefix** (`STATE_PREFIX=cache-actor`): `cache-actor.user_123.json`

## JetStream Bucket Setup (Tentative)

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

## Consistency Model (Tentative)

NATS KV provides strong consistency via Raft consensus. Writes are linearizable when bucket has `replicas > 1`.

**Expected behavior**:

- Last-Write-Wins semantics by default
- Optional CAS support via revision-based conditional updates (if implemented)

## Authentication (Tentative)

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

## Development Status

This connector is in the planning phase. Contributions welcome.

**Implementation tasks**:

- [ ] Define connector interface implementation (`StateProxyConnector`)
- [ ] Implement NATS JetStream KV client integration
- [ ] Add buffered write mode support
- [ ] Add CAS support via revision-based updates
- [ ] Create Dockerfile and publish image
- [ ] Add component tests
- [ ] Document authentication patterns
- [ ] Add Helm chart integration

See [asya-state-proxy](https://github.com/deliveryhero/asya/tree/main/src/asya-state-proxy) for implementation reference.

## Related Documentation

- [State Proxy Architecture](../components/core-state-proxy.md)
- [Redis Connector](redis.md)
- [S3 Connector](s3.md)
- [NATS JetStream KV Documentation](https://docs.nats.io/nats-concepts/jetstream/key-value-store)
