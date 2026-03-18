package consumer

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/envelopestore"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ResultConsumer consumes envelopes from x-sink and x-sump queues
// and updates envelope status accordingly
type ResultConsumer struct {
	queueClient queue.Client
	taskStore   envelopestore.EnvelopeStore
}

// NewResultConsumer creates a new result consumer
func NewResultConsumer(queueClient queue.Client, taskStore envelopestore.EnvelopeStore) *ResultConsumer {
	return &ResultConsumer{
		queueClient: queueClient,
		taskStore:   taskStore,
	}
}

// Start starts consuming from x-sink and x-sump queues
func (c *ResultConsumer) Start(ctx context.Context) error {
	slog.Info("Starting result consumer for end queues")

	// Start consumer for x-sink queue
	go c.consumeQueue(ctx, "x-sink", types.EnvelopeStatusSucceeded)

	// Start consumer for x-sump queue
	go c.consumeQueue(ctx, "x-sump", types.EnvelopeStatusFailed)

	return nil
}

// consumeQueue consumes envelopes from a specific queue and updates task status
func (c *ResultConsumer) consumeQueue(ctx context.Context, queueName string, status types.EnvelopeStatus) {
	slog.Info("Starting consumer", "queue", queueName)

	for {
		select {
		case <-ctx.Done():
			slog.Info("Stopping consumer", "queue", queueName)
			return
		default:
			// Receive task from queue (blocks until task available or context cancelled)
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

			// Process the task
			c.processMessage(ctx, msg, status)
		}
	}
}

// processMessage processes an envelope and updates the task status
func (c *ResultConsumer) processMessage(ctx context.Context, msg queue.QueueMessage, status types.EnvelopeStatus) {
	defer func() {
		if err := c.queueClient.Ack(ctx, msg); err != nil {
			slog.Error("Failed to ack envelope", "error", err)
		}
	}()

	slog.Debug("Processing envelope", "status", status)

	// Parse the task to extract task ID, result, and error (flat format)
	var parsedMsg struct {
		ID      string `json:"id"`
		Error   string `json:"error,omitempty"`
		Details struct {
			Message   string `json:"message,omitempty"`
			Type      string `json:"type,omitempty"`
			Traceback string `json:"traceback,omitempty"`
		} `json:"details,omitempty"`
		Route struct {
			Prev []string `json:"prev"`
			Curr string   `json:"curr"`
			Next []string `json:"next"`
		} `json:"route"`
		Payload map[string]interface{} `json:"payload"` // Result payload
		Status  struct {
			Phase       string `json:"phase,omitempty"`
			Reason      string `json:"reason,omitempty"`
			Actor       string `json:"actor,omitempty"`
			Attempt     int    `json:"attempt,omitempty"`
			MaxAttempts int    `json:"max_attempts,omitempty"`
			Error       *struct {
				Type      string   `json:"type,omitempty"`
				MRO       []string `json:"mro,omitempty"`
				Message   string   `json:"message,omitempty"`
				Traceback string   `json:"traceback,omitempty"`
			} `json:"error,omitempty"`
		} `json:"status,omitempty"`
	}

	if err := json.Unmarshal(msg.Body(), &parsedMsg); err != nil {
		slog.Error("Failed to parse task", "error", err)
		return
	}

	// Extract task ID from top-level field
	taskID := parsedMsg.ID

	if taskID == "" {
		slog.Error("No envelope ID found, skipping", "body", string(msg.Body()[:min(len(msg.Body()), 200)]))
		return
	}

	slog.Debug("Extracted envelope ID", "id", taskID)

	// Determine final status using status.phase, falling back to queue-based status param
	finalStatus := status // queue-name fallback (backward compat)
	switch parsedMsg.Status.Phase {
	case "succeeded":
		finalStatus = types.EnvelopeStatusSucceeded
	case "failed":
		finalStatus = types.EnvelopeStatusFailed
	case "":
		// No status field: use queue-based determination (backward compat)
	default:
		// Non-terminal phase: silently ack without updating gateway
		slog.Debug("Non-terminal phase in result queue, skipping task update",
			"id", taskID, "phase", parsedMsg.Status.Phase)
		return
	}

	// Extract result payload
	var result interface{} = parsedMsg.Payload
	if parsedMsg.Payload == nil {
		result = map[string]interface{}{}
	}

	// Build the update with enriched error from status.error and status.reason
	update := types.EnvelopeUpdate{
		ID:        taskID,
		Status:    finalStatus,
		Result:    result,
		Timestamp: time.Now(),
	}

	if finalStatus == types.EnvelopeStatusSucceeded {
		update.Message = "Task completed successfully"
		slog.Debug("Marking envelope as Succeeded", "id", taskID)
	} else {
		if parsedMsg.Status.Error != nil {
			errType := parsedMsg.Status.Error.Type
			errMsg := parsedMsg.Status.Error.Message
			switch {
			case errType != "" && errMsg != "":
				update.Error = fmt.Sprintf("%s: %s", errType, errMsg)
			case errMsg != "":
				update.Error = errMsg
			case errType != "":
				update.Error = errType
			}
		} else if parsedMsg.Error != "" {
			update.Error = parsedMsg.Error
			if parsedMsg.Details.Message != "" {
				update.Error = fmt.Sprintf("%s: %s", parsedMsg.Error, parsedMsg.Details.Message)
			}
		}
		if parsedMsg.Status.Reason != "" {
			update.Message = fmt.Sprintf("Task failed: %s", parsedMsg.Status.Reason)
		} else {
			update.Message = "Task failed"
		}
		slog.Debug("Marking envelope as Failed", "id", taskID, "error", update.Error, "reason", parsedMsg.Status.Reason)
	}

	slog.Debug("Updating envelope with final status", "id", taskID, "status", finalStatus, "result", result)

	if err := c.taskStore.Update(update); err != nil {
		slog.Error("Failed to update envelope", "id", taskID, "error", err)
		return
	}

	slog.Debug("Envelope successfully updated to final status", "id", taskID, "status", finalStatus)

	slog.Info("Envelope marked as final status", "id", taskID, "status", finalStatus)
}
