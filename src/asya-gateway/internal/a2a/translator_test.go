package a2a

import (
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestMessageToPayload_SingleDataPart(t *testing.T) {
	msg := types.A2AMessage{
		Role: "user",
		Parts: []types.A2APart{
			{Type: "data", Data: map[string]any{"key": "val"}},
		},
	}
	payload := MessageToPayload(msg)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}
	if m["key"] != "val" {
		t.Errorf("key = %v, want val", m["key"])
	}
}

func TestMessageToPayload_TextPart(t *testing.T) {
	msg := types.A2AMessage{
		Role:  "user",
		Parts: []types.A2APart{{Type: "text", Text: "hello"}},
	}
	payload := MessageToPayload(msg)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}
	if m["_a2a_text"] != "hello" {
		t.Errorf("_a2a_text = %v, want hello", m["_a2a_text"])
	}
}

func TestMessageToPayload_MixedParts(t *testing.T) {
	msg := types.A2AMessage{
		Role: "user",
		Parts: []types.A2APart{
			{Type: "text", Text: "analyze this"},
			{Type: "data", Data: map[string]any{"x": 1}},
			{Type: "file", URL: "s3://b/f.pdf", MediaType: "application/pdf"},
		},
	}
	payload := MessageToPayload(msg)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}
	if m["_a2a_text"] != "analyze this" {
		t.Error("missing _a2a_text")
	}
	files, ok := m["_a2a_files"].([]map[string]string)
	if !ok || len(files) != 1 {
		t.Error("missing or wrong _a2a_files")
	}
}

func TestTaskToA2ATask(t *testing.T) {
	task := &types.Task{
		ID:        "t1",
		ContextID: "ctx-1",
		Status:    types.TaskStatusSucceeded,
		Result:    map[string]any{"score": 0.9},
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	a2aTask := TaskToA2ATask(task)
	if a2aTask.ID != "t1" {
		t.Errorf("ID = %s, want t1", a2aTask.ID)
	}
	if a2aTask.ContextID != "ctx-1" {
		t.Errorf("ContextID = %s, want ctx-1", a2aTask.ContextID)
	}
	if a2aTask.Status.State != types.A2AStateCompleted {
		t.Errorf("State = %s, want completed", a2aTask.Status.State)
	}
	if len(a2aTask.Artifacts) != 1 {
		t.Errorf("Artifacts count = %d, want 1", len(a2aTask.Artifacts))
	}
}

func TestTaskToA2ATask_Running(t *testing.T) {
	task := &types.Task{
		ID:               "t2",
		Status:           types.TaskStatusRunning,
		ProgressPercent:  50.0,
		CurrentActorName: "analyzer",
		ActorsCompleted:  1,
		TotalActors:      3,
		Message:          "Processing",
		UpdatedAt:        time.Now(),
	}
	a2aTask := TaskToA2ATask(task)
	if a2aTask.Status.State != types.A2AStateWorking {
		t.Errorf("State = %s, want working", a2aTask.Status.State)
	}
	if a2aTask.Metadata == nil {
		t.Fatal("Metadata should not be nil for running task")
	}
	meta, ok := a2aTask.Metadata.(map[string]any)
	if !ok {
		t.Fatal("Metadata should be map[string]any")
	}
	if meta["progress_percent"] != 50.0 {
		t.Errorf("progress_percent = %v, want 50.0", meta["progress_percent"])
	}
}

func TestTaskToA2ATask_Failed(t *testing.T) {
	task := &types.Task{
		ID:        "t3",
		Status:    types.TaskStatusFailed,
		Error:     "processing error",
		UpdatedAt: time.Now(),
	}
	a2aTask := TaskToA2ATask(task)
	if a2aTask.Status.State != types.A2AStateFailed {
		t.Errorf("State = %s, want failed", a2aTask.Status.State)
	}
	if a2aTask.Status.Message == nil {
		t.Fatal("Status.Message should not be nil for failed task with error")
	}
	if a2aTask.Status.Message.Parts[0].Text != "processing error" {
		t.Errorf("error text = %s, want 'processing error'", a2aTask.Status.Message.Parts[0].Text)
	}
}

func TestTaskUpdateToSSEEvents(t *testing.T) {
	update := types.TaskUpdate{
		ID:        "t1",
		Status:    types.TaskStatusSucceeded,
		Message:   "done",
		Timestamp: time.Now(),
	}
	event := TaskUpdateToSSEEvents(update)
	if event.ID != "t1" {
		t.Errorf("ID = %s, want t1", event.ID)
	}
	if event.Status.State != types.A2AStateCompleted {
		t.Errorf("State = %s, want completed", event.Status.State)
	}
	if !event.Final {
		t.Error("Final should be true for completed state")
	}
}

func TestTaskUpdateToSSEEvents_NotFinal(t *testing.T) {
	update := types.TaskUpdate{
		ID:        "t2",
		Status:    types.TaskStatusRunning,
		Message:   "working",
		Timestamp: time.Now(),
	}
	event := TaskUpdateToSSEEvents(update)
	if event.Final {
		t.Error("Final should be false for working state")
	}
	if event.Status.State != types.A2AStateWorking {
		t.Errorf("State = %s, want working", event.Status.State)
	}
}

func TestTaskUpdateToSSEEvents_ErrorMessage(t *testing.T) {
	update := types.TaskUpdate{
		ID:        "t3",
		Status:    types.TaskStatusFailed,
		Error:     "something broke",
		Timestamp: time.Now(),
	}
	event := TaskUpdateToSSEEvents(update)
	if !event.Final {
		t.Error("Final should be true for failed state")
	}
	if event.Status.Message == nil {
		t.Fatal("Status.Message should not be nil when error is set")
	}
	if event.Status.Message.Parts[0].Text != "something broke" {
		t.Errorf("error text = %s, want 'something broke'", event.Status.Message.Parts[0].Text)
	}
}
