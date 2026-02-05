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

		if r.URL.Path != "/envelopes/test-message-123/progress" {
			t.Errorf("Path = %v, want /envelopes/test-message-123/progress", r.URL.Path)
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
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"status":           "ok",
			"progress_percent": 50.0,
		})
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Actors:          []string{"parser", "processor", "finalizer"},
		CurrentActorIdx: 1,
		Status:          StatusProcessing,
		Message:         "Processing data",
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "test-message-123", update)

	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	if receivedRequests != 1 {
		t.Errorf("Received %d requests, want 1", receivedRequests)
	}

	// Verify received update
	if len(receivedUpdate.Actors) != 3 {
		t.Errorf("Received %d actors, want 3", len(receivedUpdate.Actors))
	}

	if receivedUpdate.CurrentActorIdx != 1 {
		t.Errorf("Received currentActorIdx = %v, want 1", receivedUpdate.CurrentActorIdx)
	}

	if receivedUpdate.Status != StatusProcessing {
		t.Errorf("Received status = %v, want processing", receivedUpdate.Status)
	}

	if receivedUpdate.Message != "Processing data" {
		t.Errorf("Received message = %v, want 'Processing data'", receivedUpdate.Message)
	}
}

func TestReportProgress_EmptyID(t *testing.T) {
	requestReceived := false

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestReceived = true
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Actors:          []string{"test"},
		CurrentActorIdx: 0,
		Status:          StatusReceived,
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "", update)

	// Should not return error (graceful skip)
	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	// Should not send request
	if requestReceived {
		t.Error("Request was sent despite empty message id")
	}
}

func TestReportProgress_ServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("Internal server error"))
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Actors:          []string{"test"},
		CurrentActorIdx: 0,
		Status:          StatusReceived,
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
		Actors:          []string{"test"},
		CurrentActorIdx: 0,
		Status:          StatusReceived,
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
		Actors:          []string{"test"},
		CurrentActorIdx: 0,
		Status:          StatusReceived,
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
				_ = json.NewDecoder(r.Body).Decode(&update)
				receivedStatus = update.Status
				w.WriteHeader(http.StatusOK)
			}))
			defer server.Close()

			reporter := NewReporter(server.URL, "test-actor")

			update := ProgressUpdate{
				Actors:          []string{"test"},
				CurrentActorIdx: 0,
				Status:          tt.status,
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
				Actors:          []string{"test"},
				CurrentActorIdx: idx,
				Status:          StatusProcessing,
			}
			ctx := context.Background()
			_ = reporter.ReportProgress(ctx, "test-job", update)
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
		Actors:          []string{"parser", "processor", "finalizer"},
		CurrentActorIdx: 1,
		Status:          StatusCompleted,
		Message:         "Completed processing in 1234ms",
		DurationMs:      &durationMs,
		MessageSizeKB:   &messageSizeKB,
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "test-message-123", update)

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

func TestReportProgress_RetriesOnFailure(t *testing.T) {
	attemptCount := 0
	var receivedUpdate ProgressUpdate

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attemptCount++

		// Fail first 2 attempts, succeed on 3rd
		if attemptCount < 3 {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		if err := json.NewDecoder(r.Body).Decode(&receivedUpdate); err != nil {
			t.Errorf("Failed to decode request body: %v", err)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Actors:          []string{"parser", "processor", "finalizer"},
		CurrentActorIdx: 1,
		Status:          StatusProcessing,
		Message:         "Processing data",
	}

	ctx := context.Background()
	start := time.Now()
	err := reporter.ReportProgress(ctx, "test-message-123", update)
	duration := time.Since(start)

	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	// Should have retried 3 times total (2 failures + 1 success)
	if attemptCount != 3 {
		t.Errorf("Expected 3 attempts, got %d", attemptCount)
	}

	// Should have taken at least 2 retry delays (2 * 200ms = 400ms)
	minExpectedDuration := 400 * time.Millisecond
	if duration < minExpectedDuration {
		t.Errorf("Duration %v is less than expected minimum %v", duration, minExpectedDuration)
	}

	// Verify update was received on successful attempt
	if len(receivedUpdate.Actors) == 0 || receivedUpdate.Actors[receivedUpdate.CurrentActorIdx] != "processor" {
		t.Errorf("Received actors = %v, currentIdx = %d, want processor at index", receivedUpdate.Actors, receivedUpdate.CurrentActorIdx)
	}
}

func TestReportProgress_RetriesUpToMaxAttempts(t *testing.T) {
	attemptCount := 0

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attemptCount++
		// Always fail
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Actors:          []string{"parser", "processor", "finalizer"},
		CurrentActorIdx: 1,
		Status:          StatusProcessing,
	}

	ctx := context.Background()
	err := reporter.ReportProgress(ctx, "test-message-123", update)

	// Should not return error (non-blocking)
	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	// Should have retried 5 times (maxRetries = 5)
	if attemptCount != 5 {
		t.Errorf("Expected 5 attempts, got %d", attemptCount)
	}
}

