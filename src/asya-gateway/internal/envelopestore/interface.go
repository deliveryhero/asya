package envelopestore

import (
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// EnvelopeStore defines the interface for envelope storage
type EnvelopeStore interface {
	// Create creates a new envelope
	Create(envelope *types.Envelope) error

	// Get retrieves a envelope by ID
	Get(id string) (*types.Envelope, error)

	// Update updates a envelope's status
	Update(update types.EnvelopeUpdate) error

	// UpdateProgress updates envelope progress (lighter weight than Update)
	UpdateProgress(update types.EnvelopeUpdate) error

	// GetUpdates retrieves all updates for an envelope (optionally filtered by time)
	GetUpdates(id string, since *time.Time) ([]types.EnvelopeUpdate, error)

	// Subscribe creates a listener channel for envelope updates
	Subscribe(id string) chan types.EnvelopeUpdate

	// Unsubscribe removes a listener channel
	Unsubscribe(id string, ch chan types.EnvelopeUpdate)

	// IsActive checks if a envelope is still active
	IsActive(id string) bool
}
