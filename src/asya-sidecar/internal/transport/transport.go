package transport

import (
	"context"
)

// QueueMessage represents a message received from a queue
type QueueMessage struct {
	ID            string
	Body          []byte
	ReceiptHandle interface{}       // Transport-specific receipt handle
	Headers       map[string]string // User-defined metadata (protocol-level headers)
}

// Transport defines the interface for queue transport implementations
type Transport interface {
	// Receive receives a message from the specified queue
	Receive(ctx context.Context, queueName string) (QueueMessage, error)

	// Send sends a message to the specified queue
	Send(ctx context.Context, queueName string, body []byte) error

	// Ack acknowledges successful processing of a message
	Ack(ctx context.Context, msg QueueMessage) error

	// Nack negatively acknowledges a message (for retry)
	Nack(ctx context.Context, msg QueueMessage) error

	// TODO: Add Requeue method for message redelivery behavior
	// Requeue(ctx context.Context, msg QueueMessage, visibilityTimeout time.Duration) error
	// This would allow explicit control over message redelivery timing instead of
	// relying on queue visibility timeout after pod crash

	// Close closes the transport connection
	Close() error
}
