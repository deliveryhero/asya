package a2a

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/internal/envelopestore"
	"github.com/deliveryhero/asya/asya-gateway/internal/stateproxy"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// StoreAdapter wraps the internal TaskStore to implement a2asrv.TaskStore.
type StoreAdapter struct {
	internal   envelopestore.EnvelopeStore
	stateProxy stateproxy.Reader // optional; nil means history/artifacts are always omitted
}

// NewStoreAdapter creates a new StoreAdapter wrapping the provided internal store.
// stateProxy may be nil, in which case GetTask responses omit history and artifacts.
func NewStoreAdapter(store envelopestore.EnvelopeStore, sp stateproxy.Reader) *StoreAdapter {
	return &StoreAdapter{
		internal:   store,
		stateProxy: sp,
	}
}

// Save translates a2a.Task state change to internal TaskUpdate and calls internal.Update.
func (a *StoreAdapter) Save(ctx context.Context, task *a2alib.Task, event a2alib.Event, prev a2alib.TaskVersion) (a2alib.TaskVersion, error) {
	// Streaming artifact chunks are ephemeral — accumulate in a2a-go's
	// Manager.lastSaved in-memory, but do not persist to the DB.
	// Final artifacts are delivered by actors via state proxy.
	if _, ok := event.(*a2alib.TaskArtifactUpdateEvent); ok {
		return prev, nil
	}

	status := FromA2AState(task.Status.State)

	update := types.EnvelopeUpdate{
		ID:        string(task.ID),
		Status:    status,
		Timestamp: time.Now(),
	}

	if task.Status.Message != nil {
		var texts []string
		for _, part := range task.Status.Message.Parts {
			switch p := part.(type) {
			case *a2alib.TextPart:
				texts = append(texts, p.Text)
			case a2alib.TextPart:
				texts = append(texts, p.Text)
			}
		}
		update.Message = strings.Join(texts, "\n")
	}

	if err := a.internal.Update(update); err != nil {
		return 0, fmt.Errorf("failed to update task: %w", err)
	}

	updatedTask, err := a.internal.Get(string(task.ID))
	if err != nil {
		return 0, fmt.Errorf("failed to get updated task: %w", err)
	}

	version := a2alib.TaskVersion(updatedTask.UpdatedAt.UnixNano())
	return version, nil
}

// Get calls internal.Get and translates types.Envelope to a2a.Task.
// For completed and paused tasks, it attempts to hydrate history and artifacts
// from the state proxy mount. Hydration failures are logged and silently ignored —
// history and artifacts are optional per the A2A spec.
func (a *StoreAdapter) Get(ctx context.Context, taskID a2alib.TaskID) (*a2alib.Task, a2alib.TaskVersion, error) {
	envelope, err := a.internal.Get(string(taskID))
	if err != nil {
		if err == envelopestore.ErrNotFound || strings.Contains(err.Error(), "envelope not found") {
			return nil, 0, a2alib.ErrTaskNotFound
		}
		return nil, 0, fmt.Errorf("failed to get envelope: %w", err)
	}

	a2aTask := internalToA2ATask(envelope)
	version := a2alib.TaskVersion(envelope.UpdatedAt.UnixNano())

	// Hydrate history and artifacts from the state proxy for terminal/paused envelopes.
	// In-flight envelopes (pending/running) are skipped — history is not available from queues.
	if a.stateProxy != nil {
		a.hydrateFromStateProxy(ctx, envelope, a2aTask)
	}

	// Synthesize an artifact from the DB result for succeeded tasks when no
	// state-proxy artifacts were hydrated. The sidecar stores the final payload
	// in envelope.Result via POST /mesh/{id}/final; this exposes it per A2A spec.
	if len(a2aTask.Artifacts) == 0 && envelope.Result != nil && envelope.Status == types.EnvelopeStatusSucceeded {
		if artifact := resultToArtifact(envelope.Result); artifact != nil {
			a2aTask.Artifacts = []*a2alib.Artifact{artifact}
		}
	}

	return a2aTask, version, nil
}

// hydrateFromStateProxy reads the persisted envelope from the state proxy and populates
// History and Artifacts on a2aTask. Errors are logged and swallowed — both fields are
// optional per the A2A spec, so callers always get a valid (possibly partial) task.
func (a *StoreAdapter) hydrateFromStateProxy(ctx context.Context, envelope *types.Envelope, a2aTask *a2alib.Task) {
	prefix := stateProxyPrefix(envelope.Status)
	if prefix == "" {
		return // in-flight task; history not available from queues
	}

	payload, err := a.stateProxy.ReadPayload(ctx, prefix, envelope.ID)
	if err != nil {
		slog.Warn("State proxy read failed; omitting history/artifacts",
			"task_id", envelope.ID, "prefix", prefix, "error", err)
		return
	}
	if payload == nil {
		return // file not persisted yet or wrong prefix; silently omit
	}

	history, artifacts := extractA2ATaskData(payload)
	if len(history) > 0 {
		a2aTask.History = history
	}
	if len(artifacts) > 0 {
		a2aTask.Artifacts = artifacts
	}
}

