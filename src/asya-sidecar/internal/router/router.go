package router

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/progress"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
)

// Router handles message routing between queues and runtime client
type Router struct {
	cfg              *config.Config
	transport        transport.Transport
	runtimeClient    *runtime.Client
	sidecarQueue     string
	happyEndQueue    string
	errorEndQueue    string
	metrics          *metrics.Metrics
	progressReporter *progress.Reporter
}

// NewRouter creates a new router instance
func NewRouter(cfg *config.Config, transport transport.Transport, runtimeClient *runtime.Client, m *metrics.Metrics) *Router {
	var progressReporter *progress.Reporter
	if cfg.GatewayURL != "" {
		progressReporter = progress.NewReporter(cfg.GatewayURL, cfg.ActorName)
	}

	return &Router{
		cfg:              cfg,
		transport:        transport,
		runtimeClient:    runtimeClient,
		sidecarQueue:     cfg.QueueName,
		happyEndQueue:    cfg.HappyEndQueue,
		errorEndQueue:    cfg.ErrorEndQueue,
		metrics:          m,
		progressReporter: progressReporter,
	}
}

// ProcessMessage handles a single message from the queue
func (r *Router) ProcessMessage(ctx context.Context, msg transport.QueueMessage) error {
	startTime := time.Now()

	// Increment active messages
	if r.metrics != nil {
		r.metrics.IncrementActiveMessages()
		defer r.metrics.DecrementActiveMessages()
	}

	slog.Debug("Processing message", "msgID", msg.ID)

	// Record message size
	if r.metrics != nil {
		r.metrics.RecordMessageSize("received", len(msg.Body))
	}

	// Parse message
	var message messages.Message
	if err := json.Unmarshal(msg.Body, &message); err != nil {
		slog.Error("Failed to parse message", "error", err)

		// Record metrics
		if r.metrics != nil {
			r.metrics.RecordMessageFailed(r.sidecarQueue, "parse_error")
			r.metrics.RecordProcessingDuration(r.sidecarQueue, time.Since(startTime))
		}

		// Send to error queue with parsing error
		return r.sendToErrorQueue(ctx, msg.Body, fmt.Sprintf("Failed to parse message: %v", err))
	}

	// Report progress: message received
	if r.progressReporter != nil {
		messageSizeKB := float64(len(msg.Body)) / 1024.0
		r.progressReporter.ReportProgress(ctx, message.JobID, progress.ProgressUpdate{
			Step:          message.Route.GetCurrentStep(),
			StepIndex:     message.Route.Current,
			TotalSteps:    len(message.Route.Steps),
			Status:        progress.StatusReceived,
			Message:       fmt.Sprintf("Received message (%.2f KB)", messageSizeKB),
			MessageSizeKB: &messageSizeKB,
		})
	}

	// Validate current step
	currentStep := message.Route.GetCurrentStep()
	if currentStep != r.sidecarQueue {
		slog.Warn("Route mismatch: message routed to wrong queue",
			"expected", r.sidecarQueue, "actual", currentStep, "jobID", message.JobID)
	}

	// Report progress: processing
	if r.progressReporter != nil {
		r.progressReporter.ReportProgress(ctx, message.JobID, progress.ProgressUpdate{
			Step:       currentStep,
			StepIndex:  message.Route.Current,
			TotalSteps: len(message.Route.Steps),
			Status:     progress.StatusProcessing,
			Message:    fmt.Sprintf("Processing in %s", r.cfg.ActorName),
		})
	}

	// Send full message to runtime
	runtimeStart := time.Now()
	// TODO: implement timeout here
	responses, err := r.runtimeClient.CallRuntime(ctx, msg.Body)
	runtimeDuration := time.Since(runtimeStart)

	slog.Debug("Runtime call completed",
		"jobID", message.JobID,
		"duration", runtimeDuration,
		"responses", len(responses),
		"error", err)

	if r.metrics != nil {
		r.metrics.RecordRuntimeDuration(r.sidecarQueue, runtimeDuration)
	}
	if err != nil {
		slog.Error("Runtime calling error", "error", err)

		// Record metrics
		if r.metrics != nil {
			r.metrics.RecordMessageFailed(r.sidecarQueue, "runtime_error")
			r.metrics.RecordRuntimeError(r.sidecarQueue, "execution_error")
			r.metrics.RecordProcessingDuration(r.sidecarQueue, time.Since(startTime))
		}

		// Send to error queue
		return r.sendToErrorQueue(ctx, msg.Body, err.Error())
	}

	// Handle responses
	if len(responses) == 0 {
		// Empty response - abort execution, send to happy-end
		// This signals early termination with success (e.g., conditional processing that decides to skip)
		slog.Info("Empty response from runtime, routing to happy-end", "jobID", message.JobID)

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.sidecarQueue, "empty_response")
			r.metrics.RecordProcessingDuration(r.sidecarQueue, time.Since(startTime))
		}

		return r.sendToHappyQueue(ctx, message)
	}

	// Terminal actor mode: do NOT route responses
	// Terminal actors (happy-end, error-end) consume messages but don't produce new routing
	if r.cfg.IsTerminal {
		slog.Debug("Terminal actor consumed message", "jobID", message.JobID, "queue", r.sidecarQueue)

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.sidecarQueue, "terminal_consumed")
			r.metrics.RecordProcessingDuration(r.sidecarQueue, time.Since(startTime))
		}

		return nil
	}

	// Fan-out or single: send each response to its destination
	for i, response := range responses {
		slog.Debug("Processing response", "index", i+1, "total", len(responses))
		if response.IsError() {
			if err := r.sendToErrorQueue(ctx, msg.Body, response.Error, response.Details); err != nil {
				slog.Error("Failed to send error to error queue", "error", err)
				if r.metrics != nil {
					r.metrics.RecordMessageFailed(r.sidecarQueue, "error_queue_send_failed")
					r.metrics.RecordProcessingDuration(r.sidecarQueue, time.Since(startTime))
				}
				return fmt.Errorf("failed to send error to error queue: %w", err)
			}
			if r.metrics != nil {
				r.metrics.RecordMessageFailed(r.sidecarQueue, "runtime_error")
				r.metrics.RecordProcessingDuration(r.sidecarQueue, time.Since(startTime))
			}
			return nil
		}

		// Report progress: completed processing (only for successful responses, once per step)
		if i == 0 && r.progressReporter != nil {
			durationMs := runtimeDuration.Milliseconds()
			r.progressReporter.ReportProgress(ctx, message.JobID, progress.ProgressUpdate{
				Step:       currentStep,
				StepIndex:  message.Route.Current,
				TotalSteps: len(message.Route.Steps),
				Status:     progress.StatusCompleted,
				Message:    fmt.Sprintf("Completed processing in %dms", durationMs),
				DurationMs: &durationMs,
			})
		}

		// Validate route before incrementing
		currentStep := response.Route.GetCurrentStep()
		if currentStep != r.sidecarQueue {
			slog.Warn("Runtime outputed route with current step not matching the actor's queue name",
				"currentStep", currentStep, "expected", r.sidecarQueue, "actor", r.cfg.ActorName)
		}

		// Increment route current index before routing to next step
		incrementedRoute := response.Route.IncrementCurrent()
		// TODO: protect from loops
		if err := r.routeResponse(ctx, message.JobID, incrementedRoute, response.Payload); err != nil {
			if r.metrics != nil {
				r.metrics.RecordMessageFailed(r.sidecarQueue, "routing_error")
				r.metrics.RecordProcessingDuration(r.sidecarQueue, time.Since(startTime))
			}
			return fmt.Errorf("failed to route response %d: %w", i, err)
		}
	}

	// Success
	if r.metrics != nil {
		r.metrics.RecordMessageProcessed(r.sidecarQueue, "success")
		r.metrics.RecordProcessingDuration(r.sidecarQueue, time.Since(startTime))
	}

	return nil
}

