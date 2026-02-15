package router

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"math/rand/v2"
	"net/http"
	"os"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/progress"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
)

const (
	statusSucceeded = "succeeded"
	statusFailed    = "failed"
)

// Router handles message routing between queues and runtime client
type Router struct {
	cfg              *config.Config
	transport        transport.Transport
	runtimeClient    *runtime.Client
	actorName        string
	sinkQueue        string
	sumpQueue        string
	metrics          *metrics.Metrics
	progressReporter *progress.Reporter
	gatewayURL       string
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
		actorName:        cfg.ActorName,
		sinkQueue:        cfg.SinkQueue,
		sumpQueue:        cfg.SumpQueue,
		metrics:          m,
		progressReporter: progressReporter,
		gatewayURL:       cfg.GatewayURL,
	}
}

// ensureAndUpdateStatus initializes or updates the status on a message before processing.
// If status is nil, creates a default with phase=processing.
// If status exists, transitions to processing phase and updates actor/timestamps.
// MaxAttempts is set from the resiliency config when available.
func (r *Router) ensureAndUpdateStatus(msg *messages.Message) {
	now := time.Now().UTC().Format(time.RFC3339)
	maxAttempts := r.maxAttempts()

	if msg.Status == nil {
		msg.Status = &messages.Status{
			Phase:       messages.PhaseProcessing,
			Actor:       r.actorName,
			Attempt:     1,
			MaxAttempts: maxAttempts,
			CreatedAt:   now,
			UpdatedAt:   now,
		}
		return
	}

	// Reset attempt counter when transitioning between actors
	if msg.Status.Actor != r.actorName {
		msg.Status.Attempt = 1
	}

	msg.Status.Phase = messages.PhaseProcessing
	msg.Status.Reason = ""
	msg.Status.Actor = r.actorName
	msg.Status.MaxAttempts = maxAttempts
	msg.Status.UpdatedAt = now
	msg.Status.Error = nil
}

// maxAttempts returns the max retry attempts from resiliency config, or 1 if not configured.
func (r *Router) maxAttempts() int {
	if r.cfg != nil && r.cfg.Resiliency != nil {
		return r.cfg.Resiliency.Retry.MaxAttempts
	}
	return 1
}

// processEndActorMessage handles message processing for end actors (x-sink, x-sump)
// End actors are terminal nodes that:
// - Accept messages with ANY route state (no validation)
// - Process the message through runtime
// - Do NOT route responses anywhere (terminal processing)
// - Report final status to gateway
func (r *Router) processEndActorMessage(ctx context.Context, msg messages.Message, msgBody []byte, startTime time.Time) error {
	slog.Debug("End actor processing message", "id", msg.ID, "actor", r.actorName)

	// IMPORTANT: End actors are terminal - they do NOT route to any queue
	// and do NOT increment route.current. They only:
	// 1. Process the message via runtime
	// 2. Report final status to gateway
	// End actors run in message mode with validation disabled.
	// They typically return empty dict {}, which is ignored by the sidecar.

	// Send to runtime without route validation
	runtimeStart := time.Now()
	responses, err := r.runtimeClient.CallRuntime(ctx, msgBody)
	runtimeDuration := time.Since(runtimeStart)

	if r.metrics != nil {
		r.metrics.RecordRuntimeDuration(r.actorName, runtimeDuration)
	}

	if err != nil {
		slog.Error("End actor runtime error", "id", msg.ID, "error", err)
		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "runtime_error")
			r.metrics.RecordRuntimeError(r.actorName, "execution_error")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}

		if errors.Is(err, context.DeadlineExceeded) {
			slog.Error("End actor runtime timeout exceeded - crashing pod to recover",
				"timeout", r.cfg.Timeout, "message", msg.ID)

			if r.progressReporter != nil {
				errorCtx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
				defer cancel()
				_ = r.progressReporter.ReportFinalError(errorCtx, msg.ID, "Runtime timeout exceeded")
			}

			slog.Error("Exiting to prevent zombie processing (runtime may still be working)")
			os.Exit(1)
		}

		return fmt.Errorf("runtime error in end actor: %w", err)
	}

	// Record success metrics
	if r.metrics != nil {
		r.metrics.RecordMessageProcessed(r.actorName, "end_consumed")
		r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
	}

	// Extract result payload from runtime response
	// End handlers should return empty dict, so we use the original message payload as result
	var resultPayload json.RawMessage
	if len(responses) > 0 && len(responses[0].Payload) > 0 {
		// Runtime returned a payload, use it
		resultPayload = responses[0].Payload
	} else {
		// Runtime returned empty/null, use original message payload as result
		resultPayload = msg.Payload
	}

	// Report final status to gateway if configured
	if r.progressReporter != nil {
		if err := r.reportFinalStatusWithMessage(ctx, &msg, resultPayload, runtimeDuration); err != nil {
			slog.Warn("Failed to report final status to gateway", "id", msg.ID, "error", err)
		}
	}

	slog.Debug("End actor completed processing", "id", msg.ID, "actor", r.actorName)
	return nil
}

