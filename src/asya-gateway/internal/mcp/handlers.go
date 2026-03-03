package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"regexp"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2a"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/mark3labs/mcp-go/mcp"
)

var (
	meshPathRegex         = regexp.MustCompile(`^/mesh/([^/]+)$`)
	meshStreamPathRegex   = regexp.MustCompile(`^/mesh/([^/]+)/stream$`)
	meshActivePathRegex   = regexp.MustCompile(`^/mesh/([^/]+)/active$`)
	meshProgressPathRegex = regexp.MustCompile(`^/mesh/([^/]+)/progress$`)
	meshFinalPathRegex    = regexp.MustCompile(`^/mesh/([^/]+)/final$`)
	meshFlyPathRegex      = regexp.MustCompile(`^/mesh/([^/]+)/fly$`)
)

// Handler provides HTTP endpoints for task management
// MCP endpoints are now handled directly by mark3labs/mcp-go server
type Handler struct {
	taskStore taskstore.TaskStore
	server    *Server // For direct tool calls
}

// NewHandler creates a new HTTP handler for task management
func NewHandler(taskStore taskstore.TaskStore) *Handler {
	return &Handler{
		taskStore: taskStore,
	}
}

// SetServer sets the MCP server for direct tool calls
func (h *Handler) SetServer(server *Server) {
	h.server = server
}

