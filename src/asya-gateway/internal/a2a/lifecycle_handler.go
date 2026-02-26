package a2a

import (
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// LifecycleHandler handles task lifecycle operations: pause, cancel, list.
type LifecycleHandler struct {
	taskStore taskstore.TaskStore
}

// NewLifecycleHandler creates a new lifecycle handler.
func NewLifecycleHandler(store taskstore.TaskStore) *LifecycleHandler {
	return &LifecycleHandler{taskStore: store}
}

// HandlePause handles POST /a2a/tasks/{id}:pause
func (h *LifecycleHandler) HandlePause(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	taskID := strings.TrimSuffix(r.PathValue("id"), ":pause")
	if taskID == "" {
		http.Error(w, "Missing task ID", http.StatusBadRequest)
		return
	}

	task, err := h.taskStore.Get(taskID)
	if err != nil {
		http.Error(w, "Task not found", http.StatusNotFound)
		return
	}

	if task.Status != types.TaskStatusRunning {
		http.Error(w, "Task is not running", http.StatusConflict)
		return
	}

	// Parse optional pause metadata from body (empty body is valid)
	var body struct {
		Metadata json.RawMessage `json:"metadata,omitempty"`
		Message  string          `json:"message,omitempty"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil && !errors.Is(err, io.EOF) {
		http.Error(w, "Invalid JSON in request body", http.StatusBadRequest)
		return
	}

	msg := "Task paused by external request"
	if body.Message != "" {
		msg = body.Message
	}

	update := types.TaskUpdate{
		ID:            taskID,
		Status:        types.TaskStatusPaused,
		PauseMetadata: body.Metadata,
		Message:       msg,
		Timestamp:     time.Now(),
	}

	if err := h.taskStore.Update(update); err != nil {
		slog.Error("Failed to pause task", "id", taskID, "error", err)
		http.Error(w, "Failed to pause task", http.StatusInternalServerError)
		return
	}

	slog.Info("Task paused via external request", "id", taskID)

	h.writeTaskResponse(w, taskID)
}

// HandleCancel handles POST /a2a/tasks/{id}:cancel
func (h *LifecycleHandler) HandleCancel(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	taskID := strings.TrimSuffix(r.PathValue("id"), ":cancel")
	if taskID == "" {
		http.Error(w, "Missing task ID", http.StatusBadRequest)
		return
	}

	task, err := h.taskStore.Get(taskID)
	if err != nil {
		http.Error(w, "Task not found", http.StatusNotFound)
		return
	}

	// Cannot cancel tasks already in a final state
	if task.Status == types.TaskStatusSucceeded || task.Status == types.TaskStatusFailed || task.Status == types.TaskStatusCanceled {
		http.Error(w, "Task is already in a final state", http.StatusConflict)
		return
	}

	update := types.TaskUpdate{
		ID:        taskID,
		Status:    types.TaskStatusCanceled,
		Message:   "Task canceled",
		Timestamp: time.Now(),
	}

	if err := h.taskStore.Update(update); err != nil {
		slog.Error("Failed to cancel task", "id", taskID, "error", err)
		http.Error(w, "Failed to cancel task", http.StatusInternalServerError)
		return
	}

	slog.Info("Task canceled", "id", taskID)

	h.writeTaskResponse(w, taskID)
}

// writeTaskResponse fetches a task by ID and writes it as a JSON response.
func (h *LifecycleHandler) writeTaskResponse(w http.ResponseWriter, taskID string) {
	task, err := h.taskStore.Get(taskID)
	if err != nil {
		slog.Error("Failed to get task for response", "id", taskID, "error", err)
		http.Error(w, "Failed to retrieve updated task", http.StatusInternalServerError)
		return
	}
	a2aTask := TaskToA2ATask(task)
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(a2aTask); err != nil {
		slog.Error("Failed to write task response", "id", taskID, "error", err)
	}
}

// HandleList handles GET /a2a/tasks
func (h *LifecycleHandler) HandleList(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse optional status filter from query string
	var statusFilter *types.TaskStatus
	if statusParam := r.URL.Query().Get("status"); statusParam != "" {
		s := types.TaskStatus(statusParam)
		statusFilter = &s
	}

	tasks, err := h.taskStore.List(statusFilter)
	if err != nil {
		slog.Error("Failed to list tasks", "error", err)
		http.Error(w, "Failed to list tasks", http.StatusInternalServerError)
		return
	}

	// Convert to A2A task format
	a2aTasks := make([]types.A2ATask, 0, len(tasks))
	for _, task := range tasks {
		a2aTasks = append(a2aTasks, TaskToA2ATask(task))
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(a2aTasks); err != nil {
		slog.Error("Failed to write task list response", "error", err)
	}
}
