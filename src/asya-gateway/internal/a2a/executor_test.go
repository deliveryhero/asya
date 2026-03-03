package a2a

import (
	"context"
	"testing"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestExecutorResolveSkill_ExplicitHint(t *testing.T) {
	reg := toolstore.NewInMemoryRegistry()
	ctx := context.Background()
	_ = reg.Upsert(ctx, toolstore.Tool{Name: "analyze", Actor: "start-analysis", A2AEnabled: true})
	_ = reg.Upsert(ctx, toolstore.Tool{Name: "extract", Actor: "start-extract", A2AEnabled: true})

	exec := NewExecutor(nil, taskstore.NewStore(), reg, "default")
	msg := a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"})

	skill, err := exec.resolveSkill(msg, map[string]any{"skill": "analyze"})
	if err != nil {
		t.Fatalf("resolveSkill failed: %v", err)
	}
	if skill.Actor != "start-analysis" {
		t.Errorf("actor = %q, want %q", skill.Actor, "start-analysis")
	}
}

func TestExecutorResolveSkill_SingleDefault(t *testing.T) {
	reg := toolstore.NewInMemoryRegistry()
	ctx := context.Background()
	_ = reg.Upsert(ctx, toolstore.Tool{Name: "only-skill", Actor: "my-actor", A2AEnabled: true})

	exec := NewExecutor(nil, taskstore.NewStore(), reg, "default")
	msg := a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"})

	skill, err := exec.resolveSkill(msg, nil)
	if err != nil {
		t.Fatalf("resolveSkill failed: %v", err)
	}
	if skill.Actor != "my-actor" {
		t.Errorf("actor = %q, want %q", skill.Actor, "my-actor")
	}
}

func TestExecutorResolveSkill_MultipleNoHint(t *testing.T) {
	reg := toolstore.NewInMemoryRegistry()
	ctx := context.Background()
	_ = reg.Upsert(ctx, toolstore.Tool{Name: "s1", Actor: "a1", A2AEnabled: true})
	_ = reg.Upsert(ctx, toolstore.Tool{Name: "s2", Actor: "a2", A2AEnabled: true})

	exec := NewExecutor(nil, taskstore.NewStore(), reg, "default")
	msg := a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"})

	_, err := exec.resolveSkill(msg, nil)
	if err == nil {
		t.Fatal("expected error for multiple skills without hint")
	}
}

func TestExecutorResolveSkill_NoSkills(t *testing.T) {
	reg := toolstore.NewInMemoryRegistry()
	exec := NewExecutor(nil, taskstore.NewStore(), reg, "default")
	msg := a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"})

	_, err := exec.resolveSkill(msg, nil)
	if err == nil {
		t.Fatal("expected error for no skills")
	}
}

func TestExecutorExecute(t *testing.T) {
	reg := toolstore.NewInMemoryRegistry()
	ctx := context.Background()
	_ = reg.Upsert(ctx, toolstore.Tool{Name: "analyze", Actor: "start-analysis", A2AEnabled: true})

	store := taskstore.NewStore()
	exec := NewExecutor(nil, store, reg, "default")

	reqCtx := &a2asrv.RequestContext{
		TaskID:    a2alib.NewTaskID(),
		ContextID: a2alib.NewContextID(),
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "hello"}),
		Metadata:  map[string]any{"skill": "analyze"},
	}

	mockQueue := &mockEventQueue{}
	err := exec.Execute(ctx, reqCtx, mockQueue)
	if err != nil {
		t.Fatalf("Execute failed: %v", err)
	}

	// Verify task was created in store
	task, getErr := store.Get(string(reqCtx.TaskID))
	if getErr != nil {
		t.Fatalf("task not found in store: %v", getErr)
	}
	if task.Route.Curr != "start-analysis" {
		t.Errorf("route.curr = %q, want %q", task.Route.Curr, "start-analysis")
	}

	// Verify event was written
	if len(mockQueue.events) == 0 {
		t.Fatal("expected at least one event written to queue")
	}
}

func TestExecutorCancel(t *testing.T) {
	reg := toolstore.NewInMemoryRegistry()
	store := taskstore.NewStore()
	exec := NewExecutor(nil, store, reg, "default")
	ctx := context.Background()

	// Create a task first
	taskID := a2alib.NewTaskID()
	_ = store.Create(&types.Task{
		ID:     string(taskID),
		Status: types.TaskStatusRunning,
	})

	reqCtx := &a2asrv.RequestContext{
		TaskID:    taskID,
		ContextID: a2alib.NewContextID(),
	}

	mockQueue := &mockEventQueue{}
	err := exec.Cancel(ctx, reqCtx, mockQueue)
	if err != nil {
		t.Fatalf("Cancel failed: %v", err)
	}

	// Verify task was canceled in store
	task, _ := store.Get(string(taskID))
	if task.Status != types.TaskStatusCanceled {
		t.Errorf("task status = %q, want %q", task.Status, types.TaskStatusCanceled)
	}

	if len(mockQueue.events) == 0 {
		t.Fatal("expected cancel event written to queue")
	}
}

// mockEventQueue implements eventqueue.Queue for testing.
type mockEventQueue struct {
	events []a2alib.Event
}

func (m *mockEventQueue) Write(_ context.Context, event a2alib.Event) error {
	m.events = append(m.events, event)
	return nil
}

func (m *mockEventQueue) WriteVersioned(_ context.Context, event a2alib.Event, _ a2alib.TaskVersion) error {
	m.events = append(m.events, event)
	return nil
}

func (m *mockEventQueue) Read(_ context.Context) (a2alib.Event, a2alib.TaskVersion, error) {
	return nil, 0, nil
}

func (m *mockEventQueue) Close() error { return nil }