// parseAndValidateMessage parses and validates the message from message body
func (r *Router) parseAndValidateMessage(ctx context.Context, msgBody []byte, startTime time.Time) (*messages.Message, error) {
	var msg messages.Message
	if err := json.Unmarshal(msgBody, &msg); err != nil {
		slog.Error("Failed to parse message", "error", err)

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "parse_error")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}

		_ = r.sendToSumpQueue(ctx, msgBody, fmt.Sprintf("Failed to parse message: %v", err))
		return nil, err
	}

	if msg.ID == "" {
		slog.Error("Message missing required ID field")

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "validation_error")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}

		_ = r.sendToSumpQueue(ctx, msgBody, "Message missing required 'id' field")
		return nil, fmt.Errorf("message missing required 'id' field")
	}

	slog.Info("Message parsed and validated", "id", msg.ID, "route", msg.Route)
	return &msg, nil
}

// handleRuntimeResponses processes runtime responses and routes them to appropriate destinations
func (r *Router) handleRuntimeResponses(ctx context.Context, msg *messages.Message, responses []runtime.RuntimeResponse, _ []byte, runtimeDuration time.Duration, startTime time.Time) error {
	if len(responses) == 0 {
		slog.Info("Empty response from runtime, routing to x-sink", "id", msg.ID)

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "empty_response")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}

		return r.sendToSinkQueue(ctx, *msg)
	}

	for i, response := range responses {
		slog.Debug("Processing response", "index", i+1, "total", len(responses))

		if response.IsError() {
			return r.handleErrorResponse(ctx, msg, response, startTime)
		}

		if err := r.handleSuccessResponse(ctx, msg, response, i, len(responses), runtimeDuration); err != nil {
			if r.metrics != nil {
				r.metrics.RecordMessageFailed(r.actorName, "routing_error")
				r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
			}
			return fmt.Errorf("failed to route response %d: %w", i, err)
		}
	}

	if r.metrics != nil {
		r.metrics.RecordMessageProcessed(r.actorName, "success")
		r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
	}

	return nil
}

// handleErrorResponse handles error responses from runtime with retry logic.
// When resiliency is configured, it checks whether the error is retryable and
// whether retry attempts remain before deciding to retry or fail permanently.
func (r *Router) handleErrorResponse(ctx context.Context, msg *messages.Message, response runtime.RuntimeResponse, startTime time.Time) error {
	// Check for flow-level _on_error header — bypasses retry logic
	if onError, ok := msg.Headers["_on_error"].(string); ok && onError != "" {
		return r.routeToFlowErrorHandler(ctx, msg, onError, response, startTime)
	}

	// No resiliency configured — fail immediately (legacy behavior)
	if r.cfg.Resiliency == nil || r.cfg.Resiliency.Retry.MaxAttempts <= 1 {
		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "runtime_error")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}
		return r.sendRetryFailure(ctx, msg, response, messages.ReasonRuntimeError)
	}

	// Check MRO-based non-retryable error classification
	if r.isNonRetryableError(response.Details.Type, response.Details.MRO) {
		slog.Info("Non-retryable error detected, routing to x-sump",
			"id", msg.ID, "type", response.Details.Type,
			"attempt", msg.Status.Attempt, "max_attempts", msg.Status.MaxAttempts)

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "non_retryable_error")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}
		return r.sendRetryFailure(ctx, msg, response, messages.ReasonNonRetryableFailure)
	}

	// Check if max attempts exhausted
	if msg.Status.Attempt >= r.cfg.Resiliency.Retry.MaxAttempts {
		slog.Info("Max retry attempts exhausted, routing to x-sump",
			"id", msg.ID, "attempt", msg.Status.Attempt,
			"max_attempts", r.cfg.Resiliency.Retry.MaxAttempts)

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "max_retries_exhausted")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}
		return r.sendRetryFailure(ctx, msg, response, messages.ReasonMaxRetriesExhausted)
	}

	// Retry: compute delay, update status, send with delay to own queue
	delay := r.computeRetryDelay(msg.Status.Attempt)
	slog.Info("Retrying message with backoff",
		"id", msg.ID,
		"attempt", msg.Status.Attempt,
		"max_attempts", r.cfg.Resiliency.Retry.MaxAttempts,
		"delay", delay,
		"error_type", response.Details.Type)

	if err := r.retryMessage(ctx, msg, response.Details, delay); err != nil {
		slog.Error("Failed to send retry message, routing to x-sump",
			"id", msg.ID, "error", err)
		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "retry_send_failed")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}
		return r.sendRetryFailure(ctx, msg, response, messages.ReasonRuntimeError)
	}

	if r.metrics != nil {
		r.metrics.RecordMessageProcessed(r.actorName, "retried")
		r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
	}
	return nil
}