// routeResponse routes a single response to the appropriate queue
// The route parameter should already have its Current index incremented by the caller
func (r *Router) routeResponse(ctx context.Context, jobID string, route messages.Route, payload json.RawMessage) error {
	// Create new message with the provided route (already incremented)
	newMessage := messages.Message{
		JobID:   jobID, // Propagate job_id
		Route:   route,
		Payload: payload,
	}

	// Determine destination queue
	var destinationQueue string
	var messageType string
	stepToSend := route.GetCurrentStep() // should already point to next step
	if stepToSend != "" {
		destinationQueue = stepToSend
		messageType = "routing"
	} else {
		// No more steps, send to happy-end
		destinationQueue = r.happyEndQueue
		messageType = "happy_end"
	}

	// Marshal message
	messageBody, err := json.Marshal(newMessage)
	if err != nil {
		return fmt.Errorf("failed to marshal message: %w", err)
	}

	// Record message size
	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(messageBody))
	}

	// Send to destination queue
	sendStart := time.Now()
	slog.Debug("Sending message to queue", "queue", destinationQueue)
	err = r.transport.Send(ctx, destinationQueue, messageBody)
	sendDuration := time.Since(sendStart)

	// Record metrics
	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(destinationQueue, "rabbitmq", sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(destinationQueue, messageType)
		}
	}

	return err
}

