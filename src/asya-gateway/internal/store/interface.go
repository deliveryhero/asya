package store

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ErrNotFound is returned when a message is not found.
var ErrNotFound = errors.New("message not found")

// ErrStaleStatus is returned when a status update is rejected by monotonic ordering.
var ErrStaleStatus = errors.New("stale status update rejected")

// MessageStore defines the mesh-api's storage interface.
// Persistence methods talk to the state-proxy over HTTP/Unix socket.
// Publish/subscribe methods below use in-process Go channels (not GCP Pub/Sub).
type MessageStore interface {
	// Persistence (state-proxy)
	Create(ctx context.Context, msg *types.Message) error
	Get(ctx context.Context, id string) (*types.Message, error)
	UpdateStatus(ctx context.Context, id string, status types.MessageStatus, data json.RawMessage) error
	Delete(ctx context.Context, id string) error
	List(ctx context.Context, params types.ListParams) ([]*types.Message, int, error)

	// In-process publish/subscribe via Go channels (ephemeral, not persisted)
	Subscribe(id string) <-chan types.Event
	Unsubscribe(id string, ch <-chan types.Event)
	Publish(id string, event types.Event)
}
