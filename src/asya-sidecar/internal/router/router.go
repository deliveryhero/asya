package router

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"math/rand/v2"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/progress"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/tracing"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
)

const (
	statusSucceeded = "succeeded"
	statusFailed    = "failed"
)

// Router handles envelope routing between queues and runtime client
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
	tracer           trace.Tracer
	reporters        sync.Map // gateway URL -> *progress.Reporter
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
		tracer:           otel.Tracer("asya-sidecar"),
	}
}

// getTracer returns the router's tracer, falling back to the global OTEL tracer.
// This ensures tests that construct Router structs directly (without NewRouter)
// get a valid no-op tracer instead of nil.
func (r *Router) getTracer() trace.Tracer {
	if r.tracer != nil {
		return r.tracer
	}
	return otel.Tracer("asya-sidecar")
}

// startProcessSpan extracts trace context from envelope headers and starts
// the root processing span for this actor hop.
func (r *Router) startProcessSpan(ctx context.Context, msg *envelopes.Envelope) (context.Context, trace.Span) {
	ctx = tracing.ExtractTraceContext(ctx, msg.Headers)
	spanAttrs := []attribute.KeyValue{
		attribute.String("asya.actor", r.actorName),
		attribute.String("asya.envelope_id", msg.ID),
		attribute.String("asya.queue", r.resolveQueueName(r.actorName)),
	}
	if flowID, ok := msg.Headers["x-asya-flow"].(string); ok && flowID != "" {
		spanAttrs = append(spanAttrs, attribute.String("asya.flow", flowID))
	}
	return r.getTracer().Start(ctx, "actor.process",
		trace.WithSpanKind(trace.SpanKindServer),
		trace.WithAttributes(spanAttrs...),
	)
}

// ensureAndUpdateStatus initializes or updates the status on a envelope before processing.
// If status is nil, creates a default with phase=processing.
// If status exists, transitions to processing phase and updates actor/timestamps.
// MaxAttempts is set to 0 (unknown until policy is matched at error time).
func (r *Router) ensureAndUpdateStatus(msg *envelopes.Envelope) {
	now := time.Now().UTC().Format(time.RFC3339)

	if msg.Status == nil {
		msg.Status = &envelopes.Status{
			Phase:       envelopes.PhaseProcessing,
			Actor:       r.actorName,
			Attempt:     1,
			MaxAttempts: 0,
			CreatedAt:   now,
			UpdatedAt:   now,
		}
		return
	}

	// Reset attempt counter when transitioning between actors
	if msg.Status.Actor != r.actorName {
		msg.Status.Attempt = 1
	}

	msg.Status.Phase = envelopes.PhaseProcessing
	msg.Status.Reason = ""
	msg.Status.Actor = r.actorName
	msg.Status.MaxAttempts = 0
	msg.Status.UpdatedAt = now
	msg.Status.Error = nil
}

// effectiveTimeout computes the per-envelope timeout as the minimum of:
//   - ASYA_RESILIENCY_ACTOR_TIMEOUT (per-actor timeout, r.cfg.Timeout)
//   - remaining SLA (deadline_at - now, from envelope status)
func (r *Router) effectiveTimeout(msg *envelopes.Envelope) time.Duration {
	timeout := r.cfg.Timeout

	if deadline, ok := msg.ParseDeadline(); ok {
		remaining := time.Until(deadline)
		if remaining < timeout {
			timeout = remaining
		}
	}

	return timeout
}

// shouldReportFinalToGateway returns false for envelopes that must NOT trigger
// a final-status report to the gateway:
//  1. x-asya-fan-in header: fan-in partial batch (actor handles aggregation, not gateway)
//  2. parent_id set: fire-and-forget fan-out child (only root envelope is tracked by gateway)
//  3. non-terminal status.phase: human-in-the-loop or custom intermediate states
func (r *Router) shouldReportFinalToGateway(msg *envelopes.Envelope) bool {
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
		if phase != envelopes.PhaseSucceeded && phase != envelopes.PhaseFailed {
			slog.Debug("Skipping gateway report: non-terminal phase", "id", msg.ID, "phase", phase)
			return false
		}
	}
	return true
}

// resolveGatewayURL returns the gateway URL for this envelope.
// Envelope header x-asya-gateway-url takes precedence over the env var fallback.
// The header value is validated to prevent SSRF: only http/https schemes are
// accepted and the URL must parse correctly. Invalid values are logged and
// ignored, falling back to the configured gateway URL.
func (r *Router) resolveGatewayURL(msg *envelopes.Envelope) string {
	if msg.Headers != nil {
		if raw, ok := msg.Headers[envelopes.HeaderGatewayURL]; ok {
			if s, ok := raw.(string); ok && s != "" {
				if isValidGatewayURL(s) {
					return s
				}
				slog.Warn("Ignoring invalid x-asya-gateway-url header",
					"id", msg.ID, "value", s)
			}
		}
	}
	return r.gatewayURL
}

