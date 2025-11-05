package types

import "time"

// JobStatus represents the current state of a job (K8s-style)
type JobStatus string

const (
	JobStatusPending   JobStatus = "Pending"
	JobStatusRunning   JobStatus = "Running"
	JobStatusSucceeded JobStatus = "Succeeded"
	JobStatusFailed    JobStatus = "Failed"
	JobStatusUnknown   JobStatus = "Unknown"
)

// Job represents a job in the system
type Job struct {
	ID              string    `json:"id"`
	Status          JobStatus `json:"status"`
	Route           Route     `json:"route"`
	Payload         any       `json:"payload"`
	Result          any       `json:"result,omitempty"`
	Error           string    `json:"error,omitempty"`
	TimeoutSec      int       `json:"timeout_seconds,omitempty"` // Total timeout in seconds
	Deadline        time.Time `json:"deadline,omitempty"`        // Absolute deadline
	ProgressPercent float64   `json:"progress_percent"`
	CurrentStep     string    `json:"current_step,omitempty"`
	StepsCompleted  int       `json:"steps_completed"`
	TotalSteps      int       `json:"total_steps"`
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
}

// Route represents the message routing information
type Route struct {
	Steps    []string               `json:"steps"`
	Current  int                    `json:"current"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// JobUpdate represents a status update for a job
type JobUpdate struct {
	JobID           string    `json:"job_id"`
	Status          JobStatus `json:"status"`
	Message         string    `json:"message,omitempty"`
	Result          any       `json:"result,omitempty"`
	Error           string    `json:"error,omitempty"`
	ProgressPercent *float64  `json:"progress_percent,omitempty"`
	Step            string    `json:"step,omitempty"`
	StepStatus      string    `json:"step_status,omitempty"`
	Timestamp       time.Time `json:"timestamp"`
}

// ProgressUpdate represents a progress report from an actor
type ProgressUpdate struct {
	JobID           string  `json:"job_id"`
	Step            string  `json:"step"`
	StepIndex       int     `json:"step_index"`
	TotalSteps      int     `json:"total_steps"`
	Status          string  `json:"status"` // "received" | "processing" | "completed"
	ActorName       string  `json:"actor_name"`
	Message         string  `json:"message,omitempty"`
	ProgressPercent float64 `json:"progress_percent"`
}
