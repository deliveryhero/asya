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
	"github.com/deliveryhero/asya/asya-gateway/internal/stateproxy"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// StoreAdapter wraps the internal TaskStore to implement a2asrv.TaskStore.
type StoreAdapter struct {
	internal   taskstore.TaskStore
	stateProxy stateproxy.Reader // optional; nil means history/artifacts are always omitted
}

// NewStoreAdapter creates a new StoreAdapter wrapping the provided internal store.
// stateProxy may be nil, in which case GetTask responses omit history and artifacts.
func NewStoreAdapter(store taskstore.TaskStore, sp stateproxy.Reader) *StoreAdapter {
	return &StoreAdapter{
		internal:   store,
		stateProxy: sp,
	}
}

// Save translates a2a.Task state change to internal TaskUpdate and calls internal.Update.
func (a *StoreAdapter) Save(ctx context.Context, task *a2alib.Task, event a2alib.Event, prev a2alib.TaskVersion) (a2alib.TaskVersion, error) {
	status := FromA2AState(task.Status.State)

	update := types.TaskUpdate{
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

// Get calls internal.Get and translates types.Task to a2a.Task.
// For completed and paused tasks, it attempts to hydrate history and artifacts
// from the state proxy mount. Hydration failures are logged and silently ignored —
// history and artifacts are optional per the A2A spec.
func (a *StoreAdapter) Get(ctx context.Context, taskID a2alib.TaskID) (*a2alib.Task, a2alib.TaskVersion, error) {
	task, err := a.internal.Get(string(taskID))
	if err != nil {
		if err == taskstore.ErrNotFound || strings.Contains(err.Error(), "task not found") {
			return nil, 0, a2alib.ErrTaskNotFound
		}
		return nil, 0, fmt.Errorf("failed to get task: %w", err)
	}

	a2aTask := internalToA2ATask(task)
	version := a2alib.TaskVersion(task.UpdatedAt.UnixNano())

	// Hydrate history and artifacts from the state proxy for terminal/paused tasks.
	// In-flight tasks (pending/running) are skipped — history is not available from queues.
	if a.stateProxy != nil {
		a.hydrateFromStateProxy(ctx, task, a2aTask)
	}

	return a2aTask, version, nil
}

// hydrateFromStateProxy reads the persisted envelope from the state proxy and populates
// History and Artifacts on a2aTask. Errors are logged and swallowed — both fields are
// optional per the A2A spec, so callers always get a valid (possibly partial) task.
func (a *StoreAdapter) hydrateFromStateProxy(ctx context.Context, task *types.Task, a2aTask *a2alib.Task) {
	prefix := stateProxyPrefix(task.Status)
	if prefix == "" {
		return // in-flight task; history not available from queues
	}

	payload, err := a.stateProxy.ReadPayload(ctx, prefix, task.ID)
	if err != nil {
		slog.Warn("State proxy read failed; omitting history/artifacts",
			"task_id", task.ID, "prefix", prefix, "error", err)
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
func stateProxyPrefix(status types.TaskStatus) string {
	switch status {
	case types.TaskStatusSucceeded:
		return "succeeded"
	case types.TaskStatusFailed:
		return "failed"
	case types.TaskStatusPaused:
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

	params := taskstore.ListParams{
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
	for _, task := range tasks {
		a2aTasks = append(a2aTasks, internalToA2ATask(task))
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

// internalToA2ATask converts an internal types.Task to a2a.Task.
func internalToA2ATask(task *types.Task) *a2alib.Task {
	a2aTask := &a2alib.Task{
		ID:        a2alib.TaskID(task.ID),
		ContextID: task.ContextID,
		Status: a2alib.TaskStatus{
			State: ToA2AState(task.Status),
		},
		Metadata: make(map[string]any),
	}

	if task.Message != "" {
		timestamp := task.UpdatedAt
		msg := a2alib.NewMessage(a2alib.MessageRoleAgent, &a2alib.TextPart{Text: task.Message})
		msg.TaskID = a2alib.TaskID(task.ID)
		msg.ContextID = task.ContextID
		a2aTask.Status.Message = msg
		a2aTask.Status.Timestamp = &timestamp
	}

	return a2aTask
}
