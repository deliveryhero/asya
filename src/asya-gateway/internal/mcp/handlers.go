package mcp

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"regexp"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/mark3labs/mcp-go/mcp"
)

var (
	envelopePathRegex         = regexp.MustCompile(`^/envelopes/([^/]+)$`)
	envelopeStreamPathRegex   = regexp.MustCompile(`^/envelopes/([^/]+)/stream$`)
	envelopeActivePathRegex   = regexp.MustCompile(`^/envelopes/([^/]+)/active$`)
	envelopeProgressPathRegex = regexp.MustCompile(`^/envelopes/([^/]+)/progress$`)
	envelopeFinalPathRegex    = regexp.MustCompile(`^/envelopes/([^/]+)/final$`)
)

// Handler provides HTTP endpoints for envelope management
// MCP endpoints are now handled directly by mark3labs/mcp-go server
type Handler struct {
	jobStore jobs.JobStore
	server   *Server // For direct tool calls
}

// NewHandler creates a new HTTP handler for envelope management
func NewHandler(jobStore jobs.JobStore) *Handler {
	return &Handler{
		jobStore: jobStore,
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

// HandleEnvelopeCreate handles POST /envelopes (for sidecars to create fanout child envelopes)
func (h *Handler) HandleEnvelopeCreate(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse create request
	var createReq struct {
		ID       string   `json:"id"`
		ParentID string   `json:"parent_id"`
		Actors   []string `json:"actors"`
		Current  int      `json:"current"`
	}

	if err := json.NewDecoder(r.Body).Decode(&createReq); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if createReq.ID == "" {
		http.Error(w, "Missing required field: id", http.StatusBadRequest)
		return
	}

	slog.Info("Creating fanout envelope", "id", createReq.ID, "parent_id", createReq.ParentID)

	// Create minimal envelope for fanout child
	envelope := &types.Envelope{
		ID:              createReq.ID,
		ParentID:        &createReq.ParentID,
		Status:          types.EnvelopeStatusPending,
		Route:           types.Route{Actors: createReq.Actors, Current: createReq.Current},
		ProgressPercent: 0.0,
		TotalActors:     len(createReq.Actors),
		ActorsCompleted: 0,
	}

	if err := h.jobStore.Create(envelope); err != nil {
		slog.Error("Failed to create fanout envelope", "id", createReq.ID, "error", err)
		http.Error(w, "Failed to create envelope", http.StatusInternalServerError)
		return
	}

	slog.Info("Fanout envelope created successfully", "id", createReq.ID)

	// Send fanout envelope to queue (async)
	go func() {
		// Update status to Running
		_ = h.jobStore.Update(types.EnvelopeUpdate{
			ID:        createReq.ID,
			Status:    types.EnvelopeStatusRunning,
			Message:   "Sending envelope to first actor",
			Timestamp: time.Now(),
		})

		// Skip sending to queue if server is not configured
		if h.server == nil || h.server.queueClient == nil {
			slog.Warn("Queue client not configured, skipping envelope send", "id", createReq.ID)
			return
		}

		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()

		if err := h.server.queueClient.SendEnvelope(ctx, envelope); err != nil {
			slog.Error("Failed to send fanout envelope to queue", "id", createReq.ID, "error", err)
			_ = h.jobStore.Update(types.EnvelopeUpdate{
				ID:        createReq.ID,
				Status:    types.EnvelopeStatusFailed,
				Error:     fmt.Sprintf("failed to send envelope: %v", err),
				Timestamp: time.Now(),
			})
			return
		}
	}()

	w.WriteHeader(http.StatusCreated)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "created", "id": createReq.ID})
}

// HandleJobStatus handles GET /envelopes/{id}
func (h *Handler) HandleEnvelopeStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := envelopePathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid envelope path", http.StatusBadRequest)
		return
	}
	envelopeID := matches[1]

	envelope, err := h.jobStore.Get(envelopeID)
	if err != nil {
		http.Error(w, "Envelope not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(envelope); err != nil {
		slog.Error("Failed to encode envelope", "error", err)
	}
}

