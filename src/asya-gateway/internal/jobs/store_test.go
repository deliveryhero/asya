package jobs

import (
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestUpdateProgress_InMemoryStore(t *testing.T) {
	store := NewStore()

	// Create a test job
	job := &types.Job{
		ID: "test-job-1",
		Route: types.Route{
			Steps:   []string{"step1", "step2", "step3"},
			Current: 0,
		},
		Status: types.JobStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	tests := []struct {
		name           string
		update         types.JobUpdate
		wantProgress   float64
		wantStep       string
		wantStepStatus string
	}{
		{
			name: "update with progress",
			update: types.JobUpdate{
				JobID:           "test-job-1",
				Status:          types.JobStatusRunning,
				Message:         "Processing step 1",
				ProgressPercent: floatPtr(25.0),
				Step:            "step1",
				StepStatus:      "processing",
				Timestamp:       time.Now(),
			},
			wantProgress:   25.0,
			wantStep:       "step1",
			wantStepStatus: "processing",
		},
		{
			name: "update progress to 50%",
			update: types.JobUpdate{
				JobID:           "test-job-1",
				Status:          types.JobStatusRunning,
				Message:         "Processing step 2",
				ProgressPercent: floatPtr(50.0),
				Step:            "step2",
				StepStatus:      "processing",
				Timestamp:       time.Now(),
			},
			wantProgress:   50.0,
			wantStep:       "step2",
			wantStepStatus: "processing",
		},
		{
			name: "update progress to 100%",
			update: types.JobUpdate{
				JobID:           "test-job-1",
				Status:          types.JobStatusRunning,
				Message:         "Completed",
				ProgressPercent: floatPtr(100.0),
				Step:            "step3",
				StepStatus:      "completed",
				Timestamp:       time.Now(),
			},
			wantProgress:   100.0,
			wantStep:       "step3",
			wantStepStatus: "completed",
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

			if updatedJob.CurrentStep != tt.wantStep {
				t.Errorf("CurrentStep = %v, want %v", updatedJob.CurrentStep, tt.wantStep)
			}

			if updatedJob.Status != types.JobStatusRunning {
				t.Errorf("Status = %v, want Running", updatedJob.Status)
			}
		})
	}
}

func TestUpdateProgress_NotifiesListeners(t *testing.T) {
	store := NewStore()

	job := &types.Job{
		ID: "test-job-notify",
		Route: types.Route{
			Steps:   []string{"step1"},
			Current: 0,
		},
		Status: types.JobStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Subscribe to updates
	updateChan := store.Subscribe("test-job-notify")
	defer store.Unsubscribe("test-job-notify", updateChan)

	// Send progress update
	progressPercent := 33.33
	update := types.JobUpdate{
		JobID:           "test-job-notify",
		Status:          types.JobStatusRunning,
		Message:         "Processing",
		ProgressPercent: &progressPercent,
		Step:            "step1",
		StepStatus:      "processing",
		Timestamp:       time.Now(),
	}

	if err := store.UpdateProgress(update); err != nil {
		t.Fatalf("UpdateProgress failed: %v", err)
	}

	// Wait for notification
	select {
	case receivedUpdate := <-updateChan:
		if receivedUpdate.JobID != "test-job-notify" {
			t.Errorf("JobID = %v, want test-job-notify", receivedUpdate.JobID)
		}
		if receivedUpdate.Step != "step1" {
			t.Errorf("Step = %v, want step1", receivedUpdate.Step)
		}
		if receivedUpdate.StepStatus != "processing" {
			t.Errorf("StepStatus = %v, want processing", receivedUpdate.StepStatus)
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

	update := types.JobUpdate{
		JobID:           "non-existent-job",
		Status:          types.JobStatusRunning,
		ProgressPercent: floatPtr(50.0),
		Timestamp:       time.Now(),
	}

	err := store.UpdateProgress(update)
	if err == nil {
		t.Error("Expected error for non-existent job, got nil")
	}
}

func TestUpdateProgress_MultipleSubscribers(t *testing.T) {
	store := NewStore()

	job := &types.Job{
		ID: "test-job-multi",
		Route: types.Route{
			Steps:   []string{"step1"},
			Current: 0,
		},
		Status: types.JobStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Create multiple subscribers
	numSubscribers := 5
	channels := make([]chan types.JobUpdate, numSubscribers)
	for i := 0; i < numSubscribers; i++ {
		channels[i] = store.Subscribe("test-job-multi")
		defer store.Unsubscribe("test-job-multi", channels[i])
	}

	// Send progress update
	progressPercent := 50.0
	update := types.JobUpdate{
		JobID:           "test-job-multi",
		Status:          types.JobStatusRunning,
		ProgressPercent: &progressPercent,
		Step:            "step1",
		Timestamp:       time.Now(),
	}

	if err := store.UpdateProgress(update); err != nil {
		t.Fatalf("UpdateProgress failed: %v", err)
	}

	// Verify all subscribers received the update
	for i, ch := range channels {
		select {
		case receivedUpdate := <-ch:
			if receivedUpdate.JobID != "test-job-multi" {
				t.Errorf("Subscriber %d: JobID = %v, want test-job-multi", i, receivedUpdate.JobID)
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

	job := &types.Job{
		ID: "test-job-sequence",
		Route: types.Route{
			Steps:   []string{"step1", "step2", "step3"},
			Current: 0,
		},
		Status: types.JobStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Simulate progress through all steps
	progressSequence := []struct {
		percent    float64
		step       string
		stepStatus string
	}{
		{3.33, "step1", "received"},
		{16.67, "step1", "processing"},
		{33.33, "step1", "completed"},
		{36.67, "step2", "received"},
		{50.0, "step2", "processing"},
		{66.67, "step2", "completed"},
		{70.0, "step3", "received"},
		{83.33, "step3", "processing"},
		{100.0, "step3", "completed"},
	}

	for _, p := range progressSequence {
		update := types.JobUpdate{
			JobID:           "test-job-sequence",
			Status:          types.JobStatusRunning,
			ProgressPercent: &p.percent,
			Step:            p.step,
			StepStatus:      p.stepStatus,
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
		if j.CurrentStep != p.step {
			t.Errorf("After update to %s, got %s", p.step, j.CurrentStep)
		}
	}

	// Final verification
	finalJob, _ := store.Get("test-job-sequence")
	if finalJob.ProgressPercent != 100.0 {
		t.Errorf("Final progress = %.2f%%, want 100.00%%", finalJob.ProgressPercent)
	}
	if finalJob.CurrentStep != "step3" {
		t.Errorf("Final step = %v, want step3", finalJob.CurrentStep)
	}
}

func TestJobCreation_InitializesProgress(t *testing.T) {
	store := NewStore()

	job := &types.Job{
		ID: "test-job-init",
		Route: types.Route{
			Steps:   []string{"step1", "step2", "step3"},
			Current: 0,
		},
		Status: types.JobStatusPending,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Verify initial progress values
	createdJob, _ := store.Get("test-job-init")
	if createdJob.ProgressPercent != 0.0 {
		t.Errorf("Initial ProgressPercent = %v, want 0.0", createdJob.ProgressPercent)
	}
	if createdJob.TotalSteps != 3 {
		t.Errorf("TotalSteps = %v, want 3", createdJob.TotalSteps)
	}
	if createdJob.StepsCompleted != 0 {
		t.Errorf("StepsCompleted = %v, want 0", createdJob.StepsCompleted)
	}
}

// Helper function
func floatPtr(f float64) *float64 {
	return &f
}