// sendToHappyQueue sends the original message to the happy-end queue
func (r *Router) sendToHappyQueue(ctx context.Context, message messages.Message) error {
	messageBody, err := json.Marshal(message)
	if err != nil {
		return fmt.Errorf("failed to marshal message for happy-end: %w", err)
	}

	// Record message size
	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(messageBody))
	}

	// Send to happy-end queue
	sendStart := time.Now()
	err = r.transport.Send(ctx, r.happyEndQueue, messageBody)
	sendDuration := time.Since(sendStart)

	// Record metrics
	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(r.happyEndQueue, "rabbitmq", sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(r.happyEndQueue, "happy_end")
		}
	}

	return err
}

// sendToErrorQueue sends an error message to the error-end queue
func (r *Router) sendToErrorQueue(ctx context.Context, originalBody []byte, errorMsg string, errorDetails ...runtime.ErrorDetails) error {
	// Parse original message to extract job_id
	var originalMsg messages.Message
	jobID := ""
	if err := json.Unmarshal(originalBody, &originalMsg); err == nil {
		jobID = originalMsg.JobID
	}

	// Build error message
	errorMessage := map[string]any{
		"job_id":           jobID,
		"error":            errorMsg,
		"original_message": string(originalBody),
	}
	if len(errorDetails) > 0 {
		errorMessage["error_details"] = errorDetails[0]
	}

	messageBody, err := json.Marshal(errorMessage)
	if err != nil {
		return fmt.Errorf("failed to marshal error message: %w", err)
	}

	// Record message size
	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(messageBody))
	}

	// Send to error queue
	sendStart := time.Now()
	err = r.transport.Send(ctx, r.errorEndQueue, messageBody)
	sendDuration := time.Since(sendStart)

	// Record metrics
	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(r.errorEndQueue, "rabbitmq", sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(r.errorEndQueue, "error_end")
		}
	}

	return err
}

// Run starts the message processing loop
func (r *Router) Run(ctx context.Context) error {
	slog.Info("Starting router", "queue", r.sidecarQueue)

	for {
		select {
		case <-ctx.Done():
			slog.Info("Router shutting down", "reason", ctx.Err())
			return ctx.Err()
		default:
			// Receive message from queue
			receiveStart := time.Now()
			msg, err := r.transport.Receive(ctx, r.sidecarQueue)
			receiveDuration := time.Since(receiveStart)

			if err != nil {
				slog.Error("Failed to receive message", "error", err)
				continue
			}

			// Record receive metrics
			if r.metrics != nil {
				r.metrics.RecordMessageReceived(r.sidecarQueue, "rabbitmq")
				r.metrics.RecordQueueReceiveDuration(r.sidecarQueue, "rabbitmq", receiveDuration)
			}

			// Process message
			if err := r.ProcessMessage(ctx, msg); err != nil {
				slog.Error("Message processing failed", "msgID", msg.ID, "error", err)
				// NACK the message for retry
				if nackErr := r.transport.Nack(ctx, msg); nackErr != nil {
					slog.Error("Failed to NACK message", "msgID", msg.ID, "error", nackErr)
				}
				continue
			}

			// ACK the message on success
			if err := r.transport.Ack(ctx, msg); err != nil {
				slog.Error("Failed to ACK message", "msgID", msg.ID, "error", err)
			}
		}
	}
}
