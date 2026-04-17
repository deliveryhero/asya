---
description: "Pluggable storage: S3, GCS, Redis, NATS KV, PostgreSQL backends for state proxy virtual actor memory"
---

# Pluggable Storage

## State Proxy Connectors

The [state proxy](../reference/components/core-state-proxy.md) gives actors virtual persistent
memory through filesystem emulation. Actors read and write `/state/...` paths; the proxy
translates these operations to the configured storage backend.

Storage backends are pluggable — swap by changing configuration, not code:

| Backend | Use case |
|---------|----------|
| **S3 / GCS** | Durable object storage for large state (conversation history, documents) |
| **Redis** | Low-latency key-value access for hot state (session data, counters) |
| **NATS KV** | Lightweight distributed KV for mesh-local state |
| **PostgreSQL** | JSONB document store for gateway mesh-api envelope state |

## How It Works

The state proxy runs as an optional sidecar alongside the actor runtime. Your handler
code uses standard file I/O:

```python
def process(state: dict) -> dict:
    # Read previous state
    with open("/state/history.json") as f:
        history = json.load(f)

    # Update and write back
    history.append(state["new_entry"])
    with open("/state/history.json", "w") as f:
        json.dump(history, f)

    return state
```

The runtime intercepts these file operations and forwards them to the state proxy over
a Unix socket. The proxy translates to the configured backend (S3 PUT, Redis SET, etc.).

## Architecture: sidecar over Unix socket

The state proxy is deployed as a sidecar container alongside the actor runtime,
communicating over HTTP via a Unix socket. Handler code uses standard Python file
I/O (`open`, `read`, `write`) — the runtime intercepts these calls transparently
and forwards them to the state proxy. No SDK or special imports are needed.

## Connector interface

Adding a new storage backend means implementing the `StateProxyConnector` interface:

```python
class StateProxyConnector(ABC):
    def read(self, key: str) -> BinaryIO: ...
    def write(self, key: str, data: BinaryIO, size: int | None = None,
              *, exclusive: bool = False) -> None: ...
    def exists(self, key: str) -> bool: ...
    def stat(self, key: str) -> KeyMeta | None: ...
    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult: ...
    def delete(self, key: str) -> None: ...
```

For example, the S3 passthrough connector implements `read` as:

```python
class S3Passthrough(StateProxyConnector):
    def read(self, key: str) -> BinaryIO:
        response = self._s3.get_object(Bucket=self._bucket, Key=self._full_key(key))
        return _StreamingBodyWrapper(response["Body"])
```

Available connectors: `s3-passthrough`, `s3-buffered-lww`, `s3-buffered-cas`,
`gcs-buffered-lww`, `gcs-buffered-cas`, `redis-buffered-cas`, `state-proxy-pg`
(Go). Each is a separate Docker image selected at deployment time.

## Consistency Guarantees

Each connector supports configurable consistency:

- **LWW (Last Writer Wins)** — simple, fast, eventual consistency
- **CAS (Compare-and-Swap)** — optimistic concurrency for conflict detection

## Separation from Virtual Actors

Pluggable storage is the **infrastructure layer** — which backends are available and how
they're configured. [Virtual Actors](virtual-actors.md) is the **concept** — actors that
appear stateful while remaining stateless Kubernetes Deployments.

## Further Reading

- **[State Proxy](../reference/components/core-state-proxy.md)** — component deep dive
- **[S3 Connector](../reference/state-proxy-connectors/s3.md)** — S3/GCS configuration
- **[Redis Connector](../reference/state-proxy-connectors/redis.md)** — Redis configuration
- **[NATS KV Connector](../reference/state-proxy-connectors/nats-kv.md)** — NATS KV configuration
- **[PostgreSQL Connector](../reference/state-proxy-connectors/pg.md)** — Go JSONB document store for mesh-api
- **[Virtual Actors](virtual-actors.md)** — the concept that pluggable storage enables
