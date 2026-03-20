# Redis State Connector

Redis key-value connector for state proxy with Check-And-Set consistency.

## Available Variants

| Image Suffix | Consistency | Write Mode | Use Case |
|--------------|-------------|------------|----------|
| `redis-buffered-cas` | Compare-And-Set | Buffered | Fast key-value storage, small objects, TTL support |

## Configuration

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `REDIS_URL` | ✅ | Redis connection URL (e.g. `redis://localhost:6379/0`) | — |
| `STATE_PREFIX` | ❌ | Key prefix inside Redis namespace | `""` (root) |

**Authentication**: Include credentials in the URL (`redis://user:password@host:port/db`).

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
        image: ghcr.io/deliveryhero/asya-state-proxy-redis-buffered-cas:v1.0.0
        env:
          - name: REDIS_URL
            valueFrom:
              secretKeyRef:
                name: redis-credentials
                key: url
          - name: STATE_PREFIX
            value: actor-cache
        resources:
          requests:
            cpu: 20m
            memory: 32Mi
          limits:
            memory: 64Mi
```

**Secret example**:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-credentials
  namespace: prod
type: Opaque
stringData:
  url: redis://:mypassword@redis.default.svc.cluster.local:6379/0
```

## Key Patterns

Handler path `/state/cache/user_123.json` maps to Redis key:

- **Without prefix**: `user_123.json`
- **With prefix** (`STATE_PREFIX=actor-cache`): `actor-cache:user_123.json`

Directory semantics are simulated using `SCAN` with prefix matching. `os.listdir("/state/cache/users/")` scans keys matching `users/*` and returns pseudo-directory entries.

## Connection Pooling

The connector uses `redis-py` with default connection pooling. Each connector sidecar maintains a single connection pool to the Redis server.

**Connection limits**: Default pool size is unlimited; set `max_connections` in Redis URL if needed (advanced use case, not exposed via env vars).

## Consistency Model

### Compare-And-Set (CAS)

Uses Redis `WATCH`/`MULTI`/`EXEC` for optimistic locking. On write:

1. Key is `WATCH`ed
2. Transaction begins (`MULTI`)
3. `SET` command queued
4. Transaction executes (`EXEC`)

If the key was modified between `WATCH` and `EXEC`, Redis raises `WatchError`, which the connector maps to `FileExistsError`.

CAS retries are handled by the sidecar: on a CAS conflict (`FileExistsError`),
the sidecar requeues the message with exponential backoff, and the handler runs
again from scratch with a fresh `read()` that sees the latest value. In most
cases, your handler does not need explicit retry logic.

**Handler code**:

```python
import json

async def handler(payload):
    # Read current value (connector watches the key internally)
    with open("/state/cache/counter.json") as f:
        data = json.load(f)

    data["count"] += 1

    # Write — uses WATCH/MULTI/EXEC for CAS.
    # On conflict, raises FileExistsError; sidecar requeues the message.
    with open("/state/cache/counter.json", "w") as f:
        json.dump(data, f)

    return payload
```

### Exclusive Writes

The connector supports atomic create-if-absent via `SET NX` (set-if-not-exists).
This is triggered internally by the `If-None-Match: *` HTTP header on PUT requests
and is not directly exposed to handler code.

## Write Mode

Uses **buffered** write mode: collects all writes into memory. On `close()`, sends a single `SET` command to Redis.

**Advantages**: Supports `seek()` and `tell()`, transactional writes.

**Limitations**: Memory overhead for large values. Redis itself has a maximum value size (512 MB by default).

**Best practice**: Use Redis for small objects (< 1 MB). For large files, use S3 or GCS connectors.

## TTL Support (Extended Attributes)

Redis connector supports TTL via the extended attributes (xattr) API. The
runtime uses the `user.asya.{attr}` naming convention — it strips the
`user.asya.` prefix before forwarding to the connector.

**Set TTL**:

```python
import json, os

async def handler(payload):
    # Write key
    with open("/state/cache/temp.json", "w") as f:
        json.dump(data, f)

    # Set TTL to 3600 seconds (1 hour)
    os.setxattr("/state/cache/temp.json", "user.asya.ttl", b"3600")

    return payload
```

**Get TTL**:

```python
ttl = os.getxattr("/state/cache/temp.json", "user.asya.ttl")
print(f"TTL: {ttl.decode()} seconds")
```

**Notes**:

- TTL is applied via `EXPIRE` after the key is written
- Negative TTL values: `-1` = no expiry, `-2` = key does not exist
- Only `ttl` is supported as an extended attribute; other attribute names raise `KeyError`

## Performance Characteristics

- **Latency**: Sub-millisecond for local Redis, 1-10 ms for network Redis
- **Throughput**: Limited by Redis server throughput (10k-100k ops/s depending on instance size)
- **Concurrency**: Connection pooling supports concurrent requests
- **Caching**: Redis is the cache — no additional caching layer

**Optimization**: Redis is already fast; minimize round-trips by batching reads in handler code.

## Redis Deployment

**Recommended for Kubernetes**: Use Redis Operator or Helm chart for HA setup.

**Example Helm install** (Bitnami Redis):

```bash
helm install redis oci://registry-1.docker.io/bitnamicharts/redis \
  --namespace default \
  --set auth.password=mypassword \
  --set master.persistence.enabled=true \
  --set replica.replicaCount=2
```

**Connection URL**:

```
redis://:mypassword@redis-master.default.svc.cluster.local:6379/0
```

## Best Practices

- Use Redis for small, frequently accessed key-value data (< 1 MB per key)
- Set `STATE_PREFIX` to namespace keys by actor or environment
- Enable Redis persistence (RDB or AOF) to avoid data loss on pod restart
- Use Redis Sentinel or Cluster for high availability
- Monitor Redis memory usage and eviction policy (e.g. `allkeys-lru`)
- Set TTLs on ephemeral data to avoid memory bloat
- For large files, use S3 or GCS connectors instead

## Troubleshooting

**`FileNotFoundError` on read**: Key does not exist in Redis. Verify key name and `STATE_PREFIX`.

**`ConnectionError`**: Redis server is unreachable. Verify `REDIS_URL` and network access from pod.

**`FileExistsError` during write**: Concurrent modification detected by CAS. Retry or merge changes.

**`WatchError` in logs**: Another client modified the key during transaction. This is expected behavior for CAS; handler receives `FileExistsError`.

**Slow writes**: Large values (> 10 MB) or high concurrency. Redis is optimized for small values; use object storage for large files.

**Memory pressure**: Redis evicting keys before expiry. Increase Redis memory limit or set stricter TTLs.

**TTL not working**: Verify `os.setxattr` is called after the file is closed. TTL is applied via `EXPIRE` after the key exists.

## Limitations

- **Max value size**: Redis default is 512 MB; practical limit is much lower (< 10 MB for performance)
- **No streaming writes**: Buffered mode only — entire value is buffered in memory before `SET`
- **CAS via WATCH**: Redis CAS uses WATCH/MULTI/EXEC optimistic locking, not version/revision tracking. The key is watched at write time; if it changed between watch and exec, the transaction fails with `FileExistsError`. This gives Redis CAS a narrower conflict detection window than S3/GCS CAS: Redis WATCH is called inside `write()` itself, so only modifications between WATCH and EXEC are caught — not between `read()` and `write()`. For S3/GCS, the ETag or generation from `read()` is cached and verified at `write()` time, covering the full read-modify-write span

## Related Documentation

- [State Proxy Architecture](../components/core-state-proxy.md)
- [S3 Connector](s3.md)
- [GCS Connector](gcs.md)
- [Redis Documentation](https://redis.io/docs/)
