package mesh

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// QueueClientSender adapts queue.Client to the EnvelopeSender interface
// used by the mesh handler. It converts raw envelope JSON into the
// types.Envelope struct that queue.Client.SendMessage expects.
type QueueClientSender struct {
	client    queue.Client
	namespace string
}

// NewQueueClientSender wraps a queue.Client as an EnvelopeSender.
func NewQueueClientSender(client queue.Client, namespace string) *QueueClientSender {
	return &QueueClientSender{client: client, namespace: namespace}
}

// Send dispatches an envelope to the actor's queue.
// It unmarshals the raw envelope JSON into a types.Envelope, sets the route,
// and delegates to queue.Client.SendMessage.
func (s *QueueClientSender) Send(ctx context.Context, actor, namespace string, envelopeJSON []byte) error {
	// Parse the envelope from raw JSON
	var raw struct {
		ID      string         `json:"id"`
		Route   types.Route    `json:"route"`
		Headers map[string]any `json:"headers"`
		Payload any            `json:"payload"`
		Status  any            `json:"status,omitempty"`
	}
	if err := json.Unmarshal(envelopeJSON, &raw); err != nil {
		return fmt.Errorf("unmarshal envelope: %w", err)
	}

	// Build a types.Envelope for queue.Client.SendMessage
	envelope := &types.Envelope{
		ID:      raw.ID,
		Status:  types.EnvelopeStatusPending,
		Route:   raw.Route,
		Headers: raw.Headers,
		Payload: raw.Payload,
	}

	// Use provided namespace or fall back to default
	ns := namespace
	if ns == "" {
		ns = s.namespace
	}
	// The queue client uses the namespace internally via its config
	_ = ns

	return s.client.SendMessage(ctx, envelope)
}