// HandleJobStream handles GET /envelopes/{id}/stream (SSE)
func (h *Handler) HandleEnvelopeStream(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := envelopeStreamPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid envelope stream path", http.StatusBadRequest)
		return
	}
	envelopeID := matches[1]

	// Verify envelope exists
	_, err := h.jobStore.Get(envelopeID)
	if err != nil {
		http.Error(w, "Envelope not found", http.StatusNotFound)
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

	// Send historical updates first (to avoid missing early progress updates)
	historicalUpdates, err := h.jobStore.GetUpdates(envelopeID, nil)
	if err != nil {
		slog.Warn("Failed to get historical updates", "error", err, "envelope_id", envelopeID)
	} else {
		for _, update := range historicalUpdates {
			data, err := json.Marshal(update)
			if err != nil {
				slog.Error("Failed to marshal historical update", "error", err)
				continue
			}
			// Security: Safe to use Fprintf here - data is pre-encoded JSON for SSE streaming.
			// This is not HTML rendering context, so XSS concerns don't apply. The SSE
			// Content-Type is text/event-stream, and json.Marshal already escapes the data.
			_, _ = fmt.Fprintf(w, "event: update\n")
			_, _ = fmt.Fprintf(w, "data: %s\n\n", data)
			flusher.Flush()
		}
	}

	// Subscribe to updates
	updateChan := h.jobStore.Subscribe(envelopeID)
	defer h.jobStore.Unsubscribe(envelopeID, updateChan)

	// Send keepalive comments every 15 seconds to prevent connection timeout
	keepaliveTicker := time.NewTicker(15 * time.Second)
	defer keepaliveTicker.Stop()

	// Stream updates until envelope completes or client disconnects
	for {
		select {
		case <-r.Context().Done():
			return
		case <-keepaliveTicker.C:
			// Send keepalive comment to prevent proxy/client timeout
			_, _ = fmt.Fprintf(w, ": keepalive\n\n")
			flusher.Flush()
		case update := <-updateChan:
			// Send update
			data, err := json.Marshal(update)
			if err != nil {
				slog.Error("Failed to marshal update", "error", err)
				continue
			}

			// Security: Safe to use Fprintf here - data is pre-encoded JSON for SSE streaming.
			// This is not HTML rendering context, so XSS concerns don't apply. The SSE
			// Content-Type is text/event-stream, and json.Marshal already escapes the data.
			_, _ = fmt.Fprintf(w, "event: update\n")
			_, _ = fmt.Fprintf(w, "data: %s\n\n", data)
			flusher.Flush()

			// Close stream if envelope is in final state
			if isFinalStatus(update.Status) {
				// Final flush to ensure envelope is sent before closing
				flusher.Flush()
				return
			}
		}
	}
}

// isFinalStatus checks if a status is final (Succeeded or Failed)
func isFinalStatus(status types.EnvelopeStatus) bool {
	return status == types.EnvelopeStatusSucceeded ||
		status == types.EnvelopeStatusFailed
}

// HandleJobActive handles GET /envelopes/{id}/active (for actors to check if envelope is still valid)
func (h *Handler) HandleEnvelopeActive(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := envelopeActivePathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid envelope active path", http.StatusBadRequest)
		return
	}
	envelopeID := matches[1]

	// Check if envelope is active
	if h.jobStore.IsActive(envelopeID) {
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]bool{"active": true})
	} else {
		w.WriteHeader(http.StatusGone) // 410 Gone - envelope timed out or completed
		_ = json.NewEncoder(w).Encode(map[string]bool{"active": false})
	}
}

