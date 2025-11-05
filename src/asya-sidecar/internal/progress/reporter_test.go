package progress

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestNewReporter(t *testing.T) {
	gatewayURL := "http://gateway:8080"
	actorName := "test-actor"

	reporter := NewReporter(gatewayURL, actorName)

	if reporter == nil {
		t.Fatal("NewReporter returned nil")
	}

	if reporter.gatewayURL != gatewayURL {
		t.Errorf("gatewayURL = %v, want %v", reporter.gatewayURL, gatewayURL)
	}

	if reporter.actorName != actorName {
		t.Errorf("actorName = %v, want %v", reporter.actorName, actorName)
	}

	if reporter.httpClient == nil {
		t.Error("httpClient is nil")
	}

	if reporter.httpClient.Timeout != 5*time.Second {
		t.Errorf("httpClient timeout = %v, want 5s", reporter.httpClient.Timeout)
	}
}

func TestReportProgress_Success(t *testing.T) {
	receivedRequests := 0
	var receivedUpdate ProgressUpdate

	// Create mock server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedRequests++

		// Verify request method and path
		if r.Method != http.MethodPost {
			t.Errorf("Method = %v, want POST", r.Method)
		}

		if r.URL.Path != "/jobs/test-job-123/progress" {
			t.Errorf("Path = %v, want /jobs/test-job-123/progress", r.URL.Path)
		}

		// Verify content type
		if r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("Content-Type = %v, want application/json", r.Header.Get("Content-Type"))
		}

		// Decode request body
		if err := json.NewDecoder(r.Body).Decode(&receivedUpdate); err != nil {
			t.Errorf("Failed to decode request body: %v", err)
		}

		// Send success response
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":           "ok",
			"progress_percent": 50.0,
		})
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Step:       "processor",
		StepIndex:  1,
		TotalSteps: 3,
		Status:     StatusProcessing,
		Message:    "Processing data",
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "test-job-123", update)

	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	if receivedRequests != 1 {
		t.Errorf("Received %d requests, want 1", receivedRequests)
	}

	// Verify received update
	if receivedUpdate.Step != "processor" {
		t.Errorf("Received step = %v, want processor", receivedUpdate.Step)
	}

	if receivedUpdate.StepIndex != 1 {
		t.Errorf("Received stepIndex = %v, want 1", receivedUpdate.StepIndex)
	}

	if receivedUpdate.TotalSteps != 3 {
		t.Errorf("Received totalSteps = %v, want 3", receivedUpdate.TotalSteps)
	}

	if receivedUpdate.Status != StatusProcessing {
		t.Errorf("Received status = %v, want processing", receivedUpdate.Status)
	}

	if receivedUpdate.ActorName != "test-actor" {
		t.Errorf("Received actorName = %v, want test-actor", receivedUpdate.ActorName)
	}

	if receivedUpdate.Message != "Processing data" {
		t.Errorf("Received message = %v, want 'Processing data'", receivedUpdate.Message)
	}
}

func TestReportProgress_EmptyJobID(t *testing.T) {
	requestReceived := false

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestReceived = true
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Step:       "test",
		StepIndex:  0,
		TotalSteps: 1,
		Status:     StatusReceived,
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "", update)

	// Should not return error (graceful skip)
	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	// Should not send request
	if requestReceived {
		t.Error("Request was sent despite empty job_id")
	}
}

func TestReportProgress_ServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte("Internal server error"))
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Step:       "test",
		StepIndex:  0,
		TotalSteps: 1,
		Status:     StatusReceived,
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "test-job", update)

	// Should not return error (non-blocking)
	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}
}

func TestReportProgress_NetworkError(t *testing.T) {
	// Use invalid URL to simulate network error
	reporter := NewReporter("http://invalid-host-that-does-not-exist:99999", "test-actor")

	update := ProgressUpdate{
		Step:       "test",
		StepIndex:  0,
		TotalSteps: 1,
		Status:     StatusReceived,
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "test-job", update)

	// Should not return error (non-blocking)
	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}
}

func TestReportProgress_ContextCancellation(t *testing.T) {
	// Create slow server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(2 * time.Second)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Step:       "test",
		StepIndex:  0,
		TotalSteps: 1,
		Status:     StatusReceived,
	}

	// Create context with short timeout
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	err := reporter.ReportProgress(ctx, "test-job", update)

	// Should not return error (non-blocking)
	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}
}

func TestReportProgress_AllStatuses(t *testing.T) {
	tests := []struct {
		name   string
		status ProgressStatus
	}{
		{"received", StatusReceived},
		{"processing", StatusProcessing},
		{"completed", StatusCompleted},
	}

	for _, tt := range tests {
		t.Run(string(tt.status), func(t *testing.T) {
			var receivedStatus ProgressStatus

			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var update ProgressUpdate
				json.NewDecoder(r.Body).Decode(&update)
				receivedStatus = update.Status
				w.WriteHeader(http.StatusOK)
			}))
			defer server.Close()

			reporter := NewReporter(server.URL, "test-actor")

			update := ProgressUpdate{
				Step:       "test",
				StepIndex:  0,
				TotalSteps: 1,
				Status:     tt.status,
			}

			ctx := context.Background()
			err := reporter.ReportProgress(ctx, "test-job", update)

			if err != nil {
				t.Errorf("ReportProgress returned error: %v", err)
			}

			if receivedStatus != tt.status {
				t.Errorf("Received status = %v, want %v", receivedStatus, tt.status)
			}
		})
	}
}

func TestReportProgress_ConcurrentCalls(t *testing.T) {
	requestCount := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestCount++
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	// Send multiple concurrent requests
	numRequests := 10
	done := make(chan bool, numRequests)

	for i := 0; i < numRequests; i++ {
		go func(idx int) {
			update := ProgressUpdate{
				Step:       "test",
				StepIndex:  idx,
				TotalSteps: numRequests,
				Status:     StatusProcessing,
			}
			ctx := context.Background()
			reporter.ReportProgress(ctx, "test-job", update)
			done <- true
		}(i)
	}

	// Wait for all requests to complete
	for i := 0; i < numRequests; i++ {
		<-done
	}

	// Give server time to process
	time.Sleep(100 * time.Millisecond)

	if requestCount != numRequests {
		t.Errorf("Received %d requests, want %d", requestCount, numRequests)
	}
}

func TestReportProgress_WithTimingMetrics(t *testing.T) {
	var receivedUpdate ProgressUpdate

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&receivedUpdate); err != nil {
			t.Errorf("Failed to decode request body: %v", err)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	// Test with duration and message size
	durationMs := int64(1234)
	messageSizeKB := 5.67

	update := ProgressUpdate{
		Step:          "processor",
		StepIndex:     1,
		TotalSteps:    3,
		Status:        StatusCompleted,
		Message:       "Completed processing in 1234ms",
		DurationMs:    &durationMs,
		MessageSizeKB: &messageSizeKB,
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "test-job-123", update)

	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	// Verify timing fields were sent
	if receivedUpdate.DurationMs == nil {
		t.Error("DurationMs was not sent")
	} else if *receivedUpdate.DurationMs != durationMs {
		t.Errorf("DurationMs = %v, want %v", *receivedUpdate.DurationMs, durationMs)
	}

	if receivedUpdate.MessageSizeKB == nil {
		t.Error("MessageSizeKB was not sent")
	} else if *receivedUpdate.MessageSizeKB != messageSizeKB {
		t.Errorf("MessageSizeKB = %v, want %v", *receivedUpdate.MessageSizeKB, messageSizeKB)
	}
}
