package a2a

import (
	"context"
	"testing"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"

	"github.com/deliveryhero/asya/asya-gateway/internal/envelopestore"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// crossProcessStore simulates a task store where status updates arrive via an
// external process (e.g., mesh gateway). Subscribe returns a channel that never
// fires; the updated status is only visible through Get(), mimicking a DB write
// from a separate gateway pod that bypasses this process's in-memory listeners.
type crossProcessStore struct {
	envelopestore.EnvelopeStore
	taskID    string
	finalAt   time.Time
	finalStat types.EnvelopeStatus
}

func (s *crossProcessStore) Get(id string) (*types.Envelope, error) {
	if id == s.taskID && !time.Now().Before(s.finalAt) {
		return &types.Envelope{ID: id, Status: s.finalStat}, nil
	}
	return &types.Envelope{ID: id, Status: types.EnvelopeStatusPending}, nil
}

func (s *crossProcessStore) Subscribe(_ string) chan types.EnvelopeUpdate {
	return make(chan types.EnvelopeUpdate) // unbuffered, never written — simulates cross-process update
}

func (s *crossProcessStore) Unsubscribe(_ string, _ chan types.EnvelopeUpdate) {}

func TestTerminalOrInterrupted(t *testing.T) {
	tests := []struct {
		status types.EnvelopeStatus
		want   bool
	}{
		{types.EnvelopeStatusSucceeded, true},
		{types.EnvelopeStatusFailed, true},
		{types.EnvelopeStatusCanceled, true},
		{types.EnvelopeStatusPaused, true},
		{types.EnvelopeStatusAuthRequired, true},
		{types.EnvelopeStatusPending, false},
		{types.EnvelopeStatusRunning, false},
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
	store := envelopestore.NewStore()
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
		_ = store.Update(types.EnvelopeUpdate{
			ID:        string(reqCtx.TaskID),
			Status:    types.EnvelopeStatusSucceeded,
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
	store := envelopestore.NewStore()
	taskID := "timeout-test-task"

	// Create a task that will never complete
	err := store.Create(&types.Envelope{
		ID:         taskID,
		Status:     types.EnvelopeStatusPending,
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
	store := envelopestore.NewStore()
	taskID := "ctx-cancel-task"

	err := store.Create(&types.Envelope{
		ID:     taskID,
		Status: types.EnvelopeStatusPending,
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
	store := envelopestore.NewStore()
	taskID := "already-done-task"

	err := store.Create(&types.Envelope{
		ID:     taskID,
		Status: types.EnvelopeStatusPending,
	})
	if err != nil {
		t.Fatalf("create task: %v", err)
	}

	// Update to succeeded before calling wait
	_ = store.Update(types.EnvelopeUpdate{
		ID:        taskID,
		Status:    types.EnvelopeStatusSucceeded,
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

// TestBlockingModeCrossProcessUpdate verifies that waitAndRelayEvents detects
// task completion written by an external process (e.g., mesh gateway) that
// updates the DB without triggering this process's in-memory listeners.
func TestBlockingModeCrossProcessUpdate(t *testing.T) {
	taskID := "cross-process-task"
	store := &crossProcessStore{
		EnvelopeStore: envelopestore.NewStore(),
		taskID:        taskID,
		// Task becomes terminal after 1.5× the poll interval — requires polling to detect
		finalAt:   time.Now().Add(dbPollInterval + dbPollInterval/2),
		finalStat: types.EnvelopeStatusSucceeded,
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
		10*time.Second,
		reqCtx, eq,
	)
	elapsed := time.Since(start)

	if waitErr != nil {
		t.Fatalf("waitAndRelayEvents failed: %v", waitErr)
	}

	// Should complete within a few poll intervals, not the full timeout
	if elapsed > 5*dbPollInterval {
		t.Errorf("cross-process update took %v, expected < %v (5× poll interval)", elapsed, 5*dbPollInterval)
	}

	// Should have written a final completed event
	if len(eq.events) == 0 {
		t.Fatal("expected at least one event")
	}
	lastEvt, ok := eq.events[len(eq.events)-1].(*a2alib.TaskStatusUpdateEvent)
	if !ok {
		t.Fatalf("last event is not TaskStatusUpdateEvent: %T", eq.events[len(eq.events)-1])
	}
	if !lastEvt.Final {
		t.Error("last event Final = false, want true")
	}
	if lastEvt.Status.State != a2alib.TaskStateCompleted {
		t.Errorf("last event state = %q, want %q", lastEvt.Status.State, a2alib.TaskStateCompleted)
	}
}

// TestBlockingModeRelaysIntermediateEvents verifies that non-terminal subscription
// updates do NOT trigger eq.Write() (to avoid the StoreAdapter.Save feedback loop),
// but terminal updates are still detected and forwarded immediately via subscription.
// The subscription channel is a fast path for in-process terminal detection only.
func TestBlockingModeRelaysIntermediateEvents(t *testing.T) {
	store := envelopestore.NewStore()
	taskID := "intermediate-task"

	err := store.Create(&types.Envelope{
		ID:     taskID,
		Status: types.EnvelopeStatusPending,
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
		_ = store.Update(types.EnvelopeUpdate{
			ID:        taskID,
			Status:    types.EnvelopeStatusRunning,
			Timestamp: time.Now(),
		})
		time.Sleep(50 * time.Millisecond) // Spacing between updates
		_ = store.Update(types.EnvelopeUpdate{
			ID:        taskID,
			Status:    types.EnvelopeStatusSucceeded,
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

	// Non-terminal subscription updates (running/working) are dropped to prevent the
	// StoreAdapter.Save() → notifyListeners() → eq.Write() feedback loop that would
	// continuously overwrite tasks.status and prevent mesh gateway writes from persisting.
	// The subscription channel is only used as a fast path for terminal state detection.
	// So we expect exactly 1 event: the final completed event.
	if len(eq.events) != 1 {
		t.Fatalf("expected exactly 1 event (completed), got %d", len(eq.events))
	}

	// Verify the final event is completed
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

func TestBlockingModeRelaysFLYAsArtifactChunks(t *testing.T) {
	store := envelopestore.NewStore()
	taskID := "fly-relay-task"

	err := store.Create(&types.Envelope{
		ID:     taskID,
		Status: types.EnvelopeStatusPending,
	})
	if err != nil {
		t.Fatalf("create task: %v", err)
	}

	reqCtx := &a2asrv.RequestContext{
		TaskID:    a2alib.TaskID(taskID),
		ContextID: "fly-ctx",
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"}),
	}

	eq := &mockEventQueue{}

	go func() {
		time.Sleep(50 * time.Millisecond) // wait for Subscribe() to register before sending events

		store.NotifyFLY(taskID, []byte(`{"text":"Hello"}`))
		time.Sleep(20 * time.Millisecond) // space between FLY events to ensure ordering
		store.NotifyFLY(taskID, []byte(`{"text":" world"}`))
		time.Sleep(20 * time.Millisecond) // space before terminal event

		_ = store.Update(types.EnvelopeUpdate{
			ID:        taskID,
			Status:    types.EnvelopeStatusSucceeded,
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

	// Should have: artifact events + LastChunk + terminal status event
	if len(eq.events) < 3 {
		t.Fatalf("expected at least 3 events (artifacts + LastChunk + terminal), got %d", len(eq.events))
	}

	// First event should be TaskArtifactUpdateEvent with Append=false
	firstEvt, ok := eq.events[0].(*a2alib.TaskArtifactUpdateEvent)
	if !ok {
		t.Fatalf("first event type = %T, want *TaskArtifactUpdateEvent", eq.events[0])
	}
	if firstEvt.Append {
		t.Error("first artifact event should have Append=false")
	}

	// If we got a second FLY event, it should be an append
	if len(eq.events) >= 4 {
		secondEvt, ok := eq.events[1].(*a2alib.TaskArtifactUpdateEvent)
		if !ok {
			t.Fatalf("second event type = %T, want *TaskArtifactUpdateEvent", eq.events[1])
		}
		if !secondEvt.Append {
			t.Error("second artifact event should have Append=true")
		}
	}

	// Second-to-last event should be LastChunk artifact
	lastChunkEvt, ok := eq.events[len(eq.events)-2].(*a2alib.TaskArtifactUpdateEvent)
	if !ok {
		t.Fatalf("second-to-last event type = %T, want *TaskArtifactUpdateEvent", eq.events[len(eq.events)-2])
	}
	if !lastChunkEvt.LastChunk {
		t.Error("second-to-last event LastChunk = false, want true")
	}
	if !lastChunkEvt.Append {
		t.Error("LastChunk event should have Append=true")
	}

	// Last event should be terminal status
	lastEvt, ok := eq.events[len(eq.events)-1].(*a2alib.TaskStatusUpdateEvent)
	if !ok {
		t.Fatalf("last event type = %T, want *TaskStatusUpdateEvent", eq.events[len(eq.events)-1])
	}
	if !lastEvt.Final {
		t.Error("last event Final = false, want true")
	}
}

func TestBlockingModeNonTerminalStatusStillDropped(t *testing.T) {
	store := envelopestore.NewStore()
	taskID := "no-feedback-task"

	err := store.Create(&types.Envelope{
		ID:     taskID,
		Status: types.EnvelopeStatusPending,
	})
	if err != nil {
		t.Fatalf("create task: %v", err)
	}

	reqCtx := &a2asrv.RequestContext{
		TaskID:    a2alib.TaskID(taskID),
		ContextID: "ctx",
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"}),
	}

	eq := &mockEventQueue{}

	go func() {
		time.Sleep(50 * time.Millisecond) // wait for Subscribe() to register before sending updates
		_ = store.Update(types.EnvelopeUpdate{
			ID:        taskID,
			Status:    types.EnvelopeStatusRunning,
			Timestamp: time.Now(),
		})
		time.Sleep(50 * time.Millisecond) // space before terminal update
		_ = store.Update(types.EnvelopeUpdate{
			ID:        taskID,
			Status:    types.EnvelopeStatusSucceeded,
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

	if len(eq.events) != 1 {
		t.Fatalf("expected 1 event (terminal only), got %d", len(eq.events))
	}
}
