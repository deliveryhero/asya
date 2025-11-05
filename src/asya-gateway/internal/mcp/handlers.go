package mcp

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"net/http"
	"strings"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/mark3labs/mcp-go/mcp"
)

// Handler provides HTTP endpoints for job management
// MCP endpoints are now handled directly by mark3labs/mcp-go server
type Handler struct {
	jobStore jobs.JobStore
	server   *Server // For direct tool calls
}

// NewHandler creates a new HTTP handler for job management
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

// HandleJobStatus handles GET /jobs/{id}
func (h *Handler) HandleJobStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract job ID from path (simple parsing)
	jobID := r.URL.Path[len("/jobs/"):]
	if jobID == "" {
		http.Error(w, "Job ID required", http.StatusBadRequest)
		return
	}

	job, err := h.jobStore.Get(jobID)
	if err != nil {
		http.Error(w, "Job not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(job); err != nil {
		slog.Error("Failed to encode job", "error", err)
	}
}

// HandleJobStream handles GET /jobs/{id}/stream (SSE)
func (h *Handler) HandleJobStream(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract job ID from path
	jobID := r.URL.Path[len("/jobs/"):]
	if len(jobID) > 7 && jobID[len(jobID)-7:] == "/stream" {
		jobID = jobID[:len(jobID)-7]
	}

	if jobID == "" {
		http.Error(w, "Job ID required", http.StatusBadRequest)
		return
	}

	// Verify job exists
	job, err := h.jobStore.Get(jobID)
	if err != nil {
		http.Error(w, "Job not found", http.StatusNotFound)
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

	// Send initial state
	h.sendSSE(w, flusher, "status", string(job.Status))

	// Subscribe to updates
	updateChan := h.jobStore.Subscribe(jobID)
	defer h.jobStore.Unsubscribe(jobID, updateChan)

	// Stream updates until job completes or client disconnects
	for {
		select {
		case <-r.Context().Done():
			return
		case update := <-updateChan:
			// Send update
			data, err := json.Marshal(update)
			if err != nil {
				slog.Error("Failed to marshal update", "error", err)
				continue
			}

			fmt.Fprintf(w, "event: update\n")
			fmt.Fprintf(w, "data: %s\n\n", data)
			flusher.Flush()

			// Close stream if job is in terminal state
			if isTerminalStatus(update.Status) {
				// Final flush to ensure message is sent before closing
				flusher.Flush()
				return
			}
		}
	}
}

func (h *Handler) sendSSE(w http.ResponseWriter, flusher http.Flusher, event, data string) {
	fmt.Fprintf(w, "event: %s\n", event)
	fmt.Fprintf(w, "data: %s\n\n", data)
	flusher.Flush()
}

func isTerminalStatus(status types.JobStatus) bool {
	return status == types.JobStatusSucceeded ||
		status == types.JobStatusFailed
}

// HandleJobActive handles GET /jobs/{id}/active (for actors to check if job is still valid)
func (h *Handler) HandleJobActive(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract job ID from path
	jobID := r.URL.Path[len("/jobs/"):]
	if len(jobID) > 7 && jobID[len(jobID)-7:] == "/active" {
		jobID = jobID[:len(jobID)-7]
	}

	if jobID == "" {
		http.Error(w, "Job ID required", http.StatusBadRequest)
		return
	}

	// Check if job is active
	if h.jobStore.IsActive(jobID) {
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]bool{"active": true})
	} else {
		w.WriteHeader(http.StatusGone) // 410 Gone - job timed out or completed
		json.NewEncoder(w).Encode(map[string]bool{"active": false})
	}
}