// HandleJobProgress handles POST /envelopes/{id}/progress (for actors to report progress)
func (h *Handler) HandleEnvelopeProgress(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := envelopeProgressPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid envelope progress path", http.StatusBadRequest)
		return
	}
	envelopeID := matches[1]

	// Parse progress update
	var progress types.ProgressUpdate
	if err := json.NewDecoder(r.Body).Decode(&progress); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	progress.ID = envelopeID

	slog.Debug("Received progress update from actor",
		"envelope_id", envelopeID,
		"status", progress.Status,
		"current_actor_idx", progress.CurrentActorIdx,
		"actors_count", len(progress.Actors))

	// Calculate progress percentage
	// Formula: (actorIndex * 100 + statusWeight) / totalActors
	// statusWeight: received=10, processing=50, completed=100
	var statusWeight float64
	switch progress.Status {
	case "received":
		statusWeight = 10
	case "processing":
		statusWeight = 50
	case "completed":
		statusWeight = 100
	default:
		statusWeight = 0
	}

	// Always fetch envelope to get authoritative actors list and total_actors
	// This ensures progress calculation is consistent even if sidecar sends partial/empty actors list
	envelope, err := h.jobStore.Get(envelopeID)
	if err != nil {
		slog.Error("Failed to get envelope for progress calculation", "id", envelopeID, "error", err)
		http.Error(w, "Failed to get envelope", http.StatusInternalServerError)
		return
	}

	// Use envelope's actors list as the source of truth
	actors := envelope.Route.Actors
	if len(progress.Actors) > 0 && len(progress.Actors) > len(actors) {
		// If progress update has more actors (route was extended), use that instead
		actors = progress.Actors
		slog.Debug("Progress update has extended route", "id", envelopeID, "envelope_actors", len(envelope.Route.Actors), "progress_actors", len(progress.Actors))
	}
	progress.Actors = actors

	totalActors := len(actors)
	if totalActors == 0 {
		slog.Warn("No actors in route for progress calculation", "id", envelopeID)
		progress.ProgressPercent = 0
	} else {
		newProgress := (float64(progress.CurrentActorIdx)*100 + statusWeight) / float64(totalActors)

		// Enforce monotonic progress: never decrease
		if newProgress < envelope.ProgressPercent {
			slog.Debug("Skipping non-monotonic progress update",
				"id", envelopeID,
				"current", envelope.ProgressPercent,
				"new", newProgress,
				"actor_idx", progress.CurrentActorIdx,
				"status", progress.Status)
			progress.ProgressPercent = envelope.ProgressPercent
		} else {
			progress.ProgressPercent = newProgress
			slog.Debug("Calculated progress", "id", envelopeID, "actor_idx", progress.CurrentActorIdx, "status", progress.Status, "percent", progress.ProgressPercent, "total_actors", totalActors)
		}
	}

	// Ensure progress doesn't exceed 100%
	if progress.ProgressPercent > 100 {
		progress.ProgressPercent = 100
	}

	// Transform ProgressUpdate (external API from sidecar) into EnvelopeUpdate (internal event).
	// This transformation:
	// - Sets envelope-level status to Running
	// - Copies envelope processing state ("received", "processing", "completed")
	// - Copies route information (Actors and CurrentActorIdx) to persist modifications
	// - Adds calculated progress percentage and timestamp
	envelopeState := string(progress.Status)
	update := types.EnvelopeUpdate{
		ID:              envelopeID,
		Status:          types.EnvelopeStatusRunning,
		Message:         progress.Message,
		ProgressPercent: &progress.ProgressPercent,
		Actors:          progress.Actors,
		CurrentActorIdx: &progress.CurrentActorIdx,
		EnvelopeState:   &envelopeState,
		Timestamp:       time.Now(),
	}

	// Update envelope store (using UpdateProgress for lighter weight update)
	if err := h.jobStore.UpdateProgress(update); err != nil {
		slog.Error("Failed to update envelope progress", "error", err)
		http.Error(w, "Failed to update progress", http.StatusInternalServerError)
		return
	}

	slog.Debug("Progress update stored in postgres",
		"envelope_id", envelopeID,
		"status", progress.Status,
		"current_actor_idx", progress.CurrentActorIdx,
		"progress_percent", progress.ProgressPercent)

	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"status":           "ok",
		"progress_percent": progress.ProgressPercent,
	})
}

