package consumer

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ResultConsumer consumes tasks from x-sink and x-sump queues
// and updates task status accordingly
type ResultConsumer struct {
	queueClient queue.Client
	taskStore   taskstore.TaskStore
}

// NewResultConsumer creates a new result consumer
func NewResultConsumer(queueClient queue.Client, taskStore taskstore.TaskStore) *ResultConsumer {
	return &ResultConsumer{
		queueClient: queueClient,
		taskStore:   taskStore,
	}
}

// Start starts consuming from x-sink and x-sump queues
func (c *ResultConsumer) Start(ctx context.Context) error {
	slog.Info("Starting result consumer for end queues")

	// Start consumer for x-sink queue
	go c.consumeQueue(ctx, "x-sink", types.TaskStatusSucceeded)

	// Start consumer for x-sump queue
	go c.consumeQueue(ctx, "x-sump", types.TaskStatusFailed)

	return nil
}

// consumeQueue consumes tasks from a specific queue and updates task status
func (c *ResultConsumer) consumeQueue(ctx context.Context, queueName string, status types.TaskStatus) {
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

			slog.Debug("Received task", "queue", queueName, "body", string(msg.Body()[:min(len(msg.Body()), 200)]))

			// Process the task
			c.processMessage(ctx, msg, status)
		}
	}
}

// processMessage processes a task and updates the task status
func (c *ResultConsumer) processMessage(ctx context.Context, msg queue.QueueMessage, status types.TaskStatus) {
	defer func() {
		if err := c.queueClient.Ack(ctx, msg); err != nil {
			slog.Error("Failed to ack task", "error", err)
		}
	}()

	slog.Debug("Processing task", "status", status)

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
	}

	if err := json.Unmarshal(msg.Body(), &parsedMsg); err != nil {
		slog.Error("Failed to parse task", "error", err)
		return
	}

	// Extract task ID from top-level field
	taskID := parsedMsg.ID

	if taskID == "" {
		slog.Error("No task ID found, skipping", "body", string(msg.Body()[:min(len(msg.Body()), 200)]))
		return
	}

	slog.Debug("Extracted task ID", "id", taskID)

	// Extract result payload
	var result interface{} = parsedMsg.Payload
	if parsedMsg.Payload == nil {
		result = map[string]interface{}{}
	}

	// Update task status
	update := types.TaskUpdate{
		ID:        taskID,
		Status:    status,
		Result:    result,
		Timestamp: time.Now(),
	}

	if status == types.TaskStatusSucceeded {
		update.Message = "Task completed successfully"
		slog.Debug("Marking task as Succeeded", "id", taskID)
	} else {
		update.Message = "Task failed"
		// Extract error from top level (flat format)
		if parsedMsg.Error != "" {
			update.Error = parsedMsg.Error
			// Include error details if available
			if parsedMsg.Details.Message != "" {
				update.Error = fmt.Sprintf("%s: %s", parsedMsg.Error, parsedMsg.Details.Message)
			}
		}
		slog.Debug("Marking task as Failed", "id", taskID, "error", update.Error)
	}

	slog.Debug("Updating task with final status", "id", taskID, "status", status, "result", result)

	if err := c.taskStore.Update(update); err != nil {
		slog.Error("Failed to update task", "id", taskID, "error", err)
		return
	}

	slog.Debug("Task successfully updated to final status", "id", taskID, "status", status)

	slog.Info("Task marked as final status", "id", taskID, "status", status)
}
