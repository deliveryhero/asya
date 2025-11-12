package jobs

import (
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestUpdateProgress_InMemoryStore(t *testing.T) {
	store := NewStore()

	// Create a test job
	job := &types.Envelope{
		ID: "test-job-1",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2", "actor3"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	tests := []struct {
		name              string
		update            types.EnvelopeUpdate
		wantProgress      float64
		wantActor         string
		wantEnvelopeState string
	}{
		{
			name: "update with progress",
			update: types.EnvelopeUpdate{
				ID:              "test-job-1",
				Status:          types.EnvelopeStatusRunning,
				Message:         "Processing actor 1",
				ProgressPercent: floatPtr(25.0),
				Actors:          []string{"actor1", "actor2", "actor3"},
				CurrentActorIdx: intPtr(0),
				EnvelopeState:   strPtr("processing"),
				Timestamp:       time.Now(),
			},
			wantProgress:      25.0,
			wantActor:         "actor1",
			wantEnvelopeState: "processing",
		},
		{
			name: "update progress to 50%",
			update: types.EnvelopeUpdate{
				ID:              "test-job-1",
				Status:          types.EnvelopeStatusRunning,
				Message:         "Processing actor 2",
				ProgressPercent: floatPtr(50.0),
				Actors:          []string{"actor1", "actor2", "actor3"},
				CurrentActorIdx: intPtr(1),
				EnvelopeState:   strPtr("processing"),
				Timestamp:       time.Now(),
			},
			wantProgress:      50.0,
			wantActor:         "actor2",
			wantEnvelopeState: "processing",
		},
		{
			name: "update progress to 100%",
			update: types.EnvelopeUpdate{
				ID:              "test-job-1",
				Status:          types.EnvelopeStatusRunning,
				Message:         "Completed",
				ProgressPercent: floatPtr(100.0),
				Actors:          []string{"actor1", "actor2", "actor3"},
				CurrentActorIdx: intPtr(2),
				EnvelopeState:   strPtr("completed"),
				Timestamp:       time.Now(),
			},
			wantProgress:      100.0,
			wantActor:         "actor3",
			wantEnvelopeState: "completed",
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

			if updatedJob.Status != types.EnvelopeStatusRunning {
				t.Errorf("Status = %v, want Running", updatedJob.Status)
			}
		})
	}
}

