package messages

import (
	"encoding/json"
	"time"
)

// Status phase constants
const (
	PhasePending    = "pending"
	PhaseProcessing = "processing"
	PhaseRetrying   = "retrying"
	PhaseSucceeded  = "succeeded"
	PhaseFailed     = "failed"
)

// Status reason constants
const (
	ReasonCompleted           = "Completed"
	ReasonRuntimeError        = "RuntimeError"
	ReasonTimeout             = "Timeout"
	ReasonParseError          = "ParseError"
	ReasonRouteMismatch       = "RouteMismatch"
	ReasonMaxRetriesExhausted = "MaxRetriesExhausted"
	ReasonNonRetryableFailure = "NonRetryableFailure"
)

// StatusError captures error details within a status
type StatusError struct {
	Message   string   `json:"message"`
	Type      string   `json:"type,omitempty"`
	MRO       []string `json:"mro,omitempty"`
	Traceback string   `json:"traceback,omitempty"`
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

// Route represents the routing state of a message through the actor pipeline.
// prev: actors that have already processed this message (read-only to handlers).
// curr: the actor currently processing this message (read-only to handlers).
// next: actors remaining after curr (writable by envelope-mode handlers).
type Route struct {
	Prev []string `json:"prev"`
	Curr string   `json:"curr"`
	Next []string `json:"next"`
}

// Message represents the full message structure with routing metadata.
//
// Fanout ID Semantics:
// When an actor handler uses yield (generator), the runtime sends multiple response
// frames over the Unix socket. The sidecar reads each frame and creates a separate
// message for routing.
// The first fanout message retains the original ID to preserve SSE streaming compatibility.
// Subsequent fanout messages receive UUID4 IDs to avoid collisions across concurrent fan-outs.
//
// Example fanout from message "abc-123" returning 3 items:
//   - Index 0: ID = "abc-123"                               ParentID = nil        (original ID, SSE clients can track this)
//   - Index 1: ID = "550e8400-e29b-41d4-a716-446655440000"  ParentID = "abc-123"  (fanout child, UUID4)
//   - Index 2: ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"  ParentID = "abc-123"  (fanout child, UUID4)
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
	return r.Curr
}

// GetNextActor returns the next actor name, or empty if at the end
func (r *Route) GetNextActor() string {
	if len(r.Next) > 0 {
		return r.Next[0]
	}
	return ""
}

// HasNextActor returns true if there are more actors after current
func (r *Route) HasNextActor() bool {
	return len(r.Next) > 0
}

// IncrementCurrent shifts the route forward: prev appends curr, curr becomes
// next[0], next shrinks. If next is empty, curr becomes "" to signal end-of-route.
func (r *Route) IncrementCurrent() Route {
	newPrev := make([]string, len(r.Prev)+1)
	copy(newPrev, r.Prev)
	newPrev[len(r.Prev)] = r.Curr
	if len(r.Next) == 0 {
		return Route{Prev: newPrev, Curr: "", Next: []string{}}
	}
	return Route{
		Prev: newPrev,
		Curr: r.Next[0],
		Next: r.Next[1:],
	}
}
