package types

import (
	"encoding/json"
	"time"
)

// EnvelopeStatus represents the current state of an envelope's journey through the mesh.
type EnvelopeStatus string

// Envelope lifecycle statuses.
const (
	EnvelopeStatusPending      EnvelopeStatus = "pending"
	EnvelopeStatusRunning      EnvelopeStatus = "running"
	EnvelopeStatusSucceeded    EnvelopeStatus = "succeeded"
	EnvelopeStatusFailed       EnvelopeStatus = "failed"
	EnvelopeStatusUnknown      EnvelopeStatus = "unknown"
	EnvelopeStatusPaused       EnvelopeStatus = "paused"
	EnvelopeStatusCanceled     EnvelopeStatus = "canceled"
	EnvelopeStatusRejected     EnvelopeStatus = "rejected"
	EnvelopeStatusAuthRequired EnvelopeStatus = "auth_required"
)

// Envelope represents the gateway's tracking record for one envelope in flight through the actor mesh.
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
	ID                  string                 `json:"id"`
	ParentID            *string                `json:"parent_id,omitempty"`  // Set for fanout children (index > 0)
	ContextID           string                 `json:"context_id,omitempty"` // Groups related envelopes into conversations
	Status              EnvelopeStatus         `json:"status"`
	Route               Route                  `json:"route"`
	Headers             map[string]interface{} `json:"headers,omitempty"`
	Payload             any                    `json:"payload"`
	Result              any                    `json:"result,omitempty"`
	Error               string                 `json:"error,omitempty"`
	TimeoutSec          int                    `json:"timeout_seconds,omitempty"`       // Total timeout in seconds
	Deadline            time.Time              `json:"deadline,omitempty"`              // Absolute deadline
	RemainingTimeoutSec *float64               `json:"remaining_timeout_sec,omitempty"` // Saved on pause for freeze/thaw
	ProgressPercent     float64                `json:"progress_percent"`
	CurrentActorName    string                 `json:"current_actor_name,omitempty"`
	Message             string                 `json:"message,omitempty"` // Current progress message
	PauseMetadata       json.RawMessage        `json:"pause_metadata,omitempty"`
	ActorsCompleted     int                    `json:"actors_completed"`
	TotalActors         int                    `json:"total_actors"`
	CreatedAt           time.Time              `json:"created_at"`
	UpdatedAt           time.Time              `json:"updated_at"`
}

// Route represents the routing state of a message through the actor pipeline.
// prev: actors that have already processed this message.
// curr: the actor currently processing (or "" at end-of-route).
// next: actors remaining after curr.
type Route struct {
	Prev []string `json:"prev"`
	Curr string   `json:"curr"`
	Next []string `json:"next"`
}

// EnvelopeUpdate represents an internal state change event for an envelope.
//
// INTERNAL USE: This type is used within the gateway for:
// - Database persistence (updating envelope table and envelope_updates table)
// - SSE event streaming to clients (sent via /mesh/{id}/stream)
// - In-memory state management and event notification
//
// EnvelopeUpdate includes full envelope lifecycle events (status changes, results, errors)
// and is the unified format for all state changes, whether from progress updates,
// final status reports, or internal events like timeouts.
//
// Created by: Gateway handlers when processing EnvelopeProgressUpdate (from sidecars) or
// final status updates (from end actors like x-sink/x-sump).
type EnvelopeUpdate struct {
	ID              string          `json:"id"`
	Status          EnvelopeStatus  `json:"status"`                     // Envelope status (pending/running/succeeded/failed)
	Message         string          `json:"message,omitempty"`          // Human-readable status message
	Result          any             `json:"result,omitempty"`           // Final result (only for final states)
	Error           string          `json:"error,omitempty"`            // Error message (only for failed status)
	ProgressPercent *float64        `json:"progress_percent,omitempty"` // Progress 0-100 (nil if not a progress update)
	Actor           string          `json:"actor,omitempty"`            // Current actor name (for progress updates)
	Prev            []string        `json:"prev,omitempty"`             // Actors that have already processed this message
	Curr            string          `json:"curr,omitempty"`             // Actor currently processing ("" at end-of-route)
	Next            []string        `json:"next,omitempty"`             // Actors remaining after curr
	TaskState       *string         `json:"task_state,omitempty"`       // Envelope processing state at current actor: "received" | "processing" | "completed"
	PartialPayload  json.RawMessage `json:"partial_payload,omitempty"`  // Partial event payload (e.g., LLM tokens) for SSE broadcasting
	PauseMetadata   json.RawMessage `json:"pause_metadata,omitempty"`
	Timestamp       time.Time       `json:"timestamp"` // When this update occurred
}

// EnvelopeProgressUpdate represents a progress report sent FROM sidecars TO the gateway.
//
// EXTERNAL API: This type is used for the POST /mesh/{id}/progress endpoint.
// Sidecars send these updates as actors process envelopes to report:
// - Which actor is currently processing (Curr)
// - Envelope processing state ("received", "processing", "completed")
// - Updated routing table (Prev/Curr/Next may be modified via VFS by actors)
//
// Data flow:
//
//	Sidecar                    Gateway                      Database/SSE
//	-------                    -------                      ------------
//	EnvelopeProgressUpdate --->   HandleMeshProgress
//	(POST /progress)           |
//	                           v
//	                      Transform to
//	                      EnvelopeUpdate    --->    EnvelopeStore.UpdateProgress()
//	                      (internal event)              |
//	                                                    v
//	                                              - Update DB (route_prev/curr/next fields)
//	                                              - Stream to SSE clients
//
// Sent by: Sidecar's progress reporter at three points per actor:
// 1. "received" - Message pulled from queue, before forwarding to runtime
// 2. "processing" - Message sent to runtime via Unix socket
// 3. "completed" - Runtime returned successful response
type EnvelopeProgressUpdate struct {
	ID              string          `json:"id"`
	Prev            []string        `json:"prev"`                     // Actors that have already processed this message
	Curr            string          `json:"curr"`                     // Actor currently processing ("" at end-of-route)
	Next            []string        `json:"next"`                     // Actors remaining after curr
	Status          string          `json:"status"`                   // Actor status: "received" | "processing" | "completed"
	Message         string          `json:"message,omitempty"`        // Optional progress message
	ProgressPercent float64         `json:"progress_percent"`         // Calculated by gateway based on actor progress
	PauseMetadata   json.RawMessage `json:"pause_metadata,omitempty"` // x-asya-pause header content for HITL pause
}

// CreateEnvelopeRequest is sent by the sidecar to create fanout child envelopes.
type CreateEnvelopeRequest struct {
	ID       string   `json:"id"`
	ParentID *string  `json:"parent_id,omitempty"`
	Prev     []string `json:"prev"`
	Curr     string   `json:"curr"`
	Next     []string `json:"next"`
}
