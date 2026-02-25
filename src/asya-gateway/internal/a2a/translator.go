package a2a

import (
	"maps"
	"strings"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// MessageToPayload converts an A2A message to an internal task payload.
//
// Rules:
// 1. Single data part -> unwrap as payload directly
// 2. Text parts -> merge into _a2a_text
// 3. File parts -> collect into _a2a_files array
// 4. Mixed -> combine into unified payload with _a2a_* keys
func MessageToPayload(msg types.A2AMessage) any {
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

// TaskToA2ATask converts an internal Task to an A2A Task response.
func TaskToA2ATask(task *types.Task) types.A2ATask {
	a2aTask := types.A2ATask{
		ID:        task.ID,
		ContextID: task.ContextID,
		Status: types.A2ATaskStatus{
			State:     types.ToA2AState(task.Status),
			Timestamp: task.UpdatedAt.UTC().Format("2006-01-02T15:04:05Z"),
		},
	}

	// Add status message if present
	if task.Message != "" {
		a2aTask.Status.Message = &types.A2AMessage{
			Role:  "agent",
			Parts: []types.A2APart{{Type: "text", Text: task.Message}},
		}
	}

	// Convert result to artifact
	if task.Result != nil && task.Status == types.TaskStatusSucceeded {
		a2aTask.Artifacts = []types.A2AArtifact{
			{
				ArtifactID: "result-1",
				Parts:      []types.A2APart{{Type: "data", Data: task.Result}},
			},
		}
	}

	// Convert error to status message
	if task.Error != "" && task.Status == types.TaskStatusFailed {
		a2aTask.Status.Message = &types.A2AMessage{
			Role:  "agent",
			Parts: []types.A2APart{{Type: "text", Text: task.Error}},
		}
	}

	// Add progress metadata for in-progress tasks
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

// TaskUpdateToSSEEvents converts an internal TaskUpdate to A2A SSE events.
func TaskUpdateToSSEEvents(update types.TaskUpdate) types.A2ATaskStatusUpdateEvent {
	state := types.ToA2AState(update.Status)
	final := state == types.A2AStateCompleted || state == types.A2AStateFailed

	event := types.A2ATaskStatusUpdateEvent{
		ID: update.ID,
		Status: types.A2ATaskStatus{
			State:     state,
			Timestamp: update.Timestamp.UTC().Format("2006-01-02T15:04:05Z"),
		},
		Final: final,
	}

	// Add message from update
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
