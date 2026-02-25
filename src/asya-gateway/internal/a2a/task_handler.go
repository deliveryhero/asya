package a2a

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
)

// TaskStatusHandler handles GET /a2a/tasks/{id}
type TaskStatusHandler struct {
	taskStore taskstore.TaskStore
}

// NewTaskStatusHandler creates a new REST task status handler.
func NewTaskStatusHandler(store taskstore.TaskStore) *TaskStatusHandler {
	return &TaskStatusHandler{taskStore: store}
}

func (h *TaskStatusHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	taskID := r.PathValue("id")
	if taskID == "" {
		http.Error(w, "Invalid path", http.StatusBadRequest)
		return
	}

	task, err := h.taskStore.Get(taskID)
	if err != nil {
		http.Error(w, "Task not found", http.StatusNotFound)
		return
	}

	a2aTask := TaskToA2ATask(task)

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(a2aTask); err != nil {
		slog.Error("Failed to encode A2A task", "error", err)
	}
}
