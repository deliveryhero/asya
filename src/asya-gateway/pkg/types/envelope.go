package types

import "time"

// EnvelopeStatus represents the current state of an envelope (MCP-style lowercase)
type EnvelopeStatus string

const (
	EnvelopeStatusPending   EnvelopeStatus = "pending"
	EnvelopeStatusRunning   EnvelopeStatus = "running"
	EnvelopeStatusSucceeded EnvelopeStatus = "succeeded"
	EnvelopeStatusFailed    EnvelopeStatus = "failed"
	EnvelopeStatusUnknown   EnvelopeStatus = "unknown"
)

// Envelope represents an envelope in the system.
//
// Fanout ID Semantics:
// When an actor returns an array response, the sidecar creates multiple envelopes (fanout).
// The first fanout envelope retains the original ID to preserve SSE streaming compatibility.
// Subsequent fanout envelopes receive suffixed IDs following the pattern: {original_id}-{index}
//
// Example fanout from envelope "abc-123" returning 3 items:
//   - Index 0: ID = "abc-123"      (original ID, SSE clients can track this)
//   - Index 1: ID = "abc-123-1"    (fanout child)
//   - Index 2: ID = "abc-123-2"    (fanout child)
//
// All fanout children have ParentID set to the original envelope ID for traceability.
// This design ensures:
//   - SSE streaming works for at least the first fanout envelope
//   - Fanout children don't overwrite each other in the database
//   - Parent-child relationships are explicit via ParentID field
//   - Log queries can find all related envelopes via ID prefix matching
type Envelope struct {
	ID               string                 `json:"id"`
	ParentID         *string                `json:"parent_id,omitempty"` // Set for fanout children (index > 0)
	Status           EnvelopeStatus         `json:"status"`
	Route            Route                  `json:"route"`
	Headers          map[string]interface{} `json:"headers,omitempty"`
	Payload          any                    `json:"payload"`
	Result           any                    `json:"result,omitempty"`
	Error            string                 `json:"error,omitempty"`
	TimeoutSec       int                    `json:"timeout_seconds,omitempty"` // Total timeout in seconds
	Deadline         time.Time              `json:"deadline,omitempty"`        // Absolute deadline
	ProgressPercent  float64                `json:"progress_percent"`
	CurrentActorIdx  int                    `json:"current_actor_idx"`
	CurrentActorName string                 `json:"current_actor_name,omitempty"`
	Message          string                 `json:"message,omitempty"` // Current progress message
	ActorsCompleted  int                    `json:"actors_completed"`
	TotalActors      int                    `json:"total_actors"`
	CreatedAt        time.Time              `json:"created_at"`
	UpdatedAt        time.Time              `json:"updated_at"`
}

// Route represents the envelope routing information
type Route struct {
	Actors   []string               `json:"actors"`
	Current  int                    `json:"current"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// EnvelopeUpdate represents an internal state change event for an envelope.
//
// INTERNAL USE: This type is used within the gateway for:
// - Database persistence (updating envelope table and envelope_updates table)
// - SSE event streaming to clients (sent via /envelopes/{id}/stream)
// - In-memory state management and event notification
//
// EnvelopeUpdate includes full envelope lifecycle events (status changes, results, errors)
// and is the unified format for all state changes, whether from progress updates,
// final status reports, or internal events like timeouts.
//
// Created by: Gateway handlers when processing ProgressUpdate (from sidecars) or
// final status updates (from end actors like happy-end/error-end).
type EnvelopeUpdate struct {
	ID              string         `json:"id"`
	Status          EnvelopeStatus `json:"status"`                      // Envelope status (pending/running/succeeded/failed)
	Message         string         `json:"message,omitempty"`           // Human-readable status message
	Result          any            `json:"result,omitempty"`            // Final result (only for final states)
	Error           string         `json:"error,omitempty"`             // Error message (only for failed status)
	ProgressPercent *float64       `json:"progress_percent,omitempty"`  // Progress 0-100 (nil if not a progress update)
	Actor           string         `json:"actor,omitempty"`             // Current actor name (for progress updates)
	Actors          []string       `json:"actors,omitempty"`            // Full route (may be modified by envelope-mode actors)
	CurrentActorIdx *int           `json:"current_actor_idx,omitempty"` // Index of current actor (0-based, nil for non-progress updates)
	EnvelopeState   *string        `json:"envelope_state,omitempty"`    // Envelope processing state at current actor: "received" | "processing" | "completed"
	Timestamp       time.Time      `json:"timestamp"`                   // When this update occurred
}

// ProgressUpdate represents a progress report sent FROM sidecars TO the gateway.
//
// EXTERNAL API: This type is used for the POST /envelopes/{id}/progress endpoint.
// Sidecars send these updates as actors process envelopes to report:
// - Which actor is currently processing (CurrentActorIdx)
// - Envelope processing state ("received", "processing", "completed")
// - Updated routing table (Actors array may be modified by envelope-mode actors)
//
// Data flow:
//
//	Sidecar                    Gateway                      Database/SSE
//	-------                    -------                      ------------
//	ProgressUpdate    --->   HandleEnvelopeProgress
//	(POST /progress)           |
//	                           v
//	                      Transform to
//	                      EnvelopeUpdate     --->    JobStore.UpdateProgress()
//	                      (internal event)              |
//	                                                    v
//	                                              - Update DB (route_actors field)
//	                                              - Stream to SSE clients
//
// Sent by: Sidecar's progress reporter at three points per actor:
// 1. "received" - Message pulled from queue, before forwarding to runtime
// 2. "processing" - Message sent to runtime via Unix socket
// 3. "completed" - Runtime returned successful response
type ProgressUpdate struct {
	ID              string   `json:"id"`
	Actors          []string `json:"actors"`            // Full route (may differ from original if actor modified it)
	CurrentActorIdx int      `json:"current_actor_idx"` // Index of current actor being processed (0-based)
	Status          string   `json:"status"`            // Actor status: "received" | "processing" | "completed"
	Message         string   `json:"message,omitempty"` // Optional progress message
	ProgressPercent float64  `json:"progress_percent"`  // Calculated by gateway based on actor progress
}
