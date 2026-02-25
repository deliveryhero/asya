package a2a

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"regexp"
	"time"

	"github.com/google/uuid"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

var subscribePathRegex = regexp.MustCompile(`^/a2a/tasks/([^/]+):subscribe$`)

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

	matches := subscribePathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

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
	params, err := h.parseMessageParams(rpcReq)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams, err.Error()))
		return
	}

	tool, ok := h.toolIndex[params.Skill]
	if !ok {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams,
			fmt.Sprintf("skill %q not found", params.Skill)))
		return
	}

	actors, err := tool.Route.GetActors(h.config.Routes)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInternalError, err.Error()))
		return
	}

	payload := MessageToPayload(params.Message)
	contextID := params.ContextID
	if contextID == "" {
		contextID = uuid.New().String()
	}

	taskID := params.TaskID
	if taskID == "" {
		taskID = uuid.New().String()
	}

	var routeCurr string
	var routeNext []string
	if len(actors) > 0 {
		routeCurr = actors[0]
		routeNext = actors[1:]
	}

	opts := tool.GetOptions(h.config.Defaults)
	task := &types.Task{
		ID:         taskID,
		ContextID:  contextID,
		Route:      types.Route{Prev: []string{}, Curr: routeCurr, Next: routeNext},
		Payload:    payload,
		TimeoutSec: int(opts.Timeout.Seconds()),
	}

	if opts.Timeout > 0 {
		task.Deadline = time.Now().Add(opts.Timeout)
	}

	if err := h.taskStore.Create(task); err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInternalError, err.Error()))
		return
	}

	go h.sendToQueue(task)

	// Stream updates as SSE
	streamTaskUpdates(w, r, h.taskStore, taskID)
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
			_, _ = fmt.Fprintf(w, ": keepalive\n\n")
			flusher.Flush()
		case update := <-updateChan:
			writeSSEEvent(w, flusher, update)
			if isFinalA2AStatus(update.Status) {
				flusher.Flush()
				return
			}
		}
	}
}

func writeSSEEvent(w http.ResponseWriter, flusher http.Flusher, update types.TaskUpdate) {
	a2aEvent := TaskUpdateToSSEEvents(update)

	eventType := "status_update"
	data, err := json.Marshal(a2aEvent)
	if err != nil {
		slog.Error("Failed to marshal A2A event", "error", err)
		return
	}

	// Security: Safe to use Fprintf here - data is pre-encoded JSON for SSE streaming.
	_, _ = fmt.Fprintf(w, "event: %s\n", eventType)
	_, _ = fmt.Fprintf(w, "data: %s\n\n", data)
	flusher.Flush()
}

func isFinalA2AStatus(status types.TaskStatus) bool {
	return status == types.TaskStatusSucceeded || status == types.TaskStatusFailed
}