func TestUpdateProgress_NotifiesListeners(t *testing.T) {
	store := NewStore()

	job := &types.Envelope{
		ID: "test-job-notify",
		Route: types.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Subscribe to updates
	updateChan := store.Subscribe("test-job-notify")
	defer store.Unsubscribe("test-job-notify", updateChan)

	// Send progress update
	progressPercent := 33.33
	update := types.EnvelopeUpdate{
		ID:              "test-job-notify",
		Status:          types.EnvelopeStatusRunning,
		Message:         "Processing",
		ProgressPercent: &progressPercent,
		Actors:          []string{"actor1"},
		CurrentActorIdx: intPtr(0),
		EnvelopeState:   strPtr("processing"),
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
		if receivedUpdate.CurrentActorIdx == nil || len(receivedUpdate.Actors) == 0 || receivedUpdate.Actors[*receivedUpdate.CurrentActorIdx] != "actor1" {
			t.Errorf("Actor = %v, want actor1", receivedUpdate.Actors)
		}
		if receivedUpdate.EnvelopeState == nil || *receivedUpdate.EnvelopeState != "processing" {
			t.Errorf("EnvelopeState = %v, want processing", receivedUpdate.EnvelopeState)
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

	update := types.EnvelopeUpdate{
		ID:              "non-existent-job",
		Status:          types.EnvelopeStatusRunning,
		ProgressPercent: floatPtr(50.0),
		Timestamp:       time.Now(),
	}

	err := store.UpdateProgress(update)
	if err == nil {
		t.Error("Expected error for non-existent envelope, got nil")
	}
}

func TestUpdateProgress_MultipleSubscribers(t *testing.T) {
	store := NewStore()

	job := &types.Envelope{
		ID: "test-job-multi",
		Route: types.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Create multiple subscribers
	numSubscribers := 5
	channels := make([]chan types.EnvelopeUpdate, numSubscribers)
	for i := 0; i < numSubscribers; i++ {
		channels[i] = store.Subscribe("test-job-multi")
		defer store.Unsubscribe("test-job-multi", channels[i])
	}

	// Send progress update
	progressPercent := 50.0
	update := types.EnvelopeUpdate{
		ID:              "test-job-multi",
		Status:          types.EnvelopeStatusRunning,
		ProgressPercent: &progressPercent,
		Actors:          []string{"actor1"},
		CurrentActorIdx: intPtr(0),
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

	job := &types.Envelope{
		ID: "test-job-sequence",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2", "actor3"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Simulate progress through all actors
	progressSequence := []struct {
		percent       float64
		actor         string
		envelopeState string
	}{
		{3.33, "actor1", "received"},
		{16.67, "actor1", "processing"},
		{33.33, "actor1", "completed"},
		{36.67, "actor2", "received"},
		{50.0, "actor2", "processing"},
		{66.67, "actor2", "completed"},
		{70.0, "actor3", "received"},
		{83.33, "actor3", "processing"},
		{100.0, "actor3", "completed"},
	}

	for i, p := range progressSequence {
		var currentIdx int
		if i < 3 {
			currentIdx = 0
		} else if i < 6 {
			currentIdx = 1
		} else {
			currentIdx = 2
		}
		update := types.EnvelopeUpdate{
			ID:              "test-job-sequence",
			Status:          types.EnvelopeStatusRunning,
			ProgressPercent: &p.percent,
			Actors:          []string{"actor1", "actor2", "actor3"},
			CurrentActorIdx: intPtr(currentIdx),
			EnvelopeState:   strPtr(p.envelopeState),
			Timestamp:       time.Now(),
		}

		if err := store.UpdateProgress(update); err != nil {
			t.Fatalf("UpdateProgress failed for %.2f%%: %v", p.percent, err)
		}

		// Verify current state
		j, _ := store.Get("test-job-sequence")
		if j.ProgressPercent != p.percent {
			t.Errorf("After update to %.2f%%, got %.2f%%", p.percent, j.ProgressPercent)
		}
		if j.CurrentActorName != p.actor {
			t.Errorf("After update to %s, got %s", p.actor, j.CurrentActorName)
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

	job := &types.Envelope{
		ID: "test-job-init",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2", "actor3"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Verify initial progress values
	createdJob, _ := store.Get("test-job-init")
	if createdJob.ProgressPercent != 0.0 {
		t.Errorf("Initial ProgressPercent = %v, want 0.0", createdJob.ProgressPercent)
	}
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
		setupJob    *types.Envelope
		update      types.EnvelopeUpdate
		wantStatus  types.EnvelopeStatus
		wantError   string
		wantResult  bool
		checkFields func(*testing.T, *types.Envelope)
	}{
		{
			name: "update status to running",
			setupJob: &types.Envelope{
				ID: "test-update-1",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			update: types.EnvelopeUpdate{
				ID:        "test-update-1",
				Status:    types.EnvelopeStatusRunning,
				Timestamp: time.Now(),
			},
			wantStatus: types.EnvelopeStatusRunning,
		},
		{
			name: "update to succeeded with result",
			setupJob: &types.Envelope{
				ID: "test-update-2",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			update: types.EnvelopeUpdate{
				ID:        "test-update-2",
				Status:    types.EnvelopeStatusSucceeded,
				Result:    map[string]interface{}{"output": "success"},
				Message:   "Processing completed",
				Timestamp: time.Now(),
			},
			wantStatus: types.EnvelopeStatusSucceeded,
			wantResult: true,
			checkFields: func(t *testing.T, env *types.Envelope) {
				if env.Result == nil {
					t.Error("Expected result to be set")
				}
			},
		},
		{
			name: "update to failed with error",
			setupJob: &types.Envelope{
				ID: "test-update-3",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			update: types.EnvelopeUpdate{
				ID:        "test-update-3",
				Status:    types.EnvelopeStatusFailed,
				Error:     "Processing failed",
				Message:   "Error occurred",
				Timestamp: time.Now(),
			},
			wantStatus: types.EnvelopeStatusFailed,
			checkFields: func(t *testing.T, env *types.Envelope) {
				if env.Error != "Processing failed" {
					t.Errorf("Error = %v, want 'Processing failed'", env.Error)
				}
			},
		},
		{
			name: "update progress percent",
			setupJob: &types.Envelope{
				ID: "test-update-4",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			update: types.EnvelopeUpdate{
				ID:              "test-update-4",
				Status:          types.EnvelopeStatusRunning,
				ProgressPercent: floatPtr(45.5),
				Timestamp:       time.Now(),
			},
			wantStatus: types.EnvelopeStatusRunning,
			checkFields: func(t *testing.T, env *types.Envelope) {
				if env.ProgressPercent != 45.5 {
					t.Errorf("ProgressPercent = %v, want 45.5", env.ProgressPercent)
				}
			},
		},
		{
			name: "update actor information",
			setupJob: &types.Envelope{
				ID: "test-update-5",
				Route: types.Route{
					Actors:  []string{"actor1", "actor2"},
					Current: 0,
				},
			},
			update: types.EnvelopeUpdate{
				ID:              "test-update-5",
				Status:          types.EnvelopeStatusRunning,
				Actors:          []string{"actor1", "actor2"},
				CurrentActorIdx: intPtr(1),
				EnvelopeState:   strPtr("processing"),
				Timestamp:       time.Now(),
			},
			wantStatus: types.EnvelopeStatusRunning,
			checkFields: func(t *testing.T, env *types.Envelope) {
				if env.CurrentActorName != "actor2" {
					t.Errorf("CurrentActorName = %v, want actor2", env.CurrentActorName)
				}
			},
		},
		{
			name: "update non-existent envelope",
			setupJob: &types.Envelope{
				ID: "test-update-6",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			update: types.EnvelopeUpdate{
				ID:        "nonexistent",
				Status:    types.EnvelopeStatusRunning,
				Timestamp: time.Now(),
			},
			wantError: "envelope nonexistent not found",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := NewStore()

			if tt.setupJob != nil {
				if err := store.Create(tt.setupJob); err != nil {
					t.Fatalf("Failed to create test envelope: %v", err)
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

			env, err := store.Get(tt.update.ID)
			if err != nil {
				t.Fatalf("Failed to get envelope: %v", err)
			}

			if env.Status != tt.wantStatus {
				t.Errorf("Status = %v, want %v", env.Status, tt.wantStatus)
			}

			if tt.checkFields != nil {
				tt.checkFields(t, env)
			}
		})
	}
}

// TestIsActive tests the IsActive method
func TestIsActive(t *testing.T) {
	tests := []struct {
		name       string
		setupJob   *types.Envelope
		updateTo   types.EnvelopeStatus
		envelopeID string
		wantActive bool
	}{
		{
			name: "pending envelope is active",
			setupJob: &types.Envelope{
				ID: "test-active-1",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			envelopeID: "test-active-1",
			wantActive: true,
		},
		{
			name: "running envelope is active",
			setupJob: &types.Envelope{
				ID: "test-active-2",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			updateTo:   types.EnvelopeStatusRunning,
			envelopeID: "test-active-2",
			wantActive: true,
		},
		{
			name: "succeeded envelope is not active",
			setupJob: &types.Envelope{
				ID: "test-active-3",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			updateTo:   types.EnvelopeStatusSucceeded,
			envelopeID: "test-active-3",
			wantActive: false,
		},
		{
			name: "failed envelope is not active",
			setupJob: &types.Envelope{
				ID: "test-active-4",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
			},
			updateTo:   types.EnvelopeStatusFailed,
			envelopeID: "test-active-4",
			wantActive: false,
		},
		{
			name:       "non-existent envelope is not active",
			envelopeID: "nonexistent",
			wantActive: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := NewStore()

			if tt.setupJob != nil {
				if err := store.Create(tt.setupJob); err != nil {
					t.Fatalf("Failed to create envelope: %v", err)
				}

				if tt.updateTo != "" {
					update := types.EnvelopeUpdate{
						ID:        tt.envelopeID,
						Status:    tt.updateTo,
						Timestamp: time.Now(),
					}
					if err := store.Update(update); err != nil {
						t.Fatalf("Failed to update envelope: %v", err)
					}
				}
			}

			active := store.IsActive(tt.envelopeID)
			if active != tt.wantActive {
				t.Errorf("IsActive() = %v, want %v", active, tt.wantActive)
			}
		})
	}
}

// TestHandleTimeout tests timeout handling
func TestHandleTimeout(t *testing.T) {
	store := NewStore()

	env := &types.Envelope{
		ID: "test-timeout",
		Route: types.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
		TimeoutSec: 1,
	}

	if err := store.Create(env); err != nil {
		t.Fatalf("Failed to create envelope: %v", err)
	}

	updateChan := store.Subscribe("test-timeout")
	defer store.Unsubscribe("test-timeout", updateChan)

	select {
	case update := <-updateChan:
		if update.Status != types.EnvelopeStatusFailed {
			t.Errorf("Timeout update status = %v, want Failed", update.Status)
		}
		if update.Error != "envelope timed out" {
			t.Errorf("Timeout error = %v, want 'envelope timed out'", update.Error)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Did not receive timeout notification")
	}

	timedOutEnv, _ := store.Get("test-timeout")
	if timedOutEnv.Status != types.EnvelopeStatusFailed {
		t.Errorf("Envelope status after timeout = %v, want Failed", timedOutEnv.Status)
	}
}

// TestCancelTimer tests timer cancellation on final status
func TestCancelTimer(t *testing.T) {
	store := NewStore()

	env := &types.Envelope{
		ID: "test-cancel-timer",
		Route: types.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
		TimeoutSec: 5,
	}

	if err := store.Create(env); err != nil {
		t.Fatalf("Failed to create envelope: %v", err)
	}

	time.Sleep(100 * time.Millisecond)

	update := types.EnvelopeUpdate{
		ID:        "test-cancel-timer",
		Status:    types.EnvelopeStatusSucceeded,
		Timestamp: time.Now(),
	}

	if err := store.Update(update); err != nil {
		t.Fatalf("Failed to update envelope: %v", err)
	}

	time.Sleep(6 * time.Second)

	completedEnv, _ := store.Get("test-cancel-timer")
	if completedEnv.Status != types.EnvelopeStatusSucceeded {
		t.Errorf("Status should remain Succeeded, got %v", completedEnv.Status)
	}
}

// TestCreateDuplicate tests creating duplicate envelopes
func TestCreateDuplicate(t *testing.T) {
	store := NewStore()

	env := &types.Envelope{
		ID: "test-duplicate",
		Route: types.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
	}

	if err := store.Create(env); err != nil {
		t.Fatalf("First create failed: %v", err)
	}

	err := store.Create(env)
	if err == nil {
		t.Error("Expected error for duplicate envelope, got nil")
	}
}

// TestGetNonExistent tests getting non-existent envelope
func TestGetNonExistent(t *testing.T) {
	store := NewStore()

	_, err := store.Get("nonexistent")
	if err == nil {
		t.Error("Expected error for non-existent envelope, got nil")
	}
}

// TestSubscribeUnsubscribe tests subscription lifecycle
func TestSubscribeUnsubscribe(t *testing.T) {
	store := NewStore()

	env := &types.Envelope{
		ID: "test-subscribe",
		Route: types.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
	}

	if err := store.Create(env); err != nil {
		t.Fatalf("Failed to create envelope: %v", err)
	}

	ch1 := store.Subscribe("test-subscribe")
	ch2 := store.Subscribe("test-subscribe")

	progressPercent := 50.0
	update := types.EnvelopeUpdate{
		ID:              "test-subscribe",
		Status:          types.EnvelopeStatusRunning,
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
	update2 := types.EnvelopeUpdate{
		ID:              "test-subscribe",
		Status:          types.EnvelopeStatusRunning,
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

// Helper functions
func floatPtr(f float64) *float64 {
	return &f
}

func intPtr(i int) *int {
	return &i
}
