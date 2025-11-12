# Actor Sidecar Architecture

Go-based message routing service between async queues and actor runtimes.

## Design Principles

- **Transport Agnostic**: Pluggable interface for multiple queue systems
- **Simple Protocol**: JSON over Unix sockets
- **Fault Tolerant**: NACK retry, timeout handling
- **Stateless**: No shared state between messages
- **Observable**: Structured logging

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Asya🎭 Actor Sidecar                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐     ┌──────────┐     ┌─────────────────┐   │
│  │ Config   │────▶│ Main     │────▶│ Router          │   │
│  └──────────┘     └──────────┘     └────────┬────────┘   │
│                                              │             │
│                   ┌──────────────────────────┼──────────┐ │
│                   │                          │          │ │
│                   ▼                          ▼          ▼ │
│           ┌──────────────┐         ┌──────────────────┐  │
│           │  Transport   │         │ Runtime Client   │  │
│           │  Interface   │         └──────────────────┘  │
│           └──────┬───────┘                 │             │
│                  │                         │             │
│         ┌────────┴────────┐                │             │
│         │                 │                │             │
│         ▼                 ▼                ▼             │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────┐       │
│  │ RabbitMQ    │   │ Runtime     │   │ Metrics  │       │
│  │ Transport   │   │ Client      │   │ Server   │       │
│  └─────────────┘   └─────────────┘   └──────────┘       │
│         │                 │                │             │
└─────────┼─────────────────┼────────────────┼─────────────┘
          │                 │                │
          ▼                 ▼                ▼
    ┌──────────┐      ┌─────────────┐    ┌──────────┐
    │ RabbitMQ │      │   Actor     │    │Prometheus│
    │ Queues   │      │  Runtime    │    │  / Other │
    └──────────┘      └─────────────┘    └──────────┘
```

## Envelope Flow

1. **Receive**: Poll queue → Parse JSON → Validate route
2. **Process**: Send payload to runtime via Unix socket → Wait for response
3. **Route**: Increment current → Determine next queue → Send message
4. **Acknowledge**: ACK on success, NACK on error

## Transport Interface

```go
type Transport interface {
    Receive(ctx context.Context, queueName string) (QueueMessage, error)
    Send(ctx context.Context, queueName string, body []byte) error
    Ack(ctx context.Context, msg QueueMessage) error
    Nack(ctx context.Context, msg QueueMessage) error
    Close() error
}
```

### RabbitMQ Transport

- Topic exchange routing
- Auto queue declaration
- Prefetch control
- Durable messages

## Runtime Protocol

**Request:** Raw payload bytes

**Success:** Runtime returns mutated payload directly
- Single: `{"processed": true}`
- Array: `[{"item": 1}, {"item": 2}]`
- Empty: `null` or `[]`

**Error:** `{"error": "code", "message": "...", "type": "ExceptionType"}`

## Error Handling

| Error | Action | Destination |
|-------|--------|-------------|
| Parse error | Send error | error-end |
| Runtime error | Send error | error-end |
| Timeout | Send error | error-end |
| Empty response | Send original | happy-end |
| Transport error | NACK | retry queue |

## Concurrency

**Current:** Single-threaded (one message at a time)
