package a2aadapter

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"
	"github.com/a2aproject/a2a-go/a2asrv/eventqueue"

	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/internal/sseclient"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// flyArtifactID is the deterministic artifact ID used for FLY streaming chunks.
const flyArtifactID = "fly-stream"

// resultArtifactID is the artifact ID used for the final result payload.
const resultArtifactID = "result"

// Executor implements a2asrv.AgentExecutor using mesh-api HTTP calls.
type Executor struct {
	registry   *AgentRegistry
	meshClient *meshclient.Client
	store      *StoreAdapter // for registering a2a task ID → mesh message ID
}

// NewExecutor creates a new A2A executor.
func NewExecutor(registry *AgentRegistry, meshClient *meshclient.Client, store *StoreAdapter) *Executor {
	return &Executor{
		registry:   registry,
		meshClient: meshClient,
		store:      store,
	}
}

// Execute handles tasks/send and tasks/sendSubscribe.
func (e *Executor) Execute(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	msg := reqCtx.Message
	taskID := reqCtx.TaskID
	contextID := reqCtx.ContextID

	// Check for resume of paused task
	if reqCtx.StoredTask != nil && reqCtx.StoredTask.Status.State == a2alib.TaskStateInputRequired {
		return e.handleResume(ctx, reqCtx, eq)
	}

	// Resolve skill -> agent -> actor
	var skillHint string
	if reqCtx.Metadata != nil {
		if hint, ok := reqCtx.Metadata["skill"].(string); ok {
			skillHint = hint
		}
	}

	agent, err := e.registry.ResolveActor(skillHint)
	if err != nil {
		return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
			reqCtx, a2alib.TaskStateRejected,
			a2alib.NewMessage(a2alib.MessageRoleAgent,
				&a2alib.TextPart{Text: err.Error()})))
	}

	// Translate A2A Message -> mesh payload
	payload := messageToPayload(msg, string(taskID), contextID)

	timeout := agent.Timeout
	if timeout == 0 {
		timeout = 300
	}

	// Step 1: Create message in mesh-api
	createResp, err := e.meshClient.Create(ctx, agent.Actor, meshclient.CreateRequest{
		Payload: payload,
		Headers: map[string]any{
			"x-asya-a2a-task-id":    string(taskID),
			"x-asya-a2a-context-id": contextID,
		},
		Timeout: timeout,
	})
	if err != nil {
		slog.Error("Mesh create failed", "task_id", taskID, "error", err)
		return fmt.Errorf("dispatch: %w", err)
	}

	// Register a2a task ID → mesh message ID so tasks/get can resolve it
	if e.store != nil {
		e.store.RegisterTask(taskID, createResp.ID)
	}

	// Write submitted event
	if err := eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateSubmitted, nil)); err != nil {
		return fmt.Errorf("write submitted event: %w", err)
	}

	// Step 2: Subscribe to SSE events and relay as A2A events
	sseCtx, sseCancel := context.WithTimeout(ctx, time.Duration(timeout)*time.Second)
	defer sseCancel()

	events, errCh := e.meshClient.SubscribeEvents(sseCtx, createResp.ID)

	firstFLY := true
	for evt := range events {
		switch evt.Type {
		case "status":
			var status sseclient.StatusData
			if json.Unmarshal(evt.Data, &status) != nil {
				continue
			}

			a2aState := MeshStatusToA2A(status.Status)

			if sseclient.IsTerminal(status.Status) || sseclient.IsInterrupted(status.Status) {
				// Close artifact stream if FLY events were sent
				if !firstFLY {
					closeArtifactStream(ctx, reqCtx, eq)
				}

				// Write result artifact for succeeded tasks
				if status.Status == string(types.MessageStatusSucceeded) && status.Result != nil {
					writeResultArtifact(ctx, reqCtx, eq, status.Result)
				}

				// Write terminal event
				termEvt := a2alib.NewStatusUpdateEvent(reqCtx, a2aState, nil)
				termEvt.Final = true
				return eq.Write(ctx, termEvt)
			}

			// Non-terminal: write working status
			if status.Status == string(types.MessageStatusRunning) {
				_ = eq.Write(ctx, a2alib.NewStatusUpdateEvent(reqCtx, a2alib.TaskStateWorking, nil))
			}

		case "fly":
			// Convert FLY to A2A artifact chunk
			artifact := &a2alib.TaskArtifactUpdateEvent{
				TaskID:    reqCtx.TaskID,
				ContextID: reqCtx.ContextID,
				Append:    !firstFLY,
				Artifact: &a2alib.Artifact{
					ID:    a2alib.ArtifactID(flyArtifactID),
					Parts: a2alib.ContentParts{&a2alib.TextPart{Text: string(evt.Data)}},
				},
			}
			firstFLY = false
			if err := eq.Write(ctx, artifact); err != nil {
				slog.Warn("Failed to relay FLY as artifact", "task_id", taskID, "error", err)
			}
		}
	}

	// Check SSE error
	if sseErr := <-errCh; sseErr != nil {
		slog.Warn("SSE stream error", "task_id", taskID, "error", sseErr)
	}

	// Fallback: poll mesh-api for final status
	return e.pollAndWriteTerminal(ctx, createResp.ID, time.Duration(timeout)*time.Second, reqCtx, eq)
}

// Cancel handles tasks/cancel.
func (e *Executor) Cancel(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	taskID := reqCtx.TaskID

	if err := e.meshClient.Cancel(ctx, string(taskID)); err != nil {
		return fmt.Errorf("cancel task %q: %w", taskID, err)
	}

	return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateCanceled, nil))
}