// isValidGatewayURL validates that a gateway URL is safe to use.
// Only http and https schemes are permitted to prevent SSRF via file://,
// gopher://, or other dangerous schemes.
func isValidGatewayURL(rawURL string) bool {
	u, err := url.Parse(rawURL)
	if err != nil {
		return false
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return false
	}
	if u.Host == "" {
		return false
	}
	return true
}

// getReporter returns a progress.Reporter for the given envelope.
// If the envelope carries x-asya-gateway-url, a reporter targeting that URL is
// returned (cached per URL to avoid repeated allocations). Otherwise falls back
// to the router's default reporter (which may be nil).
func (r *Router) getReporter(msg *envelopes.Envelope) *progress.Reporter {
	url := r.resolveGatewayURL(msg)
	if url == "" {
		return nil
	}
	if url == r.gatewayURL && r.progressReporter != nil {
		return r.progressReporter
	}
	if cached, ok := r.reporters.Load(url); ok {
		rep, _ := cached.(*progress.Reporter)
		return rep
	}
	reporter := progress.NewReporter(url, r.actorName)
	r.reporters.Store(url, reporter)
	return reporter
}

// isMeshStatusEnabled returns true when gateway mesh-status reporting is active for this envelope.
// Returns false when:
//   - no gateway URL is available (neither from envelope header nor env var)
//   - envelope header x-asya-mesh-status is "off" (explicit stealth mode)
//   - envelope has no ID (no correlation context)
func (r *Router) isMeshStatusEnabled(msg *envelopes.Envelope) bool {
	if r.resolveGatewayURL(msg) == "" {
		return false
	}
	if v, ok := msg.Headers[envelopes.HeaderMeshStatus]; ok {
		if s, ok := v.(string); ok && s == envelopes.MeshStatusOff {
			slog.Debug("Skipping mesh status reporting: x-asya-mesh-status=off", "id", msg.ID)
			return false
		}
	}
	return msg.ID != ""
}

// processEndActorEnvelope handles envelope processing for end actors (x-sink, x-sump)
// End actors are terminal nodes that:
// - Accept envelopes with ANY route state (no validation)
// - Process the envelope through runtime
// - Do NOT route responses anywhere (terminal processing)
// - Report final status to gateway
func (r *Router) processEndActorEnvelope(ctx context.Context, msg envelopes.Envelope, msgBody []byte, startTime time.Time) error {
	slog.Debug("End actor processing message", "id", msg.ID, "actor", r.actorName)

	// IMPORTANT: End actors are terminal - they do NOT route to any queue
	// and do NOT shift the route. They only:
	// 1. Process the envelope via runtime
	// 2. Report final status to gateway
	// End actors run in envelope mode with validation disabled.
	// They typically return empty dict {}, which is ignored by the sidecar.

	// Send to runtime without route validation (end actors don't forward upstream events)
	var resultPayload json.RawMessage
	runtimeStart := time.Now()
	err := r.runtimeClient.CallRuntime(ctx, msgBody, r.effectiveTimeout(&msg), nil, func(frame runtime.RuntimeResponse, index int) {
		if index == 0 && len(frame.Payload) > 0 {
			resultPayload = frame.Payload
		}
	})
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

			if r.isMeshStatusEnabled(&msg) {
				errorCtx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
				defer cancel()
				_ = r.getReporter(&msg).ReportFinalError(errorCtx, msg.ID, "Runtime timeout exceeded")
			}

			slog.Error("Exiting to prevent zombie processing (runtime may still be working)")
			tracing.ForceFlush(context.Background())
			os.Exit(1)
		}

		return fmt.Errorf("runtime error in end actor: %w", err)
	}

	// Record success metrics
	if r.metrics != nil {
		r.metrics.RecordMessageProcessed(r.actorName, "end_consumed")
		r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
	}

	// Use original envelope payload if runtime returned empty/null
	if len(resultPayload) == 0 {
		resultPayload = msg.Payload
	}

	// Report final status to gateway if configured and envelope is terminal/not a fan-out child.
	if r.isMeshStatusEnabled(&msg) && r.shouldReportFinalToGateway(&msg) {
		if err := r.reportFinalStatusWithMessage(ctx, &msg, resultPayload, runtimeDuration); err != nil {
			slog.Warn("Failed to report final status to gateway", "id", msg.ID, "error", err)
		}
	}

	slog.Debug("End actor completed processing", "id", msg.ID, "actor", r.actorName)
	return nil
}

