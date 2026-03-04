package a2a

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"
	"github.com/a2aproject/a2a-go/a2asrv/eventqueue"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Executor implements a2asrv.AgentExecutor.
type Executor struct {
	queueClient queue.Client
	taskStore   taskstore.TaskStore
	registry    *toolstore.Registry
	namespace   string
}

func NewExecutor(
	queueClient queue.Client,
	taskStore taskstore.TaskStore,
	registry *toolstore.Registry,
	namespace string,
) *Executor {
	return &Executor{
		queueClient: queueClient,
		taskStore:   taskStore,
		registry:    registry,
		namespace:   namespace,
	}
}

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

	// Resolve skill -> entrypoint actor
	skill, err := e.resolveSkill(msg, reqCtx.Metadata)
	if err != nil {
		return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
			reqCtx, a2alib.TaskStateRejected,
			a2alib.NewMessage(a2alib.MessageRoleAgent,
				&a2alib.TextPart{Text: err.Error()})))
	}

	// Translate A2A Message -> envelope payload
	payload := MessageToPayload(msg, taskID, contextID)

	// Build internal task
	timeoutSec := 300
	if skill.TimeoutSec != nil {
		timeoutSec = *skill.TimeoutSec
	}

	task := &types.Task{
		ID:        string(taskID),
		ContextID: contextID,
		Status:    types.TaskStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: skill.Actor,
			Next: []string{},
		},
		Headers:    BuildA2AHeaders(string(taskID), contextID),
		Payload:    payload,
		TimeoutSec: timeoutSec,
		Deadline:   time.Now().Add(time.Duration(timeoutSec) * time.Second),
	}

	if err := e.taskStore.Create(task); err != nil {
		return fmt.Errorf("create task: %w", err)
	}

	// Dispatch to queue
	if e.queueClient != nil {
		if err := e.queueClient.SendMessage(ctx, task); err != nil {
			slog.Error("Failed to dispatch envelope to queue", "task_id", taskID, "error", err)
			_ = e.taskStore.Update(types.TaskUpdate{
				ID:        string(taskID),
				Status:    types.TaskStatusFailed,
				Error:     fmt.Sprintf("dispatch failed: %v", err),
				Timestamp: time.Now(),
			})
			return fmt.Errorf("dispatch: %w", err)
		}
	}

	if err := eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateSubmitted, nil)); err != nil {
		return fmt.Errorf("write submitted event: %w", err)
	}

	// Block until the task reaches a terminal/interrupted state, times out,
	// or the client disconnects (context canceled).
	return waitAndRelayEvents(
		ctx, e.taskStore, string(taskID),
		time.Duration(timeoutSec)*time.Second,
		reqCtx, eq,
	)
}

func (e *Executor) Cancel(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	taskID := reqCtx.TaskID

	// Check current state — reject if already terminal
	task, err := e.taskStore.Get(string(taskID))
	if err != nil {
		return fmt.Errorf("cancel task %q: %w", taskID, err)
	}

	switch task.Status {
	case types.TaskStatusSucceeded, types.TaskStatusFailed, types.TaskStatusCanceled:
		return a2alib.ErrTaskNotCancelable
	}

	err = e.taskStore.Update(types.TaskUpdate{
		ID:        string(taskID),
		Status:    types.TaskStatusCanceled,
		Message:   "Canceled by client",
		Timestamp: time.Now(),
	})
	if err != nil {
		return fmt.Errorf("cancel task %q: %w", taskID, err)
	}

	return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateCanceled, nil))
}

// resolveSkill determines which actor to route to.
// Priority: explicit hint -> single-skill default -> error with guidance.
func (e *Executor) resolveSkill(msg *a2alib.Message, metadata map[string]any) (*toolstore.Tool, error) {
	skills := e.registry.A2ASkills()

	// 1. Explicit skill hint in metadata
	if metadata != nil {
		if hint, ok := metadata["skill"].(string); ok && hint != "" {
			tool := e.registry.GetByName(hint)
			if tool == nil || !tool.A2AEnabled {
				return nil, fmt.Errorf("skill %q not found", hint)
			}
			return tool, nil
		}
	}

	// 2. Single skill default
	if len(skills) == 1 {
		return &skills[0], nil
	}

	// 3. No skills registered
	if len(skills) == 0 {
		return nil, fmt.Errorf("no A2A skills registered")
	}

	// 4. Multiple skills, no hint -> reject with guidance
	names := make([]string, len(skills))
	for i, s := range skills {
		names[i] = s.Name
	}
	return nil, fmt.Errorf("skill not specified. Available: %v", names)
}

// handleResume dispatches a resume envelope to x-resume for paused tasks.
func (e *Executor) handleResume(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	taskID := reqCtx.TaskID
	contextID := reqCtx.ContextID
	msg := reqCtx.Message

	payload := MessageToPayload(msg, taskID, contextID)

	task := &types.Task{
		ID:        fmt.Sprintf("resume-%s", taskID),
		ContextID: contextID,
		Status:    types.TaskStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: "x-resume",
			Next: []string{},
		},
		Headers: map[string]any{
			"x-asya-resume-task":    string(taskID),
			"x-asya-a2a-task-id":    string(taskID),
			"x-asya-a2a-context-id": contextID,
		},
		Payload: payload,
	}

	if _, err := e.taskStore.Resume(string(taskID)); err != nil {
		return fmt.Errorf("resume task %q: %w", taskID, err)
	}

	if e.queueClient != nil {
		if err := e.queueClient.SendMessage(ctx, task); err != nil {
			return fmt.Errorf("dispatch resume: %w", err)
		}
	}

	return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateWorking, nil))
}
