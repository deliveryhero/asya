package queue

import (
	"context"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ActorEnvelope represents the envelope format sent to actors
type ActorEnvelope struct {
	ID       string      `json:"id"`
	Route    types.Route `json:"route"`
	Payload  any         `json:"payload"`
	Deadline string      `json:"deadline,omitempty"` // ISO8601 timestamp
}

// QueueMessage represents a envelope received from a queue
type QueueMessage interface {
	Body() []byte
	DeliveryTag() uint64
}

// Client defines the interface for sending and receiving envelopes from queues
type Client interface {
	SendEnvelope(ctx context.Context, envelope *types.Envelope) error
	Receive(ctx context.Context, queueName string) (QueueMessage, error)
	Ack(ctx context.Context, msg QueueMessage) error
	Close() error
}
