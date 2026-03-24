package a2a

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"
	"github.com/a2aproject/a2a-go/a2asrv/eventqueue"

	"github.com/deliveryhero/asya/asya-gateway/internal/envelopestore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// flyArtifactID is the deterministic artifact ID used for FLY streaming chunks.
const flyArtifactID = "fly-stream"

// resultArtifactID is the artifact ID used for the final result payload.
const resultArtifactID = "result"

// convertFLYToArtifactUpdate converts a FLY event (PartialPayload) to an A2A
// TaskArtifactUpdateEvent. The first event creates the artifact (Append=false),
// subsequent events append to it (Append=true).
func convertFLYToArtifactUpdate(
	reqCtx *a2asrv.RequestContext,
	payload json.RawMessage,
	isFirst bool,
) *a2alib.TaskArtifactUpdateEvent {
	return &a2alib.TaskArtifactUpdateEvent{
		TaskID:    reqCtx.TaskID,
		ContextID: reqCtx.ContextID,
		Append:    !isFirst,
		Artifact: &a2alib.Artifact{
			ID:    a2alib.ArtifactID(flyArtifactID),
			Parts: a2alib.ContentParts{a2alib.TextPart{Text: string(payload)}},
		},
	}
}

// terminalOrInterrupted returns true if the status represents a terminal
// or interrupted state that should stop the blocking wait loop.
func terminalOrInterrupted(status types.EnvelopeStatus) bool {
	switch status {
	case types.EnvelopeStatusSucceeded, types.EnvelopeStatusFailed, types.EnvelopeStatusCanceled:
		return true
	case types.EnvelopeStatusPaused, types.EnvelopeStatusAuthRequired:
		return true
	default:
		return false
	}
}

// dbPollInterval is how often waitAndRelayEvents polls the DB as a backup
// to detect cross-process status updates. PG NOTIFY is the primary delivery
// mechanism; DB poll catches oversized events that exceed the 8KB PG NOTIFY limit.
const dbPollInterval = 2 * time.Second

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
	store envelopestore.EnvelopeStore,
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
		writeResultArtifact(ctx, reqCtx, eq, task.Status, task.Result)
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

	firstFLY := true

	// closeArtifactStream sends a LastChunk event to signal the end of the FLY
	// artifact stream. Only called if FLY events were actually sent (!firstFLY).
	closeArtifactStream := func() {
		if firstFLY {
			return
		}
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
			slog.Warn("Failed to write LastChunk artifact event", "task_id", taskID, "error", err)
		}
	}

	for {
		select {
		case update, ok := <-ch:
			if !ok {
				// Channel closed — subscription ended
				return nil
			}

			// FLY events: relay as A2A artifact chunks
			if update.PartialPayload != nil {
				evt := convertFLYToArtifactUpdate(reqCtx, update.PartialPayload, firstFLY)
				firstFLY = false
				if err := eq.Write(ctx, evt); err != nil {
					slog.Warn("Failed to relay FLY as artifact", "task_id", taskID, "error", err)
				}
				continue
			}

			if terminalOrInterrupted(update.Status) {
				closeArtifactStream()
				writeResultArtifact(ctx, reqCtx, eq, update.Status, update.Result)
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
				closeArtifactStream()
				writeResultArtifact(ctx, reqCtx, eq, current.Status, current.Result)
				slog.Debug("Blocking wait: terminal status detected via DB poll",
					"task_id", taskID, "status", current.Status)
				return writeTerminalEvent(ctx, reqCtx, eq, current.Status)
			}

		case <-timer.C:
			// Timeout: get current state and write as final event
			slog.Warn("Blocking wait timed out", "task_id", taskID, "timeout", timeout)
			closeArtifactStream()
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

// writeResultArtifact writes the final result payload as an A2A artifact event.
// Called before the terminal status event so clients receive the output.
// Only writes for succeeded tasks with non-empty results.
func writeResultArtifact(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
	status types.EnvelopeStatus,
	result any,
) {
	if status != types.EnvelopeStatusSucceeded || result == nil {
		return
	}
	if m, ok := result.(map[string]any); ok && len(m) == 0 {
		return
	}
	data, err := json.Marshal(result)
	if err != nil {
		slog.Warn("Failed to marshal result for artifact event", "error", err)
		return
	}
	evt := &a2alib.TaskArtifactUpdateEvent{
		TaskID:    reqCtx.TaskID,
		ContextID: reqCtx.ContextID,
		Append:    false,
		LastChunk: true,
		Artifact: &a2alib.Artifact{
			ID:    a2alib.ArtifactID(resultArtifactID),
			Name:  "Task result",
			Parts: a2alib.ContentParts{&a2alib.TextPart{Text: string(data)}},
		},
	}
	if err := eq.Write(ctx, evt); err != nil {
		slog.Warn("Failed to write result artifact event", "error", err)
	}
}

// writeTerminalEvent writes a single final event for an already-terminal task.
func writeTerminalEvent(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
	status types.EnvelopeStatus,
) error {
	state := ToA2AState(status)
	evt := a2alib.NewStatusUpdateEvent(reqCtx, state, nil)
	evt.Final = true
	return eq.Write(ctx, evt)
}