// HandleJobFinal handles POST /envelopes/{id}/final (for end actors to report final status)
// This is called by happy-end and error-end actors to report envelope completion
func (h *Handler) HandleEnvelopeFinal(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := envelopeFinalPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid envelope final path", http.StatusBadRequest)
		return
	}
	envelopeID := matches[1]

	// Parse final status update
	var finalUpdate struct {
		ID               string                 `json:"id"`
		Status           string                 `json:"status"`
		Progress         *float64               `json:"progress"`
		Result           interface{}            `json:"result"`
		Error            string                 `json:"error"`
		ErrorDetails     interface{}            `json:"error_details"`
		Metadata         map[string]interface{} `json:"metadata"`
		Actors           []string               `json:"actors"`
		CurrentActorIdx  *int                   `json:"current_actor_idx"`
		CurrentActorName string                 `json:"current_actor_name"`
		Timestamp        string                 `json:"timestamp"`
	}

	if err := json.NewDecoder(r.Body).Decode(&finalUpdate); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	// Determine envelope status from final update
	var envelopeStatus types.EnvelopeStatus
	switch finalUpdate.Status {
	case "succeeded":
		envelopeStatus = types.EnvelopeStatusSucceeded
	case "failed":
		envelopeStatus = types.EnvelopeStatusFailed
	default:
		slog.Error("Invalid final status", "id", envelopeID, "status", finalUpdate.Status)
		http.Error(w, "Invalid status: must be 'succeeded' or 'failed'", http.StatusBadRequest)
		return
	}

	slog.Info("Received final status from end actor",
		"id", envelopeID,
		"status", envelopeStatus,
		"hasResult", finalUpdate.Result != nil,
		"hasError", finalUpdate.Error != "",
		"currentActor", finalUpdate.CurrentActorName)

	// Create envelope update
	progressPercent := 100.0
	update := types.EnvelopeUpdate{
		ID:              envelopeID,
		Status:          envelopeStatus,
		Result:          finalUpdate.Result,
		ProgressPercent: &progressPercent,
		Timestamp:       time.Now(),
	}

	// Set actor and route information
	if finalUpdate.CurrentActorName != "" {
		update.Actor = finalUpdate.CurrentActorName
	}
	if finalUpdate.CurrentActorIdx != nil {
		update.CurrentActorIdx = finalUpdate.CurrentActorIdx
	}
	if len(finalUpdate.Actors) > 0 {
		update.Actors = finalUpdate.Actors
	}

	// Set message and error based on status
	if envelopeStatus == types.EnvelopeStatusSucceeded {
		update.Message = "Envelope completed successfully"
		if finalUpdate.Metadata != nil {
			if s3URI, ok := finalUpdate.Metadata["s3_uri"].(string); ok {
				update.Message = fmt.Sprintf("Envelope completed successfully, results stored at %s", s3URI)
			}
		}
	} else {
		update.Message = "Envelope failed"
		if finalUpdate.Error != "" {
			update.Error = finalUpdate.Error
			if finalUpdate.CurrentActorName != "" {
				update.Message = fmt.Sprintf("Envelope failed at actor '%s': %s", finalUpdate.CurrentActorName, finalUpdate.Error)
			} else {
				update.Message = fmt.Sprintf("Envelope failed: %s", finalUpdate.Error)
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
			if finalUpdate.CurrentActorIdx != nil {
				errorInfo["failed_actor_idx"] = *finalUpdate.CurrentActorIdx
			}
			if len(finalUpdate.Actors) > 0 {
				errorInfo["route"] = finalUpdate.Actors
			}
			update.Result = errorInfo
		}
	}

	slog.Debug("Updating envelope with final status",
		"id", envelopeID,
		"status", envelopeStatus,
		"message", update.Message)

	// Update envelope store
	if err := h.jobStore.Update(update); err != nil {
		slog.Error("Failed to update envelope with final status", "id", envelopeID, "error", err)
		http.Error(w, "Failed to update envelope", http.StatusInternalServerError)
		return
	}

	slog.Info("Envelope final status updated successfully",
		"id", envelopeID,
		"status", envelopeStatus)

	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}