// parseAndValidateMessage parses and validates the envelope from message body
func (r *Router) parseAndValidateMessage(ctx context.Context, msgBody []byte, startTime time.Time) (*envelopes.Envelope, error) {
	var msg envelopes.Envelope
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

// handleErrorResponse handles error responses from runtime with policy-based retry logic.
// When resiliency is configured, it matches the error against rules to find a policy,
// then applies that policy (retry, onExhausted routing, or fail permanently).
func (r *Router) handleErrorResponse(ctx context.Context, msg *envelopes.Envelope, response runtime.RuntimeResponse, startTime time.Time) error {
	if r.metrics != nil {
		r.metrics.RecordMessageProcessed(r.actorName, "error")
		r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
	}

	if r.cfg.Resiliency == nil {
		if r.metrics != nil {
			r.metrics.RecordMessageFailed(r.actorName, "runtime_error")
		}
		return r.sendRetryFailure(ctx, msg, response, envelopes.ReasonRuntimeError)
	}

	policy := r.matchPolicy(response.Details.Type, response.Details.MRO)
	if policy == nil {
		if r.metrics != nil {
			r.metrics.RecordMessageFailed(r.actorName, "runtime_error")
		}
		return r.sendRetryFailure(ctx, msg, response, envelopes.ReasonRuntimeError)
	}

	return r.applyPolicy(ctx, msg, policy, response)
}

// matchPolicy finds the first rule matching errorType or any of its MRO ancestors
// and returns the corresponding PolicyConfig. Falls back to policies["default"] if
// no rule matches. Returns nil if no rule matches and no default policy is defined.
//
// Matching rules:
//   - FQN pattern (contains "."): exact string equality against errorType or MRO entry
//   - Short name (no "."): matches the part after the last "." in a candidate
func (r *Router) matchPolicy(errorType string, mro []string) *config.PolicyConfig {
	if r.cfg.Resiliency == nil {
		return nil
	}

	candidates := make([]string, 0, len(mro)+1)
	candidates = append(candidates, errorType)
	candidates = append(candidates, mro...)

	for _, rule := range r.cfg.Resiliency.Rules {
		for _, pattern := range rule.Errors {
			if matchesErrorPattern(pattern, candidates) {
				if p, ok := r.cfg.Resiliency.Policies[rule.Policy]; ok {
					p := p
					return &p
				}
			}
		}
	}

	if def, ok := r.cfg.Resiliency.Policies["default"]; ok {
		def := def
		return &def
	}
	return nil
}

// matchesErrorPattern reports whether pattern matches any of the candidate type strings.
func matchesErrorPattern(pattern string, candidates []string) bool {
	isFQN := strings.Contains(pattern, ".")
	for _, candidate := range candidates {
		if isFQN {
			if candidate == pattern {
				return true
			}
		} else {
			if idx := strings.LastIndex(candidate, "."); idx >= 0 {
				if candidate[idx+1:] == pattern {
					return true
				}
			} else if candidate == pattern {
				return true
			}
		}
	}
	return false
}

// applyPolicy applies a matched policy to decide whether to retry, route, or fail.
func (r *Router) applyPolicy(ctx context.Context, msg *envelopes.Envelope, policy *config.PolicyConfig, response runtime.RuntimeResponse) error {
	maxAttempts := policy.MaxAttempts
	if maxAttempts <= 0 {
		maxAttempts = 1
	}
	msg.Status.MaxAttempts = maxAttempts

	attemptsExhausted := msg.Status.Attempt >= maxAttempts
	durationExhausted := isDurationExhausted(msg, policy.MaxDuration.Duration())

	// Determine outcome for span attributes before starting the span
	var outcome string
	if !attemptsExhausted && !durationExhausted {
		outcome = "retry"
	} else {
		outcome = "exhausted"
	}

	_, policySpan := r.getTracer().Start(ctx, "actor.resiliency.policy",
		trace.WithAttributes(
			attribute.Int("asya.attempt", msg.Status.Attempt),
			attribute.String("asya.policy_name", string(policy.Backoff)),
			attribute.Int("asya.max_attempts", maxAttempts),
			attribute.String("asya.outcome", outcome),
		),
	)
	defer policySpan.End()

	if !attemptsExhausted && !durationExhausted {
		delay := computeRetryDelayForPolicy(msg.Status.Attempt, policy)
		slog.Info("Retrying message with policy backoff",
			"id", msg.ID,
			"attempt", msg.Status.Attempt,
			"max_attempts", maxAttempts,
			"delay", delay,
			"error_type", response.Details.Type)

		if err := r.retryMessage(ctx, msg, response.Details, delay); err != nil {
			slog.Error("Failed to send retry message, routing to x-sink", "id", msg.ID, "error", err)
			policySpan.SetStatus(codes.Error, "retry send failed")
			policySpan.RecordError(err)
			if r.metrics != nil {
				r.metrics.RecordMessageFailed(r.actorName, "retry_send_failed")
			}
			return r.sendRetryFailure(ctx, msg, response, envelopes.ReasonRuntimeError)
		}

		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "retried")
		}
		return nil
	}

	if durationExhausted && !attemptsExhausted {
		slog.Info("Max retry duration exhausted",
			"id", msg.ID, "attempt", msg.Status.Attempt, "max_duration", policy.MaxDuration.Duration())
	} else {
		slog.Info("Max retry attempts exhausted",
			"id", msg.ID, "attempt", msg.Status.Attempt, "max_attempts", maxAttempts)
	}

	if len(policy.OnExhausted) > 0 {
		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "policy_routed")
		}
		return r.routeOnExhausted(ctx, msg, policy.OnExhausted, response)
	}

	if r.metrics != nil {
		r.metrics.RecordMessageFailed(r.actorName, "policy_exhausted")
	}
	return r.sendRetryFailure(ctx, msg, response, envelopes.ReasonPolicyExhausted)
}

