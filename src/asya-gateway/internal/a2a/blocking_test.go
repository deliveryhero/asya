package a2a

import (
	"context"
	"testing"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestTerminalOrInterrupted(t *testing.T) {
	tests := []struct {
		status types.TaskStatus
		want   bool
	}{
		{types.TaskStatusSucceeded, true},
		{types.TaskStatusFailed, true},
		{types.TaskStatusCanceled, true},
		{types.TaskStatusPaused, true},
		{types.TaskStatusAuthRequired, true},
		{types.TaskStatusPending, false},
		{types.TaskStatusRunning, false},
	}
	for _, tt := range tests {
		t.Run(string(tt.status), func(t *testing.T) {
			if got := terminalOrInterrupted(tt.status); got != tt.want {
				t.Errorf("terminalOrInterrupted(%q) = %v, want %v", tt.status, got, tt.want)
			}
		})
	}
}

func TestBlockingModeWaitsForCompletion(t *testing.T) {
	store := taskstore.NewStore()
	reg := toolstore.NewInMemoryRegistry()
	ctx := context.Background()
	_ = reg.Upsert(ctx, toolstore.Tool{Name: "analyze", Actor: "start-analysis", A2AEnabled: true})

	exec := NewExecutor(nil, store, reg, "default")

	reqCtx := &a2asrv.RequestContext{
		TaskID:    a2alib.NewTaskID(),
		ContextID: a2alib.NewContextID(),
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"}),
		Metadata:  map[string]any{"skill": "analyze"},
	}

	eq := &mockEventQueue{}

	// Simulate task completion after 100ms in a goroutine
	go func() {
		time.Sleep(100 * time.Millisecond) // Wait for Execute to create the task
		_ = store.Update(types.TaskUpdate{
			ID:        string(reqCtx.TaskID),
			Status:    types.TaskStatusSucceeded,
			Timestamp: time.Now(),
		})
	}()

	err := exec.Execute(ctx, reqCtx, eq)
	if err != nil {
		t.Fatalf("Execute failed: %v", err)
	}

	// Verify events were written: submitted + completed (terminal)
	if len(eq.events) < 2 {
		t.Fatalf("expected at least 2 events (submitted + completed), got %d", len(eq.events))
	}

	// First event should be submitted
	firstEvt, ok := eq.events[0].(*a2alib.TaskStatusUpdateEvent)
	if !ok {
		t.Fatalf("first event is not TaskStatusUpdateEvent: %T", eq.events[0])
	}
	if firstEvt.Status.State != a2alib.TaskStateSubmitted {
		t.Errorf("first event state = %q, want %q", firstEvt.Status.State, a2alib.TaskStateSubmitted)
	}

	// Last event should be terminal (completed) with Final=true
	lastEvt, ok := eq.events[len(eq.events)-1].(*a2alib.TaskStatusUpdateEvent)
	if !ok {
		t.Fatalf("last event is not TaskStatusUpdateEvent: %T", eq.events[len(eq.events)-1])
	}
	if lastEvt.Status.State != a2alib.TaskStateCompleted {
		t.Errorf("last event state = %q, want %q", lastEvt.Status.State, a2alib.TaskStateCompleted)
	}
	if !lastEvt.Final {
		t.Error("last event Final = false, want true")
	}
}

func TestBlockingModeTimeout(t *testing.T) {
	store := taskstore.NewStore()
	taskID := "timeout-test-task"

	// Create a task that will never complete
	err := store.Create(&types.Task{
		ID:         taskID,
		Status:     types.TaskStatusPending,
		TimeoutSec: 600, // Store-level timeout (long, not what we're testing)
	})
	if err != nil {
		t.Fatalf("create task: %v", err)
	}

	reqCtx := &a2asrv.RequestContext{
		TaskID:    a2alib.TaskID(taskID),
		ContextID: a2alib.NewContextID(),
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"}),
	}

	eq := &mockEventQueue{}

	start := time.Now()
	waitErr := waitAndRelayEvents(
		context.Background(),
		store, taskID,
		500*time.Millisecond, // Short timeout for test
		reqCtx, eq,
	)
	elapsed := time.Since(start)

	if waitErr != nil {
		t.Fatalf("waitAndRelayEvents failed: %v", waitErr)
	}

	// Should have returned within ~1s (generous margin for CI)
	if elapsed > 2*time.Second {
		t.Errorf("waitAndRelayEvents took %v, expected < 2s", elapsed)
	}

	// Should have written a final event
	if len(eq.events) == 0 {
		t.Fatal("expected at least one event on timeout")
	}

	lastEvt, ok := eq.events[len(eq.events)-1].(*a2alib.TaskStatusUpdateEvent)
	if !ok {
		t.Fatalf("last event is not TaskStatusUpdateEvent: %T", eq.events[len(eq.events)-1])
	}
	if !lastEvt.Final {
		t.Error("timeout event Final = false, want true")
	}
}

func TestBlockingModeContextCanceled(t *testing.T) {
	store := taskstore.NewStore()
	taskID := "ctx-cancel-task"

	err := store.Create(&types.Task{
		ID:     taskID,
		Status: types.TaskStatusPending,
	})
	if err != nil {
		t.Fatalf("create task: %v", err)
	}

	reqCtx := &a2asrv.RequestContext{
		TaskID:    a2alib.TaskID(taskID),
		ContextID: a2alib.NewContextID(),
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"}),
	}

	eq := &mockEventQueue{}
	ctx, cancel := context.WithCancel(context.Background())

	// Cancel context after 100ms
	go func() {
		time.Sleep(100 * time.Millisecond) // Simulate client disconnect
		cancel()
	}()

	waitErr := waitAndRelayEvents(
		ctx, store, taskID,
		10*time.Second,
		reqCtx, eq,
	)

	if waitErr != context.Canceled {
		t.Errorf("waitAndRelayEvents error = %v, want %v", waitErr, context.Canceled)
	}
}

func TestBlockingModeAlreadyTerminal(t *testing.T) {
	store := taskstore.NewStore()
	taskID := "already-done-task"

	err := store.Create(&types.Task{
		ID:     taskID,
		Status: types.TaskStatusPending,
	})
	if err != nil {
		t.Fatalf("create task: %v", err)
	}

	// Update to succeeded before calling wait
	_ = store.Update(types.TaskUpdate{
		ID:        taskID,
		Status:    types.TaskStatusSucceeded,
		Timestamp: time.Now(),
	})

	reqCtx := &a2asrv.RequestContext{
		TaskID:    a2alib.TaskID(taskID),
		ContextID: a2alib.NewContextID(),
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"}),
	}

	eq := &mockEventQueue{}

	waitErr := waitAndRelayEvents(
		context.Background(),
		store, taskID,
		10*time.Second,
		reqCtx, eq,
	)

	if waitErr != nil {
		t.Fatalf("waitAndRelayEvents failed: %v", waitErr)
	}

	// Should immediately write a single final event
	if len(eq.events) != 1 {
		t.Fatalf("expected 1 event for already-terminal task, got %d", len(eq.events))
	}

	evt, ok := eq.events[0].(*a2alib.TaskStatusUpdateEvent)
	if !ok {
		t.Fatalf("event is not TaskStatusUpdateEvent: %T", eq.events[0])
	}
	if !evt.Final {
		t.Error("event Final = false, want true")
	}
	if evt.Status.State != a2alib.TaskStateCompleted {
		t.Errorf("event state = %q, want %q", evt.Status.State, a2alib.TaskStateCompleted)
	}
}

func TestBlockingModeRelaysIntermediateEvents(t *testing.T) {
	store := taskstore.NewStore()
	taskID := "intermediate-task"

	err := store.Create(&types.Task{
		ID:     taskID,
		Status: types.TaskStatusPending,
	})
	if err != nil {
		t.Fatalf("create task: %v", err)
	}

	reqCtx := &a2asrv.RequestContext{
		TaskID:    a2alib.TaskID(taskID),
		ContextID: a2alib.NewContextID(),
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"}),
	}

	eq := &mockEventQueue{}

	// Simulate: running -> succeeded
	go func() {
		time.Sleep(50 * time.Millisecond) // Wait for subscription
		_ = store.Update(types.TaskUpdate{
			ID:        taskID,
			Status:    types.TaskStatusRunning,
			Timestamp: time.Now(),
		})
		time.Sleep(50 * time.Millisecond) // Spacing between updates
		_ = store.Update(types.TaskUpdate{
			ID:        taskID,
			Status:    types.TaskStatusSucceeded,
			Timestamp: time.Now(),
		})
	}()

	waitErr := waitAndRelayEvents(
		context.Background(),
		store, taskID,
		10*time.Second,
		reqCtx, eq,
	)

	if waitErr != nil {
		t.Fatalf("waitAndRelayEvents failed: %v", waitErr)
	}

	// Should have: working event (non-final) + completed event (final)
	if len(eq.events) < 2 {
		t.Fatalf("expected at least 2 events (working + completed), got %d", len(eq.events))
	}

	// Verify working event
	workingEvt, ok := eq.events[0].(*a2alib.TaskStatusUpdateEvent)
	if !ok {
		t.Fatalf("first event is not TaskStatusUpdateEvent: %T", eq.events[0])
	}
	if workingEvt.Status.State != a2alib.TaskStateWorking {
		t.Errorf("first event state = %q, want %q", workingEvt.Status.State, a2alib.TaskStateWorking)
	}
	if workingEvt.Final {
		t.Error("working event Final = true, want false")
	}

	// Verify completed event
	completedEvt, ok := eq.events[len(eq.events)-1].(*a2alib.TaskStatusUpdateEvent)
	if !ok {
		t.Fatalf("last event is not TaskStatusUpdateEvent: %T", eq.events[len(eq.events)-1])
	}
	if completedEvt.Status.State != a2alib.TaskStateCompleted {
		t.Errorf("last event state = %q, want %q", completedEvt.Status.State, a2alib.TaskStateCompleted)
	}
	if !completedEvt.Final {
		t.Error("completed event Final = false, want true")
	}
}
