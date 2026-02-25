package a2a

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestTaskStatusHandler(t *testing.T) {
	store := taskstore.NewStore()
	task := &types.Task{
		ID:        "rest-task-1",
		ContextID: "ctx-1",
		Status:    types.TaskStatusPending,
		Route:     types.Route{Prev: []string{}, Curr: "a1", Next: []string{"a2"}},
	}
	if err := store.Create(task); err != nil {
		t.Fatal(err)
	}

	// Update to succeeded
	if err := store.Update(types.TaskUpdate{
		ID:        "rest-task-1",
		Status:    types.TaskStatusSucceeded,
		Result:    map[string]any{"output": "done"},
		Timestamp: time.Now(),
	}); err != nil {
		t.Fatal(err)
	}

	h := NewTaskStatusHandler(store)
	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/rest-task-1", nil)
	req.SetPathValue("id", "rest-task-1")
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}

	var a2aTask types.A2ATask
	if err := json.NewDecoder(rr.Body).Decode(&a2aTask); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if a2aTask.ID != "rest-task-1" {
		t.Errorf("ID = %s, want rest-task-1", a2aTask.ID)
	}
	if a2aTask.Status.State != types.A2AStateCompleted {
		t.Errorf("State = %s, want completed", a2aTask.Status.State)
	}
	if a2aTask.ContextID != "ctx-1" {
		t.Errorf("ContextID = %s, want ctx-1", a2aTask.ContextID)
	}
}

func TestTaskStatusHandler_NotFound(t *testing.T) {
	store := taskstore.NewStore()
	h := NewTaskStatusHandler(store)
	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/nonexistent", nil)
	req.SetPathValue("id", "nonexistent")
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rr.Code)
	}
}
