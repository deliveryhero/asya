package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
)

// Worker processes DLQ messages in a continuous loop.
//
// Processing pipeline per message:
//  1. Receive message from DLQ
//  2. Parse message body to extract message ID
//  3. Report failure status to gateway (best-effort)
//  4. Persist full message to S3 (required before ACK)
//  5. ACK message from DLQ
type Worker struct {
	consumer Consumer
	gateway  GatewayReporter
	storage  Storage
}

// NewWorker creates a DLQ worker with the given dependencies.
func NewWorker(consumer Consumer, gateway GatewayReporter, storage Storage) *Worker {
	return &Worker{
		consumer: consumer,
		gateway:  gateway,
		storage:  storage,
	}
}

// Run starts the DLQ processing loop. Blocks until context is cancelled.
// Returns nil on graceful shutdown (context.Canceled) and only returns
// an error for unexpected conditions (e.g. context.DeadlineExceeded).
func (w *Worker) Run(ctx context.Context) error {
	slog.Info("DLQ worker started, polling for messages")

	for {
		select {
		case <-ctx.Done():
			slog.Info("DLQ worker shutting down")
			if errors.Is(ctx.Err(), context.Canceled) {
				return nil
			}
			return ctx.Err()
		default:
		}

		if err := w.processOne(ctx); err != nil {
			if errors.Is(err, context.Canceled) {
				return nil
			}
			if errors.Is(err, context.DeadlineExceeded) {
				return err
			}
			slog.Error("Failed to process DLQ message", "error", err)
		}
	}
}

// processOne receives and processes a single DLQ message.
func (w *Worker) processOne(ctx context.Context) error {
	msg, err := w.consumer.Receive(ctx)
	if err != nil {
		return err
	}

	slog.Info("Received DLQ message", "body_size", len(msg.Body))

	// Parse message to extract ID
	messageID, err := extractMessageID(msg.Body)
	if err != nil {
		// Malformed message: log full body for debugging, ACK to prevent infinite redelivery
		slog.Error("Failed to parse DLQ message, ACKing to prevent redelivery loop",
			"error", err, "body", string(msg.Body))
		if ackErr := w.consumer.Ack(ctx, msg); ackErr != nil {
			slog.Error("Failed to ACK malformed message", "error", ackErr)
		}
		return nil
	}

	slog.Info("Processing DLQ message", "message_id", messageID)

	// Report failure to gateway (best-effort)
	if reportErr := w.gateway.ReportFailure(ctx, messageID, "Message moved to DLQ after transport-level delivery failures"); reportErr != nil {
		slog.Warn("Failed to report DLQ failure to gateway (continuing)",
			"message_id", messageID, "error", reportErr)
	}

	// Persist to S3 (required before ACK)
	if persistErr := w.storage.Persist(ctx, messageID, msg.Body); persistErr != nil {
		slog.Error("Failed to persist DLQ message to S3, will retry on next delivery",
			"message_id", messageID, "error", persistErr)
		return persistErr
	}

	// ACK the message from DLQ
	if ackErr := w.consumer.Ack(ctx, msg); ackErr != nil {
		slog.Error("Failed to ACK DLQ message after successful persistence",
			"message_id", messageID, "error", ackErr)
		return ackErr
	}

	slog.Info("DLQ message processed successfully", "message_id", messageID)
	return nil
}

// extractMessageID parses the message body and extracts the "id" field.
func extractMessageID(body []byte) (string, error) {
	var envelope struct {
		ID string `json:"id"`
	}

	if err := json.Unmarshal(body, &envelope); err != nil {
		return "", err
	}

	if envelope.ID == "" {
		return "", errors.New("message has no 'id' field")
	}

	return envelope.ID, nil
}
