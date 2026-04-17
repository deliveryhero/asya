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
func NewActorEnvelope(envelope *types.Envelope) (ActorEnvelope, error) {
	if envelope.Route.Curr == "" {
		return ActorEnvelope{}, fmt.Errorf("route has no current actor (curr is empty)")
	}

	actorName := envelope.Route.Curr
	now := time.Now().UTC().Format(time.RFC3339)

	status := &ActorEnvelopeStatus{
		Phase:       "pending",
		Actor:       actorName,
		Attempt:     1,
		MaxAttempts: 1,
		CreatedAt:   now,
		UpdatedAt:   now,
	}

	if !envelope.Deadline.IsZero() {
		status.DeadlineAt = envelope.Deadline.UTC().Format(time.RFC3339)
	}

	msg := ActorEnvelope{
		ID:      envelope.ID,
		Route:   envelope.Route,
		Payload: envelope.Payload,
		Status:  status,
	}

	return msg, nil
}

// Message represents a message received from a queue
type Message interface {
	Body() []byte
	DeliveryTag() uint64
}

// Client defines the interface for sending and receiving messages from queues
type Client interface {
	SendMessage(ctx context.Context, envelope *types.Envelope) error
	Receive(ctx context.Context, queueName string) (Message, error)
	Ack(ctx context.Context, msg Message) error
	Close() error
}