func TestReportProgress_RespectsContextCancellationDuringRetry(t *testing.T) {
	attemptCount := 0

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attemptCount++
		// Always fail to trigger retries
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Actors:          []string{"parser", "processor", "finalizer"},
		CurrentActorIdx: 1,
		Status:          StatusProcessing,
	}

	// Create context that cancels after first attempt
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	err := reporter.ReportProgress(ctx, "test-message-123", update)

	// Should not return error (non-blocking)
	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	// Should have stopped after context cancellation (likely 1-2 attempts)
	if attemptCount >= 5 {
		t.Errorf("Expected fewer than 5 attempts due to context cancellation, got %d", attemptCount)
	}
}

func TestReportProgress_SucceedsOnFirstAttempt(t *testing.T) {
	attemptCount := 0
	var receivedUpdate ProgressUpdate

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attemptCount++
		if err := json.NewDecoder(r.Body).Decode(&receivedUpdate); err != nil {
			t.Errorf("Failed to decode request body: %v", err)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	update := ProgressUpdate{
		Actors:          []string{"parser", "processor", "finalizer"},
		CurrentActorIdx: 1,
		Status:          StatusProcessing,
		Message:         "Processing data",
	}

	ctx := context.Background()
	start := time.Now()
	err := reporter.ReportProgress(ctx, "test-message-123", update)
	duration := time.Since(start)

	if err != nil {
		t.Errorf("ReportProgress returned error: %v", err)
	}

	// Should succeed on first attempt
	if attemptCount != 1 {
		t.Errorf("Expected 1 attempt, got %d", attemptCount)
	}

	// Should not have delayed (no retries)
	maxExpectedDuration := 100 * time.Millisecond
	if duration > maxExpectedDuration {
		t.Errorf("Duration %v exceeds expected maximum %v (no retries should occur)", duration, maxExpectedDuration)
	}

	// Verify update was received
	if len(receivedUpdate.Actors) == 0 || receivedUpdate.Actors[receivedUpdate.CurrentActorIdx] != "processor" {
		t.Errorf("Received actors = %v, currentIdx = %d, want processor at index", receivedUpdate.Actors, receivedUpdate.CurrentActorIdx)
	}
}

func TestCreateEnvelope_Success(t *testing.T) {
	var receivedPayload CreateEnvelopePayload

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify request method and path
		if r.Method != http.MethodPost {
			t.Errorf("Method = %v, want POST", r.Method)
		}

		if r.URL.Path != "/envelopes" {
			t.Errorf("Path = %v, want /envelopes", r.URL.Path)
		}

		// Verify content type
		if r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("Content-Type = %v, want application/json", r.Header.Get("Content-Type"))
		}

		// Decode request body
		if err := json.NewDecoder(r.Body).Decode(&receivedPayload); err != nil {
			t.Errorf("Failed to decode request body: %v", err)
		}

		// Send success response
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "created", "id": receivedPayload.ID})
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	ctx := context.Background()
	err := reporter.CreateEnvelope(ctx, "abc-123-1", "abc-123", []string{"actor1", "actor2"}, 1)

	if err != nil {
		t.Errorf("CreateEnvelope returned error: %v", err)
	}

	// Verify received payload
	if receivedPayload.ID != "abc-123-1" {
		t.Errorf("ID = %v, want abc-123-1", receivedPayload.ID)
	}

	if receivedPayload.ParentID != "abc-123" {
		t.Errorf("ParentID = %v, want abc-123", receivedPayload.ParentID)
	}

	if len(receivedPayload.Actors) != 2 {
		t.Errorf("Actors length = %v, want 2", len(receivedPayload.Actors))
	}

	if receivedPayload.Current != 1 {
		t.Errorf("Current = %v, want 1", receivedPayload.Current)
	}
}

