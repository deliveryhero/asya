package progress

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
)

// ProgressStatus represents the status of an actor
type ProgressStatus string

const (
	StatusReceived   ProgressStatus = "received"
	StatusProcessing ProgressStatus = "processing"
	StatusCompleted  ProgressStatus = "completed"
)

// Reporter sends progress updates to the gateway
type Reporter struct {
	gatewayURL string
	httpClient *http.Client
	actorName  string
}

// NewReporter creates a new progress reporter
func NewReporter(gatewayURL, actorName string) *Reporter {
	return &Reporter{
		gatewayURL: gatewayURL,
		actorName:  actorName,
		httpClient: &http.Client{
			Timeout: 5 * time.Second,
		},
	}
}

// ProgressUpdate represents a progress update payload
type ProgressUpdate struct {
	Prev          []string        `json:"prev"`
	Curr          string          `json:"curr"`
	Next          []string        `json:"next"`
	Status        ProgressStatus  `json:"status"` // "received" | "processing" | "completed"
	Message       string          `json:"message,omitempty"`
	DurationMs    *int64          `json:"duration_ms,omitempty"`     // Processing duration in milliseconds
	MessageSizeKB *float64        `json:"message_size_kb,omitempty"` // Message size in KB
	PauseMetadata json.RawMessage `json:"pause_metadata,omitempty"`  // x-asya-pause header content for HITL
}

// ReportProgress sends a progress update to the gateway
func (r *Reporter) ReportProgress(ctx context.Context, id string, update ProgressUpdate) error {
	if id == "" {
		// No id in message, skip progress reporting
		return nil
	}

	payload, err := json.Marshal(update)
	if err != nil {
		return fmt.Errorf("failed to marshal progress update: %w", err)
	}

	url := fmt.Sprintf("%s/mesh/%s/progress", r.gatewayURL, id)

	slog.Info("Sending progress update to gateway",
		"task_id", id,
		"status", update.Status,
		"curr", update.Curr,
		"url", url)

	maxRetries := 5
	retryDelay := 200 * time.Millisecond

	for attempt := 0; attempt < maxRetries; attempt++ {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return nil
			case <-time.After(retryDelay):
			}
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
		if err != nil {
			return fmt.Errorf("failed to create request: %w", err)
		}

		req.Header.Set("Content-Type", "application/json")
		setEnvelopeHeader(req, id)

		resp, err := r.httpClient.Do(req)
		if err != nil {
			slog.Warn("Failed to send progress update", "error", err, "attempt", attempt+1, "max_retries", maxRetries)
			if attempt == maxRetries-1 {
				return nil
			}
			continue
		}
		defer func() { _ = resp.Body.Close() }()

		if resp.StatusCode != http.StatusOK {
			slog.Warn("Progress update returned non-200 status", "status", resp.StatusCode, "attempt", attempt+1)
			if attempt == maxRetries-1 {
				return nil
			}
			continue
		}

		slog.Debug("Progress update sent successfully",
			"task_id", id,
			"status", update.Status,
			"curr", update.Curr)

		return nil
	}

	return nil
}

// GetGatewayURL returns the configured gateway URL
func (r *Reporter) GetGatewayURL() string {
	return r.gatewayURL
}

// EventType distinguishes status updates from FLY events in the unified endpoint.
type EventType string

const (
	EventTypeStatus EventType = "status"
	EventTypeFly    EventType = "fly"
)

// MeshEvent is the payload for POST /api/v1/mesh/{id}/events.
type MeshEvent struct {
	Type   EventType       `json:"type"`
	Status string          `json:"status,omitempty"`
	Data   json.RawMessage `json:"data,omitempty"`
}

// MessageStatus is the response from GET /api/v1/mesh/{id}.
type MessageStatus struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

// setEnvelopeHeader adds the X-Asya-Envelope-ID header for Ingress hash routing.
func setEnvelopeHeader(req *http.Request, envelopeID string) {
	if envelopeID != "" {
		req.Header.Set("X-Asya-Envelope-ID", envelopeID)
	}
}

// PostEvent sends an event to the mesh-api unified endpoint.
// Falls back to legacy endpoints (/mesh/{id}/progress, /mesh/{id}/fly,
// /mesh/{id}/final) if the new endpoint returns 404.
func (r *Reporter) PostEvent(ctx context.Context, id string, event MeshEvent) error {
	if id == "" {
		return nil
	}

	payload, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("failed to marshal event: %w", err)
	}

	url := fmt.Sprintf("%s/api/v1/mesh/%s/events", r.gatewayURL, id)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	setEnvelopeHeader(req, id)

	resp, err := r.httpClient.Do(req)
	if err != nil {
		slog.Warn("Failed to POST event to mesh-api", "id", id, "error", err)
		return r.postEventLegacyFallback(ctx, id, event)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode == http.StatusNotFound {
		slog.Debug("Mesh-api /events returned 404, falling back to legacy endpoints", "id", id)
		return r.postEventLegacyFallback(ctx, id, event)
	}

	if resp.StatusCode >= 300 {
		return fmt.Errorf("mesh-api returned status %d for event POST", resp.StatusCode)
	}

	return nil
}