// HandleJobHeartbeat handles POST /jobs/{id}/heartbeat (for actors to send status updates)
func (h *Handler) HandleJobHeartbeat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract job ID from path
	jobID := r.URL.Path[len("/jobs/"):]
	if len(jobID) > 10 && jobID[len(jobID)-10:] == "/heartbeat" {
		jobID = jobID[:len(jobID)-10]
	}

	if jobID == "" {
		http.Error(w, "Job ID required", http.StatusBadRequest)
		return
	}

	// Parse heartbeat
	var heartbeat types.ActorHeartbeat
	if err := json.NewDecoder(r.Body).Decode(&heartbeat); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	heartbeat.JobID = jobID
	heartbeat.Timestamp = time.Now()

	slog.Debug("Heartbeat received", "job", jobID, "actor", heartbeat.ActorName, "status", heartbeat.Status)

	// Get current job to calculate progress
	job, err := h.jobStore.Get(jobID)
	if err != nil {
		slog.Error("Failed to get job", "job", jobID, "error", err)
		http.Error(w, "Job not found", http.StatusNotFound)
		return
	}

	slog.Debug("Current job status", "job", jobID, "status", job.Status, "route", job.Route.Steps)

	// Update job based on heartbeat status
	var jobStatus types.JobStatus
	var stepStatus string
	var statusWeight float64
	var message string

	slog.Debug("Processing heartbeat", "job", jobID, "actor", heartbeat.ActorName, "status", heartbeat.Status)

	switch heartbeat.Status {
	case types.HeartbeatPickedUp:
		jobStatus = types.JobStatusRunning
		stepStatus = "received"
		statusWeight = 10.0
		message = fmt.Sprintf("Actor %s picked up task", heartbeat.ActorName)
		slog.Debug("Heartbeat picked_up", "job", jobID, "actor", heartbeat.ActorName)
	case types.HeartbeatProcessing:
		jobStatus = types.JobStatusRunning
		stepStatus = "processing"
		statusWeight = 50.0
		message = heartbeat.Message
		slog.Debug("Heartbeat processing", "job", jobID, "actor", heartbeat.ActorName, "message", heartbeat.Message)
	case types.HeartbeatCompleted:
		jobStatus = types.JobStatusRunning
		stepStatus = "completed"
		statusWeight = 100.0
		message = fmt.Sprintf("Actor %s completed", heartbeat.ActorName)
		slog.Debug("Heartbeat completed", "job", jobID, "actor", heartbeat.ActorName)
	case types.HeartbeatError:
		jobStatus = types.JobStatusFailed
		stepStatus = "error"
		statusWeight = 0.0
		message = heartbeat.Message
		slog.Error("Actor reported error", "job", jobID, "actor", heartbeat.ActorName, "error", heartbeat.Message)
	default:
		slog.Error("Invalid heartbeat status", "job", jobID, "status", heartbeat.Status)
		http.Error(w, "Invalid heartbeat status", http.StatusBadRequest)
		return
	}

	// Calculate progress percentage
	// Formula: (stepIndex * 100 + statusWeight) / totalSteps
	totalSteps := float64(job.TotalSteps)
	if totalSteps == 0 {
		totalSteps = float64(len(job.Route.Steps))
	}

	// TODO: This step index calculation is brittle and relies on naming conventions.
	// Consider adding an explicit "step" or "step_index" field to ActorHeartbeat
	// so actors can report their position in the route directly.
	// See: https://github.com/deliveryhero/asya/pull/5#discussion_r2437179276
	stepIndex := 0
	for i, queueName := range job.Route.Steps {
		// Extract actor type from queue name (e.g., "test-doubler-queue" → "doubler")
		// and match against actor name (e.g., "doubler-actor")
		if strings.Contains(queueName, strings.TrimSuffix(heartbeat.ActorName, "-actor")) {
			stepIndex = i
			break
		}
	}

	var progressPercent float64
	if totalSteps == 0 {
		progressPercent = 0
	} else {
		progressPercent = (float64(stepIndex)*100.0 + statusWeight) / totalSteps
	}

	slog.Debug("Progress calculation",
		"job", jobID,
		"stepIndex", stepIndex,
		"totalSteps", totalSteps,
		"statusWeight", statusWeight,
		"progress", progressPercent)

	// Update job with progress
	update := types.JobUpdate{
		JobID:           jobID,
		Status:          jobStatus,
		Message:         message,
		Step:            heartbeat.ActorName,
		StepStatus:      stepStatus,
		ProgressPercent: &progressPercent,
		Timestamp:       heartbeat.Timestamp,
	}

	if heartbeat.Status == types.HeartbeatError {
		update.Error = heartbeat.Message
	}

	slog.Debug("Updating job progress",
		"job", jobID,
		"status", jobStatus,
		"step", heartbeat.ActorName,
		"stepStatus", stepStatus,
		"progress", progressPercent)

	if err := h.jobStore.UpdateProgress(update); err != nil {
		slog.Error("Failed to update job progress", "job", jobID, "error", err)
		http.Error(w, "Failed to update job", http.StatusInternalServerError)
		return
	}

	slog.Debug("Job progress updated successfully",
		"job", jobID,
		"status", jobStatus,
		"progress", progressPercent)

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

