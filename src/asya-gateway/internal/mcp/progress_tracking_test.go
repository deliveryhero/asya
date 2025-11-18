package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/envelopestore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// TestProgressTracking_EndToEnd simulates the complete progress tracking flow
func TestProgressTracking_EndToEnd(t *testing.T) {
	// Setup: Create job store and handler
	_ = context.Background()
	store := envelopestore.NewStore()
	handler := NewHandler(store)

	// Create a test job with 3 actors
	job := &types.Envelope{
		ID: "integration-test-job-1",
		Route: types.Route{
			Actors:  []string{"parser", "processor", "finalizer"},
			Current: 0,
		},
		Payload:    map[string]interface{}{"data": "test"},
		Status:     types.EnvelopeStatusPending,
		TimeoutSec: 300,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Subscribe to job updates (simulate SSE client)
	updateChan := store.Subscribe(job.ID)
	defer store.Unsubscribe(job.ID, updateChan)

	// Collect all updates
	updates := make([]types.EnvelopeUpdate, 0)
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
		actor      string
		actorIndex int
		status     string
		wantMin    float64
		wantMax    float64
	}{
		// Actor 0: parser
		{"parser", 0, "received", 3.0, 4.0},
		{"parser", 0, "processing", 16.0, 17.0},
		{"parser", 0, "completed", 33.0, 34.0},

		// Actor 1: processor
		{"processor", 1, "received", 36.0, 37.0},
		{"processor", 1, "processing", 49.0, 51.0},
		{"processor", 1, "completed", 66.0, 67.0},

		// Actor 2: finalizer
		{"finalizer", 2, "received", 69.0, 71.0},
		{"finalizer", 2, "processing", 83.0, 84.0},
		{"finalizer", 2, "completed", 99.0, 101.0},
	}

	for _, report := range progressReports {
		progressUpdate := types.ProgressUpdate{
			Actors:          []string{"parser", "processor", "finalizer"},
			CurrentActorIdx: report.actorIndex,
			Status:          report.status,
			Message:         "Processing " + report.actor,
		}

		body, _ := json.Marshal(progressUpdate)
		req := httptest.NewRequest(http.MethodPost, "/envelopes/"+job.ID+"/progress", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rr := httptest.NewRecorder()

		handler.HandleEnvelopeProgress(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Progress update failed for %s/%s: status=%d", report.actor, report.status, rr.Code)
		}

		var response map[string]interface{}
		_ = json.NewDecoder(rr.Body).Decode(&response)
		progressPercent := response["progress_percent"].(float64)

		if progressPercent < report.wantMin || progressPercent > report.wantMax {
			t.Errorf("Actor %s/%s: progress=%.2f, want %.2f-%.2f",
				report.actor, report.status, progressPercent, report.wantMin, report.wantMax)
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

	if finalJob.CurrentActorName != "finalizer" {
		t.Errorf("Final actor = %v, want finalizer", finalJob.CurrentActorName)
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
	store := envelopestore.NewStore()
	handler := NewHandler(store)

	// Create job
	job := &types.Envelope{
		ID: "sse-test-job",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}
	_ = store.Create(job)

	// Start SSE stream in goroutine
	req := httptest.NewRequest(http.MethodGet, "/envelopes/"+job.ID+"/stream", nil)
	rr := httptest.NewRecorder()

	// Stream in background
	go func() {
		handler.HandleEnvelopeStream(rr, req)
	}()

	// Give stream time to start
	time.Sleep(50 * time.Millisecond)

	// Send progress updates
	for i := 0; i < 2; i++ {
		progressUpdate := types.ProgressUpdate{
			Actors:          []string{"actor1", "actor2"},
			CurrentActorIdx: 0,
			Status:          []string{"received", "completed"}[i],
		}

		body, _ := json.Marshal(progressUpdate)
		progressReq := httptest.NewRequest(http.MethodPost, "/envelopes/"+job.ID+"/progress", bytes.NewReader(body))
		progressReq.Header.Set("Content-Type", "application/json")
		progressRr := httptest.NewRecorder()

		handler.HandleEnvelopeProgress(progressRr, progressReq)

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

// TestProgressTracking_SSEKeepalive tests that keepalive comments are sent to prevent timeout
func TestProgressTracking_SSEKeepalive(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping keepalive test in short mode")
	}

	store := envelopestore.NewStore()
	handler := NewHandler(store)

	job := &types.Envelope{
		ID: "keepalive-test-job",
		Route: types.Route{
			Actors:  []string{"long-running-actor"},
			Current: 0,
		},
		Status: types.EnvelopeStatusRunning,
	}
	_ = store.Create(job)

	req := httptest.NewRequest(http.MethodGet, "/envelopes/"+job.ID+"/stream", nil)
	rr := httptest.NewRecorder()

	done := make(chan bool)
	go func() {
		handler.HandleEnvelopeStream(rr, req)
		done <- true
	}()

	time.Sleep(16 * time.Second)

	_ = store.Update(types.EnvelopeUpdate{
		ID:        job.ID,
		Status:    types.EnvelopeStatusSucceeded,
		Timestamp: time.Now(),
	})

	<-done

	body := rr.Body.String()

	if !strings.Contains(body, ": keepalive") {
		t.Error("SSE stream should contain keepalive comments")
	}

	keepaliveCount := strings.Count(body, ": keepalive")
	if keepaliveCount == 0 {
		t.Error("Expected at least one keepalive comment in 16-second window")
	}

	t.Logf("Found %d keepalive comments in stream", keepaliveCount)
}

// TestProgressTracking_ConcurrentUpdates tests handling of concurrent progress updates
func TestProgressTracking_ConcurrentUpdates(t *testing.T) {
	store := envelopestore.NewStore()
	handler := NewHandler(store)

	envelopeID := "concurrent-test-envelope"
	job := &types.Envelope{
		ID: envelopeID,
		Route: types.Route{
			Actors:  []string{"actor1", "actor2", "actor3"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}
	_ = store.Create(job)

	// Send multiple concurrent progress updates
	numUpdates := 10
	done := make(chan bool, numUpdates)

	for i := 0; i < numUpdates; i++ {
		go func(idx int) {
			progressUpdate := types.ProgressUpdate{
				Actors:          []string{"actor1", "actor2", "actor3"},
				CurrentActorIdx: 0,
				Status:          "processing",
			}

			body, _ := json.Marshal(progressUpdate)
			req := httptest.NewRequest(http.MethodPost, "/envelopes/"+envelopeID+"/progress", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			handler.HandleEnvelopeProgress(rr, req)

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

	// Verify envelope state is consistent
	finalEnvelope, err := store.Get(envelopeID)
	if err != nil {
		t.Fatalf("Failed to get envelope: %v", err)
	}

	// Should have some progress (exact value doesn't matter due to concurrency)
	if finalEnvelope.ProgressPercent <= 0 {
		t.Error("Progress should be > 0 after updates")
	}
}

// TestProgressTracking_InvalidEnvelopeID tests behavior with non-existent envelope
func TestProgressTracking_InvalidEnvelopeID(t *testing.T) {
	store := envelopestore.NewStore()
	handler := NewHandler(store)

	progressUpdate := types.ProgressUpdate{
		Actors:          []string{"test"},
		CurrentActorIdx: 0,
		Status:          "processing",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/envelopes/non-existent-envelope/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleEnvelopeProgress(rr, req)

	// Should return error for non-existent envelope
	if rr.Code == http.StatusOK {
		t.Error("Expected error for non-existent envelope, got success")
	}
}

// TestProgressTracking_RouteActorsUpdate tests that route_actors field is updated on each progress report
func TestProgressTracking_RouteActorsUpdate(t *testing.T) {
	store := envelopestore.NewStore()
	handler := NewHandler(store)

	// Create envelope with initial route
	envelopeID := "route-update-test"
	envelope := &types.Envelope{
		ID: envelopeID,
		Route: types.Route{
			Actors:  []string{"actor-a", "actor-b"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}
	if err := store.Create(envelope); err != nil {
		t.Fatalf("Failed to create envelope: %v", err)
	}

	// Simulate actor modifying route (adding new actors to the end)
	modifiedRoute := []string{"actor-a", "actor-b", "actor-c", "actor-d"}

	progressUpdate := types.ProgressUpdate{
		ID:              envelopeID,
		Actors:          modifiedRoute,
		CurrentActorIdx: 0,
		Status:          "processing",
		Message:         "Processing with modified route",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/envelopes/"+envelopeID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleEnvelopeProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Progress update failed: status=%d", rr.Code)
	}

	// Retrieve envelope and verify route_actors was updated
	updatedEnvelope, err := store.Get(envelopeID)
	if err != nil {
		t.Fatalf("Failed to get envelope: %v", err)
	}

	// Verify route_actors field was updated with modified route
	if len(updatedEnvelope.Route.Actors) != len(modifiedRoute) {
		t.Errorf("Route actors length = %d, want %d", len(updatedEnvelope.Route.Actors), len(modifiedRoute))
	}

	for i, actor := range modifiedRoute {
		if i >= len(updatedEnvelope.Route.Actors) {
			t.Errorf("Missing actor at index %d: want %s", i, actor)
			continue
		}
		if updatedEnvelope.Route.Actors[i] != actor {
			t.Errorf("Route actor[%d] = %s, want %s", i, updatedEnvelope.Route.Actors[i], actor)
		}
	}
}

// TestProgressTracking_RouteActorsMultipleUpdates tests route updates across multiple progress reports
func TestProgressTracking_RouteActorsMultipleUpdates(t *testing.T) {
	store := envelopestore.NewStore()
	handler := NewHandler(store)

	envelopeID := "route-multi-update-test"
	envelope := &types.Envelope{
		ID: envelopeID,
		Route: types.Route{
			Actors:  []string{"step1", "step2"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}
	if err := store.Create(envelope); err != nil {
		t.Fatalf("Failed to create envelope: %v", err)
	}

	// First progress update with extended route
	firstRoute := []string{"step1", "step2", "step3"}
	sendProgressUpdate(t, handler, envelopeID, firstRoute, 0, "received")

	env, _ := store.Get(envelopeID)
	if len(env.Route.Actors) != 3 {
		t.Errorf("After first update: route length = %d, want 3", len(env.Route.Actors))
	}

	// Second progress update with further extended route
	secondRoute := []string{"step1", "step2", "step3", "step4", "step5"}
	sendProgressUpdate(t, handler, envelopeID, secondRoute, 1, "processing")

	env, _ = store.Get(envelopeID)
	if len(env.Route.Actors) != 5 {
		t.Errorf("After second update: route length = %d, want 5", len(env.Route.Actors))
	}

	// Verify all actors are present
	for i, expected := range secondRoute {
		if env.Route.Actors[i] != expected {
			t.Errorf("Route actor[%d] = %s, want %s", i, env.Route.Actors[i], expected)
		}
	}
}

// TestProgressTracking_EmptyActorsList tests progress calculation when Actors list is empty
// This is a regression test for the bug where empty Actors list caused progress_percent = 0
func TestProgressTracking_EmptyActorsList(t *testing.T) {
	store := envelopestore.NewStore()
	handler := NewHandler(store)

	// Create an envelope with 3 actors
	envelopeID := "test-empty-actors-" + time.Now().Format("20060102150405")
	initialRoute := []string{"actor1", "actor2", "actor3"}

	envelope := &types.Envelope{
		ID: envelopeID,
		Route: types.Route{
			Actors:  initialRoute,
			Current: 0,
		},
		Status:     types.EnvelopeStatusPending,
		TimeoutSec: 300,
	}

	if err := store.Create(envelope); err != nil {
		t.Fatalf("Failed to create envelope: %v", err)
	}

	// Send progress update with EMPTY actors list (simulating bug scenario)
	progressUpdate := types.ProgressUpdate{
		ID:              envelopeID,
		Actors:          []string{}, // Empty actors list
		CurrentActorIdx: 1,
		Status:          "processing",
		Message:         "Processing with empty actors list",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/envelopes/"+envelopeID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleEnvelopeProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Progress update failed: status=%d, body=%s", rr.Code, rr.Body.String())
	}

	// Parse response to get calculated progress
	var response map[string]interface{}
	_ = json.NewDecoder(rr.Body).Decode(&response)
	progressPercent := response["progress_percent"].(float64)

	// Expected: (1*100 + 50) / 3 = 50.0%
	// With the bug: progress would be 0% because totalActors = len([]string{}) = 0
	expectedMin := 49.0
	expectedMax := 51.0

	if progressPercent < expectedMin || progressPercent > expectedMax {
		t.Errorf("Progress = %.2f%%, want %.2f-%.2f%% (should use envelope's route when Actors is empty)",
			progressPercent, expectedMin, expectedMax)
	}

	// Verify envelope was updated correctly
	env, err := store.Get(envelopeID)
	if err != nil {
		t.Fatalf("Failed to get envelope: %v", err)
	}

	if env.ProgressPercent < expectedMin || env.ProgressPercent > expectedMax {
		t.Errorf("Envelope progress = %.2f%%, want %.2f-%.2f%%",
			env.ProgressPercent, expectedMin, expectedMax)
	}

	// Verify route was preserved (should still have 3 actors)
	if len(env.Route.Actors) != 3 {
		t.Errorf("Route actors count = %d, want 3 (route should be preserved from original envelope)",
			len(env.Route.Actors))
	}
}

func sendProgressUpdate(t *testing.T, handler *Handler, envelopeID string, actors []string, currentIdx int, status string) {
	t.Helper()

	progressUpdate := types.ProgressUpdate{
		ID:              envelopeID,
		Actors:          actors,
		CurrentActorIdx: currentIdx,
		Status:          status,
		Message:         "Test progress update",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/envelopes/"+envelopeID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleEnvelopeProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Progress update failed: status=%d", rr.Code)
	}
}
