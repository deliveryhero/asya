package queue

import (
	"context"
	"fmt"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ActorMeshageStatus represents the lifecycle status of a message
type ActorMeshageStatus struct {
	Phase       string `json:"phase"`
	Actor       string `json:"actor"`
	Attempt     int    `json:"attempt"`
	MaxAttempts int    `json:"max_attempts"`
	CreatedAt   string `json:"created_at"`
	UpdatedAt   string `json:"updated_at"`
	DeadlineAt  string `json:"deadline_at,omitempty"`
}

// ActorMeshage represents the message format sent to actors
type ActorMeshage struct {
	ID      string              `json:"id"`
	Route   types.Route         `json:"route"`
	Payload any                 `json:"payload"`
	Status  *ActorMeshageStatus `json:"status,omitempty"`
}

// NewActorMeshage creates an ActorMeshage from a Task with validated route and initial status.
func NewActorMeshage(task *types.Task) (ActorMeshage, error) {
	if task.Route.Curr == "" {
		return ActorMeshage{}, fmt.Errorf("route has no current actor (curr is empty)")
	}

	actorName := task.Route.Curr
	now := time.Now().UTC().Format(time.RFC3339)

	status := &ActorMeshageStatus{
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

	msg := ActorMeshage{
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
