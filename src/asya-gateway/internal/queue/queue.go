package queue

import (
	"context"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ActorMessageStatus represents the lifecycle status of a message
type ActorMessageStatus struct {
	Phase       string `json:"phase"`
	Actor       string `json:"actor"`
	Attempt     int    `json:"attempt"`
	MaxAttempts int    `json:"max_attempts"`
	CreatedAt   string `json:"created_at"`
	UpdatedAt   string `json:"updated_at"`
}

// ActorMessage represents the message format sent to actors
type ActorMessage struct {
	ID       string              `json:"id"`
	Route    types.Route         `json:"route"`
	Payload  any                 `json:"payload"`
	Status   *ActorMessageStatus `json:"status,omitempty"`
	Deadline string              `json:"deadline,omitempty"` // ISO8601 timestamp
}

// QueueMessage represents a message received from a queue
type QueueMessage interface {
	Body() []byte
	DeliveryTag() uint64
}

// Client defines the interface for sending and receiving messages from queues
type Client interface {
	SendMessage(ctx context.Context, task *types.Task) error
	Receive(ctx context.Context, queueName string) (QueueMessage, error)
	Ack(ctx context.Context, msg QueueMessage) error
	Close() error
}
