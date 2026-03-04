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

	payload, headers := MessageToPayload(msg, taskID, contextID)

	// Verify root-level extraction
	if payload["key"] != "val" {
		t.Errorf("key = %v, want val", payload["key"])
	}

	// Verify a2a.task namespace exists
	a2aNamespace, ok := payload["a2a"].(map[string]any)
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

	// Verify headers
	if headers["x-asya-a2a-task-id"] != "task-1" {
		t.Errorf("task-id header = %v, want task-1", headers["x-asya-a2a-task-id"])
	}
	if headers["x-asya-a2a-context-id"] != "ctx-1" {
		t.Errorf("context-id header = %v, want ctx-1", headers["x-asya-a2a-context-id"])
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

	payload, _ := MessageToPayload(msg, taskID, contextID)

	// Verify query field set
	if payload["query"] != "hello" {
		t.Errorf("query = %v, want hello", payload["query"])
	}

	// Verify a2a.task namespace exists
	a2aNamespace, ok := payload["a2a"].(map[string]any)
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

	payload, _ := MessageToPayload(msg, taskID, contextID)

	// Verify text concatenation with "\n"
	if payload["query"] != "line 1\nline 2" {
		t.Errorf("query = %v, want 'line 1\\nline 2'", payload["query"])
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

	payload, _ := MessageToPayload(msg, taskID, contextID)

	// Verify no underscore-prefixed synthetic fields exist
	for key := range payload {
		if len(key) > 0 && key[0] == '_' {
			t.Errorf("found synthetic field: %s (forbidden by RFC)", key)
		}
	}

	// Verify data merged at root
	if payload["x"] != 1 {
		t.Error("data part not merged at root")
	}

	// Verify text as query
	if payload["query"] != "analyze this" {
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

	payload, _ := MessageToPayload(msg, taskID, contextID)

	// Verify all data parts merged at root
	if payload["type"] != "image" {
		t.Error("first data part not merged")
	}
	if payload["priority"] != "high" {
		t.Error("second data part not merged")
	}

	// Verify text as query
	if payload["query"] != "analyze" {
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

	payload, _ := MessageToPayload(msg, taskID, contextID)

	// When files are present, we should not unwrap single data part
	// Text should be stored as query
	if payload["query"] != "process this file" {
		t.Error("text not stored as query when file part present")
	}

	// Verify no synthetic _a2a_files field
	if _, exists := payload["_a2a_files"]; exists {
		t.Error("found forbidden _a2a_files synthetic field")
	}
}

func TestMessageToPayload_EmptyParts(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-empty",
		TaskID: "task-empty",
		Role:   a2alib.MessageRoleUser,
		Parts:  a2alib.ContentParts{},
	}
	taskID := a2alib.TaskID("task-empty")
	contextID := "ctx-empty"

	payload, headers := MessageToPayload(msg, taskID, contextID)

	// Verify a2a.task namespace is still initialized
	a2aNamespace, ok := payload["a2a"].(map[string]any)
	if !ok {
		t.Fatal("missing a2a namespace for empty parts")
	}
	taskNamespace, ok := a2aNamespace["task"].(map[string]any)
	if !ok {
		t.Fatal("missing a2a.task namespace for empty parts")
	}
	if taskNamespace["id"] != "task-empty" {
		t.Errorf("a2a.task.id = %v, want task-empty", taskNamespace["id"])
	}
	if taskNamespace["context_id"] != "ctx-empty" {
		t.Errorf("a2a.task.context_id = %v, want ctx-empty", taskNamespace["context_id"])
	}

	// Verify no query field when no text parts
	if _, exists := payload["query"]; exists {
		t.Error("query field should not exist when there are no text parts")
	}

	// Verify headers are still stamped
	if headers["x-asya-a2a-task-id"] != "task-empty" {
		t.Errorf("task-id header = %v, want task-empty", headers["x-asya-a2a-task-id"])
	}
	if headers["x-asya-a2a-context-id"] != "ctx-empty" {
		t.Errorf("context-id header = %v, want ctx-empty", headers["x-asya-a2a-context-id"])
	}
}

func TestMessageToPayload_NilParts(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-nil",
		TaskID: "task-nil",
		Role:   a2alib.MessageRoleUser,
		Parts:  nil,
	}
	taskID := a2alib.TaskID("task-nil")
	contextID := "ctx-nil"

	payload, headers := MessageToPayload(msg, taskID, contextID)

	// Verify a2a.task namespace is still initialized
	a2aNamespace, ok := payload["a2a"].(map[string]any)
	if !ok {
		t.Fatal("missing a2a namespace for nil parts")
	}
	taskNamespace, ok := a2aNamespace["task"].(map[string]any)
	if !ok {
		t.Fatal("missing a2a.task namespace for nil parts")
	}
	if taskNamespace["id"] != "task-nil" {
		t.Errorf("a2a.task.id = %v, want task-nil", taskNamespace["id"])
	}

	// Verify headers are still stamped
	if headers["x-asya-a2a-task-id"] != "task-nil" {
		t.Errorf("task-id header = %v, want task-nil", headers["x-asya-a2a-task-id"])
	}
	if headers["x-asya-a2a-context-id"] != "ctx-nil" {
		t.Errorf("context-id header = %v, want ctx-nil", headers["x-asya-a2a-context-id"])
	}
}

func TestMessageToPayload_HistoryContainsFullMessage(t *testing.T) {
	msg := &a2alib.Message{
		ID:        "msg-hist",
		TaskID:    "task-hist",
		ContextID: "ctx-hist",
		Role:      a2alib.MessageRoleUser,
		Parts: a2alib.ContentParts{
			&a2alib.TextPart{Text: "hello world"},
		},
	}
	taskID := a2alib.TaskID("task-hist")
	contextID := "ctx-hist"

	payload, _ := MessageToPayload(msg, taskID, contextID)

	// Verify history contains the full serialized message
	a2aNamespace := payload["a2a"].(map[string]any)
	taskNamespace := a2aNamespace["task"].(map[string]any)
	history, ok := taskNamespace["history"].([]any)
	if !ok || len(history) != 1 {
		t.Fatal("a2a.task.history should be array with 1 entry")
	}

	// The history entry should be a map containing the message fields
	entry, ok := history[0].(map[string]any)
	if !ok {
		t.Fatal("history entry should be a map")
	}

	// Verify role is preserved in history
	if entry["role"] != "user" {
		t.Errorf("history entry role = %v, want user", entry["role"])
	}
}

func TestMessageToPayload_HeaderStamping(t *testing.T) {
	msg := &a2alib.Message{
		ID:     "msg-hdr",
		TaskID: "task-hdr",
		Role:   a2alib.MessageRoleUser,
		Parts: a2alib.ContentParts{
			&a2alib.TextPart{Text: "test"},
		},
	}

	_, headers := MessageToPayload(msg, "my-task-id", "my-context-id")

	if headers["x-asya-a2a-task-id"] != "my-task-id" {
		t.Errorf("task-id header = %v, want my-task-id", headers["x-asya-a2a-task-id"])
	}
	if headers["x-asya-a2a-context-id"] != "my-context-id" {
		t.Errorf("context-id header = %v, want my-context-id", headers["x-asya-a2a-context-id"])
	}
	if len(headers) != 2 {
		t.Errorf("expected exactly 2 headers, got %d", len(headers))
	}
}
