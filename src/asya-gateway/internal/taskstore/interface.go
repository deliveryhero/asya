package taskstore

import (
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ListParams defines filtering and pagination parameters for listing tasks.
type ListParams struct {
	Status    *types.TaskStatus
	ContextID string
	Limit     int // 0 = no limit
	Offset    int
}

// TaskStore defines the interface for task storage
type TaskStore interface {
	// Create creates a new task
	Create(task *types.Task) error

	// Get retrieves a task by ID
	Get(id string) (*types.Task, error)

	// Update updates a task's status
	Update(update types.TaskUpdate) error

	// UpdateProgress updates task progress (lighter weight than Update)
	UpdateProgress(update types.TaskUpdate) error

	// GetUpdates retrieves all updates for a task (optionally filtered by time)
	GetUpdates(id string, since *time.Time) ([]types.TaskUpdate, error)

	// Subscribe creates a listener channel for task updates
	Subscribe(id string) chan types.TaskUpdate

	// Unsubscribe removes a listener channel
	Unsubscribe(id string, ch chan types.TaskUpdate)

	// IsActive checks if a task is still active
	IsActive(id string) bool

	// Resume transitions a paused task back to running, restarting the timeout timer
	// with the remaining timeout budget. Returns the updated task.
	Resume(id string) (*types.Task, error)

	// List returns tasks filtered by params, with pagination. Returns (tasks, totalCount, error).
	List(params ListParams) ([]*types.Task, int, error)
}
