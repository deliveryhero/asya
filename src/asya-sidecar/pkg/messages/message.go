package messages

import (
	"encoding/json"
	"time"
)

// Status phase constants
const (
	PhasePending    = "pending"
	PhaseProcessing = "processing"
	PhaseSucceeded  = "succeeded"
	PhaseFailed     = "failed"
)

// Status reason constants
const (
	ReasonCompleted     = "Completed"
	ReasonRuntimeError  = "RuntimeError"
	ReasonTimeout       = "Timeout"
	ReasonParseError    = "ParseError"
	ReasonRouteMismatch = "RouteMismatch"
)

// StatusError captures error details within a status
type StatusError struct {
	Message   string `json:"message"`
	Type      string `json:"type,omitempty"`
	Traceback string `json:"traceback,omitempty"`
}

// Status tracks the lifecycle phase of a message as it moves through actors
type Status struct {
	Phase       string       `json:"phase"`
	Reason      string       `json:"reason,omitempty"`
	Actor       string       `json:"actor"`
	Attempt     int          `json:"attempt"`
	MaxAttempts int          `json:"max_attempts"`
	CreatedAt   string       `json:"created_at"`
	UpdatedAt   string       `json:"updated_at"`
	Error       *StatusError `json:"error,omitempty"`
}

// NewDefaultStatus creates a status with phase=pending for the given actor
func NewDefaultStatus(actor string) *Status {
	now := time.Now().UTC().Format(time.RFC3339)
	return &Status{
		Phase:       PhasePending,
		Actor:       actor,
		Attempt:     1,
		MaxAttempts: 1,
		CreatedAt:   now,
		UpdatedAt:   now,
	}
}

// Route represents the routing information for a message
type Route struct {
	Actors   []string               `json:"actors"`
	Current  int                    `json:"current"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// Message represents the full message structure with routing metadata.
//
// Fanout ID Semantics:
// When an actor handler uses yield (generator), the runtime sends multiple response
// frames over the Unix socket. The sidecar reads each frame and creates a separate
// message for routing.
// The first fanout message retains the original ID to preserve SSE streaming compatibility.
// Subsequent fanout messages receive suffixed IDs following the pattern: {original_id}-{index}
//
// Example fanout from message "abc-123" returning 3 items:
//   - Index 0: ID = "abc-123"      ParentID = nil     (original ID, SSE clients can track this)
//   - Index 1: ID = "abc-123-1"    ParentID = "abc-123" (fanout child)
//   - Index 2: ID = "abc-123-2"    ParentID = "abc-123" (fanout child)
//
// All fanout children have ParentID set to the original message ID for traceability.
type Message struct {
	ID       string                 `json:"id"`
	ParentID *string                `json:"parent_id,omitempty"` // Set for fanout children (index > 0)
	Route    Route                  `json:"route"`
	Headers  map[string]interface{} `json:"headers,omitempty"`
	Payload  json.RawMessage        `json:"payload"`
	Status   *Status                `json:"status,omitempty"`
}

// GetCurrentActor returns the current actor name from the route
func (r *Route) GetCurrentActor() string {
	if r.Current >= 0 && r.Current < len(r.Actors) {
		return r.Actors[r.Current]
	}
	return ""
}

// GetNextActor returns the next actor name, or empty if at the end
func (r *Route) GetNextActor() string {
	nextIndex := r.Current + 1
	if nextIndex >= 0 && nextIndex < len(r.Actors) {
		return r.Actors[nextIndex]
	}
	return ""
}

// HasNextActor returns true if there are more actors after current
func (r *Route) HasNextActor() bool {
	return r.Current+1 < len(r.Actors)
}

// IncrementCurrent creates a new route with incremented current index
func (r *Route) IncrementCurrent() Route {
	return Route{
		Actors:   r.Actors,
		Current:  r.Current + 1,
		Metadata: r.Metadata,
	}
}
