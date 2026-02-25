package a2a

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// SubscribeHandler handles GET /a2a/tasks/{id}:subscribe (SSE)
type SubscribeHandler struct {
	taskStore taskstore.TaskStore
}

// NewSubscribeHandler creates a new subscribe handler.
func NewSubscribeHandler(store taskstore.TaskStore) *SubscribeHandler {
	return &SubscribeHandler{taskStore: store}
}

func (sh *SubscribeHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	taskID := strings.TrimSuffix(r.PathValue("id"), ":subscribe")
	if taskID == "" {
		http.Error(w, "Invalid path", http.StatusBadRequest)
		return
	}

	// Verify task exists
	_, err := sh.taskStore.Get(taskID)
	if err != nil {
		http.Error(w, "Task not found", http.StatusNotFound)
		return
	}

	streamTaskUpdates(w, r, sh.taskStore, taskID)
}

// handleMessageStream implements the message/stream JSON-RPC method.
// It creates a task and immediately starts streaming updates via SSE.
func (h *Handler) handleMessageStream(w http.ResponseWriter, r *http.Request, rpcReq types.A2AJSONRPCRequest) {
	task, errResp := h.resolveAndCreateTask(rpcReq)
	if errResp != nil {
		h.writeJSON(w, errResp)
		return
	}
	streamTaskUpdates(w, r, h.taskStore, task.ID)
}

// streamTaskUpdates streams A2A-formatted SSE events for a task.
// Shared between message/stream and tasks/subscribe.
func streamTaskUpdates(w http.ResponseWriter, r *http.Request, store taskstore.TaskStore, taskID string) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming not supported", http.StatusInternalServerError)
		return
	}

	// Send historical updates
	historicalUpdates, err := store.GetUpdates(taskID, nil)
	if err != nil {
		slog.Warn("Failed to get historical updates", "error", err, "task_id", taskID)
	} else {
		for _, update := range historicalUpdates {
			writeSSEEvent(w, flusher, update)
		}
	}

	// Subscribe to live updates
	updateChan := store.Subscribe(taskID)
	defer store.Unsubscribe(taskID, updateChan)

	keepaliveTicker := time.NewTicker(15 * time.Second)
	defer keepaliveTicker.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-keepaliveTicker.C:
			writeSSEKeepalive(w, flusher)
		case update := <-updateChan:
			writeSSEEvent(w, flusher, update)
			if isFinalA2AStatus(update.Status) {
				flusher.Flush()
				return
			}
		}
	}
}

func writeSSEEvent(w io.Writer, flusher http.Flusher, update types.TaskUpdate) {
	a2aEvent := TaskUpdateToSSEEvents(update)

	eventType := "status_update"
	data, err := json.Marshal(a2aEvent)
	if err != nil {
		slog.Error("Failed to marshal A2A event", "error", err)
		return
	}

	_, _ = io.WriteString(w, "event: "+eventType+"\ndata: "+string(data)+"\n\n")
	flusher.Flush()
}

func writeSSEKeepalive(w io.Writer, flusher http.Flusher) {
	_, _ = io.WriteString(w, ": keepalive\n\n")
	flusher.Flush()
}

func isFinalA2AStatus(status types.TaskStatus) bool {
	return status == types.TaskStatusSucceeded || status == types.TaskStatusFailed || status == types.TaskStatusCanceled
}
