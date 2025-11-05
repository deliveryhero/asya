package mcp

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandleJobProgress(t *testing.T) {
	tests := []struct {
		name           string
		method         string
		jobID          string
		jobExists      bool
		progressUpdate types.ProgressUpdate
		wantStatus     int
		wantProgress   float64
	}{
		{
			name:      "valid progress update - received",
			method:    http.MethodPost,
			jobID:     "test-job-1",
			jobExists: true,
			progressUpdate: types.ProgressUpdate{
				Step:       "parser",
				StepIndex:  0,
				TotalSteps: 3,
				Status:     "received",
				ActorName:  "parser-pod-123",
				Message:    "Message received",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 3.33,
		},
		{
			name:      "valid progress update - processing",
			method:    http.MethodPost,
			jobID:     "test-job-2",
			jobExists: true,
			progressUpdate: types.ProgressUpdate{
				Step:       "processor",
				StepIndex:  1,
				TotalSteps: 3,
				Status:     "processing",
				ActorName:  "processor-pod-456",
				Message:    "Processing data",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 50.0,
		},
		{
			name:      "valid progress update - completed",
			method:    http.MethodPost,
			jobID:     "test-job-3",
			jobExists: true,
			progressUpdate: types.ProgressUpdate{
				Step:       "finalizer",
				StepIndex:  2,
				TotalSteps: 3,
				Status:     "completed",
				ActorName:  "finalizer-pod-789",
				Message:    "Processing complete",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 100.0,
		},
		{
			name:       "invalid method",
			method:     http.MethodGet,
			jobID:      "test-job-4",
			jobExists:  true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "missing job ID",
			method:     http.MethodPost,
			jobID:      "",
			jobExists:  false,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create in-memory job store
			store := jobs.NewStore()

			// Create test job if needed
			if tt.jobExists {
				job := &types.Job{
					ID: tt.jobID,
					Route: types.Route{
						Steps:   []string{"parser", "processor", "finalizer"},
						Current: 0,
					},
					Status: types.JobStatusPending,
				}
				if err := store.Create(job); err != nil {
					t.Fatalf("Failed to create test job: %v", err)
				}
			}

			// Create handler
			handler := NewHandler(store)

			// Create request
			var req *http.Request
			if tt.method == http.MethodPost && tt.jobID != "" {
				body, _ := json.Marshal(tt.progressUpdate)
				req = httptest.NewRequest(tt.method, "/jobs/"+tt.jobID+"/progress", bytes.NewReader(body))
				req.Header.Set("Content-Type", "application/json")
			} else {
				req = httptest.NewRequest(tt.method, "/jobs/"+tt.jobID+"/progress", nil)
			}

			// Create response recorder
			rr := httptest.NewRecorder()

			// Call handler
			handler.HandleJobProgress(rr, req)

			// Check status code
			if rr.Code != tt.wantStatus {
				t.Errorf("HandleJobProgress() status = %v, want %v", rr.Code, tt.wantStatus)
			}

			// Check response for successful cases
			if tt.wantStatus == http.StatusOK {
				var response map[string]interface{}
				if err := json.NewDecoder(rr.Body).Decode(&response); err != nil {
					t.Fatalf("Failed to decode response: %v", err)
				}

				if response["status"] != "ok" {
					t.Errorf("Response status = %v, want 'ok'", response["status"])
				}

				progressPercent := response["progress_percent"].(float64)
				if progressPercent < tt.wantProgress-0.5 || progressPercent > tt.wantProgress+0.5 {
					t.Errorf("Progress percent = %v, want ~%v", progressPercent, tt.wantProgress)
				}

				// Verify job was updated in store
				job, err := store.Get(tt.jobID)
				if err != nil {
					t.Fatalf("Failed to get updated job: %v", err)
				}

				if job.ProgressPercent < tt.wantProgress-0.5 || job.ProgressPercent > tt.wantProgress+0.5 {
					t.Errorf("Stored progress = %v, want ~%v", job.ProgressPercent, tt.wantProgress)
				}

				if job.CurrentStep != tt.progressUpdate.Step {
					t.Errorf("Current step = %v, want %v", job.CurrentStep, tt.progressUpdate.Step)
				}
			}
		})
	}
}

func TestHandleJobProgress_ProgressCalculation(t *testing.T) {
	tests := []struct {
		name         string
		stepIndex    int
		totalSteps   int
		status       string
		wantProgress float64
	}{
		// 3-step pipeline
		{"step 0 received", 0, 3, "received", 3.33},
		{"step 0 processing", 0, 3, "processing", 16.67},
		{"step 0 completed", 0, 3, "completed", 33.33},
		{"step 1 received", 1, 3, "received", 36.67},
		{"step 1 processing", 1, 3, "processing", 50.0},
		{"step 1 completed", 1, 3, "completed", 66.67},
		{"step 2 received", 2, 3, "received", 70.0},
		{"step 2 processing", 2, 3, "processing", 83.33},
		{"step 2 completed", 2, 3, "completed", 100.0},

		// 5-step pipeline
		{"5-step: step 2 processing", 2, 5, "processing", 50.0},
		{"5-step: step 4 completed", 4, 5, "completed", 100.0},

		// Single-step pipeline
		{"1-step: step 0 received", 0, 1, "received", 10.0},
		{"1-step: step 0 processing", 0, 1, "processing", 50.0},
		{"1-step: step 0 completed", 0, 1, "completed", 100.0},

		// Edge case: zero total steps (division by zero protection)
		{"zero steps: received", 0, 0, "received", 0.0},
		{"zero steps: processing", 0, 0, "processing", 0.0},
		{"zero steps: completed", 0, 0, "completed", 0.0},
	}

	for i, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := jobs.NewStore()
			handler := NewHandler(store)

			jobID := fmt.Sprintf("test-job-%d", i)
			job := &types.Job{
				ID: jobID,
				Route: types.Route{
					Steps:   make([]string, tt.totalSteps),
					Current: 0,
				},
				Status: types.JobStatusPending,
			}
			if err := store.Create(job); err != nil {
				t.Fatalf("Failed to create test job: %v", err)
			}

			progressUpdate := types.ProgressUpdate{
				Step:       "test-step",
				StepIndex:  tt.stepIndex,
				TotalSteps: tt.totalSteps,
				Status:     tt.status,
				ActorName:  "test-actor",
			}

			body, _ := json.Marshal(progressUpdate)
			req := httptest.NewRequest(http.MethodPost, "/jobs/"+jobID+"/progress", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			handler.HandleJobProgress(rr, req)

			if rr.Code != http.StatusOK {
				t.Fatalf("Expected status 200, got %v", rr.Code)
			}

			var response map[string]interface{}
			if err := json.NewDecoder(rr.Body).Decode(&response); err != nil {
				t.Fatalf("Failed to decode response: %v", err)
			}

			progressPercent := response["progress_percent"].(float64)
			tolerance := 0.5
			if progressPercent < tt.wantProgress-tolerance || progressPercent > tt.wantProgress+tolerance {
				t.Errorf("Progress percent = %.2f, want %.2f (±%.1f)", progressPercent, tt.wantProgress, tolerance)
			}
		})
	}
}

