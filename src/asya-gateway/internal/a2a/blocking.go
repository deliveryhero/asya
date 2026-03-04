package a2a

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"
	"github.com/a2aproject/a2a-go/a2asrv/eventqueue"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// terminalOrInterrupted returns true if the status represents a terminal
// or interrupted state that should stop the blocking wait loop.
func terminalOrInterrupted(status types.TaskStatus) bool {
	switch status {
	case types.TaskStatusSucceeded, types.TaskStatusFailed, types.TaskStatusCanceled:
		return true
	case types.TaskStatusPaused, types.TaskStatusAuthRequired:
		return true
	default:
		return false
	}
}

// waitAndRelayEvents subscribes to task store updates and relays them as
// a2a events to the event queue. It blocks until the task reaches a terminal
// or interrupted state, the timeout expires, or the context is canceled.
func waitAndRelayEvents(
	ctx context.Context,
	store taskstore.TaskStore,
	taskID string,
	timeout time.Duration,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	// Check current state first — task may already be terminal if processing
	// was very fast.
	task, err := store.Get(taskID)
	if err != nil {
		return fmt.Errorf("get task for blocking wait: %w", err)
	}
	if terminalOrInterrupted(task.Status) {
		return writeTerminalEvent(ctx, reqCtx, eq, task.Status)
	}

	// Subscribe to updates
	ch := store.Subscribe(taskID)
	defer store.Unsubscribe(taskID, ch)

	timer := time.NewTimer(timeout)
	defer timer.Stop()

	for {
		select {
		case update, ok := <-ch:
			if !ok {
				// Channel closed — subscription ended
				return nil
			}

			state := ToA2AState(update.Status)
			evt := a2alib.NewStatusUpdateEvent(reqCtx, state, nil)

			if terminalOrInterrupted(update.Status) {
				evt.Final = true
				if writeErr := eq.Write(ctx, evt); writeErr != nil {
					return fmt.Errorf("write terminal event: %w", writeErr)
				}
				slog.Debug("Blocking wait: terminal event relayed",
					"task_id", taskID, "status", update.Status)
				return nil
			}

			if writeErr := eq.Write(ctx, evt); writeErr != nil {
				return fmt.Errorf("write relay event: %w", writeErr)
			}

		case <-timer.C:
			// Timeout: get current state and write as final event
			slog.Warn("Blocking wait timed out", "task_id", taskID, "timeout", timeout)
			current, getErr := store.Get(taskID)
			if getErr != nil {
				return fmt.Errorf("get task on timeout: %w", getErr)
			}
			state := ToA2AState(current.Status)
			evt := a2alib.NewStatusUpdateEvent(reqCtx, state, nil)
			evt.Final = true
			return eq.Write(ctx, evt)

		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// writeTerminalEvent writes a single final event for an already-terminal task.
func writeTerminalEvent(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
	status types.TaskStatus,
) error {
	state := ToA2AState(status)
	evt := a2alib.NewStatusUpdateEvent(reqCtx, state, nil)
	evt.Final = true
	return eq.Write(ctx, evt)
}