// handleResume dispatches a resume message for paused tasks.
func (e *Executor) handleResume(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	taskID := reqCtx.TaskID
	contextID := reqCtx.ContextID
	msg := reqCtx.Message

	payload := messageToPayload(msg, string(taskID), contextID)

	_, err := e.meshClient.Create(ctx, "x-resume", meshclient.CreateRequest{
		Payload: payload,
		Headers: map[string]any{
			"x-asya-resume-task":    string(taskID),
			"x-asya-a2a-task-id":    string(taskID),
			"x-asya-a2a-context-id": contextID,
		},
	})
	if err != nil {
		return fmt.Errorf("dispatch resume: %w", err)
	}

	return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateWorking, nil))
}

// pollAndWriteTerminal polls mesh-api until terminal status, then writes final event.
func (e *Executor) pollAndWriteTerminal(
	ctx context.Context,
	id string,
	timeout time.Duration,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	pollCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-pollCtx.Done():
			evt := a2alib.NewStatusUpdateEvent(reqCtx, a2alib.TaskStateUnknown, nil)
			evt.Final = true
			return eq.Write(ctx, evt)
		case <-ticker.C:
			status, err := e.meshClient.Get(pollCtx, id)
			if err != nil {
				continue
			}
			if sseclient.IsTerminal(status.Status) || sseclient.IsInterrupted(status.Status) {
				a2aState := MeshStatusToA2A(status.Status)
				evt := a2alib.NewStatusUpdateEvent(reqCtx, a2aState, nil)
				evt.Final = true
				return eq.Write(ctx, evt)
			}
		}
	}
}

// closeArtifactStream sends a LastChunk event to signal end of FLY artifact.
func closeArtifactStream(ctx context.Context, reqCtx *a2asrv.RequestContext, eq eventqueue.Queue) {
	lastChunk := &a2alib.TaskArtifactUpdateEvent{
		TaskID:    reqCtx.TaskID,
		ContextID: reqCtx.ContextID,
		Append:    true,
		LastChunk: true,
		Artifact: &a2alib.Artifact{
			ID:    a2alib.ArtifactID(flyArtifactID),
			Parts: a2alib.ContentParts{},
		},
	}
	if err := eq.Write(ctx, lastChunk); err != nil {
		slog.Warn("Failed to write LastChunk", "error", err)
	}
}

// writeResultArtifact writes the final result as an A2A artifact.
func writeResultArtifact(ctx context.Context, reqCtx *a2asrv.RequestContext, eq eventqueue.Queue, result any) {
	data, err := json.Marshal(result)
	if err != nil {
		return
	}
	evt := &a2alib.TaskArtifactUpdateEvent{
		TaskID:    reqCtx.TaskID,
		ContextID: reqCtx.ContextID,
		Append:    false,
		LastChunk: true,
		Artifact: &a2alib.Artifact{
			ID:   a2alib.ArtifactID(resultArtifactID),
			Name: "Task result",
			Parts: a2alib.ContentParts{
				&a2alib.TextPart{Text: string(data)},
			},
		},
	}
	if err := eq.Write(ctx, evt); err != nil {
		slog.Warn("Failed to write result artifact", "error", err)
	}
}

// messageToPayload converts an A2A message to a mesh payload.
// Follows the same rules as the existing a2a.MessageToPayload.
func messageToPayload(msg *a2alib.Message, taskID, contextID string) map[string]any {
	var textParts []string
	var dataParts []map[string]any

	if msg != nil {
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
			}
		}
	}

	var payload map[string]any

	// Single data part, no text -> copy fields into new map (do NOT use dataParts[0]
	// directly as payload; we later add payload["a2a"] to it which would create a cycle
	// if messageToHistoryEntry references the same map via payload["a2a"]["task"]["history"]).
	if len(dataParts) == 1 && len(textParts) == 0 {
		payload = make(map[string]any, len(dataParts[0])+1)
		for k, v := range dataParts[0] {
			payload[k] = v
		}
	} else {
		payload = make(map[string]any)
		for _, dp := range dataParts {
			for k, v := range dp {
				payload[k] = v
			}
		}
		if len(textParts) > 0 {
			text := ""
			for i, t := range textParts {
				if i > 0 {
					text += "\n"
				}
				text += t
			}
			payload["query"] = text
		}
	}

	// A2A task namespace
	payload["a2a"] = map[string]any{
		"task": map[string]any{
			"id":         taskID,
			"context_id": contextID,
			"history":    []any{messageToHistoryEntry(msg)},
		},
	}

	return payload
}

func messageToHistoryEntry(msg *a2alib.Message) any {
	if msg == nil {
		return map[string]any{}
	}
	// Return a simplified representation to avoid embedding the full *Message
	// struct (with ContentParts) in the payload map[string]any. Embedding the
	// actual *Message causes circular JSON encoding (message → DataPart.Data →
	// history → message → ...) leading to a fatal goroutine stack overflow.
	entry := map[string]any{
		"id":   string(msg.ID),
		"role": string(msg.Role),
	}
	for _, part := range msg.Parts {
		switch p := part.(type) {
		case *a2alib.TextPart:
			entry["text"] = p.Text
		case a2alib.TextPart:
			entry["text"] = p.Text
		case *a2alib.DataPart:
			// copy the data map to avoid sharing with the payload root
			dataCopy := make(map[string]any, len(p.Data))
			for k, v := range p.Data {
				dataCopy[k] = v
			}
			entry["data"] = dataCopy
		case a2alib.DataPart:
			dataCopy := make(map[string]any, len(p.Data))
			for k, v := range p.Data {
				dataCopy[k] = v
			}
			entry["data"] = dataCopy
		}
	}
	return entry
}
