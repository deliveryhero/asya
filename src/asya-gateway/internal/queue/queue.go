package queue

import (
	"context"
	"fmt"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ActorEnvelopeStatus represents the lifecycle status of a message
type ActorEnvelopeStatus struct {
	Phase       string `json:"phase"`
	Actor       string `json:"actor"`
	Attempt     int    `json:"attempt"`
	MaxAttempts int    `json:"max_attempts"`
	CreatedAt   string `json:"created_at"`
	UpdatedAt   string `json:"updated_at"`
	DeadlineAt  string `json:"deadline_at,omitempty"`
}

// ActorEnvelope represents the message format sent to actors
type ActorEnvelope struct {
	ID      string               `json:"id"`
	Route   types.Route          `json:"route"`
	Payload any                  `json:"payload"`
	Status  *ActorEnvelopeStatus `json:"status,omitempty"`
}

// NewActorEnvelope creates an ActorEnvelope from a Task with validated route and initial status.
func NewActorEnvelope(task *types.Task) (ActorEnvelope, error) {
	if task.Route.Curr == "" {
		return ActorEnvelope{}, fmt.Errorf("route has no current actor (curr is empty)")
	}

	actorName := task.Route.Curr
	now := time.Now().UTC().Format(time.RFC3339)

	status := &ActorEnvelopeStatus{
		Phase:       "pending",
		Actor:       actorName,
		Attempt:     1,
		MaxAttempts: 1,
		CreatedAt:   now,
		UpdatedAt:   now,
	}

	if !task.Deadline.IsZero() {
		status.DeadlineAt = task.Deadline.UTC().Format(time.RFC3339)
	}

	msg := ActorEnvelope{
		ID:      task.ID,
		Route:   task.Route,
		Payload: task.Payload,
		Status:  status,
	}

	return msg, nil
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
