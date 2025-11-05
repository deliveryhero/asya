package queue

import (
	"context"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ActorMessage represents the message format sent to actors
type ActorMessage struct {
	JobID    string      `json:"job_id"`
	Route    types.Route `json:"route"`
	Payload  any         `json:"payload"`
	Deadline string      `json:"deadline,omitempty"` // ISO8601 timestamp
}

// QueueMessage represents a message received from a queue
type QueueMessage interface {
	Body() []byte
	DeliveryTag() uint64
}

// Client defines the interface for sending and receiving messages from queues
type Client interface {
	SendMessage(ctx context.Context, job *types.Job) error
	Receive(ctx context.Context, queueName string) (QueueMessage, error)
	Ack(ctx context.Context, msg QueueMessage) error
	Close() error
}
