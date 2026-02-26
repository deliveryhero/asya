package a2a

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// createRunningTask creates a task in running state for lifecycle tests.
func createRunningTask(t *testing.T, store taskstore.TaskStore, id string) {
	t.Helper()
	task := &types.Task{
		ID:        id,
		ContextID: "ctx-" + id,
		Status:    types.TaskStatusPending,
		Route:     types.Route{Prev: []string{}, Curr: "actor-1", Next: []string{"actor-2"}},
	}
	if err := store.Create(task); err != nil {
		t.Fatal(err)
	}
	if err := store.Update(types.TaskUpdate{
		ID:        id,
		Status:    types.TaskStatusRunning,
		Message:   "Processing",
		Timestamp: time.Now(),
	}); err != nil {
		t.Fatal(err)
	}
}

// --- HandlePause tests ---

func TestHandlePause_Success(t *testing.T) {
	store := taskstore.NewStore()
	createRunningTask(t, store, "task-1")

	h := NewLifecycleHandler(store)
	body := `{"message": "Waiting for human input"}`
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/task-1:pause", bytes.NewBufferString(body))
	req.SetPathValue("id", "task-1:pause")
	rr := httptest.NewRecorder()

	h.HandlePause(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200, body: %s", rr.Code, rr.Body.String())
	}

	var a2aTask types.A2ATask
	if err := json.NewDecoder(rr.Body).Decode(&a2aTask); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if a2aTask.ID != "task-1" {
		t.Errorf("ID = %s, want task-1", a2aTask.ID)
	}
	if a2aTask.Status.State != types.A2AStateInputRequired {
		t.Errorf("State = %s, want input_required", a2aTask.Status.State)
	}
}

func TestHandlePause_EmptyBody(t *testing.T) {
	store := taskstore.NewStore()
	createRunningTask(t, store, "task-2")

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/task-2:pause", http.NoBody)
	req.SetPathValue("id", "task-2:pause")
	rr := httptest.NewRecorder()

	h.HandlePause(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200, body: %s", rr.Code, rr.Body.String())
	}

	var a2aTask types.A2ATask
	if err := json.NewDecoder(rr.Body).Decode(&a2aTask); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if a2aTask.Status.State != types.A2AStateInputRequired {
		t.Errorf("State = %s, want input_required", a2aTask.Status.State)
	}
}

func TestHandlePause_WithMetadata(t *testing.T) {
	store := taskstore.NewStore()
	createRunningTask(t, store, "task-meta")

	h := NewLifecycleHandler(store)
	body := `{"metadata": {"form_id": "approval-1"}, "message": "Need approval"}`
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/task-meta:pause", bytes.NewBufferString(body))
	req.SetPathValue("id", "task-meta:pause")
	rr := httptest.NewRecorder()

	h.HandlePause(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200, body: %s", rr.Code, rr.Body.String())
	}

	// Verify pause metadata was stored
	task, err := store.Get("task-meta")
	if err != nil {
		t.Fatalf("Get error: %v", err)
	}
	if task.PauseMetadata == nil {
		t.Fatal("PauseMetadata should not be nil")
	}
}

func TestHandlePause_TaskNotFound(t *testing.T) {
	store := taskstore.NewStore()
	h := NewLifecycleHandler(store)

	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/nonexistent:pause", http.NoBody)
	req.SetPathValue("id", "nonexistent:pause")
	rr := httptest.NewRecorder()

	h.HandlePause(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rr.Code)
	}
}

func TestHandlePause_TaskNotRunning(t *testing.T) {
	store := taskstore.NewStore()
	// Create a task but leave it in pending state
	task := &types.Task{
		ID:     "pending-task",
		Status: types.TaskStatusPending,
		Route:  types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
	}
	if err := store.Create(task); err != nil {
		t.Fatal(err)
	}

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/pending-task:pause", http.NoBody)
	req.SetPathValue("id", "pending-task:pause")
	rr := httptest.NewRecorder()

	h.HandlePause(rr, req)

	if rr.Code != http.StatusConflict {
		t.Errorf("status = %d, want 409", rr.Code)
	}
}