// isNonRetryableError checks if the error type or any of its MRO ancestors
// matches the configured nonRetryableErrors blacklist.
func (r *Router) isNonRetryableError(errorType string, mro []string) bool {
	if r.cfg.Resiliency == nil || len(r.cfg.Resiliency.NonRetryableErrors) == 0 {
		return false
	}

	typesToCheck := make(map[string]struct{}, len(mro)+1)
	typesToCheck[errorType] = struct{}{}
	for _, ancestor := range mro {
		typesToCheck[ancestor] = struct{}{}
	}

	for _, nonRetryable := range r.cfg.Resiliency.NonRetryableErrors {
		if _, ok := typesToCheck[nonRetryable]; ok {
			return true
		}
	}

	return false
}

// computeRetryDelay calculates the backoff delay for the given failed attempt.
// Formula: delay = min(initialInterval * backoffCoefficient^(attempt-1), maxInterval)
// If jitter is enabled: delay *= random(0.5, 1.5)
func (r *Router) computeRetryDelay(failedAttempt int) time.Duration {
	retryCfg := r.cfg.Resiliency.Retry

	var delay time.Duration
	switch retryCfg.Policy {
	case config.RetryPolicyConstant:
		delay = retryCfg.InitialInterval
	case config.RetryPolicyExponential:
		exponent := failedAttempt - 1
		multiplier := math.Pow(retryCfg.BackoffCoefficient, float64(exponent))
		delay = time.Duration(float64(retryCfg.InitialInterval) * multiplier)
	default:
		delay = retryCfg.InitialInterval
	}

	if delay > retryCfg.MaxInterval {
		delay = retryCfg.MaxInterval
	}

	if retryCfg.Jitter {
		jitterFactor := 0.5 + rand.Float64() // [0.5, 1.5)
		delay = time.Duration(float64(delay) * jitterFactor)
	}

	return delay
}

// retryMessage sends the message back to the actor's own queue with a delay.
// Updates the message status to reflect the retry state.
func (r *Router) retryMessage(ctx context.Context, msg *messages.Message, details runtime.ErrorDetails, delay time.Duration) error {
	now := time.Now().UTC().Format(time.RFC3339)
	msg.Status.Phase = messages.PhaseRetrying
	msg.Status.UpdatedAt = now
	msg.Status.Error = &messages.StatusError{
		Type:      details.Type,
		MRO:       details.MRO,
		Message:   details.Message,
		Traceback: details.Traceback,
	}
	// Increment attempt for the next processing cycle
	msg.Status.Attempt++

	body, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("failed to marshal retry message: %w", err)
	}

	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(body))
	}

	queueName := r.resolveQueueName(r.actorName)
	return r.transport.SendWithDelay(ctx, queueName, body, delay)
}

// sendRetryFailure sends a failed message to the x-sump queue with proper
// retry status information (attempt count, reason, error details).
func (r *Router) sendRetryFailure(ctx context.Context, msg *messages.Message, response runtime.RuntimeResponse, reason string) error {
	now := time.Now().UTC().Format(time.RFC3339)

	// Build error payload (backward compatible with x-sump actor)
	errorPayload := map[string]any{
		"error": response.Error,
	}
	if response.Details.Message != "" || response.Details.Type != "" {
		errorPayload["details"] = response.Details
	}
	if msg.Payload != nil {
		var original any
		if err := json.Unmarshal(msg.Payload, &original); err == nil {
			errorPayload["original_payload"] = original
		}
	}

	payloadBytes, err := json.Marshal(errorPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal error payload: %w", err)
	}

	createdAt := now
	if msg.Status != nil && msg.Status.CreatedAt != "" {
		createdAt = msg.Status.CreatedAt
	}

	attempt := 1
	if msg.Status != nil {
		attempt = msg.Status.Attempt
	}

	failedMsg := messages.Message{
		ID:       msg.ID,
		ParentID: msg.ParentID,
		Route:    msg.Route,
		Payload:  payloadBytes,
		Status: &messages.Status{
			Phase:       messages.PhaseFailed,
			Reason:      reason,
			Actor:       r.actorName,
			Attempt:     attempt,
			MaxAttempts: r.maxAttempts(),
			CreatedAt:   createdAt,
			UpdatedAt:   now,
			Error: &messages.StatusError{
				Type:      response.Details.Type,
				MRO:       response.Details.MRO,
				Message:   response.Details.Message,
				Traceback: response.Details.Traceback,
			},
		},
	}

	body, err := json.Marshal(failedMsg)
	if err != nil {
		return fmt.Errorf("failed to marshal failed message: %w", err)
	}

	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(body))
	}

	sendStart := time.Now()
	sumpQueueName := r.resolveQueueName(r.sumpQueue)
	err = r.transport.Send(ctx, sumpQueueName, body)
	sendDuration := time.Since(sendStart)

	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(r.sumpQueue, r.cfg.TransportType, sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(r.sumpQueue, "sump")
		}
	}

	if err != nil {
		slog.Error("Failed to send to error queue - will requeue for DLQ handling", "error", err)
		if r.metrics != nil {
			r.metrics.RecordMessageFailed(r.actorName, "error_queue_send_failed")
		}
		return fmt.Errorf("failed to send to error queue: %w", err)
	}
	return nil
}