func TestCreateEnvelope_ServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("Internal server error"))
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	ctx := context.Background()
	err := reporter.CreateEnvelope(ctx, "abc-123-1", "abc-123", []string{"actor1"}, 1)

	// Should return error
	if err == nil {
		t.Error("CreateEnvelope should return error for server error")
	}

	if err != nil && !contains(err.Error(), "status 500") {
		t.Errorf("Error should mention status 500, got: %v", err)
	}
}

func TestCreateEnvelope_NetworkError(t *testing.T) {
	// Use invalid URL to simulate network error
	reporter := NewReporter("http://invalid-host-that-does-not-exist:99999", "test-actor")

	ctx := context.Background()
	err := reporter.CreateEnvelope(ctx, "abc-123-1", "abc-123", []string{"actor1"}, 1)

	// Should return error
	if err == nil {
		t.Error("CreateEnvelope should return error for network error")
	}
}

func TestCreateEnvelope_ContextCancellation(t *testing.T) {
	// Create slow server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(2 * time.Second)
		w.WriteHeader(http.StatusCreated)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	// Create context with short timeout
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	err := reporter.CreateEnvelope(ctx, "abc-123-1", "abc-123", []string{"actor1"}, 1)

	// Should return error due to timeout
	if err == nil {
		t.Error("CreateEnvelope should return error for context cancellation")
	}
}

// Helper function
func contains(s, substr string) bool {
	for i := range s {
		if i+len(substr) <= len(s) && s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}

func TestCheckHealth_Success(t *testing.T) {
	requestReceived := false

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestReceived = true

		// Verify request method and path
		if r.Method != http.MethodGet {
			t.Errorf("Method = %v, want GET", r.Method)
		}

		if r.URL.Path != "/health" {
			t.Errorf("Path = %v, want /health", r.URL.Path)
		}

		// Send success response
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("OK"))
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	ctx := context.Background()
	err := reporter.CheckHealth(ctx)

	if err != nil {
		t.Errorf("CheckHealth returned error: %v", err)
	}

	if !requestReceived {
		t.Error("Health check request was not sent")
	}
}

func TestCheckHealth_ServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("Internal server error"))
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	ctx := context.Background()
	err := reporter.CheckHealth(ctx)

	// Should return error
	if err == nil {
		t.Error("CheckHealth should return error for server error")
	}

	if err != nil && !contains(err.Error(), "status 500") {
		t.Errorf("Error should mention status 500, got: %v", err)
	}
}

func TestCheckHealth_NetworkError(t *testing.T) {
	// Use invalid URL to simulate network error
	reporter := NewReporter("http://invalid-host-that-does-not-exist:99999", "test-actor")

	ctx := context.Background()
	err := reporter.CheckHealth(ctx)

	// Should return error
	if err == nil {
		t.Error("CheckHealth should return error for network error")
	}

	if err != nil && !contains(err.Error(), "failed to reach gateway health endpoint") {
		t.Errorf("Error should mention connection failure, got: %v", err)
	}
}

func TestCheckHealth_ContextCancellation(t *testing.T) {
	// Create slow server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(2 * time.Second)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	// Create context with short timeout
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	err := reporter.CheckHealth(ctx)

	// Should return error due to timeout
	if err == nil {
		t.Error("CheckHealth should return error for context cancellation")
	}
}

func TestCheckHealth_NonOKStatus(t *testing.T) {
	tests := []struct {
		name       string
		statusCode int
	}{
		{"400 Bad Request", http.StatusBadRequest},
		{"404 Not Found", http.StatusNotFound},
		{"503 Service Unavailable", http.StatusServiceUnavailable},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tt.statusCode)
			}))
			defer server.Close()

			reporter := NewReporter(server.URL, "test-actor")

			ctx := context.Background()
			err := reporter.CheckHealth(ctx)

			// Should return error for non-200 status
			if err == nil {
				t.Errorf("CheckHealth should return error for status %d", tt.statusCode)
			}

			if err != nil && !contains(err.Error(), "health check failed") {
				t.Errorf("Error should mention health check failure, got: %v", err)
			}
		})
	}
}
