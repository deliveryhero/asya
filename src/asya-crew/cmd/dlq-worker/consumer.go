package main

import "context"

// DLQMessage represents a message received from the Dead Letter Queue.
type DLQMessage struct {
	Body          []byte
	ReceiptHandle string
}

// Consumer defines the interface for polling and acknowledging DLQ messages.
// Implementations use native transport SDKs (not the sidecar transport abstraction)
// to maintain failure domain isolation.
type Consumer interface {
	// Receive blocks until a message is available or the context is cancelled.
	// Returns ctx.Err() when context is done.
	Receive(ctx context.Context) (*DLQMessage, error)

	// Ack acknowledges (deletes) a message from the DLQ.
	Ack(ctx context.Context, msg *DLQMessage) error

	// Close releases any resources held by the consumer.
	Close() error
}