// routeToFlowErrorHandler routes an error to a flow-level error handler (except_dispatch router)
// instead of the error-end queue. This preserves the original payload and sets error details
// in status.error for the except_dispatch router to inspect.
func (r *Router) routeToFlowErrorHandler(ctx context.Context, msg *messages.Message, onError string, response runtime.RuntimeResponse, startTime time.Time) error {
	slog.Info("Routing error to flow error handler", "id", msg.ID, "handler", onError, "error", response.Error)

	// Clear _on_error to prevent infinite error routing loops
	delete(msg.Headers, "_on_error")

	// Update route: truncate after current position and insert error handler
	current := msg.Route.Current
	msg.Route.Actors = append(msg.Route.Actors[:current+1], onError)
	msg.Route.Current = current + 1

	// Set error details in status
	now := time.Now().UTC().Format(time.RFC3339)
	createdAt := now
	if msg.Status != nil && msg.Status.CreatedAt != "" {
		createdAt = msg.Status.CreatedAt
	}
	msg.Status = &messages.Status{
		Phase:       messages.PhaseFailed,
		Actor:       r.actorName,
		Attempt:     1,
		MaxAttempts: 1,
		CreatedAt:   createdAt,
		UpdatedAt:   now,
		Error: &messages.StatusError{
			Message:   response.Details.Message,
			Type:      response.Details.Type,
			Traceback: response.Details.Traceback,
			MRO:       response.Details.MRO,
		},
	}

	// Marshal and send
	msgBody, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("failed to marshal message for flow error handler: %w", err)
	}

	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(msgBody))
	}

	sendStart := time.Now()
	queueName := r.resolveQueueName(onError)
	err = r.transport.Send(ctx, queueName, msgBody)
	sendDuration := time.Since(sendStart)

	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(onError, r.cfg.TransportType, sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(onError, "flow_error_handler")
		}
	}

	if err != nil {
		slog.Error("Failed to send to flow error handler", "id", msg.ID, "handler", onError, "error", err)
		return fmt.Errorf("failed to send to flow error handler: %w", err)
	}

	slog.Info("Routed error to flow error handler", "id", msg.ID, "handler", onError, "queue", queueName)
	return nil
}

// handleSuccessResponse handles successful responses from runtime
func (r *Router) handleSuccessResponse(ctx context.Context, msg *messages.Message, response runtime.RuntimeResponse, index, totalResponses int, runtimeDuration time.Duration) error {
	// Runtime is responsible for incrementing route.current:
	// - In payload mode: runtime auto-increments
	// - In envelope mode: user handler manually increments
	outputRoute := response.Route

	if index == 0 && r.progressReporter != nil {
		durationMs := runtimeDuration.Milliseconds()
		_ = r.progressReporter.ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
			Actors:          outputRoute.Actors,
			CurrentActorIdx: outputRoute.Current,
			Status:          progress.StatusCompleted,
			Message:         fmt.Sprintf("Completed processing in %dms", durationMs),
			DurationMs:      &durationMs,
		})
	}

	msgID := msg.ID
	var parentID *string
	if totalResponses > 1 && index > 0 {
		msgID = fmt.Sprintf("%s-%d", msg.ID, index)
		parentID = &msg.ID
		slog.Debug("Fan-out: generated unique message ID", "original", msg.ID, "fanout", msgID, "index", index)

		if r.progressReporter != nil {
			if err := r.createFanoutMessage(ctx, msgID, *parentID, outputRoute); err != nil {
				slog.Warn("Failed to create fanout message in gateway", "id", msgID, "error", err)
			}
		}
	}

	statusFromRuntime := response.Status
	if statusFromRuntime == nil {
		statusFromRuntime = msg.Status
	}
	return r.routeResponse(ctx, msgID, parentID, outputRoute, response.Payload, statusFromRuntime)
}

