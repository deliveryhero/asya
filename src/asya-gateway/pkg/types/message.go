package types

import (
	"encoding/json"
	"time"
)

// MessageStatus represents the lifecycle status of a mesh message.
type MessageStatus string

// Message lifecycle statuses with monotonic ordering.
const (
	MessageStatusPending   MessageStatus = "pending"
	MessageStatusRunning   MessageStatus = "running"
	MessageStatusPaused    MessageStatus = "paused"
	MessageStatusSucceeded MessageStatus = "succeeded"
	MessageStatusFailed    MessageStatus = "failed"
	MessageStatusCanceled  MessageStatus = "canceled"
)

// statusOrder defines monotonic ordering for status transitions.
// Higher values can overwrite lower ones, never the reverse.
var statusOrder = map[MessageStatus]int{
	MessageStatusPending:   0,
	MessageStatusRunning:   1,
	MessageStatusPaused:    2,
	MessageStatusSucceeded: 3,
	MessageStatusFailed:    3,
	MessageStatusCanceled:  3,
}

// StatusAdvances returns true if newStatus can overwrite currentStatus
// according to monotonic ordering rules.
func StatusAdvances(current, next MessageStatus) bool {
	return statusOrder[next] > statusOrder[current]
}

// IsTerminal returns true if the status is a terminal state.
func (s MessageStatus) IsTerminal() bool {
	return statusOrder[s] == 3
}

// Message is the mesh-api's view of an envelope in flight.
// Stored as JSONB in the state-proxy KV table.
type Message struct {
	ID        string          `json:"id"`
	Status    MessageStatus   `json:"status"`
	Data      json.RawMessage `json:"data"`
	CreatedAt time.Time       `json:"created_at"`
	UpdatedAt time.Time       `json:"updated_at"`
}

// MessageData holds the JSONB fields stored inside Message.Data.
type MessageData struct {
	Actor      string   `json:"actor"`
	Progress   float64  `json:"progress,omitempty"`
	Message    string   `json:"message,omitempty"`
	Error      string   `json:"error,omitempty"`
	ContextID  string   `json:"context_id,omitempty"`
	TraceID    string   `json:"trace_id,omitempty"`
	ParentID   string   `json:"parent_id,omitempty"`
	DeadlineAt string   `json:"deadline_at,omitempty"`
	Payload    any      `json:"payload,omitempty"`
	Headers    any      `json:"headers,omitempty"`
	Result     any      `json:"result,omitempty"`
	RouteNext  []string `json:"route_next,omitempty"`
}

// Event is a single event published by a sidecar or consumed by an SSE client.
type Event struct {
	Type   string          `json:"type"`             // "status" or "fly"
	Status MessageStatus   `json:"status,omitempty"` // set when Type == "status"
	Data   json.RawMessage `json:"data,omitempty"`
}

// ListParams defines filtering and pagination for message listing.
type ListParams struct {
	Prefix  string         `json:"prefix,omitempty"`
	Filters map[string]any `json:"filter,omitempty"`
	Sort    []string       `json:"sort,omitempty"`
	Limit   int            `json:"limit,omitempty"`
	Offset  int            `json:"offset,omitempty"`
}
