package types

import "time"

// ActorHeartbeat represents a status update from an actor
type ActorHeartbeat struct {
	JobID     string    `json:"job_id"`
	ActorName string    `json:"actor_name"`
	Status    string    `json:"status"` // "picked_up", "processing", "completed", "error"
	Message   string    `json:"message,omitempty"`
	Timestamp time.Time `json:"timestamp"`
}

// HeartbeatStatus represents different heartbeat statuses
const (
	HeartbeatPickedUp   = "picked_up"
	HeartbeatProcessing = "processing"
	HeartbeatCompleted  = "completed"
	HeartbeatError      = "error"
)
