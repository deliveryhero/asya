package a2a

import (
	"encoding/json"
	"maps"
	"strings"

	a2alib "github.com/a2aproject/a2a-go/a2a"
)

// MessageToPayload converts an A2A message to an envelope payload and headers.
//
// Rules (from RFC Section 5.2):
// 1. ALWAYS: Initialize payload["a2a"]["task"] with id, context_id, and history array containing the serialized message
// 2. Single DataPart, no text -> unwrap Data map at payload root
// 3. Text-only Parts -> concatenate with "\n", store as payload["query"]
// 4. Mixed -> merge data at root, add text as payload["query"]
//
// NO synthetic fields (_a2a_text, _a2a_files) are allowed.
func MessageToPayload(msg *a2alib.Message, taskID a2alib.TaskID, contextID string) (map[string]any, map[string]any) {
	var textParts []string
	var dataParts []map[string]any
	hasFiles := false

	for _, part := range msg.Parts {
		switch p := part.(type) {
		case *a2alib.TextPart:
			textParts = append(textParts, p.Text)
		case a2alib.TextPart:
			textParts = append(textParts, p.Text)
		case *a2alib.DataPart:
			dataParts = append(dataParts, p.Data)
		case a2alib.DataPart:
			dataParts = append(dataParts, p.Data)
		case *a2alib.FilePart, a2alib.FilePart:
			_ = p
			hasFiles = true
		}
	}

	// Build base payload
	var payload map[string]any

	// Rule 2: Single data part, no text or files -> unwrap directly
	if len(dataParts) == 1 && len(textParts) == 0 && !hasFiles {
		payload = dataParts[0]
	} else {
		payload = make(map[string]any)

		// Merge all data parts at root
		for _, dp := range dataParts {
			maps.Copy(payload, dp)
		}

		// Rule 3 & 4: Add text as payload["query"] if present
		if len(textParts) > 0 {
			payload["query"] = strings.Join(textParts, "\n")
		}
	}

	// Rule 1: ALWAYS initialize payload["a2a"]["task"] namespace
	a2aNamespace := map[string]any{
		"task": map[string]any{
			"id":         string(taskID),
			"context_id": contextID,
			"history":    []any{messageToHistoryEntry(msg)},
		},
	}
	payload["a2a"] = a2aNamespace

	headers := BuildA2AHeaders(string(taskID), contextID)

	return payload, headers
}

// BuildA2AHeaders returns envelope headers for A2A task tracking.
func BuildA2AHeaders(taskID, contextID string) map[string]any {
	return map[string]any{
		"x-asya-a2a-task-id":    taskID,
		"x-asya-a2a-context-id": contextID,
	}
}

// messageToHistoryEntry serializes an a2a-go Message to a JSON-compatible map
// for storage in payload.a2a.task.history[].
func messageToHistoryEntry(msg *a2alib.Message) any {
	data, err := json.Marshal(msg)
	if err != nil {
		return map[string]any{"error": "failed to serialize message"}
	}
	var entry any
	if err := json.Unmarshal(data, &entry); err != nil {
		return map[string]any{"error": "failed to deserialize message"}
	}
	return entry
}
