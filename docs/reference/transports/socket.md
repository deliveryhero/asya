# Socket Transport

⚠️ **Local testing only.** The socket transport exists exclusively for Docker Compose developer
workflows. It has no persistence, no broker, no competing consumers, and no Kubernetes support.
Do not use it in staging or production.

## Purpose

Running a full actor mesh locally normally requires a message broker (RabbitMQ, SQS, Pub/Sub).
The socket transport removes that dependency: sidecars exchange messages over Unix domain sockets
on a shared Docker volume, so a developer can spin up a complete multi-actor pipeline with a
single `docker compose up`.

## How It Works

Each actor's sidecar listens on `<ASYA_SOCKET_MESH_DIR>/<actorName>.sock`. All sidecar containers
mount the same named volume at that path, so any sidecar can address any other by actor name.

```
actor-a sidecar                    actor-b sidecar
   │                                    │
   │  Send("actor-b", body)             │
   └──► connect to actor-b.sock ───────►│ Receive()
                                        │  └─ read body
                                        │  └─ write ack byte
   ◄──────────────────────── ack ───────┘
   Send() returns nil (delivery confirmed)
```

### Wire Protocol

Every message is length-prefixed:

```
[4-byte big-endian uint32 length][body bytes]
```

After the receiver reads the body it writes one ack byte (`0x01`) back to the sender.
`Send()` blocks until this ack arrives, so a nil return means the message is in the
receiver's memory — not just on the wire.

### Queue Names

For the socket transport `resolveQueueName` returns the bare actor name (no
`asya-{namespace}-` prefix). Actor `my-processor` listens on `my-processor.sock`,
`x-sink` on `x-sink.sock`, and so on.

### Startup Ordering

Sidecar containers may start before the actor they need to send to is ready.
`Send()` retries the dial up to 60 times with 500 ms between attempts (30 s total)
before giving up, so `docker compose up` ordering is flexible.

### Requeue

`Requeue()` writes the message body to an internal buffered channel instead of
self-dialing. The next `Receive()` call drains this channel before blocking on
`Accept`, avoiding a deadlock where sender and receiver would both wait on each other.

## Constraints

| Property | Behaviour |
|---|---|
| Persistence | None — messages are in-memory only |
| Delivery | Exactly-once per connection; lost on crash |
| Concurrency | Sequential FIFO per queue; one in-flight message at a time |
| Replicas | One replica per actor (no competing consumers) |
| `SendWithDelay` | Not supported; returns `ErrDelayNotSupported` |
| Kubernetes | Not supported; use RabbitMQ, SQS, or Pub/Sub |

## Configuration

| Environment variable | Description | Default |
|---|---|---|
| `ASYA_TRANSPORT` | Must be set to `socket` | — |
| `ASYA_SOCKET_MESH_DIR` | Directory for socket files (shared Docker volume mount) | `/var/run/asya/mesh` |

## Docker Compose Setup

All containers that share the mesh volume **must run as the same UID**. The socket
file is created by the receiving sidecar and owned by that UID; peer containers can
only connect to it if they share the same owner. Docker handles this automatically
when all services use the same image and no `user:` override is set.

The mesh directory must exist before the transport starts. Docker creates it
automatically when a named volume is mounted.

```yaml
services:
  actor-a-sidecar:
    image: asya-sidecar      # all services use the same image → same UID
    environment:
      ASYA_TRANSPORT: socket
      ASYA_SOCKET_MESH_DIR: /mesh
      ASYA_ACTOR_NAME: actor-a
      ASYA_NAMESPACE: local
    volumes:
      - mesh:/mesh            # Docker creates /mesh; transport does not mkdir it

  actor-b-sidecar:
    image: asya-sidecar
    environment:
      ASYA_TRANSPORT: socket
      ASYA_SOCKET_MESH_DIR: /mesh
      ASYA_ACTOR_NAME: actor-b
      ASYA_NAMESPACE: local
    volumes:
      - mesh:/mesh

volumes:
  mesh:
```

No queue-setup service is needed: socket files are created dynamically on the first
`Receive()` call. No broker credentials, no IAM roles, no VPC endpoints.

## Component Tests

`testing/component/transport/` contains a Docker Compose test suite that exercises
`SocketTransport` methods directly (no sidecar routing, no runtime):

```bash
make -C testing/component/transport test
```

The tester binary (`src/asya-sidecar/cmd/socket-tester/`) covers: basic round-trip,
1 MB large payload, FIFO ordering, requeue, context cancellation, `SendWithDelay` error,
`Ack` no-op, and cross-container delivery.

## Security Notes

- **UID requirement**: the transport does not chmod socket files. All containers
  sharing the mesh volume must run as the same UID (the default when a single image
  is used throughout a Compose file). Do not mix images that run as different users.
- **Queue name sanitisation**: `filepath.Base` is applied to every queue name before
  constructing the socket path, preventing path traversal (`../evil` → `evil.sock`).
- **Frame size cap**: incoming message length is capped at 100 MB; frames that
  advertise a larger length are rejected before any allocation is made.