// postEventLegacyFallback routes to the old /mesh/{id}/progress, /mesh/{id}/fly,
// or /mesh/{id}/final endpoints based on event type and status.
func (r *Reporter) postEventLegacyFallback(ctx context.Context, id string, event MeshEvent) error {
	switch event.Type {
	case EventTypeFly:
		return r.ForwardFly(ctx, id, event.Data)
	case EventTypeStatus:
		if event.Status == "succeeded" || event.Status == "failed" {
			url := fmt.Sprintf("%s/mesh/%s/final", r.gatewayURL, id)
			req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(event.Data))
			if err != nil {
				return err
			}
			req.Header.Set("Content-Type", "application/json")
			setEnvelopeHeader(req, id)
			resp, err := r.httpClient.Do(req)
			if err != nil {
				return err
			}
			defer func() { _ = resp.Body.Close() }()
			if resp.StatusCode >= 300 {
				return fmt.Errorf("legacy /final returned status %d", resp.StatusCode)
			}
			return nil
		}
		return r.ReportProgress(ctx, id, ProgressUpdate{
			Status:  ProgressStatus(event.Status),
			Message: "status update via legacy fallback",
		})
	default:
		return fmt.Errorf("unknown event type: %s", event.Type)
	}
}

// CheckMessage queries the mesh-api for the current status of a message.
// Returns nil MessageStatus and nil error if the endpoint is unreachable or
// returns 404 (backward compat: old gateway has no such endpoint).
func (r *Reporter) CheckMessage(ctx context.Context, id string) (*MessageStatus, error) {
	if id == "" {
		return nil, nil
	}

	url := fmt.Sprintf("%s/api/v1/mesh/%s", r.gatewayURL, id)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create check request: %w", err)
	}
	setEnvelopeHeader(req, id)

	resp, err := r.httpClient.Do(req)
	if err != nil {
		slog.Warn("Pre-flight check failed (network), proceeding", "id", id, "error", err)
		return nil, nil
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode == http.StatusNotFound {
		slog.Debug("Pre-flight check: endpoint not found (legacy gateway), proceeding", "id", id)
		return nil, nil
	}

	if resp.StatusCode >= 300 {
		slog.Warn("Pre-flight check returned unexpected status", "id", id, "status", resp.StatusCode)
		return nil, nil
	}

	var status MessageStatus
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		slog.Warn("Pre-flight check: failed to decode response", "id", id, "error", err)
		return nil, nil
	}

	return &status, nil
}

// CheckHealth verifies the gateway is reachable by calling /health endpoint
// Returns error if gateway is not responding or returns non-200 status
func (r *Reporter) CheckHealth(ctx context.Context) error {
	url := fmt.Sprintf("%s/health", r.gatewayURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return fmt.Errorf("failed to create health check request: %w", err)
	}

	resp, err := r.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to reach gateway health endpoint: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("gateway health check failed with status %d", resp.StatusCode)
	}

	slog.Debug("Gateway health check passed", "url", url)
	return nil
}

// CreateMeshPayload represents the payload for creating a fanout mesh
type CreateMeshPayload struct {
	ID       string   `json:"id"`
	ParentID string   `json:"parent_id"`
	Prev     []string `json:"prev"`
	Curr     string   `json:"curr"`
	Next     []string `json:"next"`
}

// CreateMesh creates a fanout child mesh in the gateway
// This is called when the sidecar detects multiple responses from runtime (fanout scenario)
func (r *Reporter) CreateMesh(ctx context.Context, id, parentID string, route envelopes.Route) error {
	payload := CreateMeshPayload{
		ID:       id,
		ParentID: parentID,
		Prev:     route.Prev,
		Curr:     route.Curr,
		Next:     route.Next,
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal create mesh payload: %w", err)
	}

	url := fmt.Sprintf("%s/mesh", r.gatewayURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payloadBytes))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	setEnvelopeHeader(req, id)

	resp, err := r.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send create mesh request: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		return fmt.Errorf("create mesh returned status %d", resp.StatusCode)
	}

	slog.Debug("Created fanout mesh in gateway", "id", id, "parent_id", parentID)
	return nil
}

// ForwardFly sends a FLY event to the gateway for live SSE delivery.
// Used for streaming token-by-token output from generator handlers to connected clients.
func (r *Reporter) ForwardFly(ctx context.Context, taskID string, payload json.RawMessage) error {
	if taskID == "" {
		return nil
	}

	url := fmt.Sprintf("%s/mesh/%s/fly", r.gatewayURL, taskID)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("failed to create FLY request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	setEnvelopeHeader(req, taskID)

	resp, err := r.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to forward FLY event: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("FLY forward returned non-200 status: %d", resp.StatusCode)
	}

	return nil
}

// ReportFinalError reports a final error status to the gateway.
// Delegates to PostEvent for unified endpoint with legacy fallback.
func (r *Reporter) ReportFinalError(ctx context.Context, taskID, errorMsg string) error {
	finalPayload := map[string]interface{}{
		"id":        taskID,
		"status":    "failed",
		"error":     errorMsg,
		"timestamp": time.Now().Format(time.RFC3339),
	}

	data, err := json.Marshal(finalPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal final error: %w", err)
	}

	return r.PostEvent(ctx, taskID, MeshEvent{
		Type:   EventTypeStatus,
		Status: "failed",
		Data:   data,
	})
}
