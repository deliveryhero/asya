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

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// TestProgressTracking_EndToEnd simulates the complete progress tracking flow
func TestProgressTracking_EndToEnd(t *testing.T) {
	// Setup: Create task store and handler
	_ = context.Background()
	store := taskstore.NewStore()
	handler := NewHandler(store)

	// Create a test job with 3 actors
	job := &types.Task{
		ID: "integration-test-job-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "parser",
			Next: []string{"processor", "finalizer"},
		},
		Payload:    map[string]interface{}{"data": "test"},
		Status:     types.TaskStatusPending,
		TimeoutSec: 300,
	}

	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create job: %v", err)
	}

	// Subscribe to job updates (simulate SSE client)
	updateChan := store.Subscribe(job.ID)
	defer store.Unsubscribe(job.ID, updateChan)

	// Collect all updates
	updates := make([]types.TaskUpdate, 0)
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
		prev    []string
		curr    string
		next    []string
		status  string
		wantMin float64
		wantMax float64
	}{
		// Actor 0: parser (prev=[], curr=parser, next=[processor, finalizer])
		{[]string{}, "parser", []string{"processor", "finalizer"}, "received", 3.0, 4.0},
		{[]string{}, "parser", []string{"processor", "finalizer"}, "processing", 16.0, 17.0},
		{[]string{}, "parser", []string{"processor", "finalizer"}, "completed", 33.0, 34.0},

		// Actor 1: processor (prev=[parser], curr=processor, next=[finalizer])
		{[]string{"parser"}, "processor", []string{"finalizer"}, "received", 36.0, 37.0},
		{[]string{"parser"}, "processor", []string{"finalizer"}, "processing", 49.0, 51.0},
		{[]string{"parser"}, "processor", []string{"finalizer"}, "completed", 66.0, 67.0},

		// Actor 2: finalizer (prev=[parser,processor], curr=finalizer, next=[])
		{[]string{"parser", "processor"}, "finalizer", []string{}, "received", 69.0, 71.0},
		{[]string{"parser", "processor"}, "finalizer", []string{}, "processing", 83.0, 84.0},
		{[]string{"parser", "processor"}, "finalizer", []string{}, "completed", 99.0, 101.0},
	}

	for _, report := range progressReports {
		progressUpdate := types.ProgressUpdate{
			Prev:    report.prev,
			Curr:    report.curr,
			Next:    report.next,
			Status:  report.status,
			Message: "Processing " + report.curr,
		}

		body, _ := json.Marshal(progressUpdate)
		req := httptest.NewRequest(http.MethodPost, "/tasks/"+job.ID+"/progress", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rr := httptest.NewRecorder()

		handler.HandleTaskProgress(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Progress update failed for %s/%s: status=%d", report.curr, report.status, rr.Code)
		}

		var response map[string]interface{}
		_ = json.NewDecoder(rr.Body).Decode(&response)
		progressPercent := response["progress_percent"].(float64)

		if progressPercent < report.wantMin || progressPercent > report.wantMax {
			t.Errorf("Actor %s/%s: progress=%.2f, want %.2f-%.2f",
				report.curr, report.status, progressPercent, report.wantMin, report.wantMax)
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
	store := taskstore.NewStore()
	handler := NewHandler(store)

	// Create job
	job := &types.Task{
		ID: "sse-test-job",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Status: types.TaskStatusPending,
	}
	_ = store.Create(job)

	// Start SSE stream in goroutine
	req := httptest.NewRequest(http.MethodGet, "/tasks/"+job.ID+"/stream", nil)
	rr := httptest.NewRecorder()

	// Stream in background
	go func() {
		handler.HandleTaskStream(rr, req)
	}()

	// Give stream time to start
	time.Sleep(50 * time.Millisecond)

	// Send progress updates
	statuses := []string{"received", "completed"}
	for i := 0; i < 2; i++ {
		progressUpdate := types.ProgressUpdate{
			Prev:   []string{},
			Curr:   "actor1",
			Next:   []string{"actor2"},
			Status: statuses[i],
		}

		body, _ := json.Marshal(progressUpdate)
		progressReq := httptest.NewRequest(http.MethodPost, "/tasks/"+job.ID+"/progress", bytes.NewReader(body))
		progressReq.Header.Set("Content-Type", "application/json")
		progressRr := httptest.NewRecorder()

		handler.HandleTaskProgress(progressRr, progressReq)

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

	store := taskstore.NewStore()
	handler := NewHandler(store)

	job := &types.Task{
		ID: "keepalive-test-job",
		Route: types.Route{
			Prev: []string{},
			Curr: "long-running-actor",
			Next: []string{},
		},
		Status: types.TaskStatusRunning,
	}
	_ = store.Create(job)

	req := httptest.NewRequest(http.MethodGet, "/tasks/"+job.ID+"/stream", nil)
	rr := httptest.NewRecorder()

	done := make(chan bool)
	go func() {
		handler.HandleTaskStream(rr, req)
		done <- true
	}()

	time.Sleep(16 * time.Second)

	_ = store.Update(types.TaskUpdate{
		ID:        job.ID,
		Status:    types.TaskStatusSucceeded,
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
	store := taskstore.NewStore()
	handler := NewHandler(store)

	taskID := "concurrent-test-task"
	job := &types.Task{
		ID: taskID,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2", "actor3"},
		},
		Status: types.TaskStatusPending,
	}
	_ = store.Create(job)

	// Send multiple concurrent progress updates
	numUpdates := 10
	done := make(chan bool, numUpdates)

	for i := 0; i < numUpdates; i++ {
		go func(idx int) {
			progressUpdate := types.ProgressUpdate{
				Prev:   []string{},
				Curr:   "actor1",
				Next:   []string{"actor2", "actor3"},
				Status: "processing",
			}

			body, _ := json.Marshal(progressUpdate)
			req := httptest.NewRequest(http.MethodPost, "/tasks/"+taskID+"/progress", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			handler.HandleTaskProgress(rr, req)

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

	// Verify task state is consistent
	finalTask, err := store.Get(taskID)
	if err != nil {
		t.Fatalf("Failed to get task: %v", err)
	}

	// Should have some progress (exact value doesn't matter due to concurrency)
	if finalTask.ProgressPercent <= 0 {
		t.Error("Progress should be > 0 after updates")
	}
}

// TestProgressTracking_InvalidTaskID tests behavior with non-existent task
func TestProgressTracking_InvalidTaskID(t *testing.T) {
	store := taskstore.NewStore()
	handler := NewHandler(store)

	progressUpdate := types.ProgressUpdate{
		Prev:   []string{},
		Curr:   "test",
		Next:   []string{},
		Status: "processing",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/tasks/non-existent-task/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleTaskProgress(rr, req)

	// Should return error for non-existent task
	if rr.Code == http.StatusOK {
		t.Error("Expected error for non-existent task, got success")
	}
}

// TestProgressTracking_RouteUpdate tests that route fields are updated on each progress report
func TestProgressTracking_RouteUpdate(t *testing.T) {
	store := taskstore.NewStore()
	handler := NewHandler(store)

	// Create task with initial route
	taskID := "route-update-test"
	task := &types.Task{
		ID: taskID,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor-a",
			Next: []string{"actor-b"},
		},
		Status: types.TaskStatusPending,
	}
	if err := store.Create(task); err != nil {
		t.Fatalf("Failed to create task: %v", err)
	}

	// Simulate actor modifying route (adding new actors to next)
	progressUpdate := types.ProgressUpdate{
		ID:      taskID,
		Prev:    []string{},
		Curr:    "actor-a",
		Next:    []string{"actor-b", "actor-c", "actor-d"},
		Status:  "processing",
		Message: "Processing with modified route",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/tasks/"+taskID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleTaskProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Progress update failed: status=%d", rr.Code)
	}

	// Retrieve task and verify route was updated
	updatedTask, err := store.Get(taskID)
	if err != nil {
		t.Fatalf("Failed to get task: %v", err)
	}

	if len(updatedTask.Route.Next) != 3 {
		t.Errorf("Route next length = %d, want 3", len(updatedTask.Route.Next))
	}

	expectedNext := []string{"actor-b", "actor-c", "actor-d"}
	for i, actor := range expectedNext {
		if i >= len(updatedTask.Route.Next) {
			t.Errorf("Missing actor at next[%d]: want %s", i, actor)
			continue
		}
		if updatedTask.Route.Next[i] != actor {
			t.Errorf("Route next[%d] = %s, want %s", i, updatedTask.Route.Next[i], actor)
		}
	}
}

// TestProgressTracking_RouteActorsMultipleUpdates tests route updates across multiple progress reports
func TestProgressTracking_RouteActorsMultipleUpdates(t *testing.T) {
	store := taskstore.NewStore()
	handler := NewHandler(store)

	taskID := "route-multi-update-test"
	task := &types.Task{
		ID: taskID,
		Route: types.Route{
			Prev: []string{},
			Curr: "step1",
			Next: []string{"step2"},
		},
		Status: types.TaskStatusPending,
	}
	if err := store.Create(task); err != nil {
		t.Fatalf("Failed to create task: %v", err)
	}

	// First progress update with extended next
	sendProgressUpdateNew(t, handler, taskID, []string{}, "step1", []string{"step2", "step3"}, "received")

	env, _ := store.Get(taskID)
	// Total: prev(0) + curr(1) + next(2) = 3
	if env.TotalActors != 3 {
		t.Errorf("After first update: total actors = %d, want 3", env.TotalActors)
	}

	// Second progress update at step2 with further extended route
	sendProgressUpdateNew(t, handler, taskID, []string{"step1"}, "step2", []string{"step3", "step4", "step5"}, "processing")

	env, _ = store.Get(taskID)
	// Total: prev(1) + curr(1) + next(3) = 5
	if env.TotalActors != 5 {
		t.Errorf("After second update: total actors = %d, want 5", env.TotalActors)
	}

	if env.Route.Curr != "step2" {
		t.Errorf("After second update: curr = %s, want step2", env.Route.Curr)
	}

	if len(env.Route.Prev) != 1 || env.Route.Prev[0] != "step1" {
		t.Errorf("After second update: prev = %v, want [step1]", env.Route.Prev)
	}
}

// TestProgressTracking_EmptyActorsList tests progress calculation when actors update is empty
// This is a regression test for the bug where empty actors caused progress_percent = 0
func TestProgressTracking_EmptyActorsList(t *testing.T) {
	store := taskstore.NewStore()
	handler := NewHandler(store)

	// Create a task with 3 actors
	taskID := "test-empty-actors-" + time.Now().Format("20060102150405")

	task := &types.Task{
		ID: taskID,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2", "actor3"},
		},
		Status:     types.TaskStatusPending,
		TimeoutSec: 300,
	}

	if err := store.Create(task); err != nil {
		t.Fatalf("Failed to create task: %v", err)
	}

	// Send progress update with valid prev/curr/next for actor at position 1 (processing)
	// prev=[actor1], curr=actor2, next=[actor3] => (1+0.5)*100/3 = 50.0%
	progressUpdate := types.ProgressUpdate{
		ID:      taskID,
		Prev:    []string{"actor1"},
		Curr:    "actor2",
		Next:    []string{"actor3"},
		Status:  "processing",
		Message: "Processing at actor2",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/tasks/"+taskID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleTaskProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Progress update failed: status=%d, body=%s", rr.Code, rr.Body.String())
	}

	// Parse response to get calculated progress
	var response map[string]interface{}
	_ = json.NewDecoder(rr.Body).Decode(&response)
	progressPercent := response["progress_percent"].(float64)

	// Expected: (1+0.5)*100/3 = 50.0%
	expectedMin := 49.0
	expectedMax := 51.0

	if progressPercent < expectedMin || progressPercent > expectedMax {
		t.Errorf("Progress = %.2f%%, want %.2f-%.2f%%", progressPercent, expectedMin, expectedMax)
	}

	// Verify task was updated correctly
	env, err := store.Get(taskID)
	if err != nil {
		t.Fatalf("Failed to get task: %v", err)
	}

	if env.ProgressPercent < expectedMin || env.ProgressPercent > expectedMax {
		t.Errorf("Task progress = %.2f%%, want %.2f-%.2f%%", env.ProgressPercent, expectedMin, expectedMax)
	}

	// Verify route was updated (should now reflect prev=[actor1], curr=actor2, next=[actor3])
	if env.Route.Curr != "actor2" {
		t.Errorf("Route curr = %s, want actor2", env.Route.Curr)
	}
	if len(env.Route.Prev) != 1 || env.Route.Prev[0] != "actor1" {
		t.Errorf("Route prev = %v, want [actor1]", env.Route.Prev)
	}
}

func sendProgressUpdateNew(t *testing.T, handler *Handler, taskID string, prev []string, curr string, next []string, status string) {
	t.Helper()

	progressUpdate := types.ProgressUpdate{
		ID:      taskID,
		Prev:    prev,
		Curr:    curr,
		Next:    next,
		Status:  status,
		Message: "Test progress update",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/tasks/"+taskID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleTaskProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Progress update failed: status=%d", rr.Code)
	}
}
