package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"
)

// GatewayReporter reports DLQ failure status to the gateway.
type GatewayReporter interface {
	// ReportFailure posts a failure status for the given task ID.
	// Best-effort: returns error on failure but callers may choose to continue.
	ReportFailure(ctx context.Context, taskID, errorMsg string) error
}

// gatewayClient implements GatewayReporter using HTTP.
type gatewayClient struct {
	baseURL    string
	httpClient *http.Client
}

// NewGatewayClient creates a gateway reporter that posts to /mesh/{id}/final.
func NewGatewayClient(baseURL string) GatewayReporter {
	return &gatewayClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: 5 * time.Second,
		},
	}
}

// ReportFailure reports a DLQ failure to the gateway.
// Retries up to 3 times with 200ms backoff (matching sidecar pattern).
func (g *gatewayClient) ReportFailure(ctx context.Context, taskID, errorMsg string) error {
	payload := map[string]interface{}{
		"id":        taskID,
		"status":    "failed",
		"error":     errorMsg,
		"timestamp": time.Now().UTC().Format(time.RFC3339),
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal failure payload: %w", err)
	}

	url := fmt.Sprintf("%s/mesh/%s/final", g.baseURL, taskID)

	maxRetries := 3
	retryDelay := 200 * time.Millisecond

	for attempt := 0; attempt < maxRetries; attempt++ {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(retryDelay):
			}
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
		if err != nil {
			return fmt.Errorf("failed to create request: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")

		resp, err := g.httpClient.Do(req)
		if err != nil {
			slog.Warn("Failed to report DLQ failure to gateway",
				"task_id", taskID, "attempt", attempt+1, "error", err)
			continue
		}
		_ = resp.Body.Close()

		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			slog.Info("Reported DLQ failure to gateway", "task_id", taskID)
			return nil
		}

		slog.Warn("Gateway returned non-success status",
			"task_id", taskID, "status", resp.StatusCode, "attempt", attempt+1)
	}

	return fmt.Errorf("failed to report failure after %d attempts", maxRetries)
}

// noopGateway is a no-op reporter used when no gateway URL is configured.
type noopGateway struct{}

func (*noopGateway) ReportFailure(_ context.Context, _, _ string) error {
	return nil
}
