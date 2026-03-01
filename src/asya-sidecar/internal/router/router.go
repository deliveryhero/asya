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

	"github.com/google/uuid"

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

// effectiveTimeout computes the per-message timeout as the minimum of:
//   - ASYA_RESILIENCY_ACTOR_TIMEOUT (per-actor timeout, r.cfg.Timeout)
//   - remaining SLA (deadline_at - now, from message status)
func (r *Router) effectiveTimeout(msg *messages.Message) time.Duration {
	timeout := r.cfg.Timeout

	if deadline, ok := msg.ParseDeadline(); ok {
		remaining := time.Until(deadline)
		if remaining < timeout {
			timeout = remaining
		}
	}

	return timeout
}

// shouldReportFinalToGateway returns false for messages that must NOT trigger
// a final-status report to the gateway:
//  1. x-asya-fan-in header: fan-in partial batch (actor handles aggregation, not gateway)
//  2. parent_id set: fire-and-forget fan-out child (only root message is tracked by gateway)
//  3. non-terminal status.phase: human-in-the-loop or custom intermediate states
func (r *Router) shouldReportFinalToGateway(msg *messages.Message) bool {
	if msg.Headers != nil {
		if _, ok := msg.Headers["x-asya-fan-in"]; ok {
			slog.Debug("Skipping gateway report: x-asya-fan-in header", "id", msg.ID)
			return false
		}
	}
	if msg.ParentID != nil {
		slog.Debug("Skipping gateway report: parent_id set (fan-out child)", "id", msg.ID)
		return false
	}
	if msg.Status != nil {
		phase := msg.Status.Phase
		if phase != messages.PhaseSucceeded && phase != messages.PhaseFailed {
			slog.Debug("Skipping gateway report: non-terminal phase", "id", msg.ID, "phase", phase)
			return false
		}
	}
	return true
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
	// and do NOT shift the route. They only:
	// 1. Process the message via runtime
	// 2. Report final status to gateway
	// End actors run in message mode with validation disabled.
	// They typically return empty dict {}, which is ignored by the sidecar.

	// Send to runtime without route validation (end actors don't forward upstream events)
	runtimeStart := time.Now()
	responses, err := r.runtimeClient.CallRuntime(ctx, msgBody, r.effectiveTimeout(&msg), nil)
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

	// Report final status to gateway if configured and message is terminal/not a fan-out child.
	if r.progressReporter != nil && r.shouldReportFinalToGateway(&msg) {
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

	// Replace next actors with the error handler (runtime will do the shift)
	msg.Route.Next = []string{onError}

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
	// Runtime is responsible for shifting the route (prev/curr/next):
	// - Default: runtime auto-shifts route
	// - Via ABI: user handler yields SET ".route.next" with new actors
	outputRoute := response.Route

	if index == 0 && r.progressReporter != nil {
		durationMs := runtimeDuration.Milliseconds()
		_ = r.progressReporter.ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
			Prev:       outputRoute.Prev,
			Curr:       outputRoute.Curr,
			Next:       outputRoute.Next,
			Status:     progress.StatusCompleted,
			Message:    fmt.Sprintf("Completed processing in %dms", durationMs),
			DurationMs: &durationMs,
		})
	}

	msgID := msg.ID
	var parentID *string
	if totalResponses > 1 && index > 0 {
		msgID = uuid.New().String()
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

	// Use headers from runtime response; fall back to original message headers
	var outHeaders map[string]interface{}
	if response.Headers != nil {
		outHeaders = make(map[string]interface{}, len(response.Headers))
		for k, v := range response.Headers {
			outHeaders[k] = v
		}
	} else {
		outHeaders = msg.Headers
	}

	// Check for x-asya-pause header — signals pipeline should pause for external input
	if pauseRaw, ok := outHeaders["x-asya-pause"]; ok {
		slog.Info("Pause header detected, reporting paused status to gateway", "id", msgID)

		var pauseMetadata json.RawMessage
		switch v := pauseRaw.(type) {
		case string:
			pauseMetadata = json.RawMessage(v)
		case json.RawMessage:
			pauseMetadata = v
		default:
			pm, err := json.Marshal(v)
			if err != nil {
				slog.Error("Failed to marshal pause metadata", "id", msgID, "error", err)
			} else {
				pauseMetadata = pm
			}
		}

		if r.progressReporter != nil {
			_ = r.progressReporter.ReportProgress(ctx, msgID, progress.ProgressUpdate{
				Prev:          outputRoute.Prev,
				Curr:          outputRoute.Curr,
				Next:          outputRoute.Next,
				Status:        progress.StatusCompleted,
				Message:       "Paused: waiting for external input",
				PauseMetadata: pauseMetadata,
			})
		}

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "paused")
		}

		// Do NOT route to next actor — message is persisted by x-pause, gateway tracks state
		return nil
	}

	return r.routeResponse(ctx, msgID, parentID, outputRoute, response.Payload, statusFromRuntime, outHeaders)
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

	// SLA pre-check: reject expired messages before processing
	if deadline, ok := msg.ParseDeadline(); ok && time.Now().After(deadline) {
		slog.Warn("Message SLA expired, routing to x-sink",
			"id", msg.ID, "deadline_at", msg.Status.DeadlineAt,
			"expired_by", time.Since(deadline))

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "sla_expired")
			r.metrics.RecordMessageFailed(r.actorName, "sla_timeout")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}

		// Report timeout to gateway
		if r.progressReporter != nil {
			reportCtx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
			defer cancel()
			_ = r.progressReporter.ReportFinalError(reportCtx, msg.ID, "SLA deadline expired")
		}

		// Stamp failed/Timeout status and route to x-sink
		now := time.Now().UTC().Format(time.RFC3339)
		createdAt := now
		if msg.Status != nil {
			createdAt = msg.Status.CreatedAt
		}
		msg.Status = &messages.Status{
			Phase:       messages.PhaseFailed,
			Reason:      messages.ReasonTimeout,
			Actor:       r.actorName,
			Attempt:     1,
			MaxAttempts: 1,
			CreatedAt:   createdAt,
			DeadlineAt:  msg.Status.DeadlineAt,
			UpdatedAt:   now,
		}

		return r.sendToSinkQueue(ctx, *msg)
	}

	if r.cfg.IsEndActor {
		return r.processEndActorMessage(ctx, *msg, queueMsg.Body, startTime)
	}

	if r.progressReporter != nil {
		msgSizeKB := float64(len(queueMsg.Body)) / 1024.0
		_ = r.progressReporter.ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
			Prev:          msg.Route.Prev,
			Curr:          msg.Route.Curr,
			Next:          msg.Route.Next,
			Status:        progress.StatusReceived,
			Message:       fmt.Sprintf("Received message (%.2f KB)", msgSizeKB),
			MessageSizeKB: &msgSizeKB,
		})
	}

	currentActor := msg.Route.GetCurrentActor()
	if currentActor != r.cfg.ActorName {
		// Skip validation if a route override maps currentActor to this actor (ADR-3)
		if !r.isOverrideTarget(currentActor, msg.Headers) {
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
		slog.Info("Route override accepted: actor identity matches override target",
			"route_actor", currentActor, "this_actor", r.cfg.ActorName, "id", msg.ID)
	}

	if r.progressReporter != nil {
		_ = r.progressReporter.ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
			Prev:    msg.Route.Prev,
			Curr:    msg.Route.Curr,
			Next:    msg.Route.Next,
			Status:  progress.StatusProcessing,
			Message: fmt.Sprintf("Processing in %s", r.cfg.ActorName),
		})
	}

	// Initialize or update status before calling runtime
	r.ensureAndUpdateStatus(msg)
	updatedBody, err := json.Marshal(msg)
	if err != nil {
		slog.Error("Failed to marshal message with status", "id", msg.ID, "error", err)
		return fmt.Errorf("failed to marshal message with status: %w", err)
	}

	// Build callback that forwards partial events to gateway
	var onUpstream func(json.RawMessage)
	if r.progressReporter != nil {
		onUpstream = func(payload json.RawMessage) {
			if err := r.progressReporter.ForwardPartial(ctx, msg.ID, payload); err != nil {
				slog.Warn("Failed to forward partial event", "id", msg.ID, "error", err)
			}
		}
	}

	slog.Info("Calling runtime", "id", msg.ID, "actor", r.cfg.ActorName)
	runtimeStart := time.Now()
	responses, err := r.runtimeClient.CallRuntime(ctx, updatedBody, r.effectiveTimeout(msg), onUpstream)
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
		// Generator handlers signal errors via SSE error events, which the
		// runtime client wraps as *RuntimeError. Convert these back into a
		// normal error response so that retry/MRO logic in handleErrorResponse
		// applies consistently for both function and generator handlers.
		var runtimeErr *runtime.RuntimeError
		if errors.As(err, &runtimeErr) {
			slog.Info("Runtime handler error (SSE)", "id", msg.ID, "error", runtimeErr.Response.Error)
			return r.handleRuntimeResponses(ctx, msg, []runtime.RuntimeResponse{runtimeErr.Response}, queueMsg.Body, runtimeDuration, startTime)
		}

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
func (r *Router) routeResponse(ctx context.Context, id string, parentID *string, route messages.Route, payload json.RawMessage, inStatus *messages.Status, headers map[string]interface{}) error {
	// Determine destination queue
	var destinationQueue string
	var msgType string

	actorToSend := route.GetCurrentActor()

	if actorToSend != "" {
		// Check for route override before resolving queue name
		resolvedActor := actorToSend
		if target, ok := r.lookupRouteOverride(actorToSend, headers); ok {
			slog.Info("Route override applied",
				"original", actorToSend,
				"target", target,
				"by", r.actorName,
			)
			resolvedActor = target

			// Stamp x-asya-route-resolved for audit trail
			if headers == nil {
				headers = make(map[string]interface{})
			}
			resolved := headers["x-asya-route-resolved"]
			resolvedMap, ok := resolved.(map[string]interface{})
			if !ok {
				resolvedMap = make(map[string]interface{})
				// Preserve existing audit trail from json.RawMessage (RuntimeResponse headers)
				if raw, isRaw := resolved.(json.RawMessage); isRaw {
					if err := json.Unmarshal(raw, &resolvedMap); err != nil {
						slog.Warn("Failed to unmarshal existing x-asya-route-resolved, starting fresh audit trail",
							"error", err, "id", id)
						resolvedMap = make(map[string]interface{})
					}
				}
			}
			resolvedMap[actorToSend] = map[string]interface{}{
				"target": target,
				"by":     r.actorName,
			}
			headers["x-asya-route-resolved"] = resolvedMap
		}

		destinationQueue = r.resolveQueueName(resolvedActor)
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
			outStatus.Attempt = inStatus.Attempt
			outStatus.MaxAttempts = inStatus.MaxAttempts
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
		Headers:  headers,
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

// sendToSinkQueue sends the original message to the x-sink queue.
// If message.Status already has a terminal phase (succeeded/failed),
// it is preserved. Otherwise, PhaseSucceeded/ReasonCompleted is stamped.
func (r *Router) sendToSinkQueue(ctx context.Context, message messages.Message) error {
	if message.Status == nil || (message.Status.Phase != messages.PhaseSucceeded && message.Status.Phase != messages.PhaseFailed) {
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
		"prev": []string{},
		"curr": "x-sump",
		"next": []string{},
	}
	if err := json.Unmarshal(originalBody, &originalMsg); err == nil {
		id = originalMsg.ID
		parentID = originalMsg.ParentID
		// Preserve original route for traceability
		if originalMsg.Route.Curr != "" || len(originalMsg.Route.Prev) > 0 || len(originalMsg.Route.Next) > 0 {
			route["prev"] = originalMsg.Route.Prev
			route["curr"] = originalMsg.Route.Curr
			route["next"] = originalMsg.Route.Next
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
		if msg.Route.Curr != "" {
			currentActorName = msg.Route.Curr
			idx := len(msg.Route.Prev)
			currentActorIdx = &idx
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
		if msg.Route.Curr != "" || len(msg.Route.Prev) > 0 {
			finalPayload["prev"] = msg.Route.Prev
			finalPayload["curr"] = msg.Route.Curr
			finalPayload["next"] = msg.Route.Next
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
				Prev []string `json:"prev"`
				Curr string   `json:"curr"`
				Next []string `json:"next"`
			} `json:"route"`
		}

		if resultBytes, err := json.Marshal(result); err == nil {
			var payload errorPayload
			if err := json.Unmarshal(resultBytes, &payload); err == nil {
				errorMsg = payload.Error
				errorDetails = payload.Details
				route.Prev = payload.Route.Prev
				route.Curr = payload.Route.Curr
				route.Next = payload.Route.Next

				if payload.Route.Curr != "" {
					currentActorName = payload.Route.Curr
					idx := len(payload.Route.Prev)
					currentActorIdx = &idx
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
		if route.Curr != "" || len(route.Prev) > 0 {
			finalPayload["prev"] = route.Prev
			finalPayload["curr"] = route.Curr
			finalPayload["next"] = route.Next
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

// lookupRouteOverride checks if headers contain an x-asya-route-override mapping
// for the given actor name. Returns the override target and true if found.
//
// Handles two representations of the override value:
//   - map[string]interface{} — when headers come from a parsed Message (json.Unmarshal)
//   - json.RawMessage — when headers come from a RuntimeResponse (raw bytes)
func (r *Router) lookupRouteOverride(actorName string, headers map[string]interface{}) (string, bool) {
	if headers == nil {
		return "", false
	}
	overrides, ok := headers["x-asya-route-override"]
	if !ok {
		return "", false
	}

	// Try direct map assertion (from parsed Message.Headers)
	if overrideMap, ok := overrides.(map[string]interface{}); ok {
		target, ok := overrideMap[actorName]
		if !ok {
			return "", false
		}
		targetStr, ok := target.(string)
		if !ok || targetStr == "" {
			return "", false
		}
		return targetStr, true
	}

	// Try json.RawMessage (from RuntimeResponse.Headers copied to map[string]interface{})
	if raw, ok := overrides.(json.RawMessage); ok {
		var overrideMap map[string]string
		if err := json.Unmarshal(raw, &overrideMap); err != nil {
			return "", false
		}
		target, ok := overrideMap[actorName]
		if !ok || target == "" {
			return "", false
		}
		return target, true
	}

	return "", false
}

// isOverrideTarget checks if a route override maps the given route actor to this
// sidecar's actor name. Used to skip actor identity validation for overridden messages.
func (r *Router) isOverrideTarget(routeActor string, headers map[string]interface{}) bool {
	target, ok := r.lookupRouteOverride(routeActor, headers)
	return ok && target == r.cfg.ActorName
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
	return r.progressReporter.CreateTask(ctx, id, parentID, route)
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