// routeOnExhausted sends the failed envelope to the actor(s) configured in onExhausted.
func (r *Router) routeOnExhausted(ctx context.Context, msg *envelopes.Envelope, onExhausted []string, response runtime.RuntimeResponse) error {
	now := time.Now().UTC().Format(time.RFC3339)
	msg.Route.Next = onExhausted
	msg.Status.Phase = envelopes.PhaseFailed
	msg.Status.Reason = envelopes.ReasonPolicyRouted
	msg.Status.UpdatedAt = now
	msg.Status.Error = &envelopes.StatusError{
		Type:      response.Details.Type,
		MRO:       response.Details.MRO,
		Message:   response.Details.Message,
		Traceback: response.Details.Traceback,
	}

	body, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("failed to marshal onExhausted message: %w", err)
	}

	destQueue := r.resolveQueueName(onExhausted[0])
	slog.Info("Routing to onExhausted actor", "id", msg.ID, "queue", destQueue, "on_exhausted", onExhausted)

	if r.metrics != nil {
		r.metrics.RecordMessageSize("sent", len(body))
	}

	if err := r.transport.Send(ctx, destQueue, body); err != nil {
		return fmt.Errorf("failed to send to onExhausted queue %q: %w", destQueue, err)
	}

	if r.metrics != nil {
		r.metrics.RecordMessageSent(onExhausted[0], "on_exhausted")
	}
	return nil
}

// computeRetryDelayForPolicy calculates the backoff delay for the given policy.
func computeRetryDelayForPolicy(failedAttempt int, policy *config.PolicyConfig) time.Duration {
	if policy.InitialDelay.Duration() <= 0 {
		return 0
	}

	var delay time.Duration
	switch policy.Backoff {
	case config.RetryPolicyConstant:
		delay = policy.InitialDelay.Duration()
	case config.RetryPolicyLinear:
		delay = policy.InitialDelay.Duration() * time.Duration(failedAttempt)
	default: // exponential
		exponent := failedAttempt - 1
		multiplier := math.Pow(2.0, float64(exponent))
		delay = time.Duration(float64(policy.InitialDelay.Duration()) * multiplier)
	}

	if policy.MaxInterval.Duration() > 0 && delay > policy.MaxInterval.Duration() {
		delay = policy.MaxInterval.Duration()
	}

	if policy.Jitter {
		jitterFactor := 0.5 + rand.Float64()
		delay = time.Duration(float64(delay) * jitterFactor)
	}

	return delay
}

// isDurationExhausted reports whether the total wall-clock budget for retries
// has been exceeded. It reads x-asya-first-attempt from msg.Headers, which the
// sidecar stamps on the first attempt and preserves unchanged across retries.
// Returns false when maxDuration is zero, the header is absent, or unparseable.
func isDurationExhausted(msg *envelopes.Envelope, maxDuration time.Duration) bool {
	if maxDuration <= 0 {
		return false
	}
	if msg.Headers == nil {
		return false
	}
	raw, ok := msg.Headers[envelopes.HeaderFirstAttempt].(string)
	if !ok {
		return false
	}
	first, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		return false
	}
	return time.Since(first) >= maxDuration
}

