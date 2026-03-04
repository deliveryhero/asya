package a2a

import (
	"testing"

	a2alib "github.com/a2aproject/a2a-go/a2a"
)

func TestMessageToPayload_SingleDataPart(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-1",
		TaskID: "task-1",
		Role:   a2alib.MessageRoleUser,
		Parts: a2alib.ContentParts{
			&a2alib.DataPart{Data: map[string]any{"key": "val"}},
		},
	}
	taskID := a2alib.TaskID("task-1")
	contextID := "ctx-1"

	payload := MessageToPayload(msg, taskID, contextID)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}

	// Verify root-level extraction
	if m["key"] != "val" {
		t.Errorf("key = %v, want val", m["key"])
	}

	// Verify a2a.task namespace exists
	a2aNamespace, ok := m["a2a"].(map[string]any)
	if !ok {
		t.Fatal("missing a2a namespace")
	}
	taskNamespace, ok := a2aNamespace["task"].(map[string]any)
	if !ok {
		t.Fatal("missing a2a.task namespace")
	}
	if taskNamespace["id"] != "task-1" {
		t.Errorf("a2a.task.id = %v, want task-1", taskNamespace["id"])
	}
	if taskNamespace["context_id"] != "ctx-1" {
		t.Errorf("a2a.task.context_id = %v, want ctx-1", taskNamespace["context_id"])
	}
	history, ok := taskNamespace["history"].([]any)
	if !ok || len(history) != 1 {
		t.Fatal("a2a.task.history should be array with 1 entry")
	}
}

func TestMessageToPayload_TextOnly(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-2",
		TaskID: "task-2",
		Role:   a2alib.MessageRoleUser,
		Parts: a2alib.ContentParts{
			&a2alib.TextPart{Text: "hello"},
		},
	}
	taskID := a2alib.TaskID("task-2")
	contextID := "ctx-2"

	payload := MessageToPayload(msg, taskID, contextID)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}

	// Verify query field set
	if m["query"] != "hello" {
		t.Errorf("query = %v, want hello", m["query"])
	}

	// Verify a2a.task namespace exists
	a2aNamespace, ok := m["a2a"].(map[string]any)
	if !ok {
		t.Fatal("missing a2a namespace")
	}
	_, ok = a2aNamespace["task"].(map[string]any)
	if !ok {
		t.Fatal("missing a2a.task namespace")
	}
}

func TestMessageToPayload_MultiText(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-3",
		TaskID: "task-3",
		Role:   a2alib.MessageRoleUser,
		Parts: a2alib.ContentParts{
			&a2alib.TextPart{Text: "line 1"},
			&a2alib.TextPart{Text: "line 2"},
		},
	}
	taskID := a2alib.TaskID("task-3")
	contextID := "ctx-3"

	payload := MessageToPayload(msg, taskID, contextID)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}

	// Verify text concatenation with "\n"
	if m["query"] != "line 1\nline 2" {
		t.Errorf("query = %v, want 'line 1\\nline 2'", m["query"])
	}
}

func TestMessageToPayload_NoSyntheticFields(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-4",
		TaskID: "task-4",
		Role:   a2alib.MessageRoleUser,
		Parts: a2alib.ContentParts{
			&a2alib.TextPart{Text: "analyze this"},
			&a2alib.DataPart{Data: map[string]any{"x": 1}},
		},
	}
	taskID := a2alib.TaskID("task-4")
	contextID := "ctx-4"

	payload := MessageToPayload(msg, taskID, contextID)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}

	// Verify no underscore-prefixed synthetic fields exist
	for key := range m {
		if len(key) > 0 && key[0] == '_' {
			t.Errorf("found synthetic field: %s (forbidden by RFC)", key)
		}
	}

	// Verify data merged at root
	if m["x"] != 1 {
		t.Error("data part not merged at root")
	}

	// Verify text as query
	if m["query"] != "analyze this" {
		t.Error("text not stored as query")
	}
}

func TestMessageToPayload_MixedParts(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-5",
		TaskID: "task-5",
		Role:   a2alib.MessageRoleUser,
		Parts: a2alib.ContentParts{
			&a2alib.TextPart{Text: "analyze"},
			&a2alib.DataPart{Data: map[string]any{"type": "image"}},
			&a2alib.DataPart{Data: map[string]any{"priority": "high"}},
		},
	}
	taskID := a2alib.TaskID("task-5")
	contextID := "ctx-5"

	payload := MessageToPayload(msg, taskID, contextID)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}

	// Verify all data parts merged at root
	if m["type"] != "image" {
		t.Error("first data part not merged")
	}
	if m["priority"] != "high" {
		t.Error("second data part not merged")
	}

	// Verify text as query
	if m["query"] != "analyze" {
		t.Error("text not stored as query")
	}
}

func TestBuildA2AHeaders(t *testing.T) {
	headers := BuildA2AHeaders("task-123", "ctx-456")

	if headers["x-asya-a2a-task-id"] != "task-123" {
		t.Errorf("task-id header = %v, want task-123", headers["x-asya-a2a-task-id"])
	}
	if headers["x-asya-a2a-context-id"] != "ctx-456" {
		t.Errorf("context-id header = %v, want ctx-456", headers["x-asya-a2a-context-id"])
	}

	// Verify only expected headers are present
	if len(headers) != 2 {
		t.Errorf("expected 2 headers, got %d", len(headers))
	}
}

func TestMessageToPayload_WithFilePart(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-6",
		TaskID: "task-6",
		Role:   a2alib.MessageRoleUser,
		Parts: a2alib.ContentParts{
			&a2alib.TextPart{Text: "process this file"},
			&a2alib.FilePart{},
		},
	}
	taskID := a2alib.TaskID("task-6")
	contextID := "ctx-6"

	payload := MessageToPayload(msg, taskID, contextID)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}

	// When files are present, we should not unwrap single data part
	// Text should be stored as query
	if m["query"] != "process this file" {
		t.Error("text not stored as query when file part present")
	}

	// Verify no synthetic _a2a_files field
	if _, exists := m["_a2a_files"]; exists {
		t.Error("found forbidden _a2a_files synthetic field")
	}
}
