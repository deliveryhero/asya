package a2a

import (
	"encoding/json"
	"maps"
	"strings"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// MessageToPayload converts an A2A message to an internal task payload.
//
// Rules (from RFC Section 5.2):
// 1. ALWAYS: Initialize payload["a2a"]["task"] with id, context_id, and history array containing the serialized message
// 2. Single DataPart, no text -> unwrap Data map at payload root
// 3. Text-only Parts -> concatenate with "\n", store as payload["query"]
// 4. Mixed -> merge data at root, add text as payload["query"]
//
// NO synthetic fields (_a2a_text, _a2a_files) are allowed.
func MessageToPayload(msg *a2alib.Message, taskID a2alib.TaskID, contextID string) any {
	var textParts []string
	var dataParts []map[string]any
	hasFiles := false

	for _, part := range msg.Parts {
		switch p := part.(type) {
		case *a2alib.TextPart:
			textParts = append(textParts, p.Text)
		case *a2alib.DataPart:
			dataParts = append(dataParts, p.Data)
		case *a2alib.FilePart:
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

	return payload
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
	data, _ := json.Marshal(msg)
	var entry any
	_ = json.Unmarshal(data, &entry)
	return entry
}

// TaskToA2ATask is a temporary stub to maintain compilation.
// TODO(T5): Remove this stub when store adapter is implemented.
func TaskToA2ATask(task *types.Task) types.A2ATask {
	a2aTask := types.A2ATask{
		ID:        task.ID,
		ContextID: task.ContextID,
		Status: types.A2ATaskStatus{
			State:     types.ToA2AState(task.Status),
			Timestamp: task.UpdatedAt.UTC().Format("2006-01-02T15:04:05Z"),
		},
	}

	if task.Message != "" {
		a2aTask.Status.Message = &types.A2AMessage{
			Role:  "agent",
			Parts: []types.A2APart{{Type: "text", Text: task.Message}},
		}
	}

	if task.Result != nil && task.Status == types.TaskStatusSucceeded {
		a2aTask.Artifacts = []types.A2AArtifact{
			{
				ArtifactID: "result-1",
				Parts:      []types.A2APart{{Type: "data", Data: task.Result}},
			},
		}
	}

	if task.Error != "" && task.Status == types.TaskStatusFailed {
		a2aTask.Status.Message = &types.A2AMessage{
			Role:  "agent",
			Parts: []types.A2APart{{Type: "text", Text: task.Error}},
		}
	}

	if task.Status == types.TaskStatusRunning {
		a2aTask.Metadata = map[string]any{
			"progress_percent":   task.ProgressPercent,
			"current_actor_name": task.CurrentActorName,
			"actors_completed":   task.ActorsCompleted,
			"total_actors":       task.TotalActors,
		}
	}

	return a2aTask
}

// TaskUpdateToSSEEvents is a temporary stub to maintain compilation.
// TODO(T7): Remove this stub when a2a-go's built-in SSE handling is integrated.
func TaskUpdateToSSEEvents(update types.TaskUpdate) types.A2ATaskStatusUpdateEvent {
	state := types.ToA2AState(update.Status)
	final := state == types.A2AStateCompleted || state == types.A2AStateFailed || state == types.A2AStateCanceled

	event := types.A2ATaskStatusUpdateEvent{
		ID: update.ID,
		Status: types.A2ATaskStatus{
			State:     state,
			Timestamp: update.Timestamp.UTC().Format("2006-01-02T15:04:05Z"),
		},
		Final: final,
	}

	msg := update.Message
	if update.Error != "" {
		msg = update.Error
	}
	if msg != "" {
		event.Status.Message = &types.A2AMessage{
			Role:  "agent",
			Parts: []types.A2APart{{Type: "text", Text: msg}},
		}
	}

	return event
}

// --- BACKWARD COMPATIBILITY SHIMS (to be removed when handler.go is updated) ---

// MessageToPayloadLegacy is a temporary compatibility shim for existing handler.go code.
// This allows the old callers to continue working until they are updated in later tasks.
// TODO: Remove this when handler.go is updated to use new MessageToPayload signature.
func MessageToPayloadLegacy(msg types.A2AMessage) any {
	var textParts []string
	var dataParts []map[string]any
	var fileParts []map[string]string

	for _, part := range msg.Parts {
		switch part.Type {
		case "text":
			textParts = append(textParts, part.Text)
		case "data":
			if m, ok := part.Data.(map[string]any); ok {
				dataParts = append(dataParts, m)
			}
		case "file":
			fileParts = append(fileParts, map[string]string{
				"url":        part.URL,
				"media_type": part.MediaType,
			})
		}
	}

	// Single data part, no text or files: unwrap directly
	if len(dataParts) == 1 && len(textParts) == 0 && len(fileParts) == 0 {
		return dataParts[0]
	}

	// Build composite payload
	payload := make(map[string]any)

	// Merge data parts
	for _, dp := range dataParts {
		maps.Copy(payload, dp)
	}

	// Add text
	if len(textParts) > 0 {
		payload["_a2a_text"] = strings.Join(textParts, "\n")
	}

	// Add files
	if len(fileParts) > 0 {
		payload["_a2a_files"] = fileParts
	}

	return payload
}
