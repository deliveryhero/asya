package types

import "time"

// TaskStatus represents the current state of a task (MCP-style lowercase)
type TaskStatus string

const (
	TaskStatusPending   TaskStatus = "pending"
	TaskStatusRunning   TaskStatus = "running"
	TaskStatusSucceeded TaskStatus = "succeeded"
	TaskStatusFailed    TaskStatus = "failed"
	TaskStatusUnknown   TaskStatus = "unknown"
)

// Task represents a task in the system.
//
// Fanout ID Semantics:
// When an actor returns an array response, the sidecar creates multiple tasks (fanout).
// The first fanout task retains the original ID to preserve SSE streaming compatibility.
// Subsequent fanout tasks receive suffixed IDs following the pattern: {original_id}-{index}
//
// Example fanout from task "abc-123" returning 3 items:
//   - Index 0: ID = "abc-123"      (original ID, SSE clients can track this)
//   - Index 1: ID = "abc-123-1"    (fanout child)
//   - Index 2: ID = "abc-123-2"    (fanout child)
//
// All fanout children have ParentID set to the original task ID for traceability.
// This design ensures:
//   - SSE streaming works for at least the first fanout task
//   - Fanout children don't overwrite each other in the database
//   - Parent-child relationships are explicit via ParentID field
//   - Log queries can find all related tasks via ID prefix matching
type Task struct {
	ID               string                 `json:"id"`
	ParentID         *string                `json:"parent_id,omitempty"`  // Set for fanout children (index > 0)
	ContextID        string                 `json:"context_id,omitempty"` // Groups related tasks into conversations
	Status           TaskStatus             `json:"status"`
	Route            Route                  `json:"route"`
	Headers          map[string]interface{} `json:"headers,omitempty"`
	Payload          any                    `json:"payload"`
	Result           any                    `json:"result,omitempty"`
	Error            string                 `json:"error,omitempty"`
	TimeoutSec       int                    `json:"timeout_seconds,omitempty"` // Total timeout in seconds
	Deadline         time.Time              `json:"deadline,omitempty"`        // Absolute deadline
	ProgressPercent  float64                `json:"progress_percent"`
	CurrentActorName string                 `json:"current_actor_name,omitempty"`
	Message          string                 `json:"message,omitempty"` // Current progress message
	ActorsCompleted  int                    `json:"actors_completed"`
	TotalActors      int                    `json:"total_actors"`
	CreatedAt        time.Time              `json:"created_at"`
	UpdatedAt        time.Time              `json:"updated_at"`
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

// TaskUpdate represents an internal state change event for a task.
//
// INTERNAL USE: This type is used within the gateway for:
// - Database persistence (updating task table and task_updates table)
// - SSE event streaming to clients (sent via /tasks/{id}/stream)
// - In-memory state management and event notification
//
// TaskUpdate includes full task lifecycle events (status changes, results, errors)
// and is the unified format for all state changes, whether from progress updates,
// final status reports, or internal events like timeouts.
//
// Created by: Gateway handlers when processing ProgressUpdate (from sidecars) or
// final status updates (from end actors like x-sink/x-sump).
type TaskUpdate struct {
	ID              string     `json:"id"`
	Status          TaskStatus `json:"status"`                     // Task status (pending/running/succeeded/failed)
	Message         string     `json:"message,omitempty"`          // Human-readable status message
	Result          any        `json:"result,omitempty"`           // Final result (only for final states)
	Error           string     `json:"error,omitempty"`            // Error message (only for failed status)
	ProgressPercent *float64   `json:"progress_percent,omitempty"` // Progress 0-100 (nil if not a progress update)
	Actor           string     `json:"actor,omitempty"`            // Current actor name (for progress updates)
	Prev            []string   `json:"prev,omitempty"`             // Actors that have already processed this message
	Curr            string     `json:"curr,omitempty"`             // Actor currently processing ("" at end-of-route)
	Next            []string   `json:"next,omitempty"`             // Actors remaining after curr
	TaskState       *string    `json:"task_state,omitempty"`       // Task processing state at current actor: "received" | "processing" | "completed"
	Timestamp       time.Time  `json:"timestamp"`                  // When this update occurred
}

// ProgressUpdate represents a progress report sent FROM sidecars TO the gateway.
//
// EXTERNAL API: This type is used for the POST /tasks/{id}/progress endpoint.
// Sidecars send these updates as actors process tasks to report:
// - Which actor is currently processing (Curr)
// - Task processing state ("received", "processing", "completed")
// - Updated routing table (Prev/Curr/Next may be modified by envelope-mode actors)
//
// Data flow:
//
//	Sidecar                    Gateway                      Database/SSE
//	-------                    -------                      ------------
//	ProgressUpdate    --->   HandleTaskProgress
//	(POST /progress)           |
//	                           v
//	                      Transform to
//	                      TaskUpdate        --->    TaskStore.UpdateProgress()
//	                      (internal event)              |
//	                                                    v
//	                                              - Update DB (route_prev/curr/next fields)
//	                                              - Stream to SSE clients
//
// Sent by: Sidecar's progress reporter at three points per actor:
// 1. "received" - Message pulled from queue, before forwarding to runtime
// 2. "processing" - Message sent to runtime via Unix socket
// 3. "completed" - Runtime returned successful response
type ProgressUpdate struct {
	ID              string   `json:"id"`
	Prev            []string `json:"prev"`              // Actors that have already processed this message
	Curr            string   `json:"curr"`              // Actor currently processing ("" at end-of-route)
	Next            []string `json:"next"`              // Actors remaining after curr
	Status          string   `json:"status"`            // Actor status: "received" | "processing" | "completed"
	Message         string   `json:"message,omitempty"` // Optional progress message
	ProgressPercent float64  `json:"progress_percent"`  // Calculated by gateway based on actor progress
}

// CreateTaskRequest is sent by the sidecar to create fanout child tasks.
type CreateTaskRequest struct {
	ID       string   `json:"id"`
	ParentID *string  `json:"parent_id,omitempty"`
	Prev     []string `json:"prev"`
	Curr     string   `json:"curr"`
	Next     []string `json:"next"`
}
