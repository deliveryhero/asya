package consumer

import (
	"context"
	"encoding/json"
	"log/slog"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ResultConsumer consumes messages from happy-end and error-end queues
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
	slog.Info("Starting result consumer for terminal queues")

	// Start consumer for happy-end queue
	go c.consumeQueue(ctx, "happy-end", types.JobStatusSucceeded)

	// Start consumer for error-end queue
	go c.consumeQueue(ctx, "error-end", types.JobStatusFailed)

	return nil
}

// consumeQueue consumes messages from a specific queue and updates job status
func (c *ResultConsumer) consumeQueue(ctx context.Context, queueName string, status types.JobStatus) {
	slog.Info("Starting consumer", "queue", queueName)

	for {
		select {
		case <-ctx.Done():
			slog.Info("Stopping consumer", "queue", queueName)
			return
		default:
			// Receive message from queue (blocks until message available or context cancelled)
			msg, err := c.queueClient.Receive(ctx, queueName)
			if err != nil {
				// Check if context was cancelled
				if ctx.Err() != nil {
					return
				}
				slog.Error("Error receiving from queue", "queue", queueName, "error", err)
				continue
			}

			slog.Debug("Received message", "queue", queueName, "body", string(msg.Body()[:min(len(msg.Body()), 200)]))

			// Process the message
			c.processMessage(ctx, msg, status)
		}
	}
}

// processMessage processes a message and updates the job status
func (c *ResultConsumer) processMessage(ctx context.Context, msg queue.QueueMessage, status types.JobStatus) {
	defer func() {
		if err := c.queueClient.Ack(ctx, msg); err != nil {
			slog.Error("Failed to ack message", "error", err)
		}
	}()

	slog.Debug("Processing message", "status", status)

	// Check if this is an error message with original_message wrapped
	var errorWrapper struct {
		Error           string `json:"error"`
		OriginalMessage string `json:"original_message"`
	}

	var wrappedError string
	messageBody := msg.Body()
	if err := json.Unmarshal(messageBody, &errorWrapper); err == nil && errorWrapper.OriginalMessage != "" {
		// This is a wrapped error message, extract the original and preserve error
		slog.Debug("Unwrapping error message", "error", errorWrapper.Error)
		wrappedError = errorWrapper.Error
		messageBody = []byte(errorWrapper.OriginalMessage)
	}

	// Parse the message to extract job ID and result
	var message struct {
		JobID string `json:"job_id"` // Top-level field (from initial message)
		Route struct {
			Steps    []string               `json:"steps"`
			Current  int                    `json:"current"`
			Metadata map[string]interface{} `json:"metadata"`
		} `json:"route"`
		Payload map[string]interface{} `json:"payload"` // Result payload
	}

	if err := json.Unmarshal(messageBody, &message); err != nil {
		slog.Error("Failed to parse message", "error", err)
		return
	}

	// Extract job ID - try top-level first, then route metadata
	jobID := message.JobID
	if jobID == "" && message.Route.Metadata != nil {
		if id, ok := message.Route.Metadata["job_id"].(string); ok {
			jobID = id
		}
	}

	if jobID == "" {
		slog.Error("No job_id in message, skipping", "body", string(msg.Body()[:min(len(msg.Body()), 200)]))
		return
	}

	slog.Debug("Extracted job_id from message", "job", jobID)

	// Extract result payload
	var result interface{} = message.Payload
	if result == nil {
		result = map[string]interface{}{}
	}

	// Update job status
	update := types.JobUpdate{
		JobID:     jobID,
		Status:    status,
		Result:    result,
		Timestamp: time.Now(),
	}

	if status == types.JobStatusSucceeded {
		update.Message = "Job completed successfully"
		slog.Debug("Marking job as Succeeded", "job", jobID)
	} else {
		update.Message = "Job failed"
		// Use wrapped error if available, otherwise try to extract from payload
		if wrappedError != "" {
			update.Error = wrappedError
		} else if errMsg, ok := message.Payload["error"].(string); ok {
			update.Error = errMsg
		}
		slog.Debug("Marking job as Failed", "job", jobID, "error", update.Error)
	}

	slog.Debug("Updating job with final status", "job", jobID, "status", status, "result", result)

	if err := c.jobStore.Update(update); err != nil {
		slog.Error("Failed to update job", "job", jobID, "error", err)
		return
	}

	slog.Debug("Job successfully updated to final status", "job", jobID, "status", status)

	slog.Info("Job marked as final status", "job", jobID, "status", status)
}
