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

// dbPollInterval is how often waitAndRelayEvents polls the DB to detect
// cross-process status updates (e.g., mesh gateway writing task final status).
const dbPollInterval = 500 * time.Millisecond

// waitAndRelayEvents subscribes to task store updates and relays them as
// a2a events to the event queue. It blocks until the task reaches a terminal
// or interrupted state, the timeout expires, or the context is canceled.
//
// In dual-gateway mode (api + mesh pods), the mesh gateway writes final task
// status to the DB in a separate process. Since the in-process subscription
// channel only fires for updates within the same process, we also poll the DB
// at dbPollInterval to detect cross-process status changes.
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

	// Subscribe to in-process terminal state changes (e.g., the in-memory timeout
	// timer calling Update(failed) → notifyListeners). Only terminal/interrupted
	// statuses from the subscription channel are forwarded to the event queue.
	//
	// Non-terminal updates are intentionally dropped here to prevent a feedback
	// loop: forwarding a non-terminal update calls eq.Write(), which triggers
	// StoreAdapter.Save() → internal.Update() → notifyListeners() → ch receives
	// the same update again, overwriting the tasks table ~100x/second and
	// preventing the mesh gateway's succeeded write from persisting.
	//
	// Cross-process terminal state changes (mesh gateway writing succeeded/failed)
	// are detected by the DB poll below, which is the authoritative source.
	ch := store.Subscribe(taskID)
	defer store.Unsubscribe(taskID, ch)

	// Poll the DB to catch cross-process updates (mesh gateway writes).
	pollTicker := time.NewTicker(dbPollInterval)
	defer pollTicker.Stop()

	timer := time.NewTimer(timeout)
	defer timer.Stop()

	for {
		select {
		case update, ok := <-ch:
			if !ok {
				// Channel closed — subscription ended
				return nil
			}

			if terminalOrInterrupted(update.Status) {
				slog.Debug("Blocking wait: terminal event relayed via subscription",
					"task_id", taskID, "status", update.Status)
				return writeTerminalEvent(ctx, reqCtx, eq, update.Status)
			}
			// Non-terminal updates are dropped — see comment above.

		case <-pollTicker.C:
			current, pollErr := store.Get(taskID)
			if pollErr != nil {
				slog.Warn("Blocking wait poll error", "task_id", taskID, "error", pollErr)
				continue
			}
			if terminalOrInterrupted(current.Status) {
				slog.Debug("Blocking wait: terminal status detected via DB poll",
					"task_id", taskID, "status", current.Status)
				return writeTerminalEvent(ctx, reqCtx, eq, current.Status)
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
