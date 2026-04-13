---
title: Implement socket transport in sidecar for local testing (Docker Compose + integration tests)
status: merged
priority: 2
assignee: Artem Yushkovskiy
parent: n6g6h
tags:
  - worktree:.worktrees/asya-lab/cavw.implement-socket-transport-sidecar-docker-compose-local-testing
  - branch:asya-lab/cavw.implement-socket-transport-sidecar-docker-compose-local-testing
  - pr:299
---

Implement a Unix socket transport (`ASYA_TRANSPORT=socket`) in the Go sidecar for local Docker Compose testing. This transport replaces message queues (SQS/RabbitMQ) with Unix domain sockets, enabling full flow testing locally without external infrastructure.

## Context

The `asya d up` command runs the same sidecar+runtime architecture as K8s, but with a lightweight socket transport instead of a real message queue. Each actor's sidecar listens on a Unix socket; a shared Docker volume makes all sockets visible to all sidecars. See `adr.k-d-command-split.md` §3.

Also useful for integration tests — decouples them from RabbitMQ/SQS.

## Design

### Transport interface

Implements the existing `Consumer`/`Producer` interface in `src/asya-sidecar/internal/transport/`:

```go
// Consumer reads envelopes from a Unix socket
type SocketConsumer struct { ... }
func (c *SocketConsumer) Consume(ctx context.Context) (<-chan *Message, error)
func (c *SocketConsumer) Ack(msg *Message) error
func (c *SocketConsumer) Nack(msg *Message) error

// Producer writes envelopes to other actors' Unix sockets
type SocketProducer struct { ... }
func (p *SocketProducer) Send(ctx context.Context, queue string, envelope []byte) error
```

### Socket layout

Each actor's sidecar creates a listener at `/var/run/asya/mesh/<actor-name>.sock`. A shared Docker volume (`asya-mesh`) mounts this directory into all sidecar containers, so any sidecar can send to any other actor's socket.

### Envelope delivery

- **Sequential FIFO**: one message at a time per socket (no concurrent consumers)
- **Single replica**: one consumer per socket (acceptable for local testing)
- **No DLQ**: errors go to x-sump socket directly
- **No KEDA**: no autoscaling in Docker Compose

### Ack/Nack semantics

- `Ack`: remove message from in-flight buffer (done)
- `Nack`: forward to x-sump socket (same as queue-based Nack behavior)

### Config

```yaml
# Environment variable
ASYA_TRANSPORT=socket

# Socket path convention
ASYA_SOCKET_DIR=/var/run/asya/mesh   # shared volume mount point
```

### Docker Compose integration

`asya d up` generates a compose file with:
- Shared volume `asya-mesh` mounted at `/var/run/asya/mesh` in all sidecars
- `ASYA_TRANSPORT=socket` on all sidecars
- No RabbitMQ/SQS containers needed

## Files

- `src/asya-sidecar/internal/transport/socket/` — new package
  - `consumer.go` — SocketConsumer
  - `producer.go` — SocketProducer
  - `consumer_test.go`, `producer_test.go`
- `src/asya-sidecar/internal/transport/factory.go` — register `socket` transport type
- Integration tests can use socket transport for lighter test setup

## Constraints (acceptable for local testing)

- Single replica per actor
- No queue-level DLQ
- No KEDA autoscaling
- Sequential FIFO delivery
- No message persistence (in-memory only)

## References

- `adr.k-d-command-split.md` §3 (socket transport design decision)
- RFC §6 (Docker Compose architecture with socket transport)