// ProcessMessage handles a single message from the queue
func (r *Router) ProcessMessage(ctx context.Context, queueMsg transport.QueueMessage) error {
	startTime := time.Now()

	if r.metrics != nil {
		r.metrics.IncrementActiveMessages()
		defer r.metrics.DecrementActiveMessages()
	}

	if r.metrics != nil {
		r.metrics.RecordMessageSize("received", len(queueMsg.Body))
	}

	msg, err := r.parseAndValidateMessage(ctx, queueMsg.Body, startTime)
	if err != nil {
		slog.Error("Failed to parse/validate message, sent to error queue", "error", err)
		return nil
	}

	if r.cfg.IsEndActor {
		return r.processEndActorMessage(ctx, *msg, queueMsg.Body, startTime)
	}

	if r.progressReporter != nil {
		msgSizeKB := float64(len(queueMsg.Body)) / 1024.0
		_ = r.progressReporter.ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
			Actors:          msg.Route.Actors,
			CurrentActorIdx: msg.Route.Current,
			Status:          progress.StatusReceived,
			Message:         fmt.Sprintf("Received message (%.2f KB)", msgSizeKB),
			MessageSizeKB:   &msgSizeKB,
		})
	}

	currentActor := msg.Route.GetCurrentActor()
	if currentActor != r.cfg.ActorName {
		slog.Warn("Route mismatch: message routed to wrong actor",
			"expected", r.cfg.ActorName, "actual", currentActor, "id", msg.ID)

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "route_mismatch")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}

		errorMsg := fmt.Sprintf("Route mismatch: message routed to wrong actor (expected: %s, actual: %s)",
			r.cfg.ActorName, currentActor)
		_ = r.sendToSumpQueue(ctx, queueMsg.Body, errorMsg)
		return nil
	}

	if r.progressReporter != nil {
		_ = r.progressReporter.ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
			Actors:          msg.Route.Actors,
			CurrentActorIdx: msg.Route.Current,
			Status:          progress.StatusProcessing,
			Message:         fmt.Sprintf("Processing in %s", r.cfg.ActorName),
		})
	}

	// Initialize or update status before calling runtime
	r.ensureAndUpdateStatus(msg)
	updatedBody, err := json.Marshal(msg)
	if err != nil {
		slog.Error("Failed to marshal message with status", "id", msg.ID, "error", err)
		return fmt.Errorf("failed to marshal message with status: %w", err)
	}

	slog.Info("Calling runtime", "id", msg.ID, "actor", r.cfg.ActorName)
	runtimeStart := time.Now()
	responses, err := r.runtimeClient.CallRuntime(ctx, updatedBody)
	runtimeDuration := time.Since(runtimeStart)

	if err != nil {
		slog.Info("Runtime call failed", "id", msg.ID, "duration", runtimeDuration, "error", err)
	} else {
		slog.Info("Runtime call completed", "id", msg.ID, "duration", runtimeDuration, "responses", len(responses))
	}

	if r.metrics != nil {
		r.metrics.RecordRuntimeDuration(r.actorName, runtimeDuration)
	}

	if err != nil {
		slog.Error("Runtime calling error", "error", err)

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "error")
			r.metrics.RecordMessageFailed(r.actorName, "runtime_error")
			r.metrics.RecordRuntimeError(r.actorName, "execution_error")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}

		// Check for timeout to provide better error message
		isTimeout := errors.Is(err, context.DeadlineExceeded) || errors.Is(err, os.ErrDeadlineExceeded)
		errorMsg := err.Error()
		if isTimeout {
			slog.Error("Runtime timeout exceeded - crashing pod to recover",
				"timeout", r.cfg.Timeout, "message", msg.ID)
			errorMsg = fmt.Sprintf("Runtime timeout exceeded after %s", r.cfg.Timeout)

			if err := r.sendToSumpQueue(ctx, queueMsg.Body, errorMsg); err != nil {
				slog.Error("Failed to send timeout error to error queue - exiting anyway", "error", err)
			}

			slog.Error("Exiting to prevent zombie processing (runtime may still be working)")
			os.Exit(1)
		}

		if err := r.sendToSumpQueue(ctx, queueMsg.Body, errorMsg); err != nil {
			slog.Error("Failed to send runtime error to error queue - will requeue for DLQ handling", "error", err)
			return fmt.Errorf("failed to send runtime error to error queue: %w", err)
		}
		return nil
	}

	return r.handleRuntimeResponses(ctx, msg, responses, queueMsg.Body, runtimeDuration, startTime)
}

// routeResponse routes a single response to the appropriate queue
// The route parameter should already have its Current index incremented by the caller
// parentID should be set for fanout children (when index > 0 in fanout scenario)
func (r *Router) routeResponse(ctx context.Context, id string, parentID *string, route messages.Route, payload json.RawMessage, inStatus *messages.Status) error {
	// Determine destination queue
	var destinationQueue string
	var msgType string

	actorToSend := route.GetCurrentActor()

	if actorToSend != "" {
		// There's a next actor in the route
		destinationQueue = r.resolveQueueName(actorToSend)
		msgType = "routing"
	} else {
		// No more actors, route to x-sink automatically
		destinationQueue = r.resolveQueueName(r.sinkQueue)
		msgType = "sink"
	}

	// Build outbound status
	var outStatus *messages.Status
	now := time.Now().UTC().Format(time.RFC3339)
	if actorToSend != "" {
		outStatus = &messages.Status{
			Phase:       messages.PhasePending,
			Actor:       actorToSend,
			Attempt:     1,
			MaxAttempts: 1,
			UpdatedAt:   now,
		}
		if inStatus != nil {
			outStatus.CreatedAt = inStatus.CreatedAt
		} else {
			outStatus.CreatedAt = now
		}
	} else {
		outStatus = &messages.Status{
			Phase:       messages.PhaseSucceeded,
			Reason:      messages.ReasonCompleted,
			Attempt:     1,
			MaxAttempts: 1,
			UpdatedAt:   now,
		}
		if inStatus != nil {
			outStatus.Actor = inStatus.Actor
			outStatus.CreatedAt = inStatus.CreatedAt
		} else {
			outStatus.Actor = r.actorName
			outStatus.CreatedAt = now
		}
	}

	// Create new message with the route as-is
	newMsg := messages.Message{
		ID:       id,
		ParentID: parentID,
		Route:    route,
		Payload:  payload,
		Status:   outStatus,
	}

	// Marshal message
	msgBody, err := json.Marshal(newMsg)
	if err != nil {
		slog.Error("Failed to marshal message for routing", "id", id, "error", err)
		return fmt.Errorf("failed to marshal message: %w", err)
	}

	// Record message size
	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(msgBody))
	}

	// Send to destination queue
	sendStart := time.Now()
	slog.Info("Sending message to queue", "id", id, "queue", destinationQueue, "type", msgType)
	err = r.transport.Send(ctx, destinationQueue, msgBody)
	sendDuration := time.Since(sendStart)

	if err != nil {
		slog.Error("Failed to send message to queue", "id", id, "queue", destinationQueue, "error", err)
	} else {
		slog.Info("Successfully sent message to queue", "id", id, "queue", destinationQueue, "duration", sendDuration)
	}

	// Record metrics
	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(destinationQueue, r.cfg.TransportType, sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(destinationQueue, msgType)
		}
	}

	return err
}