// retryMessage sends the envelope back to the actor's own queue with a delay.
// Updates the envelope status to reflect the retry state.
func (r *Router) retryMessage(ctx context.Context, msg *envelopes.Envelope, details runtime.ErrorDetails, delay time.Duration) error {
	now := time.Now().UTC().Format(time.RFC3339)
	msg.Status.Phase = envelopes.PhaseRetrying
	msg.Status.UpdatedAt = now
	msg.Status.Error = &envelopes.StatusError{
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

// sendRetryFailure sends a failed envelope to the x-sink queue so that
// post-hooks and checkpointing run before x-sump receives it as the terminal layer.
func (r *Router) sendRetryFailure(ctx context.Context, msg *envelopes.Envelope, response runtime.RuntimeResponse, reason string) error {
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

	maxAttempts := 0
	if msg.Status != nil {
		maxAttempts = msg.Status.MaxAttempts
	}

	failedMsg := envelopes.Envelope{
		ID:       msg.ID,
		ParentID: msg.ParentID,
		Route:    msg.Route,
		Payload:  payloadBytes,
		Status: &envelopes.Status{
			Phase:       envelopes.PhaseFailed,
			Reason:      reason,
			Actor:       r.actorName,
			Attempt:     attempt,
			MaxAttempts: maxAttempts,
			CreatedAt:   createdAt,
			UpdatedAt:   now,
			Error: &envelopes.StatusError{
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
	sinkQueueName := r.resolveQueueName(r.sinkQueue)
	err = r.transport.Send(ctx, sinkQueueName, body)
	sendDuration := time.Since(sendStart)

	if r.metrics != nil {
		r.metrics.RecordQueueSendDuration(r.sinkQueue, r.cfg.TransportType, sendDuration)
		if err == nil {
			r.metrics.RecordMessageSent(r.sinkQueue, "sink")
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

// handleSuccessResponse handles successful responses from runtime
func (r *Router) handleSuccessResponse(ctx context.Context, msg *envelopes.Envelope, response runtime.RuntimeResponse, index int, runtimeDuration time.Duration) error {
	// Runtime is responsible for shifting the route (prev/curr/next):
	// - Default: runtime auto-shifts route
	// - Via ABI: user handler yields SET ".route.next" with new actors
	outputRoute := response.Route

	if index == 0 && r.isMeshStatusEnabled(msg) {
		durationMs := runtimeDuration.Milliseconds()
		_ = r.getReporter(msg).ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
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
	if index > 0 {
		msgID = uuid.New().String()
		parentID = &msg.ID
		slog.Debug("Fan-out: generated unique message ID", "original", msg.ID, "fanout", msgID, "index", index)

		if r.isMeshStatusEnabled(msg) {
			if err := r.getReporter(msg).CreateMesh(ctx, msgID, *parentID, outputRoute); err != nil {
				slog.Warn("Failed to create fanout message in gateway", "id", msgID, "error", err)
			}
		}
	}

	statusFromRuntime := response.Status
	if statusFromRuntime == nil {
		statusFromRuntime = msg.Status
	}

	// Use headers from runtime response; fall back to original envelope headers
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

		if r.isMeshStatusEnabled(msg) {
			_ = r.getReporter(msg).ReportProgress(ctx, msgID, progress.ProgressUpdate{
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

		// Do NOT route to next actor — envelope is persisted by x-pause, gateway tracks state
		return nil
	}

	return r.routeResponse(ctx, msgID, parentID, outputRoute, response.Payload, statusFromRuntime, outHeaders)
}

// ProcessMessage handles a single envelope from the queue
//
//nolint:gocyclo // orchestration function with pre-flight, SLA, runtime, and routing phases
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

	// Ensure headers map exists for trace context propagation
	if msg.Headers == nil {
		msg.Headers = make(map[string]interface{})
	}

	// Extract trace context and start processing span
	ctx, span := r.startProcessSpan(ctx, msg)
	defer span.End()

	// Pre-flight check: skip processing if message is already canceled or paused
	if r.isMeshStatusEnabled(msg) {
		reporter := r.getReporter(msg)
		if reporter != nil {
			preflightCtx, preflightCancel := context.WithTimeout(ctx, 2*time.Second)
			msgStatus, _ := reporter.CheckMessage(preflightCtx, msg.ID)
			preflightCancel()

			if msgStatus != nil {
				switch msgStatus.Status {
				case "canceled":
					slog.Info("Pre-flight: message canceled, routing to x-sink",
						"id", msg.ID, "status", msgStatus.Status)

					if r.metrics != nil {
						r.metrics.RecordMessageProcessed(r.actorName, "preflight_canceled")
						r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
					}

					now := time.Now().UTC().Format(time.RFC3339)
					if msg.Status == nil || msg.Status.CreatedAt == "" {
						msg.Status = &envelopes.Status{CreatedAt: now}
					}
					msg.Status.Phase = envelopes.PhaseCanceled
					msg.Status.Reason = envelopes.ReasonPreFlightCanceled
					msg.Status.Actor = r.actorName
					msg.Status.UpdatedAt = now
					return r.sendToSinkQueue(ctx, *msg)

				case "paused":
					slog.Info("Pre-flight: message paused, routing to x-sink",
						"id", msg.ID, "status", msgStatus.Status)

					if r.metrics != nil {
						r.metrics.RecordMessageProcessed(r.actorName, "preflight_paused")
						r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
					}

					now := time.Now().UTC().Format(time.RFC3339)
					if msg.Status == nil || msg.Status.CreatedAt == "" {
						msg.Status = &envelopes.Status{CreatedAt: now}
					}
					msg.Status.Phase = envelopes.PhasePaused
					msg.Status.Reason = envelopes.ReasonPreFlightPaused
					msg.Status.Actor = r.actorName
					msg.Status.UpdatedAt = now
					return r.sendToSinkQueue(ctx, *msg)
				}
			}
		}
	}

	// SLA pre-check: reject expired envelopes before processing
	if deadline, ok := msg.ParseDeadline(); ok && time.Now().After(deadline) {
		slog.Warn("Message SLA expired, routing to x-sink",
			"id", msg.ID, "deadline_at", msg.Status.DeadlineAt,
			"expired_by", time.Since(deadline))

		now := time.Now().UTC().Format(time.RFC3339)
		createdAt := now
		if msg.Status != nil {
			createdAt = msg.Status.CreatedAt
		}
		msg.Status = &envelopes.Status{
			Phase:       envelopes.PhaseFailed,
			Reason:      envelopes.ReasonTimeout,
			Actor:       r.actorName,
			Attempt:     1,
			MaxAttempts: 1,
			CreatedAt:   createdAt,
			DeadlineAt:  msg.Status.DeadlineAt,
			UpdatedAt:   now,
		}

		return r.handleSLAExpiry(ctx, *msg, startTime)
	}

	if r.cfg.IsEndActor {
		return r.processEndActorEnvelope(ctx, *msg, queueMsg.Body, startTime)
	}

	if r.isMeshStatusEnabled(msg) {
		msgSizeKB := float64(len(queueMsg.Body)) / 1024.0
		_ = r.getReporter(msg).ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
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

	if r.isMeshStatusEnabled(msg) {
		_ = r.getReporter(msg).ReportProgress(ctx, msg.ID, progress.ProgressUpdate{
			Prev:    msg.Route.Prev,
			Curr:    msg.Route.Curr,
			Next:    msg.Route.Next,
			Status:  progress.StatusProcessing,
			Message: fmt.Sprintf("Processing in %s", r.cfg.ActorName),
		})
	}

	// Initialize or update status before calling runtime
	r.ensureAndUpdateStatus(msg)

	// Stamp x-asya-first-attempt on the very first attempt so maxDuration can
	// be evaluated on each retry. Header is never overwritten once set.
	if msg.Headers == nil {
		msg.Headers = make(map[string]interface{})
	}
	if _, exists := msg.Headers[envelopes.HeaderFirstAttempt]; !exists {
		msg.Headers[envelopes.HeaderFirstAttempt] = time.Now().UTC().Format(time.RFC3339)
	}

	updatedBody, err := json.Marshal(msg)
	if err != nil {
		slog.Error("Failed to marshal message with status", "id", msg.ID, "error", err)
		return fmt.Errorf("failed to marshal message with status: %w", err)
	}

	// Build callback that forwards FLY events to gateway via unified PostEvent
	var onUpstream func(json.RawMessage)
	if r.isMeshStatusEnabled(msg) {
		reporter := r.getReporter(msg)
		onUpstream = func(payload json.RawMessage) {
			if err := reporter.PostEvent(ctx, msg.ID, progress.MeshEvent{
				Type: progress.EventTypeFly,
				Data: payload,
			}); err != nil {
				slog.Warn("Failed to forward FLY event", "id", msg.ID, "error", err)
			}
		}
	}

	// Guard against tight or expired SLA deadlines before calling the runtime.
	//
	// The SLA pre-check in ProcessMessage uses time.Now().After(deadline)
	// with whole-second RFC3339 timestamps.  Between that check and here,
	// the remaining SLA may have dropped to zero or near-zero.  A very
	// small timeout would almost certainly trigger context.DeadlineExceeded
	// inside CallRuntime, which sends the message to x-sump + os.Exit(1)
	// instead of the correct x-sink route for SLA expiry.
	//
	// The 1-second margin also absorbs the up-to-1s truncation error from
	// strftime's integer-second formatting of deadline timestamps.
	const slaGuardMargin = 1 * time.Second
	timeout := r.effectiveTimeout(msg)
	slaExpiring := false
	if deadline, ok := msg.ParseDeadline(); ok {
		slaExpiring = time.Until(deadline) < slaGuardMargin
	}
	if timeout <= 0 || slaExpiring {
		slog.Warn("SLA deadline too close, routing to x-sink",
			"id", msg.ID, "deadline_at", msg.Status.DeadlineAt,
			"effective_timeout", timeout)

		now := time.Now().UTC().Format(time.RFC3339)
		msg.Status.Phase = envelopes.PhaseFailed
		msg.Status.Reason = envelopes.ReasonTimeout
		msg.Status.UpdatedAt = now

		return r.handleSLAExpiry(ctx, *msg, startTime)
	}

	var (
		downstreamCount int
		dispatchErr     error
		streamHalted    bool
	)

	runtimeStart := time.Now()

	onDownstream := func(frame runtime.RuntimeResponse, index int) {
		if dispatchErr != nil || streamHalted {
			return
		}
		downstreamCount++

		if frame.IsError() {
			slog.Error("Runtime returned error",
				"id", msg.ID,
				"actor", r.cfg.ActorName,
				"error", frame.Error,
				"errorType", frame.Details.Type,
			)
			dispatchErr = r.handleErrorResponse(ctx, msg, frame, startTime)
			streamHalted = true
			return
		}

		if err := r.handleSuccessResponse(ctx, msg, frame, index, time.Since(runtimeStart)); err != nil {
			if r.metrics != nil {
				r.metrics.RecordMessageFailed(r.actorName, "routing_error")
				r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
			}
			dispatchErr = fmt.Errorf("failed to route response %d: %w", index, err)
			streamHalted = true
		}
	}

	slog.Info("Calling runtime", "id", msg.ID, "actor", r.cfg.ActorName)
	err = r.runtimeClient.CallRuntime(ctx, updatedBody, timeout, onUpstream, onDownstream)
	runtimeDuration := time.Since(runtimeStart)

	if err != nil {
		slog.Info("Runtime call failed", "id", msg.ID, "duration", runtimeDuration, "error", err)
	} else {
		if streamHalted {
			slog.Warn("Runtime call completed", "id", msg.ID, "duration", runtimeDuration, "frames", downstreamCount, "status", "error")
		} else {
			slog.Info("Runtime call completed", "id", msg.ID, "duration", runtimeDuration, "frames", downstreamCount, "status", "success")
		}
	}

	if r.metrics != nil {
		r.metrics.RecordRuntimeDuration(r.actorName, runtimeDuration)
	}

	if err != nil {
		return r.handleRuntimeCallError(ctx, msg, err, queueMsg.Body, startTime)
	}

	// Check for dispatch errors from the callback
	if dispatchErr != nil {
		return dispatchErr
	}

	// Handle empty response (no downstream frames)
	if downstreamCount == 0 {
		slog.Info("Empty response from runtime, routing to x-sink", "id", msg.ID)
		if r.metrics != nil {
			r.metrics.RecordMessageProcessed(r.actorName, "empty_response")
			r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
		}
		return r.sendToSinkQueue(ctx, *msg)
	}

	// All frames dispatched successfully
	if r.metrics != nil {
		r.metrics.RecordMessageProcessed(r.actorName, "success")
		r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
	}
	return nil
}

// handleRuntimeCallError handles errors returned by CallRuntime, including SSE
// handler errors (*RuntimeError), infrastructure errors, and timeouts.
func (r *Router) handleRuntimeCallError(ctx context.Context, msg *envelopes.Envelope, err error, originalBody []byte, startTime time.Time) error {
	// Generator handlers signal errors via SSE error events, which the
	// runtime client wraps as *RuntimeError. Convert these back into a
	// normal error response so that retry/MRO logic in handleErrorResponse
	// applies consistently for both function and generator handlers.
	var runtimeErr *runtime.RuntimeError
	if errors.As(err, &runtimeErr) {
		slog.Error("Runtime returned error",
			"id", msg.ID,
			"actor", r.cfg.ActorName,
			"error", runtimeErr.Response.Error,
			"errorType", runtimeErr.Response.Details.Type,
		)
		return r.handleErrorResponse(ctx, msg, runtimeErr.Response, startTime)
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

		if err := r.sendToSumpQueue(ctx, originalBody, errorMsg); err != nil {
			slog.Error("Failed to send timeout error to error queue - exiting anyway", "error", err)
		}

		slog.Error("Exiting to prevent zombie processing (runtime may still be working)")
		tracing.ForceFlush(context.Background())
		os.Exit(1)
	}

	if err := r.sendToSumpQueue(ctx, originalBody, errorMsg); err != nil {
		slog.Error("Failed to send runtime error to error queue - will requeue for DLQ handling", "error", err)
		return fmt.Errorf("failed to send runtime error to error queue: %w", err)
	}
	return nil
}

// routeResponse routes a single response to the appropriate queue
// The route parameter should already have its Current index incremented by the caller
// parentID should be set for fanout children (when index > 0 in fanout scenario)
func (r *Router) routeResponse(ctx context.Context, id string, parentID *string, route envelopes.Route, payload json.RawMessage, inStatus *envelopes.Status, headers map[string]interface{}) error {
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
	var outStatus *envelopes.Status
	now := time.Now().UTC().Format(time.RFC3339)
	if actorToSend != "" {
		outStatus = &envelopes.Status{
			Phase:       envelopes.PhasePending,
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
		outStatus = &envelopes.Status{
			Phase:       envelopes.PhaseSucceeded,
			Reason:      envelopes.ReasonCompleted,
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

	// Start a producer span for outgoing envelope
	ctx, sendSpan := r.getTracer().Start(ctx, "actor.queue.send",
		trace.WithSpanKind(trace.SpanKindClient),
		trace.WithAttributes(
			attribute.String("asya.destination_queue", destinationQueue),
			attribute.String("asya.message_type", msgType),
		),
	)
	defer sendSpan.End()

	// Inject updated trace context into headers so the next actor can continue the trace
	if headers == nil {
		headers = make(map[string]interface{})
	}
	tracing.InjectTraceContext(ctx, headers)

	// Create new message with the route as-is
	newMsg := envelopes.Envelope{
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
		sendSpan.SetStatus(codes.Error, "marshal failed")
		sendSpan.RecordError(err)
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
		sendSpan.SetStatus(codes.Error, "send failed")
		sendSpan.RecordError(err)
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

// handleSLAExpiry records SLA timeout metrics, notifies the gateway, and
// routes the envelope to x-sink. The caller must set msg.Status fields
// (Phase, Reason, etc.) before calling.
func (r *Router) handleSLAExpiry(ctx context.Context, msg envelopes.Envelope, startTime time.Time) error {
	if r.metrics != nil {
		r.metrics.RecordMessageProcessed(r.actorName, "sla_expired")
		r.metrics.RecordMessageFailed(r.actorName, "sla_timeout")
		r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
	}

	if r.isMeshStatusEnabled(&msg) {
		reportCtx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
		defer cancel()
		_ = r.getReporter(&msg).ReportFinalError(reportCtx, msg.ID, "SLA deadline expired")
	}

	return r.sendToSinkQueue(ctx, msg)
}

// sendToSinkQueue sends the original envelope to the x-sink queue.
// If envelope.Status already has a terminal phase (succeeded/failed),
// it is preserved. Otherwise, PhaseSucceeded/ReasonCompleted is stamped.
func (r *Router) sendToSinkQueue(ctx context.Context, message envelopes.Envelope) error {
	if message.Status == nil || (message.Status.Phase != envelopes.PhaseSucceeded && message.Status.Phase != envelopes.PhaseFailed && message.Status.Phase != envelopes.PhaseCanceled && message.Status.Phase != envelopes.PhasePaused) {
		now := time.Now().UTC().Format(time.RFC3339)
		createdAt := now
		if message.Status != nil {
			createdAt = message.Status.CreatedAt
		}
		message.Status = &envelopes.Status{
			Phase:       envelopes.PhaseSucceeded,
			Reason:      envelopes.ReasonCompleted,
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

// sendToSumpQueue sends an error envelope to the x-sump queue
func (r *Router) sendToSumpQueue(ctx context.Context, originalBody []byte, errorMsg string, errorDetails ...runtime.ErrorDetails) error {
	// Parse original envelope to extract id, parent_id, and route
	var originalMsg envelopes.Envelope
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
		"phase":        envelopes.PhaseFailed,
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

// reportFinalStatusWithMessage reports final envelope status to gateway with full envelope context
// This is called by end actors (x-sink, x-sump) after processing
// It has access to both the envelope (with route) and the result payload
func (r *Router) reportFinalStatusWithMessage(ctx context.Context, msg *envelopes.Envelope, resultPayload json.RawMessage, duration time.Duration) error {
	reporter := r.getReporter(msg)
	if reporter == nil {
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

	// Determine status from envelope phase and actor name.
	// x-sink now receives both succeeded and failed envelopes — use the envelope's
	// phase to distinguish them. x-sump only ever receives failed envelopes.
	var status string
	var errorMsg string
	var errorDetails interface{}
	var currentActorIdx *int
	var currentActorName string

	isFailed := msg.Status != nil && msg.Status.Phase == envelopes.PhaseFailed

	switch r.actorName {
	case r.sinkQueue:
		if isFailed {
			status = statusFailed
			// Extract error info from msg.Status.Error (set by sendRetryFailure)
			if msg.Status.Error != nil {
				errorMsg = msg.Status.Error.Message
				errorDetails = msg.Status.Error
			}
			// Extract error info from payload fallback (set by sendRetryFailure payload field)
			if errorMsg == "" {
				var msgPayload map[string]interface{}
				if err := json.Unmarshal(msg.Payload, &msgPayload); err == nil {
					if e, ok := msgPayload["error"].(string); ok {
						errorMsg = e
					}
					if d, ok := msgPayload["details"]; ok {
						errorDetails = d
					}
				}
			}
			if msg.Route.Curr != "" {
				currentActorName = msg.Route.Curr
				idx := len(msg.Route.Prev)
				currentActorIdx = &idx
			}
		} else {
			status = statusSucceeded
		}
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

	// Send to gateway via unified PostEvent
	payloadBytes, err := json.Marshal(finalPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal final status: %w", err)
	}

	if err := reporter.PostEvent(ctx, msg.ID, progress.MeshEvent{
		Type:   progress.EventTypeStatus,
		Status: status,
		Data:   payloadBytes,
	}); err != nil {
		return err
	}

	slog.Info("Reported final status to gateway", "id", msg.ID, "status", status,
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
	case "rabbitmq", "sqs", "pubsub":
		return fmt.Sprintf("asya-%s-%s", r.cfg.Namespace, actorName)
	default:
		return actorName
	}
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
