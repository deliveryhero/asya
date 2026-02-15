package transport

import (
	"context"
	"errors"
	"time"
)

// ErrDelayNotSupported is returned by SendWithDelay when the transport does not
// support delayed delivery natively (e.g. RabbitMQ without the delayed-message plugin).
var ErrDelayNotSupported = errors.New("transport does not support delayed delivery")

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

	// SendWithDelay sends a message to the specified queue with a delivery delay.
	// Returns ErrDelayNotSupported if the transport lacks native delayed delivery.
	SendWithDelay(ctx context.Context, queueName string, body []byte, delay time.Duration) error

	// Ack acknowledges successful processing of a message
	Ack(ctx context.Context, msg QueueMessage) error

	// Requeue returns a message to the queue for immediate redelivery.
	// Best-effort last-resort infrastructure signal before crashing.
	Requeue(ctx context.Context, msg QueueMessage) error

	// Close closes the transport connection
	Close() error
}