// sendToSinkQueue sends the original message to the x-sink queue
func (r *Router) sendToSinkQueue(ctx context.Context, message messages.Message) error {
	now := time.Now().UTC().Format(time.RFC3339)
	createdAt := now
	if message.Status != nil {
		createdAt = message.Status.CreatedAt
	}
	message.Status = &messages.Status{
		Phase:       messages.PhaseSucceeded,
		Reason:      messages.ReasonCompleted,
		Actor:       r.actorName,
		Attempt:     1,
		MaxAttempts: 1,
		CreatedAt:   createdAt,
		UpdatedAt:   now,
	}

	msgBody, err := json.Marshal(message)
	if err != nil {
		return fmt.Errorf("failed to marshal message for x-sink: %w", err)
	}

	// Record message size
	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(msgBody))
	}

	// Send to x-sink queue
	sendStart := time.Now()
	sinkQueueName := r.resolveQueueName(r.sinkQueue)
	err = r.transport.Send(ctx, sinkQueueName, msgBody)
	sendDuration := time.Since(sendStart)

	// Record metrics
	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(r.sinkQueue, r.cfg.TransportType, sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(r.sinkQueue, "sink")
		}
	}

	return err
}

// sendToSumpQueue sends an error message to the x-sump queue
func (r *Router) sendToSumpQueue(ctx context.Context, originalBody []byte, errorMsg string, errorDetails ...runtime.ErrorDetails) error {
	// Parse original message to extract id, parent_id, and route
	var originalMsg messages.Message
	id := ""
	var parentID *string
	route := map[string]any{
		"actors":  []string{"x-sump"},
		"current": 0,
	}
	if err := json.Unmarshal(originalBody, &originalMsg); err == nil {
		id = originalMsg.ID
		parentID = originalMsg.ParentID
		// Preserve original route for traceability
		if originalMsg.Route.Actors != nil {
			route["actors"] = originalMsg.Route.Actors
			route["current"] = originalMsg.Route.Current
		}
	}

	// Build proper message structure with error in payload
	errorPayload := map[string]any{
		"error": errorMsg,
	}

	// Add error details to payload
	if len(errorDetails) > 0 {
		errorPayload["details"] = errorDetails[0]
	}

	// Preserve original payload if available
	// Unmarshal json.RawMessage to actual object so it serializes correctly
	if originalMsg.Payload != nil {
		var originalPayload any
		if err := json.Unmarshal(originalMsg.Payload, &originalPayload); err == nil {
			errorPayload["original_payload"] = originalPayload
		}
	}

	// Build error status
	now := time.Now().UTC().Format(time.RFC3339)
	createdAt := now
	actor := r.actorName
	if originalMsg.Status != nil {
		createdAt = originalMsg.Status.CreatedAt
		if originalMsg.Status.Actor != "" {
			actor = originalMsg.Status.Actor
		}
	}
	errorStatus := map[string]any{
		"phase":        messages.PhaseFailed,
		"actor":        actor,
		"attempt":      1,
		"max_attempts": 1,
		"created_at":   createdAt,
		"updated_at":   now,
	}

	errorMessage := map[string]any{
		"id":      id,
		"route":   route,
		"payload": errorPayload,
		"status":  errorStatus,
	}
	if parentID != nil {
		errorMessage["parent_id"] = *parentID
	}

	msgBody, err := json.Marshal(errorMessage)
	if err != nil {
		return fmt.Errorf("failed to marshal error message: %w", err)
	}

	// Record message size
	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(msgBody))
	}

	// Send to error queue
	sendStart := time.Now()
	sumpQueueName := r.resolveQueueName(r.sumpQueue)
	err = r.transport.Send(ctx, sumpQueueName, msgBody)
	sendDuration := time.Since(sendStart)

	// Record metrics
	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(r.sumpQueue, r.cfg.TransportType, sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(r.sumpQueue, "sump")
		}
	}

	return err
}

