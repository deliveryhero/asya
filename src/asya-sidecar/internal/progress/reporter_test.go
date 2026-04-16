package progress

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
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

		if r.URL.Path != "/mesh/test-message-123/progress" {
			t.Errorf("Path = %v, want /mesh/test-message-123/progress", r.URL.Path)
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
		Prev:    []string{"parser"},
		Curr:    "processor",
		Next:    []string{"finalizer"},
		Status:  StatusProcessing,
		Message: "Processing data",
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
	if receivedUpdate.Curr != "processor" {
		t.Errorf("Received curr = %v, want processor", receivedUpdate.Curr)
	}

	if len(receivedUpdate.Prev) != 1 || receivedUpdate.Prev[0] != "parser" {
		t.Errorf("Received prev = %v, want [parser]", receivedUpdate.Prev)
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
		Prev:   []string{},
		Curr:   "test",
		Next:   []string{},
		Status: StatusReceived,
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
		Prev:   []string{},
		Curr:   "test",
		Next:   []string{},
		Status: StatusReceived,
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
		Prev:   []string{},
		Curr:   "test",
		Next:   []string{},
		Status: StatusReceived,
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
		Prev:   []string{},
		Curr:   "test",
		Next:   []string{},
		Status: StatusReceived,
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
				Prev:   []string{},
				Curr:   "test",
				Next:   []string{},
				Status: tt.status,
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
	var requestCount atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestCount.Add(1)
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
				Prev:   []string{},
				Curr:   "test",
				Next:   []string{},
				Status: StatusProcessing,
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

	if int(requestCount.Load()) != numRequests {
		t.Errorf("Received %d requests, want %d", requestCount.Load(), numRequests)
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
		Prev:          []string{"parser"},
		Curr:          "processor",
		Next:          []string{"finalizer"},
		Status:        StatusCompleted,
		Message:       "Completed processing in 1234ms",
		DurationMs:    &durationMs,
		MessageSizeKB: &messageSizeKB,
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
		Prev:    []string{"parser"},
		Curr:    "processor",
		Next:    []string{"finalizer"},
		Status:  StatusProcessing,
		Message: "Processing data",
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
	if receivedUpdate.Curr != "processor" {
		t.Errorf("Received curr = %v, want processor", receivedUpdate.Curr)
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
		Prev:   []string{"parser"},
		Curr:   "processor",
		Next:   []string{"finalizer"},
		Status: StatusProcessing,
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
		Prev:   []string{"parser"},
		Curr:   "processor",
		Next:   []string{"finalizer"},
		Status: StatusProcessing,
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
		Prev:    []string{"parser"},
		Curr:    "processor",
		Next:    []string{"finalizer"},
		Status:  StatusProcessing,
		Message: "Processing data",
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
	if receivedUpdate.Curr != "processor" {
		t.Errorf("Received curr = %v, want processor", receivedUpdate.Curr)
	}
}

func TestCreateMesh_Success(t *testing.T) {
	var receivedPayload CreateMeshPayload

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify request method and path
		if r.Method != http.MethodPost {
			t.Errorf("Method = %v, want POST", r.Method)
		}

		if r.URL.Path != "/mesh" {
			t.Errorf("Path = %v, want /mesh", r.URL.Path)
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
	route := envelopes.Route{
		Prev: []string{"actor1"},
		Curr: "actor2",
		Next: []string{},
	}
	err := reporter.CreateMesh(ctx, "abc-123-1", "abc-123", route)

	if err != nil {
		t.Errorf("CreateMesh returned error: %v", err)
	}

	// Verify received payload
	if receivedPayload.ID != "abc-123-1" {
		t.Errorf("ID = %v, want abc-123-1", receivedPayload.ID)
	}

	if receivedPayload.ParentID != "abc-123" {
		t.Errorf("ParentID = %v, want abc-123", receivedPayload.ParentID)
	}

	if len(receivedPayload.Prev) != 1 {
		t.Errorf("Prev length = %v, want 1", len(receivedPayload.Prev))
	}

	if receivedPayload.Curr != "actor2" {
		t.Errorf("Curr = %v, want actor2", receivedPayload.Curr)
	}
}

func TestCreateMesh_ServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("Internal server error"))
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	ctx := context.Background()
	route := envelopes.Route{Prev: []string{}, Curr: "actor1", Next: []string{}}
	err := reporter.CreateMesh(ctx, "abc-123-1", "abc-123", route)

	// Should return error
	if err == nil {
		t.Error("CreateTask should return error for server error")
	}

	if err != nil && !contains(err.Error(), "status 500") {
		t.Errorf("Error should mention status 500, got: %v", err)
	}
}

func TestCreateMesh_NetworkError(t *testing.T) {
	// Use invalid URL to simulate network error
	reporter := NewReporter("http://invalid-host-that-does-not-exist:99999", "test-actor")

	ctx := context.Background()
	route := envelopes.Route{Prev: []string{}, Curr: "actor1", Next: []string{}}
	err := reporter.CreateMesh(ctx, "abc-123-1", "abc-123", route)

	// Should return error
	if err == nil {
		t.Error("CreateTask should return error for network error")
	}
}

func TestCreateMesh_ContextCancellation(t *testing.T) {
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

	route := envelopes.Route{Prev: []string{}, Curr: "actor1", Next: []string{}}
	err := reporter.CreateMesh(ctx, "abc-123-1", "abc-123", route)

	// Should return error due to timeout
	if err == nil {
		t.Error("CreateTask should return error for context cancellation")
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

// --- PostEvent tests ---

func TestPostEvent_StatusEvent(t *testing.T) {
	var receivedEvent MeshEvent
	var receivedPath string
	var receivedEnvelopeID string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		receivedEnvelopeID = r.Header.Get("X-Asya-Envelope-ID")
		if err := json.NewDecoder(r.Body).Decode(&receivedEvent); err != nil {
			t.Errorf("Failed to decode: %v", err)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	data, _ := json.Marshal(map[string]interface{}{"actor": "train", "progress": 50})

	err := reporter.PostEvent(context.Background(), "abc123", MeshEvent{
		Type:   EventTypeStatus,
		Status: "running",
		Data:   data,
	})

	if err != nil {
		t.Fatalf("PostEvent returned error: %v", err)
	}
	if receivedPath != "/api/v1/mesh/abc123/events" {
		t.Errorf("path = %s, want /api/v1/mesh/abc123/events", receivedPath)
	}
	if receivedEnvelopeID != "abc123" {
		t.Errorf("X-Asya-Envelope-ID = %s, want abc123", receivedEnvelopeID)
	}
	if receivedEvent.Type != EventTypeStatus {
		t.Errorf("type = %s, want status", receivedEvent.Type)
	}
	if receivedEvent.Status != "running" {
		t.Errorf("status = %s, want running", receivedEvent.Status)
	}
}

func TestPostEvent_FlyEvent(t *testing.T) {
	var receivedEvent MeshEvent

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&receivedEvent)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	flyData := json.RawMessage(`{"text":"hello world"}`)

	err := reporter.PostEvent(context.Background(), "abc123", MeshEvent{
		Type: EventTypeFly,
		Data: flyData,
	})

	if err != nil {
		t.Fatalf("PostEvent returned error: %v", err)
	}
	if receivedEvent.Type != EventTypeFly {
		t.Errorf("type = %s, want fly", receivedEvent.Type)
	}
}

func TestPostEvent_FallbackToLegacy_On404(t *testing.T) {
	var legacyPath string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/events") {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		legacyPath = r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	err := reporter.PostEvent(context.Background(), "abc123", MeshEvent{
		Type: EventTypeFly,
		Data: json.RawMessage(`{"text":"token"}`),
	})

	if err != nil {
		t.Fatalf("PostEvent returned error: %v", err)
	}
	if legacyPath != "/mesh/abc123/fly" {
		t.Errorf("legacy path = %s, want /mesh/abc123/fly", legacyPath)
	}
}

func TestPostEvent_FallbackToLegacy_Final_On404(t *testing.T) {
	var legacyPath string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/events") {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		legacyPath = r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	data, _ := json.Marshal(map[string]interface{}{"id": "abc123", "status": "succeeded"})

	err := reporter.PostEvent(context.Background(), "abc123", MeshEvent{
		Type:   EventTypeStatus,
		Status: "succeeded",
		Data:   data,
	})

	if err != nil {
		t.Fatalf("PostEvent returned error: %v", err)
	}
	if legacyPath != "/mesh/abc123/final" {
		t.Errorf("legacy path = %s, want /mesh/abc123/final", legacyPath)
	}
}

func TestPostEvent_EmptyID_Skipped(t *testing.T) {
	requestReceived := false

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestReceived = true
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")

	err := reporter.PostEvent(context.Background(), "", MeshEvent{
		Type:   EventTypeStatus,
		Status: "running",
	})

	if err != nil {
		t.Fatalf("PostEvent returned error: %v", err)
	}
	if requestReceived {
		t.Error("Request should not have been sent for empty ID")
	}
}

func TestPostEvent_NetworkError_FallsBackToLegacy(t *testing.T) {
	// When PostEvent fails to connect to the unified endpoint, it attempts
	// legacy fallback. Both fail here (unreachable host), so the legacy
	// fallback also fails. For FLY events, ForwardFly returns an error.
	reporter := NewReporter("http://192.0.2.1:1", "test-actor")

	err := reporter.PostEvent(context.Background(), "abc123", MeshEvent{
		Type: EventTypeFly,
		Data: json.RawMessage(`{"text":"token"}`),
	})

	// FLY fallback calls ForwardFly which returns an error on network failure
	if err == nil {
		t.Error("PostEvent should return error for unreachable host with FLY fallback")
	}
}

// --- CheckMessage tests ---

func TestCheckMessage_Canceled(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/mesh/abc123" {
			t.Errorf("path = %s, want /api/v1/mesh/abc123", r.URL.Path)
		}
		if r.Method != http.MethodGet {
			t.Errorf("method = %s, want GET", r.Method)
		}
		if r.Header.Get("X-Asya-Envelope-ID") != "abc123" {
			t.Errorf("missing X-Asya-Envelope-ID header")
		}

		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(MessageStatus{ID: "abc123", Status: "canceled"})
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	status, err := reporter.CheckMessage(context.Background(), "abc123")

	if err != nil {
		t.Fatalf("CheckMessage returned error: %v", err)
	}
	if status == nil {
		t.Fatal("status is nil")
	}
	if status.Status != "canceled" {
		t.Errorf("status = %s, want canceled", status.Status)
	}
}

func TestCheckMessage_Running(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(MessageStatus{ID: "abc123", Status: "running"})
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	status, err := reporter.CheckMessage(context.Background(), "abc123")

	if err != nil {
		t.Fatalf("CheckMessage returned error: %v", err)
	}
	if status == nil {
		t.Fatal("status is nil")
	}
	if status.Status != "running" {
		t.Errorf("status = %s, want running", status.Status)
	}
}

func TestCheckMessage_404_ReturnsNil(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	status, err := reporter.CheckMessage(context.Background(), "abc123")

	if err != nil {
		t.Fatalf("CheckMessage returned error: %v", err)
	}
	if status != nil {
		t.Errorf("status should be nil for 404, got %+v", status)
	}
}

func TestCheckMessage_NetworkError_ReturnsNil(t *testing.T) {
	reporter := NewReporter("http://192.0.2.1:1", "test-actor")

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()
	status, err := reporter.CheckMessage(ctx, "abc123")

	if err != nil {
		t.Fatalf("CheckMessage returned error: %v", err)
	}
	if status != nil {
		t.Errorf("status should be nil for network error, got %+v", status)
	}
}

func TestCheckMessage_ServerError_ReturnsNil(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	status, err := reporter.CheckMessage(context.Background(), "abc123")

	if err != nil {
		t.Fatalf("CheckMessage returned error: %v", err)
	}
	if status != nil {
		t.Errorf("status should be nil for 500, got %+v", status)
	}
}

func TestCheckMessage_EmptyID_ReturnsNil(t *testing.T) {
	requestReceived := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestReceived = true
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	status, err := reporter.CheckMessage(context.Background(), "")

	if err != nil {
		t.Fatalf("CheckMessage returned error: %v", err)
	}
	if status != nil {
		t.Errorf("status should be nil for empty ID, got %+v", status)
	}
	if requestReceived {
		t.Error("Request should not have been sent for empty ID")
	}
}

// --- X-Asya-Envelope-ID header tests ---

func TestReportProgress_SetsEnvelopeIDHeader(t *testing.T) {
	var receivedEnvelopeID string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedEnvelopeID = r.Header.Get("X-Asya-Envelope-ID")
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	update := ProgressUpdate{
		Prev:   []string{},
		Curr:   "test",
		Next:   []string{},
		Status: StatusReceived,
	}

	err := reporter.ReportProgress(context.Background(), "env-id-123", update)
	if err != nil {
		t.Fatalf("ReportProgress returned error: %v", err)
	}

	if receivedEnvelopeID != "env-id-123" {
		t.Errorf("X-Asya-Envelope-ID = %s, want env-id-123", receivedEnvelopeID)
	}
}

func TestForwardFly_SetsEnvelopeIDHeader(t *testing.T) {
	var receivedEnvelopeID string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedEnvelopeID = r.Header.Get("X-Asya-Envelope-ID")
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	err := reporter.ForwardFly(context.Background(), "fly-id-456", json.RawMessage(`{"text":"hi"}`))

	if err != nil {
		t.Fatalf("ForwardFly returned error: %v", err)
	}

	if receivedEnvelopeID != "fly-id-456" {
		t.Errorf("X-Asya-Envelope-ID = %s, want fly-id-456", receivedEnvelopeID)
	}
}

func TestCreateMesh_SetsEnvelopeIDHeader(t *testing.T) {
	var receivedEnvelopeID string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedEnvelopeID = r.Header.Get("X-Asya-Envelope-ID")
		w.WriteHeader(http.StatusCreated)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	route := envelopes.Route{Prev: []string{}, Curr: "a1", Next: []string{}}
	err := reporter.CreateMesh(context.Background(), "mesh-id-789", "parent-1", route)

	if err != nil {
		t.Fatalf("CreateMesh returned error: %v", err)
	}

	if receivedEnvelopeID != "mesh-id-789" {
		t.Errorf("X-Asya-Envelope-ID = %s, want mesh-id-789", receivedEnvelopeID)
	}
}

// --- ReportFinalError via PostEvent tests ---

func TestReportFinalError_UsesPostEvent(t *testing.T) {
	var receivedPath string
	var receivedEvent MeshEvent

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		_ = json.NewDecoder(r.Body).Decode(&receivedEvent)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	reporter := NewReporter(server.URL, "test-actor")
	err := reporter.ReportFinalError(context.Background(), "err-123", "something broke")

	if err != nil {
		t.Fatalf("ReportFinalError returned error: %v", err)
	}

	if receivedPath != "/api/v1/mesh/err-123/events" {
		t.Errorf("path = %s, want /api/v1/mesh/err-123/events", receivedPath)
	}

	if receivedEvent.Type != EventTypeStatus {
		t.Errorf("type = %s, want status", receivedEvent.Type)
	}

	if receivedEvent.Status != "failed" {
		t.Errorf("status = %s, want failed", receivedEvent.Status)
	}

	var data map[string]interface{}
	if err := json.Unmarshal(receivedEvent.Data, &data); err != nil {
		t.Fatalf("Failed to parse event data: %v", err)
	}

	if data["error"] != "something broke" {
		t.Errorf("error = %v, want 'something broke'", data["error"])
	}
}
