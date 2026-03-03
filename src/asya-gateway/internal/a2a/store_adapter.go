package a2a

import (
	"context"
	"fmt"
	"strings"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// StoreAdapter wraps the internal TaskStore to implement a2asrv.TaskStore.
type StoreAdapter struct {
	internal taskstore.TaskStore
}

// NewStoreAdapter creates a new StoreAdapter wrapping the provided internal store.
func NewStoreAdapter(store taskstore.TaskStore) *StoreAdapter {
	return &StoreAdapter{
		internal: store,
	}
}

// Save translates a2a.Task state change to internal TaskUpdate and calls internal.Update.
func (a *StoreAdapter) Save(ctx context.Context, task *a2alib.Task, event a2alib.Event, prev a2alib.TaskVersion) (a2alib.TaskVersion, error) {
	status := FromA2AState(task.Status.State)

	update := types.TaskUpdate{
		ID:        string(task.ID),
		Status:    status,
		Timestamp: time.Now(),
	}

	if task.Status.Message != nil {
		var texts []string
		for _, part := range task.Status.Message.Parts {
			switch p := part.(type) {
			case *a2alib.TextPart:
				texts = append(texts, p.Text)
			case a2alib.TextPart:
				texts = append(texts, p.Text)
			}
		}
		update.Message = strings.Join(texts, "\n")
	}

	if err := a.internal.Update(update); err != nil {
		return 0, fmt.Errorf("failed to update task: %w", err)
	}

	updatedTask, err := a.internal.Get(string(task.ID))
	if err != nil {
		return 0, fmt.Errorf("failed to get updated task: %w", err)
	}

	version := a2alib.TaskVersion(updatedTask.UpdatedAt.UnixNano())
	return version, nil
}

// Get calls internal.Get and translates types.Task to a2a.Task.
func (a *StoreAdapter) Get(ctx context.Context, taskID a2alib.TaskID) (*a2alib.Task, a2alib.TaskVersion, error) {
	task, err := a.internal.Get(string(taskID))
	if err != nil {
		if err == taskstore.ErrNotFound || strings.Contains(err.Error(), "task not found") {
			return nil, 0, a2alib.ErrTaskNotFound
		}
		return nil, 0, fmt.Errorf("failed to get task: %w", err)
	}

	a2aTask := internalToA2ATask(task)
	version := a2alib.TaskVersion(task.UpdatedAt.UnixNano())

	return a2aTask, version, nil
}

// List translates status filter, calls internal.List, and converts results.
func (a *StoreAdapter) List(ctx context.Context, req *a2alib.ListTasksRequest) (*a2alib.ListTasksResponse, error) {
	var statusFilter *types.TaskStatus
	if req.Status != "" {
		status := FromA2AState(req.Status)
		statusFilter = &status
	}

	tasks, err := a.internal.List(statusFilter)
	if err != nil {
		return nil, fmt.Errorf("failed to list tasks: %w", err)
	}

	a2aTasks := make([]*a2alib.Task, 0, len(tasks))
	for _, task := range tasks {
		a2aTasks = append(a2aTasks, internalToA2ATask(task))
	}

	return &a2alib.ListTasksResponse{
		Tasks:     a2aTasks,
		TotalSize: len(a2aTasks),
		PageSize:  len(a2aTasks),
	}, nil
}

// internalToA2ATask converts an internal types.Task to a2a.Task.
func internalToA2ATask(task *types.Task) *a2alib.Task {
	a2aTask := &a2alib.Task{
		ID:        a2alib.TaskID(task.ID),
		ContextID: task.ContextID,
		Status: a2alib.TaskStatus{
			State: ToA2AState(task.Status),
		},
		Metadata: make(map[string]any),
	}

	if task.Message != "" {
		timestamp := task.UpdatedAt
		msg := a2alib.NewMessage(a2alib.MessageRoleAgent, &a2alib.TextPart{Text: task.Message})
		msg.TaskID = a2alib.TaskID(task.ID)
		msg.ContextID = task.ContextID
		a2aTask.Status.Message = msg
		a2aTask.Status.Timestamp = &timestamp
	}

	return a2aTask
}
