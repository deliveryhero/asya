package taskstore

import (
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestUpdateProgress_InMemoryStore(t *testing.T) {
	store := NewStore()

	// Create a test job
	job := &types.Task{
		ID: "test-job-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2", "actor3"},
		},
		Status: types.TaskStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	tests := []struct {
		name          string
		update        types.TaskUpdate
		wantProgress  float64
		wantActor     string
		wantTaskState string
	}{
		{
			name: "update with progress",
			update: types.TaskUpdate{
				ID:              "test-job-1",
				Status:          types.TaskStatusRunning,
				Message:         "Processing actor 1",
				ProgressPercent: floatPtr(25.0),
				Prev:            []string{},
				Curr:            "actor1",
				Next:            []string{"actor2", "actor3"},
				TaskState:       strPtr("processing"),
				Timestamp:       time.Now(),
			},
			wantProgress:  25.0,
			wantActor:     "actor1",
			wantTaskState: "processing",
		},
		{
			name: "update progress to 50%",
			update: types.TaskUpdate{
				ID:              "test-job-1",
				Status:          types.TaskStatusRunning,
				Message:         "Processing actor 2",
				ProgressPercent: floatPtr(50.0),
				Prev:            []string{"actor1"},
				Curr:            "actor2",
				Next:            []string{"actor3"},
				TaskState:       strPtr("processing"),
				Timestamp:       time.Now(),
			},
			wantProgress:  50.0,
			wantActor:     "actor2",
			wantTaskState: "processing",
		},
		{
			name: "update progress to 100%",
			update: types.TaskUpdate{
				ID:              "test-job-1",
				Status:          types.TaskStatusRunning,
				Message:         "Completed",
				ProgressPercent: floatPtr(100.0),
				Prev:            []string{"actor1", "actor2"},
				Curr:            "actor3",
				Next:            []string{},
				TaskState:       strPtr("completed"),
				Timestamp:       time.Now(),
			},
			wantProgress:  100.0,
			wantActor:     "actor3",
			wantTaskState: "completed",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := store.UpdateProgress(tt.update); err != nil {
				t.Fatalf("UpdateProgress failed: %v", err)
			}

			// Verify the job was updated
			updatedJob, err := store.Get("test-job-1")
			if err != nil {
				t.Fatalf("Failed to get job: %v", err)
			}

			if updatedJob.ProgressPercent != tt.wantProgress {
				t.Errorf("ProgressPercent = %v, want %v", updatedJob.ProgressPercent, tt.wantProgress)
			}

			if updatedJob.CurrentActorName != tt.wantActor {
				t.Errorf("CurrentActorName = %v, want %v", updatedJob.CurrentActorName, tt.wantActor)
			}

			if updatedJob.Status != types.TaskStatusRunning {
				t.Errorf("Status = %v, want Running", updatedJob.Status)
			}
		})
	}
}

