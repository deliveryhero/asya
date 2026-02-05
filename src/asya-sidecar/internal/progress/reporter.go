package progress

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"
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
	Actors          []string       `json:"actors"`            // Full list of actors in the route
	CurrentActorIdx int            `json:"current_actor_idx"` // Index of current actor
	Status          ProgressStatus `json:"status"`            // "received" | "processing" | "completed"
	Message         string         `json:"message,omitempty"`
	DurationMs      *int64         `json:"duration_ms,omitempty"`     // Processing duration in milliseconds
	MessageSizeKB   *float64       `json:"message_size_kb,omitempty"` // Message size in KB
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

	url := fmt.Sprintf("%s/envelopes/%s/progress", r.gatewayURL, id)

	slog.Info("Sending progress update to gateway",
		"envelope_id", id,
		"status", update.Status,
		"current_actor_idx", update.CurrentActorIdx,
		"total_actors", len(update.Actors),
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
			"envelope_id", id,
			"status", update.Status,
			"current_actor_idx", update.CurrentActorIdx)

		return nil
	}

	return nil
}

// GetGatewayURL returns the configured gateway URL
func (r *Reporter) GetGatewayURL() string {
	return r.gatewayURL
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

// CreateEnvelopePayload represents the payload for creating a fanout envelope
type CreateEnvelopePayload struct {
	ID       string   `json:"id"`
	ParentID string   `json:"parent_id"`
	Actors   []string `json:"actors"`
	Current  int      `json:"current"`
}

// CreateEnvelope creates a fanout child envelope in the gateway
// This is called when the sidecar detects multiple responses from runtime (fanout scenario)
func (r *Reporter) CreateEnvelope(ctx context.Context, id, parentID string, actors []string, current int) error {
	payload := CreateEnvelopePayload{
		ID:       id,
		ParentID: parentID,
		Actors:   actors,
		Current:  current,
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal create envelope payload: %w", err)
	}

	url := fmt.Sprintf("%s/envelopes", r.gatewayURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payloadBytes))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")

	resp, err := r.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send create envelope request: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		return fmt.Errorf("create envelope returned status %d", resp.StatusCode)
	}

	slog.Debug("Created fanout envelope in gateway", "id", id, "parent_id", parentID)
	return nil
}

// ReportFinalError reports a final error status to the gateway
// Used by end actors when they encounter unrecoverable errors (e.g., timeout)
func (r *Reporter) ReportFinalError(ctx context.Context, envelopeID, errorMsg string) error {
	finalPayload := map[string]interface{}{
		"id":        envelopeID,
		"status":    "failed",
		"error":     errorMsg,
		"timestamp": time.Now().Format(time.RFC3339),
	}

	payloadBytes, err := json.Marshal(finalPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal final error: %w", err)
	}

	url := fmt.Sprintf("%s/envelopes/%s/final", r.gatewayURL, envelopeID)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payloadBytes))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := r.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send final error: %w", err)
	}
	defer func() {
		if err := resp.Body.Close(); err != nil {
			slog.Error("Failed to close response body", "error", err)
		}
	}()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("gateway returned non-success status: %d", resp.StatusCode)
	}

	slog.Info("Reported final error to gateway", "id", envelopeID, "error", errorMsg)
	return nil
}
