//go:build integration
// +build integration

package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/internal/mcp"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// TestProgressTracking_EndToEnd simulates the complete progress tracking flow
func TestProgressTracking_EndToEnd(t *testing.T) {
	// Setup: Create job store and handler
	_ = context.Background()
	store := jobs.NewStore()
	handler := mcp.NewHandler(store)

	// Create a test job with 3 steps
	job := &types.Job{
		ID: "integration-test-job-1",
		Route: types.Route{
			Steps:   []string{"parser", "processor", "finalizer"},
			Current: 0,
		},
		Payload:    map[string]interface{}{"data": "test"},
		Status:     types.JobStatusPending,
		TimeoutSec: 300,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Subscribe to job updates (simulate SSE client)
	updateChan := store.Subscribe(job.ID)
	defer store.Unsubscribe(job.ID, updateChan)

	// Collect all updates
	updates := make([]types.JobUpdate, 0)
	done := make(chan bool)

	go func() {
		timeout := time.After(5 * time.Second)
		for {
			select {
			case update := <-updateChan:
				updates = append(updates, update)
				// Stop after receiving final update
				if update.ProgressPercent != nil && *update.ProgressPercent == 100.0 {
					done <- true
					return
				}
			case <-timeout:
				done <- true
				return
			}
		}
	}()

	// Simulate progress reports from actors through the pipeline
	progressReports := []struct {
		step      string
		stepIndex int
		status    string
		wantMin   float64
		wantMax   float64
	}{
		// Step 0: parser
		{"parser", 0, "received", 3.0, 4.0},
		{"parser", 0, "processing", 16.0, 17.0},
		{"parser", 0, "completed", 33.0, 34.0},

		// Step 1: processor
		{"processor", 1, "received", 36.0, 37.0},
		{"processor", 1, "processing", 49.0, 51.0},
		{"processor", 1, "completed", 66.0, 67.0},

		// Step 2: finalizer
		{"finalizer", 2, "received", 69.0, 71.0},
		{"finalizer", 2, "processing", 83.0, 84.0},
		{"finalizer", 2, "completed", 99.0, 101.0},
	}

	for _, report := range progressReports {
		progressUpdate := types.ProgressUpdate{
			Step:       report.step,
			StepIndex:  report.stepIndex,
			TotalSteps: 3,
			Status:     report.status,
			ActorName:  report.step + "-pod-123",
			Message:    "Processing " + report.step,
		}

		body, _ := json.Marshal(progressUpdate)
		req := httptest.NewRequest(http.MethodPost, "/jobs/"+job.ID+"/progress", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rr := httptest.NewRecorder()

		handler.HandleJobProgress(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Progress update failed for %s/%s: status=%d", report.step, report.status, rr.Code)
		}

		var response map[string]interface{}
		json.NewDecoder(rr.Body).Decode(&response)
		progressPercent := response["progress_percent"].(float64)

		if progressPercent < report.wantMin || progressPercent > report.wantMax {
			t.Errorf("Step %s/%s: progress=%.2f, want %.2f-%.2f",
				report.step, report.status, progressPercent, report.wantMin, report.wantMax)
		}

		// Small delay to simulate realistic timing
		time.Sleep(10 * time.Millisecond)
	}

	// Wait for all updates to be collected
	<-done

	// Verify we received all expected updates
	if len(updates) < 9 {
		t.Errorf("Received %d updates, want at least 9", len(updates))
	}

	// Verify final job state
	finalJob, err := store.Get(job.ID)
	if err != nil {
		t.Fatalf("Failed to get final job state: %v", err)
	}

	if finalJob.ProgressPercent < 99.0 || finalJob.ProgressPercent > 101.0 {
		t.Errorf("Final progress = %.2f%%, want ~100%%", finalJob.ProgressPercent)
	}

	if finalJob.CurrentStep != "finalizer" {
		t.Errorf("Final step = %v, want finalizer", finalJob.CurrentStep)
	}

	// Verify progress increases monotonically
	for i := 1; i < len(updates); i++ {
		if updates[i].ProgressPercent == nil || updates[i-1].ProgressPercent == nil {
			continue
		}
		if *updates[i].ProgressPercent < *updates[i-1].ProgressPercent {
			t.Errorf("Progress decreased: %.2f%% -> %.2f%%",
				*updates[i-1].ProgressPercent, *updates[i].ProgressPercent)
		}
	}
}

// TestProgressTracking_SSEStream tests the SSE streaming of progress updates
func TestProgressTracking_SSEStream(t *testing.T) {
	store := jobs.NewStore()
	handler := mcp.NewHandler(store)

	// Create job
	job := &types.Job{
		ID: "sse-test-job",
		Route: types.Route{
			Steps:   []string{"step1", "step2"},
			Current: 0,
		},
		Status: types.JobStatusPending,
	}
	store.Create(job)

	// Start SSE stream in goroutine
	req := httptest.NewRequest(http.MethodGet, "/jobs/"+job.ID+"/stream", nil)
	rr := httptest.NewRecorder()

	// Stream in background
	go func() {
		handler.HandleJobStream(rr, req)
	}()

	// Give stream time to start
	time.Sleep(50 * time.Millisecond)

	// Send progress updates
	for i := 0; i < 2; i++ {
		progressUpdate := types.ProgressUpdate{
			Step:       "step1",
			StepIndex:  0,
			TotalSteps: 2,
			Status:     []string{"received", "completed"}[i],
			ActorName:  "test-actor",
		}

		body, _ := json.Marshal(progressUpdate)
		progressReq := httptest.NewRequest(http.MethodPost, "/jobs/"+job.ID+"/progress", bytes.NewReader(body))
		progressReq.Header.Set("Content-Type", "application/json")
		progressRr := httptest.NewRecorder()

		handler.HandleJobProgress(progressRr, progressReq)

		if progressRr.Code != http.StatusOK {
			t.Fatalf("Progress update %d failed: %v", i, progressRr.Code)
		}

		time.Sleep(100 * time.Millisecond)
	}

	// Verify SSE stream contains progress data
	body := rr.Body.String()
	if body == "" {
		t.Error("SSE stream is empty")
	}

	// Check for SSE event format
	if !strings.Contains(body, "event: ") {
		t.Error("SSE stream missing event markers")
	}

	if !strings.Contains(body, "data: ") {
		t.Error("SSE stream missing data markers")
	}
}

// TestProgressTracking_ConcurrentUpdates tests handling of concurrent progress updates
func TestProgressTracking_ConcurrentUpdates(t *testing.T) {
	store := jobs.NewStore()
	handler := mcp.NewHandler(store)

	jobID := "concurrent-test-job"
	job := &types.Job{
		ID: jobID,
		Route: types.Route{
			Steps:   []string{"step1", "step2", "step3"},
			Current: 0,
		},
		Status: types.JobStatusPending,
	}
	store.Create(job)

	// Send multiple concurrent progress updates
	numUpdates := 10
	done := make(chan bool, numUpdates)

	for i := 0; i < numUpdates; i++ {
		go func(idx int) {
			progressUpdate := types.ProgressUpdate{
				Step:       "step1",
				StepIndex:  0,
				TotalSteps: 3,
				Status:     "processing",
				ActorName:  "test-actor",
			}

			body, _ := json.Marshal(progressUpdate)
			req := httptest.NewRequest(http.MethodPost, "/jobs/"+jobID+"/progress", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			handler.HandleJobProgress(rr, req)

			if rr.Code != http.StatusOK {
				t.Errorf("Update %d failed: status=%d", idx, rr.Code)
			}
			done <- true
		}(i)
	}

	// Wait for all updates
	for i := 0; i < numUpdates; i++ {
		<-done
	}

	// Verify job state is consistent
	finalJob, err := store.Get(jobID)
	if err != nil {
		t.Fatalf("Failed to get job: %v", err)
	}

	// Should have some progress (exact value doesn't matter due to concurrency)
	if finalJob.ProgressPercent <= 0 {
		t.Error("Progress should be > 0 after updates")
	}
}

// TestProgressTracking_InvalidJobID tests behavior with non-existent job
func TestProgressTracking_InvalidJobID(t *testing.T) {
	store := jobs.NewStore()
	handler := mcp.NewHandler(store)

	progressUpdate := types.ProgressUpdate{
		Step:       "test",
		StepIndex:  0,
		TotalSteps: 1,
		Status:     "processing",
		ActorName:  "test-actor",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/jobs/non-existent-job/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleJobProgress(rr, req)

	// Should return error for non-existent job
	if rr.Code == http.StatusOK {
		t.Error("Expected error for non-existent job, got success")
	}
}