// reportFinalStatusWithMessage reports final message status to gateway with full message context
// This is called by end actors (x-sink, x-sump) after processing
// It has access to both the message (with route) and the result payload
func (r *Router) reportFinalStatusWithMessage(ctx context.Context, msg *messages.Message, resultPayload json.RawMessage, duration time.Duration) error {
	if r.progressReporter == nil {
		return nil
	}

	// Parse result payload to extract the actual result
	var result interface{}
	if len(resultPayload) > 0 {
		if err := json.Unmarshal(resultPayload, &result); err != nil {
			slog.Warn("Failed to parse result payload", "error", err)
			result = nil
		}
	}

	// Determine status from queue name
	var status string
	var errorMsg string
	var errorDetails interface{}
	var currentActorIdx *int
	var currentActorName string

	switch r.actorName {
	case r.sinkQueue:
		status = statusSucceeded
	case r.sumpQueue:
		status = statusFailed
		// For x-sump, extract error info from msg.Payload (not result)
		// The msg.Payload contains error details set by sendToSumpQueue
		var msgPayload interface{}
		if err := json.Unmarshal(msg.Payload, &msgPayload); err == nil {
			if payloadMap, ok := msgPayload.(map[string]interface{}); ok {
				if err, ok := payloadMap["error"].(string); ok {
					errorMsg = err
				}
				if details, ok := payloadMap["details"]; ok {
					errorDetails = details
				}
			}
		}
		// Use route from message to identify where the error occurred
		if len(msg.Route.Actors) > 0 {
			currentIdx := msg.Route.Current
			currentActorIdx = &currentIdx
			// Get the actor name where the error occurred
			if currentIdx >= 0 && currentIdx < len(msg.Route.Actors) {
				currentActorName = msg.Route.Actors[currentIdx]
			}
		}
	default:
		slog.Warn("reportFinalStatusWithMessage called on non-end actor", "queue", r.actorName)
		return nil
	}

	// Build final status payload
	finalPayload := map[string]interface{}{
		"id":        msg.ID,
		"status":    status,
		"timestamp": time.Now().Format(time.RFC3339),
	}

	if status == statusSucceeded {
		finalPayload["progress"] = 1.0
		// Use the message payload as the result
		if result != nil {
			finalPayload["result"] = result
		}
	} else {
		if errorMsg != "" {
			finalPayload["error"] = errorMsg
		}
		if errorDetails != nil {
			finalPayload["error_details"] = errorDetails
		}
		if len(msg.Route.Actors) > 0 {
			finalPayload["actors"] = msg.Route.Actors
		}
		if currentActorIdx != nil {
			finalPayload["current_actor_idx"] = *currentActorIdx
		}
		if currentActorName != "" {
			finalPayload["current_actor_name"] = currentActorName
		}
	}

	// Send to gateway
	payloadBytes, err := json.Marshal(finalPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal final status: %w", err)
	}

	url := fmt.Sprintf("%s/tasks/%s/final", r.gatewayURL, msg.ID)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payloadBytes))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send final status: %w", err)
	}
	defer func() {
		if err := resp.Body.Close(); err != nil {
			slog.Error("Failed to close response body", "error", err)
		}
	}()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("gateway returned non-success status: %d", resp.StatusCode)
	}

	slog.Info("Reported final status to gateway", "id", msg.ID, "status", status,
		"actor", currentActorName, "actor_idx", currentActorIdx)
	return nil
}

// reportFinalStatus reports final message status to gateway (legacy version without message context)
// Deprecated: Use reportFinalStatusWithMessage instead
func (r *Router) reportFinalStatus(ctx context.Context, msgID string, resultPayload json.RawMessage, duration time.Duration) error {
	if r.progressReporter == nil {
		return nil
	}

	// Parse result payload to extract the actual result
	var result interface{}
	if len(resultPayload) > 0 {
		if err := json.Unmarshal(resultPayload, &result); err != nil {
			slog.Warn("Failed to parse result payload", "error", err)
			result = nil
		}
	}

	// Determine status from queue name
	var status string
	var errorMsg string
	var errorDetails interface{}
	var route messages.Route
	var currentActorIdx *int
	var currentActorName string

	switch r.actorName {
	case r.sinkQueue:
		status = statusSucceeded
	case r.sumpQueue:
		status = statusFailed
		// For x-sump, extract error info and route from payload
		type errorPayload struct {
			Error   string      `json:"error"`
			Details interface{} `json:"details"`
			Route   struct {
				Actors  []string `json:"actors"`
				Current int      `json:"current"`
			} `json:"route"`
		}

		if resultBytes, err := json.Marshal(result); err == nil {
			var payload errorPayload
			if err := json.Unmarshal(resultBytes, &payload); err == nil {
				errorMsg = payload.Error
				errorDetails = payload.Details
				route.Actors = payload.Route.Actors
				route.Current = payload.Route.Current

				if len(route.Actors) > 0 && payload.Route.Current >= 0 {
					currentIdx := payload.Route.Current
					currentActorIdx = &currentIdx
					if currentIdx < len(route.Actors) {
						currentActorName = route.Actors[currentIdx]
					}
				}
			} else {
				slog.Warn("Failed to unmarshal error payload", "error", err)
			}
		} else {
			slog.Warn("Failed to marshal result for parsing", "error", err)
		}
	default:
		slog.Warn("reportFinalStatus called on non-end actor", "queue", r.actorName)
		return nil
	}

	// Build final status payload
	finalPayload := map[string]interface{}{
		"id":        msgID,
		"status":    status,
		"timestamp": time.Now().Format(time.RFC3339),
	}

	if status == statusSucceeded {
		finalPayload["progress"] = 1.0
		// Use the message payload as the result
		if result != nil {
			finalPayload["result"] = result
		}
	} else {
		if errorMsg != "" {
			finalPayload["error"] = errorMsg
		}
		if errorDetails != nil {
			finalPayload["error_details"] = errorDetails
		}
		if len(route.Actors) > 0 {
			finalPayload["actors"] = route.Actors
		}
		if currentActorIdx != nil {
			finalPayload["current_actor_idx"] = *currentActorIdx
		}
		if currentActorName != "" {
			finalPayload["current_actor_name"] = currentActorName
		}
	}

	// Send to gateway
	payloadBytes, err := json.Marshal(finalPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal final status: %w", err)
	}

	url := fmt.Sprintf("%s/tasks/%s/final", r.gatewayURL, msgID)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payloadBytes))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send final status: %w", err)
	}
	defer func() {
		if err := resp.Body.Close(); err != nil {
			slog.Error("Failed to close response body", "error", err)
		}
	}()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("gateway returned non-success status: %d", resp.StatusCode)
	}

	slog.Info("Reported final status to gateway", "id", msgID, "status", status,
		"actor", currentActorName, "actor_idx", currentActorIdx)
	return nil
}

