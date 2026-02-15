package queue

import (
	"context"
	"fmt"
	"time"

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

// NewActorMessage creates an ActorMessage from a Task with validated route and initial status.
func NewActorMessage(task *types.Task) (ActorMessage, error) {
	if len(task.Route.Actors) == 0 {
		return ActorMessage{}, fmt.Errorf("route has no actors")
	}
	if task.Route.Current < 0 || task.Route.Current >= len(task.Route.Actors) {
		return ActorMessage{}, fmt.Errorf("invalid route.current=%d for actors length %d", task.Route.Current, len(task.Route.Actors))
	}

	actorName := task.Route.Actors[task.Route.Current]
	now := time.Now().UTC().Format(time.RFC3339)

	msg := ActorMessage{
		ID:      task.ID,
		Route:   task.Route,
		Payload: task.Payload,
		Status: &ActorMessageStatus{
			Phase:       "pending",
			Actor:       actorName,
			Attempt:     1,
			MaxAttempts: 1,
			CreatedAt:   now,
			UpdatedAt:   now,
		},
	}

	if !task.Deadline.IsZero() {
		msg.Deadline = task.Deadline.Format("2006-01-02T15:04:05Z07:00")
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
