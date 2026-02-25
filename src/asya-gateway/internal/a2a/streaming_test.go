package a2a

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandler_MessageStream(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{
		Tools: []config.Tool{
			{Name: "echo", Description: "Echo", Route: config.RouteSpec{Actors: []string{"echo-actor"}}},
		},
	}
	h := NewHandler(store, nil, cfg)

	reqBody := types.A2AJSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "message/stream",
		Params: map[string]any{
			"message": map[string]any{
				"role":  "user",
				"parts": []any{map[string]any{"type": "text", "text": "hi"}},
			},
			"skill": "echo",
		},
	}

	body, _ := json.Marshal(reqBody)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader(body)).WithContext(ctx)
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	// Run handler in goroutine since streaming blocks
	done := make(chan struct{})
	go func() {
		h.ServeHTTP(rr, req)
		close(done)
	}()

	// Wait briefly for task creation, then cancel to stop streaming
	time.Sleep(100 * time.Millisecond) // Wait for handler to create task and start streaming
	cancel()
	<-done

	// Check SSE headers
	ct := rr.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "text/event-stream") {
		t.Errorf("Content-Type = %s, want text/event-stream", ct)
	}

	// Parse SSE events
	scanner := bufio.NewScanner(rr.Body)
	eventCount := 0
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "data: ") {
			eventCount++
		}
	}

	if eventCount < 1 {
		t.Errorf("expected at least 1 SSE event, got %d", eventCount)
	}
}

func TestSubscribeHandler(t *testing.T) {
	store := taskstore.NewStore()
	task := &types.Task{
		ID:     "sub-test-1",
		Status: types.TaskStatusPending,
		Route:  types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
	}
	if err := store.Create(task); err != nil {
		t.Fatal(err)
	}

	sh := NewSubscribeHandler(store)

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/sub-test-1:subscribe", nil).WithContext(ctx)
	req.SetPathValue("id", "sub-test-1:subscribe")
	rr := httptest.NewRecorder()

	// Complete task after a delay
	go func() {
		time.Sleep(100 * time.Millisecond) // Wait for subscription to be set up
		_ = store.Update(types.TaskUpdate{
			ID:        "sub-test-1",
			Status:    types.TaskStatusSucceeded,
			Result:    map[string]any{"ok": true},
			Timestamp: time.Now(),
		})
	}()

	sh.ServeHTTP(rr, req)

	ct := rr.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "text/event-stream") {
		t.Errorf("Content-Type = %s, want text/event-stream", ct)
	}

	// Should have received events
	body := rr.Body.String()
	if !strings.Contains(body, "event:") {
		t.Error("expected SSE events in response")
	}
}

func TestSubscribeHandler_TaskNotFound(t *testing.T) {
	store := taskstore.NewStore()
	sh := NewSubscribeHandler(store)

	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/nonexistent:subscribe", nil)
	req.SetPathValue("id", "nonexistent:subscribe")
	rr := httptest.NewRecorder()

	sh.ServeHTTP(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rr.Code)
	}
}
