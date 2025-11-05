package jobs

import "github.com/deliveryhero/asya/asya-gateway/pkg/types"

// JobStore defines the interface for job storage
type JobStore interface {
	// Create creates a new job
	Create(job *types.Job) error

	// Get retrieves a job by ID
	Get(id string) (*types.Job, error)

	// Update updates a job's status
	Update(update types.JobUpdate) error

	// UpdateProgress updates job progress (lighter weight than Update)
	UpdateProgress(update types.JobUpdate) error

	// Subscribe creates a listener channel for job updates
	Subscribe(jobID string) chan types.JobUpdate

	// Unsubscribe removes a listener channel
	Unsubscribe(jobID string, ch chan types.JobUpdate)

	// IsActive checks if a job is still active
	IsActive(jobID string) bool
}
