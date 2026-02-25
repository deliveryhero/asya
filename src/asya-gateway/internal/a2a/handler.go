package a2a

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Handler handles A2A JSON-RPC requests at POST /a2a/
type Handler struct {
	taskStore   taskstore.TaskStore
	queueClient queue.Client
	config      *config.Config
	toolIndex   map[string]*config.Tool // tool name -> tool def
}

// NewHandler creates a new A2A handler.
func NewHandler(store taskstore.TaskStore, queueClient queue.Client, cfg *config.Config) *Handler {
	idx := make(map[string]*config.Tool)
	if cfg != nil {
		for i := range cfg.Tools {
			idx[cfg.Tools[i].Name] = &cfg.Tools[i]
		}
	}
	return &Handler{
		taskStore:   store,
		queueClient: queueClient,
		config:      cfg,
		toolIndex:   idx,
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var rpcReq types.A2AJSONRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&rpcReq); err != nil {
		h.writeJSON(w, types.NewA2AError(nil, types.A2AErrParseError, "invalid JSON"))
		return
	}

	switch rpcReq.Method {
	case "message/send":
		h.handleMessageSend(w, rpcReq)
	case "message/stream":
		h.handleMessageStream(w, r, rpcReq)
	case "tasks/get":
		h.handleTasksGet(w, rpcReq)
	default:
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrMethodNotFound,
			fmt.Sprintf("method %q not found", rpcReq.Method)))
	}
}

func (h *Handler) handleMessageSend(w http.ResponseWriter, rpcReq types.A2AJSONRPCRequest) {
	params, err := h.parseMessageParams(rpcReq)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams, err.Error()))
		return
	}

	// Resolve skill (tool)
	tool, ok := h.toolIndex[params.Skill]
	if !ok {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams,
			fmt.Sprintf("skill %q not found", params.Skill)))
		return
	}

	// Resolve route actors
	actors, err := tool.Route.GetActors(h.config.Routes)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInternalError,
			fmt.Sprintf("route error: %v", err)))
		return
	}

	// Translate A2A message to payload
	payload := MessageToPayload(params.Message)

	// Determine context_id
	contextID := params.ContextID
	if contextID == "" {
		contextID = uuid.New().String()
	}

	// Create task
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
		ID:        taskID,
		ContextID: contextID,
		Status:    types.TaskStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: routeCurr,
			Next: routeNext,
		},
		Payload:    payload,
		TimeoutSec: int(opts.Timeout.Seconds()),
	}

	if opts.Timeout > 0 {
		task.Deadline = time.Now().Add(opts.Timeout)
	}

	if err := h.taskStore.Create(task); err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInternalError,
			fmt.Sprintf("failed to create task: %v", err)))
		return
	}

	// Send to queue async
	go h.sendToQueue(task)

	// Return A2A Task response
	a2aTask := TaskToA2ATask(task)
	h.writeJSON(w, types.NewA2AResult(rpcReq.ID, a2aTask))
}

func (h *Handler) sendToQueue(task *types.Task) {
	_ = h.taskStore.Update(types.TaskUpdate{
		ID:        task.ID,
		Status:    types.TaskStatusRunning,
		Message:   "Sending task to first actor",
		Timestamp: time.Now(),
	})

	if h.queueClient == nil {
		slog.Warn("Queue client not configured, skipping task send", "id", task.ID)
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := h.queueClient.SendMessage(ctx, task); err != nil {
		slog.Error("Failed to send task to queue", "id", task.ID, "error", err)
		_ = h.taskStore.Update(types.TaskUpdate{
			ID:        task.ID,
			Status:    types.TaskStatusFailed,
			Error:     fmt.Sprintf("failed to send task: %v", err),
			Timestamp: time.Now(),
		})
	}
}

func (h *Handler) handleTasksGet(w http.ResponseWriter, rpcReq types.A2AJSONRPCRequest) {
	// Parse params to get task ID
	paramsBytes, err := json.Marshal(rpcReq.Params)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams, "invalid params"))
		return
	}
	var params struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(paramsBytes, &params); err != nil || params.ID == "" {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams, "missing task id"))
		return
	}

	task, err := h.taskStore.Get(params.ID)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrTaskNotFound,
			fmt.Sprintf("task %q not found", params.ID)))
		return
	}

	a2aTask := TaskToA2ATask(task)
	h.writeJSON(w, types.NewA2AResult(rpcReq.ID, a2aTask))
}

func (h *Handler) parseMessageParams(rpcReq types.A2AJSONRPCRequest) (*types.A2ASendMessageParams, error) {
	paramsBytes, err := json.Marshal(rpcReq.Params)
	if err != nil {
		return nil, fmt.Errorf("invalid params: %w", err)
	}

	var params types.A2ASendMessageParams
	if err := json.Unmarshal(paramsBytes, &params); err != nil {
		return nil, fmt.Errorf("invalid message params: %w", err)
	}

	if len(params.Message.Parts) == 0 {
		return nil, fmt.Errorf("message must have at least one part")
	}

	if params.Skill == "" {
		return nil, fmt.Errorf("skill is required")
	}

	return &params, nil
}

func (h *Handler) writeJSON(w http.ResponseWriter, resp *types.A2AJSONRPCResponse) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		slog.Error("Failed to encode A2A response", "error", err)
	}
}