// HandleToolCall handles POST /tools/call (REST endpoint for MCP tool calls)
// This provides a simpler REST interface without requiring SSE session management
func (h *Handler) HandleToolCall(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse request body
	var req struct {
		Name      string         `json:"name"`
		Arguments map[string]any `json:"arguments"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if req.Name == "" {
		http.Error(w, "Tool name is required", http.StatusBadRequest)
		return
	}

	// Create MCP CallToolRequest
	mcpReq := mcp.CallToolRequest{
		Params: mcp.CallToolParams{
			Name:      req.Name,
			Arguments: req.Arguments,
		},
	}

	// Get the tool handler from registry
	if h.server == nil || h.server.registry == nil {
		http.Error(w, "MCP server not initialized", http.StatusInternalServerError)
		return
	}

	handler := h.server.registry.GetToolHandler(req.Name)
	if handler == nil {
		http.Error(w, fmt.Sprintf("Tool %q not found", req.Name), http.StatusNotFound)
		return
	}

	// Call the tool handler
	result, err := handler(context.Background(), mcpReq)
	if err != nil {
		slog.Error("Tool call failed", "error", err)
		http.Error(w, fmt.Sprintf("Tool call failed: %v", err), http.StatusInternalServerError)
		return
	}

	// Return the result
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(result); err != nil {
		slog.Error("Failed to encode result", "error", err)
	}
}

// HandleMeshCreate handles POST /tasks (for sidecars to create fanout child tasks)
func (h *Handler) HandleMeshCreate(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse create request
	var createReq types.CreateTaskRequest

	if err := json.NewDecoder(r.Body).Decode(&createReq); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if createReq.ID == "" {
		http.Error(w, "Missing required field: id", http.StatusBadRequest)
		return
	}

	slog.Info("Creating fanout task", "id", createReq.ID, "parent_id", createReq.ParentID)

	totalActors := len(createReq.Prev) + len(createReq.Next)
	if createReq.Curr != "" {
		totalActors++
	}

	// Create minimal task for fanout child
	task := &types.Task{
		ID:       createReq.ID,
		ParentID: createReq.ParentID,
		Status:   types.TaskStatusPending,
		Route: types.Route{
			Prev: createReq.Prev,
			Curr: createReq.Curr,
			Next: createReq.Next,
		},
		ProgressPercent: 0.0,
		TotalActors:     totalActors,
		ActorsCompleted: len(createReq.Prev),
	}

	if err := h.taskStore.Create(task); err != nil {
		slog.Error("Failed to create fanout task", "id", createReq.ID, "error", err)
		http.Error(w, "Failed to create task", http.StatusInternalServerError)
		return
	}

	slog.Info("Fanout task created successfully", "id", createReq.ID)

	// Send fanout task to queue (async)
	go func() {
		// Update status to Running
		_ = h.taskStore.Update(types.TaskUpdate{
			ID:        createReq.ID,
			Status:    types.TaskStatusRunning,
			Message:   "Sending task to first actor",
			Timestamp: time.Now(),
		})

		// Skip sending to queue if server is not configured
		if h.server == nil || h.server.queueClient == nil {
			slog.Warn("Queue client not configured, skipping task send", "id", createReq.ID)
			return
		}

		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()

		if err := h.server.queueClient.SendMessage(ctx, task); err != nil {
			slog.Error("Failed to send fanout task to queue", "id", createReq.ID, "error", err)
			_ = h.taskStore.Update(types.TaskUpdate{
				ID:        createReq.ID,
				Status:    types.TaskStatusFailed,
				Error:     fmt.Sprintf("failed to send task: %v", err),
				Timestamp: time.Now(),
			})
			return
		}
	}()

	w.WriteHeader(http.StatusCreated)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "created", "id": createReq.ID})
}

// HandleMeshStatus handles GET /tasks/{id}
func (h *Handler) HandleMeshStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := meshPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid task path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

	task, err := h.taskStore.Get(taskID)
	if err != nil {
		http.Error(w, "Task not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(task); err != nil {
		slog.Error("Failed to encode task", "error", err)
	}
}

// HandleMeshStream handles GET /mesh/{id}/stream (SSE)
func (h *Handler) HandleMeshStream(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := meshStreamPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid task stream path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

	// Verify task exists
	_, err := h.taskStore.Get(taskID)
	if err != nil {
		http.Error(w, "Task not found", http.StatusNotFound)
		return
	}

	// Set SSE headers
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming not supported", http.StatusInternalServerError)
		return
	}

	sse := newSSEWriter(w, flusher)

	// Send historical updates first (to avoid missing early progress updates)
	historicalUpdates, err := h.taskStore.GetUpdates(taskID, nil)
	if err != nil {
		slog.Warn("Failed to get historical updates", "error", err, "task_id", taskID)
	} else {
		for _, update := range historicalUpdates {
			sse.writeEvent(update)
		}
	}

	// Subscribe to updates
	updateChan := h.taskStore.Subscribe(taskID)
	defer h.taskStore.Unsubscribe(taskID, updateChan)

	// Send keepalive comments every 15 seconds to prevent connection timeout
	keepaliveTicker := time.NewTicker(15 * time.Second)
	defer keepaliveTicker.Stop()

	// Stream updates until task completes or client disconnects
	for {
		select {
		case <-r.Context().Done():
			return
		case <-keepaliveTicker.C:
			sse.writeKeepalive()
		case update := <-updateChan:
			sse.writeEvent(update)

			if isFinalStatus(update.Status) {
				flusher.Flush()
				return
			}
		}
	}
}

// sseWriter wraps an io.Writer for SSE event formatting.
// Typed as io.Writer (not http.ResponseWriter) because SSE streams use
// Content-Type text/event-stream — HTML escaping would corrupt the protocol.
type sseWriter struct {
	w       io.Writer
	flusher http.Flusher
}

func newSSEWriter(w io.Writer, flusher http.Flusher) *sseWriter {
	return &sseWriter{w: w, flusher: flusher}
}

func (s *sseWriter) writeKeepalive() {
	_, _ = io.WriteString(s.w, ": keepalive\n\n")
	s.flusher.Flush()
}

func (s *sseWriter) writeEvent(update types.TaskUpdate) {
	if update.PartialPayload != nil {
		var payload map[string]any
		eventType := "partial"
		if json.Unmarshal(update.PartialPayload, &payload) == nil {
			eventType = a2a.DetectFLYEventType(payload)
		}
		_, _ = io.WriteString(s.w, "event: "+eventType+"\ndata: "+string(update.PartialPayload)+"\n\n") // #nosec G203 -- SSE text/event-stream, not HTML
	} else {
		data, err := json.Marshal(update)
		if err != nil {
			slog.Error("Failed to marshal SSE update", "error", err)
			return
		}
		_, _ = io.WriteString(s.w, "event: update\ndata: "+string(data)+"\n\n") // #nosec G203 -- SSE text/event-stream, not HTML
	}
	s.flusher.Flush()
}

// isFinalStatus checks if a status is final (Succeeded, Failed, or Canceled)
func isFinalStatus(status types.TaskStatus) bool {
	return status == types.TaskStatusSucceeded ||
		status == types.TaskStatusFailed ||
		status == types.TaskStatusCanceled
}

// HandleMeshActive handles GET /mesh/{id}/active (for actors to check if task is still valid)
func (h *Handler) HandleMeshActive(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := meshActivePathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid task active path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

	// Check if task is active
	if h.taskStore.IsActive(taskID) {
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]bool{"active": true})
	} else {
		w.WriteHeader(http.StatusGone) // 410 Gone - task timed out or completed
		_ = json.NewEncoder(w).Encode(map[string]bool{"active": false})
	}
}

// calculateProgress calculates progress percentage from prev/curr/next and status.
// statusWeight: received=0.1, processing=0.5, completed=1.0
// Formula: (len(prev) + statusWeight) * 100 / total
func calculateProgress(prev []string, next []string, statusWeight float64) float64 {
	total := len(prev) + 1 + len(next)
	if total == 0 {
		return 0.0
	}
	progress := (float64(len(prev)) + statusWeight) * 100.0 / float64(total)
	if progress > 100.0 {
		return 100.0
	}
	return progress
}

// HandleMeshProgress handles POST /mesh/{id}/progress (for actors to report progress)
func (h *Handler) HandleMeshProgress(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := meshProgressPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid task progress path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

	// Parse progress update
	var progress types.ProgressUpdate
	if err := json.NewDecoder(r.Body).Decode(&progress); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	progress.ID = taskID

	slog.Debug("Received progress update from actor",
		"task_id", taskID,
		"status", progress.Status,
		"curr", progress.Curr,
		"prev_count", len(progress.Prev),
		"next_count", len(progress.Next))

	// Calculate progress percentage based on status weight.
	// statusWeight: received=0.1, processing=0.5, completed=1.0
	var statusWeight float64
	switch progress.Status {
	case "received":
		statusWeight = 0.1
	case "processing":
		statusWeight = 0.5
	case "completed":
		statusWeight = 1.0
	default:
		statusWeight = 0.0
	}

	// Fetch task to enforce monotonic progress
	task, err := h.taskStore.Get(taskID)
	if err != nil {
		if errors.Is(err, taskstore.ErrNotFound) {
			slog.Debug("Task not found for progress update, skipping", "id", taskID)
			w.WriteHeader(http.StatusOK)
		} else {
			slog.Error("Failed to get task for progress calculation", "id", taskID, "error", err)
			http.Error(w, "Failed to get task", http.StatusInternalServerError)
		}
		return
	}

	// Calculate new progress
	var newProgress float64
	if progress.Curr == "" && len(progress.Next) == 0 {
		// End-of-route: full completion
		newProgress = 100.0
	} else {
		newProgress = calculateProgress(progress.Prev, progress.Next, statusWeight)
	}

	// Enforce monotonic progress: never decrease
	if newProgress < task.ProgressPercent {
		slog.Debug("Skipping non-monotonic progress update",
			"id", taskID,
			"current", task.ProgressPercent,
			"new", newProgress,
			"curr", progress.Curr,
			"status", progress.Status)
		newProgress = task.ProgressPercent
	} else {
		slog.Debug("Calculated progress",
			"id", taskID,
			"curr", progress.Curr,
			"status", progress.Status,
			"percent", newProgress)
	}

	// Ensure progress doesn't exceed 100%
	if newProgress > 100 {
		newProgress = 100
	}

	// Transform ProgressUpdate (external API from sidecar) into TaskUpdate (internal event).
	// This transformation:
	// - Sets task-level status to Running (or Paused if PauseMetadata present)
	// - Copies task processing state ("received", "processing", "completed")
	// - Copies route information (Prev/Curr/Next) to persist modifications
	// - Adds calculated progress percentage and timestamp
	taskState := string(progress.Status)
	update := types.TaskUpdate{
		ID:              taskID,
		Status:          types.TaskStatusRunning,
		Message:         progress.Message,
		ProgressPercent: &newProgress,
		Prev:            progress.Prev,
		Curr:            progress.Curr,
		Next:            progress.Next,
		TaskState:       &taskState,
		Timestamp:       time.Now(),
	}

	// If pause metadata is present, transition to paused state instead of running.
	// The sidecar sends this when it detects the x-asya-pause header from the runtime.
	if progress.PauseMetadata != nil {
		update.Status = types.TaskStatusPaused
		update.PauseMetadata = progress.PauseMetadata
		slog.Info("Task paused via x-asya-pause header",
			"task_id", taskID,
			"curr", progress.Curr)
	}

	// Update task store (using UpdateProgress for lighter weight update)
	if err := h.taskStore.UpdateProgress(update); err != nil {
		slog.Error("Failed to update task progress", "error", err)
		http.Error(w, "Failed to update progress", http.StatusInternalServerError)
		return
	}

	slog.Debug("Progress update stored",
		"task_id", taskID,
		"status", progress.Status,
		"curr", progress.Curr,
		"progress_percent", newProgress)

	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"status":           "ok",
		"progress_percent": newProgress,
	})
}

// HandleMeshFinal handles POST /mesh/{id}/final (for end actors to report final status)
// This is called by x-sink and x-sump actors to report task completion
func (h *Handler) HandleMeshFinal(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := meshFinalPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid task final path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

	// Parse final status update
	var finalUpdate struct {
		ID               string                 `json:"id"`
		Status           string                 `json:"status"`
		Progress         *float64               `json:"progress"`
		Result           interface{}            `json:"result"`
		Error            string                 `json:"error"`
		ErrorDetails     interface{}            `json:"error_details"`
		Metadata         map[string]interface{} `json:"metadata"`
		CurrentActorName string                 `json:"current_actor_name"`
		Timestamp        string                 `json:"timestamp"`
	}

	if err := json.NewDecoder(r.Body).Decode(&finalUpdate); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	// Determine task status from final update
	var taskStatus types.TaskStatus
	switch finalUpdate.Status {
	case "succeeded":
		taskStatus = types.TaskStatusSucceeded
	case "failed":
		taskStatus = types.TaskStatusFailed
	default:
		slog.Error("Invalid final status", "id", taskID, "status", finalUpdate.Status)
		http.Error(w, "Invalid status: must be 'succeeded' or 'failed'", http.StatusBadRequest)
		return
	}

	slog.Info("Received final status from end actor",
		"id", taskID,
		"status", taskStatus,
		"hasResult", finalUpdate.Result != nil,
		"hasError", finalUpdate.Error != "",
		"currentActor", finalUpdate.CurrentActorName)

	// Create task update
	progressPercent := 100.0
	update := types.TaskUpdate{
		ID:              taskID,
		Status:          taskStatus,
		Result:          finalUpdate.Result,
		ProgressPercent: &progressPercent,
		Timestamp:       time.Now(),
	}

	// Set actor information
	if finalUpdate.CurrentActorName != "" {
		update.Actor = finalUpdate.CurrentActorName
		update.Curr = finalUpdate.CurrentActorName
	}

	// Set message and error based on status
	if taskStatus == types.TaskStatusSucceeded {
		update.Message = "Task completed successfully"
		if finalUpdate.Metadata != nil {
			if s3URI, ok := finalUpdate.Metadata["s3_uri"].(string); ok {
				update.Message = fmt.Sprintf("Task completed successfully, results stored at %s", s3URI)
			}
		}
	} else {
		update.Message = "Task failed"
		if finalUpdate.Error != "" {
			update.Error = finalUpdate.Error
			if finalUpdate.CurrentActorName != "" {
				update.Message = fmt.Sprintf("Task failed at actor '%s': %s", finalUpdate.CurrentActorName, finalUpdate.Error)
			} else {
				update.Message = fmt.Sprintf("Task failed: %s", finalUpdate.Error)
			}
		}
		// Include error details in the result field for queryability
		if finalUpdate.ErrorDetails != nil {
			errorInfo := map[string]interface{}{
				"error":   finalUpdate.Error,
				"details": finalUpdate.ErrorDetails,
			}
			if finalUpdate.CurrentActorName != "" {
				errorInfo["failed_actor"] = finalUpdate.CurrentActorName
			}
			update.Result = errorInfo
		}
	}

	slog.Debug("Updating task with final status",
		"id", taskID,
		"status", taskStatus,
		"message", update.Message)

	// Update task store
	if err := h.taskStore.Update(update); err != nil {
		slog.Error("Failed to update task with final status", "id", taskID, "error", err)
		http.Error(w, "Failed to update task", http.StatusInternalServerError)
		return
	}

	slog.Info("Task final status updated successfully",
		"id", taskID,
		"status", taskStatus)

	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

// HandleMeshFly handles POST /mesh/{id}/fly (for sidecar to forward FLY events)
// FLY events are incremental results (e.g., LLM tokens) from generator handlers.
// They bypass message queues and are forwarded directly to SSE clients.
func (h *Handler) HandleMeshFly(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := meshFlyPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid task fly path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

	// Limit request body size to prevent resource exhaustion (1MB)
	r.Body = http.MaxBytesReader(w, r.Body, 1024*1024)

	// Read raw payload body
	body, err := io.ReadAll(r.Body)
	if err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			http.Error(w, "Request body too large", http.StatusRequestEntityTooLarge)
		} else {
			http.Error(w, "Failed to read request body", http.StatusBadRequest)
		}
		return
	}

	// Create a TaskUpdate with PartialPayload for SSE broadcasting
	update := types.TaskUpdate{
		ID:             taskID,
		Status:         types.TaskStatusRunning,
		PartialPayload: json.RawMessage(body),
		Timestamp:      time.Now(),
	}

	// Store and broadcast to SSE subscribers
	if err := h.taskStore.UpdateProgress(update); err != nil {
		slog.Error("Failed to store FLY event", "task_id", taskID, "error", err)
		http.Error(w, "Failed to store FLY event", http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusOK)
}