func TestUpdateProgress_NotifiesListeners(t *testing.T) {
	store := NewStore()

	job := &types.Task{
		ID: "test-job-notify",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Status: types.TaskStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Subscribe to updates
	updateChan := store.Subscribe("test-job-notify")
	defer store.Unsubscribe("test-job-notify", updateChan)

	// Send progress update
	progressPercent := 33.33
	update := types.TaskUpdate{
		ID:              "test-job-notify",
		Status:          types.TaskStatusRunning,
		Message:         "Processing",
		ProgressPercent: &progressPercent,
		Prev:            []string{},
		Curr:            "actor1",
		Next:            []string{},
		TaskState:       strPtr("processing"),
		Timestamp:       time.Now(),
	}

	if err := store.UpdateProgress(update); err != nil {
		t.Fatalf("UpdateProgress failed: %v", err)
	}

	// Wait for notification
	select {
	case receivedUpdate := <-updateChan:
		if receivedUpdate.ID != "test-job-notify" {
			t.Errorf("JobID = %v, want test-job-notify", receivedUpdate.ID)
		}
		if receivedUpdate.Curr != "actor1" {
			t.Errorf("Curr = %v, want actor1", receivedUpdate.Curr)
		}
		if receivedUpdate.TaskState == nil || *receivedUpdate.TaskState != "processing" {
			t.Errorf("TaskState = %v, want processing", receivedUpdate.TaskState)
		}
		if receivedUpdate.ProgressPercent == nil || *receivedUpdate.ProgressPercent != 33.33 {
			t.Errorf("ProgressPercent = %v, want 33.33", receivedUpdate.ProgressPercent)
		}
	case <-time.After(1 * time.Second):
		t.Fatal("Did not receive notification within timeout")
	}
}

func TestUpdateProgress_NonExistentJob(t *testing.T) {
	store := NewStore()

	update := types.TaskUpdate{
		ID:              "non-existent-job",
		Status:          types.TaskStatusRunning,
		ProgressPercent: floatPtr(50.0),
		Timestamp:       time.Now(),
	}

	err := store.UpdateProgress(update)
	if err == nil {
		t.Error("Expected error for non-existent task, got nil")
	}
}

func TestUpdateProgress_MultipleSubscribers(t *testing.T) {
	store := NewStore()

	job := &types.Task{
		ID: "test-job-multi",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Status: types.TaskStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Create multiple subscribers
	numSubscribers := 5
	channels := make([]chan types.TaskUpdate, numSubscribers)
	for i := 0; i < numSubscribers; i++ {
		channels[i] = store.Subscribe("test-job-multi")
		defer store.Unsubscribe("test-job-multi", channels[i])
	}

	// Send progress update
	progressPercent := 50.0
	update := types.TaskUpdate{
		ID:              "test-job-multi",
		Status:          types.TaskStatusRunning,
		ProgressPercent: &progressPercent,
		Prev:            []string{},
		Curr:            "actor1",
		Next:            []string{},
		Timestamp:       time.Now(),
	}

	if err := store.UpdateProgress(update); err != nil {
		t.Fatalf("UpdateProgress failed: %v", err)
	}

	// Verify all subscribers received the update
	for i, ch := range channels {
		select {
		case receivedUpdate := <-ch:
			if receivedUpdate.ID != "test-job-multi" {
				t.Errorf("Subscriber %d: JobID = %v, want test-job-multi", i, receivedUpdate.ID)
			}
			if receivedUpdate.ProgressPercent == nil || *receivedUpdate.ProgressPercent != 50.0 {
				t.Errorf("Subscriber %d: ProgressPercent = %v, want 50.0", i, receivedUpdate.ProgressPercent)
			}
		case <-time.After(1 * time.Second):
			t.Fatalf("Subscriber %d did not receive notification", i)
		}
	}
}

func TestUpdateProgress_ProgressSequence(t *testing.T) {
	store := NewStore()

	job := &types.Task{
		ID: "test-job-sequence",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2", "actor3"},
		},
		Status: types.TaskStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Simulate progress through all actors
	progressSequence := []struct {
		prev      []string
		curr      string
		next      []string
		percent   float64
		taskState string
	}{
		{[]string{}, "actor1", []string{"actor2", "actor3"}, 3.33, "received"},
		{[]string{}, "actor1", []string{"actor2", "actor3"}, 16.67, "processing"},
		{[]string{}, "actor1", []string{"actor2", "actor3"}, 33.33, "completed"},
		{[]string{"actor1"}, "actor2", []string{"actor3"}, 36.67, "received"},
		{[]string{"actor1"}, "actor2", []string{"actor3"}, 50.0, "processing"},
		{[]string{"actor1"}, "actor2", []string{"actor3"}, 66.67, "completed"},
		{[]string{"actor1", "actor2"}, "actor3", []string{}, 70.0, "received"},
		{[]string{"actor1", "actor2"}, "actor3", []string{}, 83.33, "processing"},
		{[]string{"actor1", "actor2"}, "actor3", []string{}, 100.0, "completed"},
	}

	for i, p := range progressSequence {
		update := types.TaskUpdate{
			ID:              "test-job-sequence",
			Status:          types.TaskStatusRunning,
			ProgressPercent: &p.percent,
			Prev:            p.prev,
			Curr:            p.curr,
			Next:            p.next,
			TaskState:       strPtr(p.taskState),
			Timestamp:       time.Now(),
		}

		if err := store.UpdateProgress(update); err != nil {
			t.Fatalf("UpdateProgress failed for step %d (%.2f%%): %v", i, p.percent, err)
		}

		// Verify current state
		j, _ := store.Get("test-job-sequence")
		if j.ProgressPercent != p.percent {
			t.Errorf("After update to %.2f%%, got %.2f%%", p.percent, j.ProgressPercent)
		}
		if j.CurrentActorName != p.curr {
			t.Errorf("After update to %s, got %s", p.curr, j.CurrentActorName)
		}
	}

	// Final verification
	finalJob, _ := store.Get("test-job-sequence")
	if finalJob.ProgressPercent != 100.0 {
		t.Errorf("Final progress = %.2f%%, want 100.00%%", finalJob.ProgressPercent)
	}
	if finalJob.CurrentActorName != "actor3" {
		t.Errorf("Final actor = %v, want actor3", finalJob.CurrentActorName)
	}
}

func TestJobCreation_InitializesProgress(t *testing.T) {
	store := NewStore()

	job := &types.Task{
		ID: "test-job-init",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2", "actor3"},
		},
		Status: types.TaskStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Verify initial progress values
	createdJob, _ := store.Get("test-job-init")
	if createdJob.ProgressPercent != 0.0 {
		t.Errorf("Initial ProgressPercent = %v, want 0.0", createdJob.ProgressPercent)
	}
	// Total: prev(0) + curr(1) + next(2) = 3
	if createdJob.TotalActors != 3 {
		t.Errorf("TotalActors = %v, want 3", createdJob.TotalActors)
	}
	if createdJob.ActorsCompleted != 0 {
		t.Errorf("ActorsCompleted = %v, want 0", createdJob.ActorsCompleted)
	}
}

// TestUpdate tests the Update method with various scenarios
func TestUpdate(t *testing.T) {
	tests := []struct {
		name        string
		setupJob    *types.Task
		update      types.TaskUpdate
		wantStatus  types.TaskStatus
		wantError   string
		wantResult  bool
		checkFields func(*testing.T, *types.Task)
	}{
		{
			name: "update status to running",
			setupJob: &types.Task{
				ID: "test-update-1",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			update: types.TaskUpdate{
				ID:        "test-update-1",
				Status:    types.TaskStatusRunning,
				Timestamp: time.Now(),
			},
			wantStatus: types.TaskStatusRunning,
		},
		{
			name: "update to succeeded with result",
			setupJob: &types.Task{
				ID: "test-update-2",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			update: types.TaskUpdate{
				ID:        "test-update-2",
				Status:    types.TaskStatusSucceeded,
				Result:    map[string]interface{}{"output": "success"},
				Message:   "Processing completed",
				Timestamp: time.Now(),
			},
			wantStatus: types.TaskStatusSucceeded,
			wantResult: true,
			checkFields: func(t *testing.T, task *types.Task) {
				if task.Result == nil {
					t.Error("Expected result to be set")
				}
			},
		},
		{
			name: "update to failed with error",
			setupJob: &types.Task{
				ID: "test-update-3",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			update: types.TaskUpdate{
				ID:        "test-update-3",
				Status:    types.TaskStatusFailed,
				Error:     "Processing failed",
				Message:   "Error occurred",
				Timestamp: time.Now(),
			},
			wantStatus: types.TaskStatusFailed,
			checkFields: func(t *testing.T, task *types.Task) {
				if task.Error != "Processing failed" {
					t.Errorf("Error = %v, want 'Processing failed'", task.Error)
				}
			},
		},
		{
			name: "update progress percent",
			setupJob: &types.Task{
				ID: "test-update-4",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			update: types.TaskUpdate{
				ID:              "test-update-4",
				Status:          types.TaskStatusRunning,
				ProgressPercent: floatPtr(45.5),
				Timestamp:       time.Now(),
			},
			wantStatus: types.TaskStatusRunning,
			checkFields: func(t *testing.T, task *types.Task) {
				if task.ProgressPercent != 45.5 {
					t.Errorf("ProgressPercent = %v, want 45.5", task.ProgressPercent)
				}
			},
		},
		{
			name: "update actor information",
			setupJob: &types.Task{
				ID: "test-update-5",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{"actor2"},
				},
			},
			update: types.TaskUpdate{
				ID:        "test-update-5",
				Status:    types.TaskStatusRunning,
				Prev:      []string{"actor1"},
				Curr:      "actor2",
				Next:      []string{},
				TaskState: strPtr("processing"),
				Timestamp: time.Now(),
			},
			wantStatus: types.TaskStatusRunning,
			checkFields: func(t *testing.T, task *types.Task) {
				if task.CurrentActorName != "actor2" {
					t.Errorf("CurrentActorName = %v, want actor2", task.CurrentActorName)
				}
			},
		},
		{
			name: "update non-existent task",
			setupJob: &types.Task{
				ID: "test-update-6",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			update: types.TaskUpdate{
				ID:        "nonexistent",
				Status:    types.TaskStatusRunning,
				Timestamp: time.Now(),
			},
			wantError: "task nonexistent not found",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := NewStore()

			if tt.setupJob != nil {
				if err := store.Create(tt.setupJob); err != nil {
					t.Fatalf("Failed to create test task: %v", err)
				}
			}

			err := store.Update(tt.update)

			if tt.wantError != "" {
				if err == nil {
					t.Errorf("Expected error %q, got nil", tt.wantError)
				} else if err.Error() != tt.wantError {
					t.Errorf("Error = %v, want %v", err.Error(), tt.wantError)
				}
				return
			}

			if err != nil {
				t.Fatalf("Unexpected error: %v", err)
			}

			task, err := store.Get(tt.update.ID)
			if err != nil {
				t.Fatalf("Failed to get task: %v", err)
			}

			if task.Status != tt.wantStatus {
				t.Errorf("Status = %v, want %v", task.Status, tt.wantStatus)
			}

			if tt.checkFields != nil {
				tt.checkFields(t, task)
			}
		})
	}
}

// TestIsActive tests the IsActive method
func TestIsActive(t *testing.T) {
	tests := []struct {
		name       string
		setupJob   *types.Task
		updateTo   types.TaskStatus
		taskID     string
		wantActive bool
	}{
		{
			name: "pending task is active",
			setupJob: &types.Task{
				ID: "test-active-1",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			taskID:     "test-active-1",
			wantActive: true,
		},
		{
			name: "running task is active",
			setupJob: &types.Task{
				ID: "test-active-2",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			updateTo:   types.TaskStatusRunning,
			taskID:     "test-active-2",
			wantActive: true,
		},
		{
			name: "succeeded task is not active",
			setupJob: &types.Task{
				ID: "test-active-3",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			updateTo:   types.TaskStatusSucceeded,
			taskID:     "test-active-3",
			wantActive: false,
		},
		{
			name: "failed task is not active",
			setupJob: &types.Task{
				ID: "test-active-4",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
			},
			updateTo:   types.TaskStatusFailed,
			taskID:     "test-active-4",
			wantActive: false,
		},
		{
			name:       "non-existent task is not active",
			taskID:     "nonexistent",
			wantActive: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := NewStore()

			if tt.setupJob != nil {
				if err := store.Create(tt.setupJob); err != nil {
					t.Fatalf("Failed to create task: %v", err)
				}

				if tt.updateTo != "" {
					update := types.TaskUpdate{
						ID:        tt.taskID,
						Status:    tt.updateTo,
						Timestamp: time.Now(),
					}
					if err := store.Update(update); err != nil {
						t.Fatalf("Failed to update task: %v", err)
					}
				}
			}

			active := store.IsActive(tt.taskID)
			if active != tt.wantActive {
				t.Errorf("IsActive() = %v, want %v", active, tt.wantActive)
			}
		})
	}
}

// TestHandleTimeout tests timeout handling
func TestHandleTimeout(t *testing.T) {
	store := NewStore()

	task := &types.Task{
		ID: "test-timeout",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		TimeoutSec: 1,
	}

	if err := store.Create(task); err != nil {
		t.Fatalf("Failed to create task: %v", err)
	}

	updateChan := store.Subscribe("test-timeout")
	defer store.Unsubscribe("test-timeout", updateChan)

	select {
	case update := <-updateChan:
		if update.Status != types.TaskStatusFailed {
			t.Errorf("Timeout update status = %v, want Failed", update.Status)
		}
		if update.Error != "task timed out" {
			t.Errorf("Timeout error = %v, want 'task timed out'", update.Error)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Did not receive timeout notification")
	}

	timedOutTask, _ := store.Get("test-timeout")
	if timedOutTask.Status != types.TaskStatusFailed {
		t.Errorf("Task status after timeout = %v, want Failed", timedOutTask.Status)
	}
}

// TestCancelTimer tests timer cancellation on final status
func TestCancelTimer(t *testing.T) {
	store := NewStore()

	task := &types.Task{
		ID: "test-cancel-timer",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		TimeoutSec: 5,
	}

	if err := store.Create(task); err != nil {
		t.Fatalf("Failed to create task: %v", err)
	}

	time.Sleep(100 * time.Millisecond)

	update := types.TaskUpdate{
		ID:        "test-cancel-timer",
		Status:    types.TaskStatusSucceeded,
		Timestamp: time.Now(),
	}

	if err := store.Update(update); err != nil {
		t.Fatalf("Failed to update task: %v", err)
	}

	time.Sleep(6 * time.Second)

	completedTask, _ := store.Get("test-cancel-timer")
	if completedTask.Status != types.TaskStatusSucceeded {
		t.Errorf("Status should remain Succeeded, got %v", completedTask.Status)
	}
}

// TestCreateDuplicate tests creating duplicate tasks
func TestCreateDuplicate(t *testing.T) {
	store := NewStore()

	task := &types.Task{
		ID: "test-duplicate",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
	}

	if err := store.Create(task); err != nil {
		t.Fatalf("First create failed: %v", err)
	}

	err := store.Create(task)
	if err == nil {
		t.Error("Expected error for duplicate task, got nil")
	}
}

// TestGetNonExistent tests getting non-existent task
func TestGetNonExistent(t *testing.T) {
	store := NewStore()

	_, err := store.Get("nonexistent")
	if err == nil {
		t.Error("Expected error for non-existent task, got nil")
	}
}

// TestSubscribeUnsubscribe tests subscription lifecycle
func TestSubscribeUnsubscribe(t *testing.T) {
	store := NewStore()

	task := &types.Task{
		ID: "test-subscribe",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
	}

	if err := store.Create(task); err != nil {
		t.Fatalf("Failed to create task: %v", err)
	}

	ch1 := store.Subscribe("test-subscribe")
	ch2 := store.Subscribe("test-subscribe")

	progressPercent := 50.0
	update := types.TaskUpdate{
		ID:              "test-subscribe",
		Status:          types.TaskStatusRunning,
		ProgressPercent: &progressPercent,
		Timestamp:       time.Now(),
	}

	if err := store.UpdateProgress(update); err != nil {
		t.Fatalf("UpdateProgress failed: %v", err)
	}

	select {
	case <-ch1:
	case <-time.After(1 * time.Second):
		t.Error("ch1 did not receive update")
	}

	select {
	case <-ch2:
	case <-time.After(1 * time.Second):
		t.Error("ch2 did not receive update")
	}

	store.Unsubscribe("test-subscribe", ch1)

	time.Sleep(50 * time.Millisecond)

	progressPercent2 := 75.0
	update2 := types.TaskUpdate{
		ID:              "test-subscribe",
		Status:          types.TaskStatusRunning,
		ProgressPercent: &progressPercent2,
		Timestamp:       time.Now(),
	}

	if err := store.UpdateProgress(update2); err != nil {
		t.Fatalf("Second UpdateProgress failed: %v", err)
	}

	select {
	case <-ch2:
	case <-time.After(1 * time.Second):
		t.Error("ch2 did not receive second update")
	}

	select {
	case msg := <-ch1:
		if msg.ProgressPercent != nil && *msg.ProgressPercent == 75.0 {
			t.Error("ch1 should not receive update after unsubscribe")
		}
	case <-time.After(100 * time.Millisecond):
	}

	store.Unsubscribe("test-subscribe", ch2)
}

// TestStore_ContextID tests that ContextID is preserved through Create/Get
func TestStore_ContextID(t *testing.T) {
	store := NewStore()
	task := &types.Task{
		ID:        "ctx-test-1",
		ContextID: "conv-123",
		Route:     types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
	}
	if err := store.Create(task); err != nil {
		t.Fatal(err)
	}
	got, err := store.Get("ctx-test-1")
	if err != nil {
		t.Fatal(err)
	}
	if got.ContextID != "conv-123" {
		t.Errorf("ContextID = %q, want %q", got.ContextID, "conv-123")
	}
}

// Helper functions
func floatPtr(f float64) *float64 {
	return &f
}

func strPtr(s string) *string {
	return &s
}