func TestHandlePause_InvalidJSON(t *testing.T) {
	store := taskstore.NewStore()
	createRunningTask(t, store, "task-badjson")

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/task-badjson:pause", bytes.NewBufferString("{invalid"))
	req.SetPathValue("id", "task-badjson:pause")
	rr := httptest.NewRecorder()

	h.HandlePause(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Errorf("status = %d, want 400", rr.Code)
	}
}

func TestHandlePause_MethodNotAllowed(t *testing.T) {
	store := taskstore.NewStore()
	h := NewLifecycleHandler(store)

	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/task-1:pause", nil)
	req.SetPathValue("id", "task-1:pause")
	rr := httptest.NewRecorder()

	h.HandlePause(rr, req)

	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("status = %d, want 405", rr.Code)
	}
}

// --- HandleCancel tests ---

func TestHandleCancel_RunningTask(t *testing.T) {
	store := taskstore.NewStore()
	createRunningTask(t, store, "cancel-1")

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/cancel-1:cancel", http.NoBody)
	req.SetPathValue("id", "cancel-1:cancel")
	rr := httptest.NewRecorder()

	h.HandleCancel(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200, body: %s", rr.Code, rr.Body.String())
	}

	var a2aTask types.A2ATask
	if err := json.NewDecoder(rr.Body).Decode(&a2aTask); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if a2aTask.ID != "cancel-1" {
		t.Errorf("ID = %s, want cancel-1", a2aTask.ID)
	}
	if a2aTask.Status.State != types.A2AStateCanceled {
		t.Errorf("State = %s, want canceled", a2aTask.Status.State)
	}
}

func TestHandleCancel_PendingTask(t *testing.T) {
	store := taskstore.NewStore()
	task := &types.Task{
		ID:     "cancel-pending",
		Status: types.TaskStatusPending,
		Route:  types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
	}
	if err := store.Create(task); err != nil {
		t.Fatal(err)
	}

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/cancel-pending:cancel", http.NoBody)
	req.SetPathValue("id", "cancel-pending:cancel")
	rr := httptest.NewRecorder()

	h.HandleCancel(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (pending tasks can be canceled), body: %s", rr.Code, rr.Body.String())
	}

	var a2aTask types.A2ATask
	if err := json.NewDecoder(rr.Body).Decode(&a2aTask); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if a2aTask.Status.State != types.A2AStateCanceled {
		t.Errorf("State = %s, want canceled", a2aTask.Status.State)
	}
}

func TestHandleCancel_TaskNotFound(t *testing.T) {
	store := taskstore.NewStore()
	h := NewLifecycleHandler(store)

	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/nonexistent:cancel", http.NoBody)
	req.SetPathValue("id", "nonexistent:cancel")
	rr := httptest.NewRecorder()

	h.HandleCancel(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rr.Code)
	}
}

func TestHandleCancel_AlreadySucceeded(t *testing.T) {
	store := taskstore.NewStore()
	task := &types.Task{
		ID:     "done-task",
		Status: types.TaskStatusPending,
		Route:  types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
	}
	if err := store.Create(task); err != nil {
		t.Fatal(err)
	}
	if err := store.Update(types.TaskUpdate{
		ID:        "done-task",
		Status:    types.TaskStatusSucceeded,
		Result:    map[string]any{"output": "done"},
		Timestamp: time.Now(),
	}); err != nil {
		t.Fatal(err)
	}

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/done-task:cancel", http.NoBody)
	req.SetPathValue("id", "done-task:cancel")
	rr := httptest.NewRecorder()

	h.HandleCancel(rr, req)

	if rr.Code != http.StatusConflict {
		t.Errorf("status = %d, want 409", rr.Code)
	}
}

