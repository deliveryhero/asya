package consumer

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ResultConsumer consumes envelopes from happy-end and error-end queues
// and updates job status accordingly
type ResultConsumer struct {
	queueClient queue.Client
	jobStore    jobs.JobStore
}

// NewResultConsumer creates a new result consumer
func NewResultConsumer(queueClient queue.Client, jobStore jobs.JobStore) *ResultConsumer {
	return &ResultConsumer{
		queueClient: queueClient,
		jobStore:    jobStore,
	}
}

// Start starts consuming from happy-end and error-end queues
func (c *ResultConsumer) Start(ctx context.Context) error {
	slog.Info("Starting result consumer for end queues")

	// Start consumer for happy-end queue
	go c.consumeQueue(ctx, "happy-end", types.EnvelopeStatusSucceeded)

	// Start consumer for error-end queue
	go c.consumeQueue(ctx, "error-end", types.EnvelopeStatusFailed)

	return nil
}

// consumeQueue consumes envelopes from a specific queue and updates envelope status
func (c *ResultConsumer) consumeQueue(ctx context.Context, queueName string, status types.EnvelopeStatus) {
	slog.Info("Starting consumer", "queue", queueName)

	for {
		select {
		case <-ctx.Done():
			slog.Info("Stopping consumer", "queue", queueName)
			return
		default:
			// Receive envelope from queue (blocks until envelope available or context cancelled)
			msg, err := c.queueClient.Receive(ctx, queueName)
			if err != nil {
				// Check if context was cancelled
				if ctx.Err() != nil {
					return
				}
				slog.Error("Error receiving from queue", "queue", queueName, "error", err)
				continue
			}

			slog.Debug("Received envelope", "queue", queueName, "body", string(msg.Body()[:min(len(msg.Body()), 200)]))

			// Process the envelope
			c.processMessage(ctx, msg, status)
		}
	}
}

// processMessage processes a envelope and updates the envelope status
func (c *ResultConsumer) processMessage(ctx context.Context, msg queue.QueueMessage, status types.EnvelopeStatus) {
	defer func() {
		if err := c.queueClient.Ack(ctx, msg); err != nil {
			slog.Error("Failed to ack envelope", "error", err)
		}
	}()

	slog.Debug("Processing envelope", "status", status)

	// Parse the envelope to extract envelope ID, result, and error (flat format)
	var parsedMsg struct {
		ID      string `json:"id"`
		Error   string `json:"error,omitempty"`
		Details struct {
			Message   string `json:"message,omitempty"`
			Type      string `json:"type,omitempty"`
			Traceback string `json:"traceback,omitempty"`
		} `json:"details,omitempty"`
		Route struct {
			Actors   []string               `json:"actors"`
			Current  int                    `json:"current"`
			Metadata map[string]interface{} `json:"metadata"`
		} `json:"route"`
		Payload map[string]interface{} `json:"payload"` // Result payload
	}

	if err := json.Unmarshal(msg.Body(), &parsedMsg); err != nil {
		slog.Error("Failed to parse envelope", "error", err)
		return
	}

	// Extract envelope ID - try top-level first, then route metadata
	envelopeID := parsedMsg.ID
	if envelopeID == "" && parsedMsg.Route.Metadata != nil {
		if id, ok := parsedMsg.Route.Metadata["job_id"].(string); ok {
			envelopeID = id
		}
	}

	if envelopeID == "" {
		slog.Error("No envelope ID found, skipping", "body", string(msg.Body()[:min(len(msg.Body()), 200)]))
		return
	}

	slog.Debug("Extracted envelope ID", "id", envelopeID)

	// Extract result payload
	var result interface{} = parsedMsg.Payload
	if parsedMsg.Payload == nil {
		result = map[string]interface{}{}
	}

	// Update envelope status
	update := types.EnvelopeUpdate{
		ID:        envelopeID,
		Status:    status,
		Result:    result,
		Timestamp: time.Now(),
	}

	if status == types.EnvelopeStatusSucceeded {
		update.Message = "Envelope completed successfully"
		slog.Debug("Marking envelope as Succeeded", "id", envelopeID)
	} else {
		update.Message = "Envelope failed"
		// Extract error from top level (flat format)
		if parsedMsg.Error != "" {
			update.Error = parsedMsg.Error
			// Include error details if available
			if parsedMsg.Details.Message != "" {
				update.Error = fmt.Sprintf("%s: %s", parsedMsg.Error, parsedMsg.Details.Message)
			}
		}
		slog.Debug("Marking envelope as Failed", "id", envelopeID, "error", update.Error)
	}

	slog.Debug("Updating envelope with final status", "id", envelopeID, "status", status, "result", result)

	if err := c.jobStore.Update(update); err != nil {
		slog.Error("Failed to update envelope", "id", envelopeID, "error", err)
		return
	}

	slog.Debug("Envelope successfully updated to final status", "id", envelopeID, "status", status)

	slog.Info("Envelope marked as final status", "id", envelopeID, "status", status)
}