// resolveQueueName resolves an actor name to a queue name based on transport type
func (r *Router) resolveQueueName(actorName string) string {
	switch r.cfg.TransportType {
	case "rabbitmq", "sqs":
		// Both RabbitMQ and SQS use asya-{namespace}-{actor} naming convention
		return fmt.Sprintf("asya-%s-%s", r.cfg.Namespace, actorName)
	default:
		return actorName
	}
}

// createFanoutMessage creates a fanout child message in the gateway
// Fanout children use the same route state as the parent after runtime processing
func (r *Router) createFanoutMessage(ctx context.Context, id, parentID string, route messages.Route) error {
	return r.progressReporter.CreateTask(ctx, id, parentID, route.Actors, route.Current)
}

// CheckGatewayHealth verifies the gateway is reachable if gateway URL is configured
// Returns nil if gateway is not configured (URL empty) or if health check passes
// Returns error if gateway is configured but unreachable
func (r *Router) CheckGatewayHealth(ctx context.Context) error {
	if r.progressReporter == nil {
		return nil
	}
	return r.progressReporter.CheckHealth(ctx)
}

// Run starts the message processing loop
func (r *Router) Run(ctx context.Context) error {
	queueName := r.resolveQueueName(r.actorName)
	slog.Info("Starting router", "queue", queueName)

	var consecutiveFailures int
	const maxBackoff = 30 * time.Second

	for {
		select {
		case <-ctx.Done():
			slog.Info("Router shutting down", "reason", ctx.Err())
			return ctx.Err()
		default:
			// Receive message from queue
			receiveStart := time.Now()
			queueName := r.resolveQueueName(r.actorName)
			queueMsg, err := r.transport.Receive(ctx, queueName)
			receiveDuration := time.Since(receiveStart)

			if err != nil {
				consecutiveFailures++
				exponent := min(consecutiveFailures-1, 5)
				if exponent < 0 {
					exponent = 0
				}
				var shift uint
				if exponent >= 0 {
					shift = uint(exponent)
				}
				backoff := time.Duration(1<<shift) * time.Second
				if backoff > maxBackoff {
					backoff = maxBackoff
				}

				slog.Error("Failed to receive message",
					"error", err,
					"consecutiveFailures", consecutiveFailures,
					"backoffSeconds", backoff.Seconds())

				select {
				case <-time.After(backoff):
					continue
				case <-ctx.Done():
					return ctx.Err()
				}
			}

			consecutiveFailures = 0

			slog.Info("Message received from queue", "msgID", queueMsg.ID, "receiveDuration", receiveDuration)

			// Record receive metrics
			if r.metrics != nil {
				r.metrics.RecordMessageReceived(r.actorName, r.cfg.TransportType)
				r.metrics.RecordQueueReceiveDuration(r.actorName, r.cfg.TransportType, receiveDuration)
			}

			// Process message
			slog.Info("Processing message", "msgID", queueMsg.ID)
			if err := r.ProcessMessage(ctx, queueMsg); err != nil {
				slog.Error("Message processing failed", "msgID", queueMsg.ID, "error", err)
				// Requeue the message for retry
				if requeueErr := r.transport.Requeue(ctx, queueMsg); requeueErr != nil {
					slog.Error("Failed to requeue message", "msgID", queueMsg.ID, "error", requeueErr)
				}
				continue
			}

			// ACK the message on success
			if err := r.transport.Ack(ctx, queueMsg); err != nil {
				slog.Error("Failed to ACK message", "msgID", queueMsg.ID, "error", err)
			}
		}
	}
}
