package envelopestore

import (
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// EnvelopeListParams defines filtering and pagination parameters for listing tasks.
type EnvelopeListParams struct {
	Status    *types.EnvelopeStatus
	ContextID string
	Limit     int // 0 = no limit
	Offset    int
}

// EnvelopeStore defines the interface for task storage
type EnvelopeStore interface {
	// Create creates a new task
	Create(envelope *types.Envelope) error

	// Get retrieves a task by ID
	Get(id string) (*types.Envelope, error)

	// Update updates a task's status
	Update(update types.EnvelopeUpdate) error

	// UpdateProgress updates task progress (lighter weight than Update)
	UpdateProgress(update types.EnvelopeUpdate) error

	// GetUpdates retrieves all updates for a task (optionally filtered by time)
	GetUpdates(id string, since *time.Time) ([]types.EnvelopeUpdate, error)

	// Subscribe creates a listener channel for task updates
	Subscribe(id string) chan types.EnvelopeUpdate

	// Unsubscribe removes a listener channel
	Unsubscribe(id string, ch chan types.EnvelopeUpdate)

	// IsActive checks if a task is still active
	IsActive(id string) bool

	// Resume transitions a paused task back to running, restarting the timeout timer
	// with the remaining timeout budget. Returns the updated task.
	Resume(id string) (*types.Envelope, error)

	// List returns tasks filtered by params, with pagination. Returns (tasks, totalCount, error).
	List(params EnvelopeListParams) ([]*types.Envelope, int, error)

	// NotifyFLY dispatches an ephemeral FLY event to in-process subscribers without persisting to storage.
	// Used for streaming LLM tokens and real-time progress updates.
	NotifyFLY(id string, payload []byte)
}