// HandleJobProgress handles POST /jobs/{id}/progress (for actors to report progress)
func (h *Handler) HandleJobProgress(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract job ID from path
	jobID := r.URL.Path[len("/jobs/"):]
	if len(jobID) > 9 && jobID[len(jobID)-9:] == "/progress" {
		jobID = jobID[:len(jobID)-9]
	}

	if jobID == "" {
		http.Error(w, "Job ID required", http.StatusBadRequest)
		return
	}

	// Parse progress update
	var progress types.ProgressUpdate
	if err := json.NewDecoder(r.Body).Decode(&progress); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	progress.JobID = jobID

	// Calculate progress percentage
	// Formula: (stepIndex * 100 + statusWeight) / totalSteps
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

	if progress.TotalSteps == 0 {
		progress.ProgressPercent = 0
	} else {
		progress.ProgressPercent = (float64(progress.StepIndex)*100 + statusWeight) / float64(progress.TotalSteps)
	}

	// Ensure progress doesn't exceed 100%
	if progress.ProgressPercent > 100 {
		progress.ProgressPercent = 100
	}

	// Create job update
	update := types.JobUpdate{
		JobID:           jobID,
		Status:          types.JobStatusRunning,
		Message:         progress.Message,
		ProgressPercent: &progress.ProgressPercent,
		Step:            progress.Step,
		StepStatus:      progress.Status,
		Timestamp:       time.Now(),
	}

	// Update job store (using UpdateProgress for lighter weight update)
	if err := h.jobStore.UpdateProgress(update); err != nil {
		slog.Error("Failed to update job progress", "error", err)
		http.Error(w, "Failed to update progress", http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":           "ok",
		"progress_percent": progress.ProgressPercent,
	})
}

// HandleJobFinal handles POST /jobs/{id}/final (for terminal actors to report final status)
// This is called by happy-end and error-end actors to report job completion
func (h *Handler) HandleJobFinal(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract job ID from path
	jobID := r.URL.Path[len("/jobs/"):]
	if len(jobID) > 6 && jobID[len(jobID)-6:] == "/final" {
		jobID = jobID[:len(jobID)-6]
	}

	if jobID == "" {
		http.Error(w, "Job ID required", http.StatusBadRequest)
		return
	}

	// Parse final status update
	var finalUpdate struct {
		JobID     string                 `json:"job_id"`
		Status    string                 `json:"status"`
		Progress  *float64               `json:"progress"`
		Result    interface{}            `json:"result"`
		Error     string                 `json:"error"`
		Metadata  map[string]interface{} `json:"metadata"`
		Timestamp string                 `json:"timestamp"`
	}

	if err := json.NewDecoder(r.Body).Decode(&finalUpdate); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	// Determine job status from final update
	var jobStatus types.JobStatus
	switch finalUpdate.Status {
	case "succeeded":
		jobStatus = types.JobStatusSucceeded
	case "failed":
		jobStatus = types.JobStatusFailed
	default:
		slog.Error("Invalid final status", "job", jobID, "status", finalUpdate.Status)
		http.Error(w, "Invalid status: must be 'succeeded' or 'failed'", http.StatusBadRequest)
		return
	}

	slog.Info("Received final status from terminal actor",
		"job", jobID,
		"status", jobStatus,
		"hasResult", finalUpdate.Result != nil,
		"hasError", finalUpdate.Error != "")

	// Create job update
	update := types.JobUpdate{
		JobID:     jobID,
		Status:    jobStatus,
		Result:    finalUpdate.Result,
		Timestamp: time.Now(),
	}

	// Set message and error based on status
	if jobStatus == types.JobStatusSucceeded {
		update.Message = "Job completed successfully"
		if finalUpdate.Metadata != nil {
			if s3URI, ok := finalUpdate.Metadata["s3_uri"].(string); ok {
				update.Message = fmt.Sprintf("Job completed successfully, results stored at %s", s3URI)
			}
		}
	} else {
		update.Message = "Job failed"
		if finalUpdate.Error != "" {
			update.Error = finalUpdate.Error
			update.Message = fmt.Sprintf("Job failed: %s", finalUpdate.Error)
		}
	}

	slog.Debug("Updating job with final status",
		"job", jobID,
		"status", jobStatus,
		"message", update.Message)

	// Update job store
	if err := h.jobStore.Update(update); err != nil {
		slog.Error("Failed to update job with final status", "job", jobID, "error", err)
		http.Error(w, "Failed to update job", http.StatusInternalServerError)
		return
	}

	slog.Info("Job final status updated successfully",
		"job", jobID,
		"status", jobStatus)

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}