func TestHandleJobProgress_SSENotification(t *testing.T) {
	store := jobs.NewStore()
	handler := NewHandler(store)

	jobID := "test-job-sse"
	job := &types.Job{
		ID: jobID,
		Route: types.Route{
			Steps:   []string{"step1", "step2"},
			Current: 0,
		},
		Status: types.JobStatusPending,
	}
	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create test job: %v", err)
	}

	// Subscribe to job updates
	updateChan := store.Subscribe(jobID)
	defer store.Unsubscribe(jobID, updateChan)

	// Send progress update
	progressUpdate := types.ProgressUpdate{
		Step:       "step1",
		StepIndex:  0,
		TotalSteps: 2,
		Status:     "processing",
		ActorName:  "test-actor",
		Message:    "Processing step 1",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/jobs/"+jobID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleJobProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Expected status 200, got %v", rr.Code)
	}

	// Wait for SSE notification
	select {
	case update := <-updateChan:
		if update.JobID != jobID {
			t.Errorf("Update job ID = %v, want %v", update.JobID, jobID)
		}
		if update.Step != "step1" {
			t.Errorf("Update step = %v, want step1", update.Step)
		}
		if update.StepStatus != "processing" {
			t.Errorf("Update step status = %v, want processing", update.StepStatus)
		}
		if update.ProgressPercent == nil || *update.ProgressPercent < 24.5 || *update.ProgressPercent > 25.5 {
			t.Errorf("Update progress = %v, want ~25.0", update.ProgressPercent)
		}
	case <-time.After(1 * time.Second):
		t.Fatal("Did not receive SSE notification within timeout")
	}
}
