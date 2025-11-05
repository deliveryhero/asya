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

// ProgressStatus represents the status of a step
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
	Step          string         `json:"step"`
	StepIndex     int            `json:"step_index"`
	TotalSteps    int            `json:"total_steps"`
	Status        ProgressStatus `json:"status"`
	ActorName     string         `json:"actor_name"`
	Message       string         `json:"message,omitempty"`
	DurationMs    *int64         `json:"duration_ms,omitempty"`     // Processing duration in milliseconds
	MessageSizeKB *float64       `json:"message_size_kb,omitempty"` // Message size in KB
}

// ReportProgress sends a progress update to the gateway
func (r *Reporter) ReportProgress(ctx context.Context, jobID string, update ProgressUpdate) error {
	if jobID == "" {
		// No job_id in message, skip progress reporting
		return nil
	}

	update.ActorName = r.actorName

	payload, err := json.Marshal(update)
	if err != nil {
		return fmt.Errorf("failed to marshal progress update: %w", err)
	}

	url := fmt.Sprintf("%s/jobs/%s/progress", r.gatewayURL, jobID)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")

	resp, err := r.httpClient.Do(req)
	if err != nil {
		// Log but don't fail the message processing
		slog.Warn("Failed to send progress update", "error", err)
		return nil // Non-blocking
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		slog.Warn("Progress update returned non-200 status", "status", resp.StatusCode)
	}

	return nil
}