func TestHandleCancel_AlreadyCanceled(t *testing.T) {
	store := taskstore.NewStore()
	createRunningTask(t, store, "double-cancel")

	// Cancel once
	if err := store.Update(types.TaskUpdate{
		ID:        "double-cancel",
		Status:    types.TaskStatusCanceled,
		Message:   "Canceled",
		Timestamp: time.Now(),
	}); err != nil {
		t.Fatal(err)
	}

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks/double-cancel:cancel", http.NoBody)
	req.SetPathValue("id", "double-cancel:cancel")
	rr := httptest.NewRecorder()

	h.HandleCancel(rr, req)

	if rr.Code != http.StatusConflict {
		t.Errorf("status = %d, want 409 (already canceled)", rr.Code)
	}
}

func TestHandleCancel_MethodNotAllowed(t *testing.T) {
	store := taskstore.NewStore()
	h := NewLifecycleHandler(store)

	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/task-1:cancel", nil)
	req.SetPathValue("id", "task-1:cancel")
	rr := httptest.NewRecorder()

	h.HandleCancel(rr, req)

	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("status = %d, want 405", rr.Code)
	}
}

// --- HandleList tests ---

func TestHandleList_Empty(t *testing.T) {
	store := taskstore.NewStore()
	h := NewLifecycleHandler(store)

	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks", nil)
	rr := httptest.NewRecorder()

	h.HandleList(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200, body: %s", rr.Code, rr.Body.String())
	}

	var tasks []types.A2ATask
	if err := json.NewDecoder(rr.Body).Decode(&tasks); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if len(tasks) != 0 {
		t.Errorf("len(tasks) = %d, want 0", len(tasks))
	}
}

func TestHandleList_AllTasks(t *testing.T) {
	store := taskstore.NewStore()

	// Create tasks in different states
	for _, id := range []string{"list-1", "list-2", "list-3"} {
		task := &types.Task{
			ID:     id,
			Status: types.TaskStatusPending,
			Route:  types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
		}
		if err := store.Create(task); err != nil {
			t.Fatal(err)
		}
	}
	// Move list-2 to running
	if err := store.Update(types.TaskUpdate{
		ID:        "list-2",
		Status:    types.TaskStatusRunning,
		Timestamp: time.Now(),
	}); err != nil {
		t.Fatal(err)
	}

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks", nil)
	rr := httptest.NewRecorder()

	h.HandleList(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}

	var tasks []types.A2ATask
	if err := json.NewDecoder(rr.Body).Decode(&tasks); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if len(tasks) != 3 {
		t.Errorf("len(tasks) = %d, want 3", len(tasks))
	}
}

func TestHandleList_WithStatusFilter(t *testing.T) {
	store := taskstore.NewStore()

	// Create tasks: 2 pending, 1 running
	for _, id := range []string{"filter-1", "filter-2"} {
		task := &types.Task{
			ID:     id,
			Status: types.TaskStatusPending,
			Route:  types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
		}
		if err := store.Create(task); err != nil {
			t.Fatal(err)
		}
	}
	createRunningTask(t, store, "filter-3")

	h := NewLifecycleHandler(store)
	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks?status=running", nil)
	rr := httptest.NewRecorder()

	h.HandleList(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}

	var tasks []types.A2ATask
	if err := json.NewDecoder(rr.Body).Decode(&tasks); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if len(tasks) != 1 {
		t.Errorf("len(tasks) = %d, want 1", len(tasks))
	}
	if len(tasks) > 0 && tasks[0].ID != "filter-3" {
		t.Errorf("task ID = %s, want filter-3", tasks[0].ID)
	}
}

func TestHandleList_MethodNotAllowed(t *testing.T) {
	store := taskstore.NewStore()
	h := NewLifecycleHandler(store)

	req := httptest.NewRequest(http.MethodPost, "/a2a/tasks", nil)
	rr := httptest.NewRecorder()

	h.HandleList(rr, req)

	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("status = %d, want 405", rr.Code)
	}
}