// stateProxyPrefix maps internal task status to the filesystem prefix used by crew actors.
// Returns "" for in-flight statuses (pending/running) where history is not available.
func stateProxyPrefix(status types.EnvelopeStatus) string {
	switch status {
	case types.EnvelopeStatusSucceeded:
		return "succeeded"
	case types.EnvelopeStatusFailed:
		return "failed"
	case types.EnvelopeStatusPaused:
		return "paused"
	default:
		return "" // pending, running, canceled, etc.
	}
}

// extractA2ATaskData parses payload.a2a.task.{history,artifacts} from a persisted envelope payload.
// Both fields are optional; missing or malformed values are silently skipped.
func extractA2ATaskData(payload map[string]any) ([]*a2alib.Message, []*a2alib.Artifact) {
	a2aRaw, ok := payload["a2a"]
	if !ok {
		return nil, nil
	}
	a2aMap, ok := a2aRaw.(map[string]any)
	if !ok {
		return nil, nil
	}
	taskRaw, ok := a2aMap["task"]
	if !ok {
		return nil, nil
	}
	taskMap, ok := taskRaw.(map[string]any)
	if !ok {
		return nil, nil
	}

	history := parseMessages(taskMap["history"])
	artifacts := parseArtifacts(taskMap["artifacts"])
	return history, artifacts
}

// parseMessages decodes a raw JSON value into a slice of A2A Messages.
func parseMessages(raw any) []*a2alib.Message {
	if raw == nil {
		return nil
	}
	data, err := json.Marshal(raw)
	if err != nil {
		return nil
	}
	var msgs []*a2alib.Message
	if err := json.Unmarshal(data, &msgs); err != nil {
		return nil
	}
	return msgs
}

// parseArtifacts decodes a raw JSON value into a slice of A2A Artifacts.
func parseArtifacts(raw any) []*a2alib.Artifact {
	if raw == nil {
		return nil
	}
	data, err := json.Marshal(raw)
	if err != nil {
		return nil
	}
	var arts []*a2alib.Artifact
	if err := json.Unmarshal(data, &arts); err != nil {
		return nil
	}
	return arts
}

// resultToArtifact converts an envelope Result to an A2A Artifact with JSON-serialized content.
// Returns nil if serialization fails. Used as fallback when state-proxy artifacts are not available.
func resultToArtifact(result any) *a2alib.Artifact {
	data, err := json.Marshal(result)
	if err != nil {
		slog.Warn("Failed to marshal result for artifact", "error", err)
		return nil
	}
	return &a2alib.Artifact{
		ID:   "result",
		Name: "Task result",
		Parts: a2alib.ContentParts{
			&a2alib.TextPart{Text: string(data)},
		},
	}
}

// List translates status filter, calls internal.List with pagination, and converts results.
func (a *StoreAdapter) List(ctx context.Context, req *a2alib.ListTasksRequest) (*a2alib.ListTasksResponse, error) {
	// Clamp PageSize to 1-100, default 50
	pageSize := req.PageSize
	if pageSize <= 0 {
		pageSize = 50
	}
	if pageSize > 100 {
		pageSize = 100
	}

	// Parse PageToken as offset integer
	offset := 0
	if req.PageToken != "" {
		parsed, err := strconv.Atoi(req.PageToken)
		if err != nil || parsed < 0 {
			return nil, fmt.Errorf("invalid page_token: %q", req.PageToken)
		}
		offset = parsed
	}

	params := envelopestore.EnvelopeListParams{
		ContextID: req.ContextID,
		Limit:     pageSize,
		Offset:    offset,
	}

	if req.Status != "" {
		status := FromA2AState(req.Status)
		params.Status = &status
	}

	tasks, totalCount, err := a.internal.List(params)
	if err != nil {
		return nil, fmt.Errorf("failed to list tasks: %w", err)
	}

	a2aTasks := make([]*a2alib.Task, 0, len(tasks))
	for _, envelope := range tasks {
		a2aTasks = append(a2aTasks, internalToA2ATask(envelope))
	}

	// Calculate NextPageToken
	nextPageToken := ""
	nextOffset := offset + pageSize
	if nextOffset < totalCount {
		nextPageToken = strconv.Itoa(nextOffset)
	}

	return &a2alib.ListTasksResponse{
		Tasks:         a2aTasks,
		TotalSize:     totalCount,
		PageSize:      pageSize,
		NextPageToken: nextPageToken,
	}, nil
}

// internalToA2ATask converts an internal types.Envelope to a2a.Task.
func internalToA2ATask(envelope *types.Envelope) *a2alib.Task {
	a2aTask := &a2alib.Task{
		ID:        a2alib.TaskID(envelope.ID),
		ContextID: envelope.ContextID,
		Status: a2alib.TaskStatus{
			State: ToA2AState(envelope.Status),
		},
		Metadata: make(map[string]any),
	}

	if envelope.Message != "" {
		timestamp := envelope.UpdatedAt
		msg := a2alib.NewMessage(a2alib.MessageRoleAgent, &a2alib.TextPart{Text: envelope.Message})
		msg.TaskID = a2alib.TaskID(envelope.ID)
		msg.ContextID = envelope.ContextID
		a2aTask.Status.Message = msg
		a2aTask.Status.Timestamp = &timestamp
	}

	return a2aTask
}
