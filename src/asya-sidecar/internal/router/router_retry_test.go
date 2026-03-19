package router

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"path/filepath"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
)

// delayedMessage tracks a message sent via SendWithDelay
type delayedMessage struct {
	queue string
	body  []byte
	delay time.Duration
}

// retryMockTransport extends mockTransport to track SendWithDelay calls
type retryMockTransport struct {
	mockTransport
	delayedMessages []delayedMessage
	sendWithDelayFn func(ctx context.Context, queueName string, body []byte, delay time.Duration) error
}

func (m *retryMockTransport) SendWithDelay(ctx context.Context, queueName string, body []byte, delay time.Duration) error {
	if m.sendWithDelayFn != nil {
		return m.sendWithDelayFn(ctx, queueName, body, delay)
	}
	m.delayedMessages = append(m.delayedMessages, delayedMessage{
		queue: queueName,
		body:  body,
		delay: delay,
	})
	return nil
}

// newRetryConfig creates a resiliency config for tests with sensible defaults.
// Uses the "default" policy with exponential backoff.
func newRetryConfig(maxAttempts int, onExhausted []string) *config.ResiliencyConfig {
	policy := config.PolicyConfig{
		MaxAttempts:  maxAttempts,
		Backoff:      config.RetryPolicyExponential,
		InitialDelay: config.JSONDuration(time.Second),
		MaxInterval:  config.JSONDuration(300 * time.Second),
		Jitter:       false,
	}
	if len(onExhausted) > 0 {
		policy.OnExhausted = onExhausted
	}
	return &config.ResiliencyConfig{
		Policies: map[string]config.PolicyConfig{"default": policy},
	}
}

// newTestRouterWithRetry creates a router with retry config for tests
func newTestRouterWithRetry(t *testing.T, transport transport.Transport, resiliency *config.ResiliencyConfig) (*Router, string) {
	t.Helper()
	socketPath := filepath.Join(t.TempDir(), "runtime.sock")

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    resiliency,
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	r := &Router{
		cfg:           cfg,
		transport:     transport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	return r, socketPath
}

// --- TestMatchPolicy tests ---

func TestMatchPolicy(t *testing.T) {
	makePolicies := func(names ...string) map[string]config.PolicyConfig {
		m := make(map[string]config.PolicyConfig)
		for _, n := range names {
			m[n] = config.PolicyConfig{MaxAttempts: 3}
		}
		return m
	}

	tests := []struct {
		name      string
		errorType string
		mro       []string
		rules     []config.RetryRule
		policies  map[string]config.PolicyConfig
		wantNil   bool
		wantName  string
	}{
		{
			name:      "FQN exact match on errorType",
			errorType: "openai.RateLimitError",
			mro:       []string{"openai.OpenAIError", "builtins.Exception"},
			rules:     []config.RetryRule{{Errors: []string{"openai.RateLimitError"}, Policy: "retryFast"}},
			policies:  makePolicies("retryFast"),
			wantName:  "retryFast",
		},
		{
			name:      "short name match on errorType",
			errorType: "requests.exceptions.ConnectionError",
			mro:       []string{"builtins.OSError", "builtins.Exception"},
			rules:     []config.RetryRule{{Errors: []string{"ConnectionError"}, Policy: "retryFast"}},
			policies:  makePolicies("retryFast"),
			wantName:  "retryFast",
		},
		{
			name:      "FQN match on MRO ancestor",
			errorType: "openai.AuthenticationError",
			mro:       []string{"openai.OpenAIError", "builtins.Exception"},
			rules:     []config.RetryRule{{Errors: []string{"openai.OpenAIError"}, Policy: "retryBase"}},
			policies:  makePolicies("retryBase"),
			wantName:  "retryBase",
		},
		{
			name:      "first rule wins",
			errorType: "openai.RateLimitError",
			mro:       []string{"openai.OpenAIError"},
			rules: []config.RetryRule{
				{Errors: []string{"openai.RateLimitError"}, Policy: "specific"},
				{Errors: []string{"openai.OpenAIError"}, Policy: "general"},
			},
			policies: makePolicies("specific", "general"),
			wantName: "specific",
		},
		{
			name:      "no match returns default",
			errorType: "mylib.UnknownError",
			mro:       []string{"builtins.Exception"},
			rules:     []config.RetryRule{{Errors: []string{"openai.RateLimitError"}, Policy: "retryFast"}},
			policies:  map[string]config.PolicyConfig{"retryFast": {MaxAttempts: 5}, "default": {MaxAttempts: 1}},
			wantName:  "default",
		},
		{
			name:      "no match and no default returns nil",
			errorType: "mylib.UnknownError",
			mro:       []string{"builtins.Exception"},
			rules:     []config.RetryRule{{Errors: []string{"openai.RateLimitError"}, Policy: "retryFast"}},
			policies:  makePolicies("retryFast"),
			wantNil:   true,
		},
		{
			name:      "empty rules returns default",
			errorType: "anything.Error",
			mro:       nil,
			rules:     nil,
			policies:  map[string]config.PolicyConfig{"default": {MaxAttempts: 3}},
			wantName:  "default",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			socketPath := filepath.Join(t.TempDir(), "runtime.sock")
			r := &Router{cfg: &config.Config{
				ActorName:  "test-actor",
				SocketPath: socketPath,
				SinkQueue:  "x-sink",
				SumpQueue:  "x-sump",
				Resiliency: &config.ResiliencyConfig{
					Policies: tc.policies,
					Rules:    tc.rules,
				},
			}}
			got := r.matchPolicy(tc.errorType, tc.mro)
			if tc.wantNil {
				if got != nil {
					t.Errorf("matchPolicy() = %v, want nil", got)
				}
				return
			}
			if got == nil {
				t.Fatalf("matchPolicy() = nil, want policy %q", tc.wantName)
			}
			expected := tc.policies[tc.wantName]
			if got.MaxAttempts != expected.MaxAttempts {
				t.Errorf("matchPolicy().MaxAttempts = %d, want %d", got.MaxAttempts, expected.MaxAttempts)
			}
		})
	}
}

// --- computeRetryDelayForPolicy tests ---

func TestComputeRetryDelayForPolicy_Exponential(t *testing.T) {
	policy := &config.PolicyConfig{
		Backoff:      config.RetryPolicyExponential,
		InitialDelay: config.JSONDuration(time.Second),
		MaxInterval:  config.JSONDuration(300 * time.Second),
		Jitter:       false,
	}

	tests := []struct {
		attempt       int
		expectedDelay time.Duration
	}{
		{1, 1 * time.Second},    // 1 * 2^0 = 1s
		{2, 2 * time.Second},    // 1 * 2^1 = 2s
		{3, 4 * time.Second},    // 1 * 2^2 = 4s
		{4, 8 * time.Second},    // 1 * 2^3 = 8s
		{5, 16 * time.Second},   // 1 * 2^4 = 16s
		{10, 300 * time.Second}, // 1 * 2^9 = 512s, capped at 300s
	}

	for _, tc := range tests {
		t.Run(fmt.Sprintf("attempt_%d", tc.attempt), func(t *testing.T) {
			delay := computeRetryDelayForPolicy(tc.attempt, policy)
			if delay != tc.expectedDelay {
				t.Errorf("attempt %d: expected %v, got %v", tc.attempt, tc.expectedDelay, delay)
			}
		})
	}
}

func TestComputeRetryDelayForPolicy_Constant(t *testing.T) {
	policy := &config.PolicyConfig{
		Backoff:      config.RetryPolicyConstant,
		InitialDelay: config.JSONDuration(3 * time.Second),
		MaxInterval:  config.JSONDuration(300 * time.Second),
		Jitter:       false,
	}

	for attempt := 1; attempt <= 5; attempt++ {
		delay := computeRetryDelayForPolicy(attempt, policy)
		if delay != 3*time.Second {
			t.Errorf("attempt %d: expected constant 3s, got %v", attempt, delay)
		}
	}
}

func TestComputeRetryDelayForPolicy_Linear(t *testing.T) {
	policy := &config.PolicyConfig{
		Backoff:      config.RetryPolicyLinear,
		InitialDelay: config.JSONDuration(2 * time.Second),
		MaxInterval:  config.JSONDuration(300 * time.Second),
		Jitter:       false,
	}

	tests := []struct {
		attempt       int
		expectedDelay time.Duration
	}{
		{1, 2 * time.Second},  // 2s * 1
		{2, 4 * time.Second},  // 2s * 2
		{3, 6 * time.Second},  // 2s * 3
		{4, 8 * time.Second},  // 2s * 4
		{5, 10 * time.Second}, // 2s * 5
	}

	for _, tc := range tests {
		t.Run(fmt.Sprintf("attempt_%d", tc.attempt), func(t *testing.T) {
			delay := computeRetryDelayForPolicy(tc.attempt, policy)
			if delay != tc.expectedDelay {
				t.Errorf("attempt %d: expected %v, got %v", tc.attempt, tc.expectedDelay, delay)
			}
		})
	}
}

func TestComputeRetryDelayForPolicy_WithJitter(t *testing.T) {
	policy := &config.PolicyConfig{
		Backoff:      config.RetryPolicyExponential,
		InitialDelay: config.JSONDuration(time.Second),
		MaxInterval:  config.JSONDuration(300 * time.Second),
		Jitter:       true,
	}

	baseDelay := time.Second
	minDelay := time.Duration(float64(baseDelay) * 0.5)
	maxDelay := time.Duration(float64(baseDelay) * 1.5)

	seenDifferent := false
	var first time.Duration
	for i := 0; i < 20; i++ {
		delay := computeRetryDelayForPolicy(1, policy)
		if delay < minDelay || delay >= maxDelay {
			t.Errorf("jitter delay %v outside expected range [%v, %v)", delay, minDelay, maxDelay)
		}
		if i == 0 {
			first = delay
		} else if delay != first {
			seenDifferent = true
		}
	}

	if !seenDifferent {
		t.Error("Jitter should produce varied delays across multiple calls")
	}
}

func TestComputeRetryDelayForPolicy_MaxIntervalCap(t *testing.T) {
	policy := &config.PolicyConfig{
		Backoff:      config.RetryPolicyExponential,
		InitialDelay: config.JSONDuration(time.Second),
		MaxInterval:  config.JSONDuration(10 * time.Second),
		Jitter:       false,
	}

	// attempt 5: 1 * 2^4 = 16s, capped at 10s
	delay := computeRetryDelayForPolicy(5, policy)
	if delay != 10*time.Second {
		t.Errorf("Expected delay capped at 10s, got %v", delay)
	}
}

// --- ensureAndUpdateStatus tests ---

func TestRouter_EnsureAndUpdateStatus_DefaultMaxAttemptsZeroWithoutResiliency(t *testing.T) {
	r := &Router{
		actorName: "actor-a",
		cfg:       &config.Config{},
	}

	msg := &envelopes.Envelope{
		ID:      "msg-1",
		Route:   envelopes.Route{Prev: []string{}, Curr: "actor-a", Next: []string{}},
		Payload: json.RawMessage(`{}`),
	}

	r.ensureAndUpdateStatus(msg)

	if msg.Status.MaxAttempts != 0 {
		t.Errorf("Expected default MaxAttempts=0 (unknown until policy matched), got %d", msg.Status.MaxAttempts)
	}
}

func TestRouter_EnsureAndUpdateStatus_ResetsAttemptOnActorTransition(t *testing.T) {
	r := &Router{
		actorName: "actor-b",
		cfg: &config.Config{
			Resiliency: newRetryConfig(7, nil),
		},
	}

	msg := &envelopes.Envelope{
		ID:      "msg-1",
		Route:   envelopes.Route{Prev: []string{"actor-a"}, Curr: "actor-b", Next: []string{}},
		Payload: json.RawMessage(`{}`),
		Status: &envelopes.Status{
			Phase:       envelopes.PhasePending,
			Actor:       "actor-a",
			Attempt:     3,
			MaxAttempts: 5,
		},
	}

	r.ensureAndUpdateStatus(msg)

	if msg.Status.Attempt != 1 {
		t.Errorf("Expected Attempt reset to 1 on actor transition, got %d", msg.Status.Attempt)
	}
}

// --- retryMessage tests ---

func TestRouter_RetryMessage_SendsToOwnQueue(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, newRetryConfig(5, nil))

	msg := &envelopes.Envelope{
		ID:      "msg-retry-1",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next-actor"}},
		Payload: json.RawMessage(`{"data": "test"}`),
		Status: &envelopes.Status{
			Phase:       envelopes.PhaseProcessing,
			Actor:       "test-actor",
			Attempt:     1,
			MaxAttempts: 5,
			CreatedAt:   "2025-01-01T00:00:00Z",
			UpdatedAt:   "2025-01-01T00:00:01Z",
		},
	}

	details := runtime.ErrorDetails{
		Type:      "requests.exceptions.ConnectionError",
		MRO:       []string{"ConnectionError", "IOError", "OSError", "Exception"},
		Message:   "Connection refused",
		Traceback: "Traceback ...",
	}

	err := r.retryMessage(context.Background(), msg, details, 2*time.Second)
	if err != nil {
		t.Fatalf("retryMessage failed: %v", err)
	}

	if len(mt.delayedMessages) != 1 {
		t.Fatalf("Expected 1 delayed message, got %d", len(mt.delayedMessages))
	}

	dm := mt.delayedMessages[0]

	if dm.queue != "asya-default-test-actor" {
		t.Errorf("Expected queue asya-default-test-actor, got %s", dm.queue)
	}

	if dm.delay != 2*time.Second {
		t.Errorf("Expected delay 2s, got %v", dm.delay)
	}

	var retryMsg envelopes.Envelope
	if err := json.Unmarshal(dm.body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal retry message: %v", err)
	}

	if retryMsg.Status.Phase != envelopes.PhaseRetrying {
		t.Errorf("Expected phase retrying, got %s", retryMsg.Status.Phase)
	}

	if retryMsg.Status.Attempt != 2 {
		t.Errorf("Expected attempt incremented to 2, got %d", retryMsg.Status.Attempt)
	}

	if retryMsg.Status.Error == nil {
		t.Fatal("Expected error details in status")
	}

	if retryMsg.Status.Error.Type != "requests.exceptions.ConnectionError" {
		t.Errorf("Expected error type requests.exceptions.ConnectionError, got %s", retryMsg.Status.Error.Type)
	}

	if len(retryMsg.Status.Error.MRO) != 4 {
		t.Errorf("Expected 4 MRO entries, got %d", len(retryMsg.Status.Error.MRO))
	}

	var originalPayload, retryPayload any
	_ = json.Unmarshal([]byte(`{"data": "test"}`), &originalPayload)
	_ = json.Unmarshal(retryMsg.Payload, &retryPayload)
	origBytes, _ := json.Marshal(originalPayload)
	retryBytes, _ := json.Marshal(retryPayload)
	if string(origBytes) != string(retryBytes) {
		t.Errorf("Payload should be preserved, got %s", string(retryMsg.Payload))
	}

	if retryMsg.Route.Curr != "test-actor" {
		t.Errorf("Route.Curr should be preserved as test-actor, got %q", retryMsg.Route.Curr)
	}
}

// --- Full ProcessMessage retry flow tests ---

func TestRouter_ProcessMessage_RetryOnRetriableError(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "requests.exceptions.ConnectionError",
					MRO:     []string{"ConnectionError", "IOError", "OSError", "Exception"},
					Message: "Connection refused",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    newRetryConfig(3, nil),
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := envelopes.Envelope{
		ID:      "test-retry-msg",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next"}},
		Payload: json.RawMessage(`{"input": "data"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage should return nil on retry: %v", err)
	}

	if len(mt.sentMessages) != 0 {
		t.Errorf("Expected no regular sends (to x-sump), got %d", len(mt.sentMessages))
	}

	if len(mt.delayedMessages) != 1 {
		t.Fatalf("Expected 1 delayed message (retry), got %d", len(mt.delayedMessages))
	}

	dm := mt.delayedMessages[0]
	if dm.queue != "asya-default-test-actor" {
		t.Errorf("Retry should go to own queue, got %s", dm.queue)
	}

	var retryMsg envelopes.Envelope
	if err := json.Unmarshal(dm.body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if retryMsg.Status.Phase != envelopes.PhaseRetrying {
		t.Errorf("Expected phase retrying, got %s", retryMsg.Status.Phase)
	}
	if retryMsg.Status.Attempt != 2 {
		t.Errorf("Expected attempt 2, got %d", retryMsg.Status.Attempt)
	}
}

// TestRouter_ProcessMessage_SSEErrorTriggersRetry verifies that generator handler
// errors (delivered as SSE error events) are retried the same way as function
// handler errors (delivered as HTTP 500 JSON responses).
func TestRouter_ProcessMessage_SSEErrorTriggersRetry(t *testing.T) {
	socketPath := startMockSSERuntime(t, func(body []byte) *runtime.RuntimeResponse {
		return &runtime.RuntimeResponse{
			Error: "processing_error",
			Details: runtime.ErrorDetails{
				Type:    "ValueError",
				MRO:     []string{"Exception"},
				Message: "Intentional first-attempt failure",
			},
		}
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    newRetryConfig(3, nil),
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := envelopes.Envelope{
		ID:      "test-sse-retry-msg",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next"}},
		Payload: json.RawMessage(`{"input": "data"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-sse-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage should return nil on retry: %v", err)
	}

	if len(mt.sentMessages) != 0 {
		t.Errorf("Expected no regular sends (to x-sump), got %d", len(mt.sentMessages))
	}

	if len(mt.delayedMessages) != 1 {
		t.Fatalf("Expected 1 delayed message (retry), got %d", len(mt.delayedMessages))
	}

	dm := mt.delayedMessages[0]
	if dm.queue != "asya-default-test-actor" {
		t.Errorf("Retry should go to own queue, got %s", dm.queue)
	}

	var retryMsg envelopes.Envelope
	if err := json.Unmarshal(dm.body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if retryMsg.Status.Phase != envelopes.PhaseRetrying {
		t.Errorf("Expected phase retrying, got %s", retryMsg.Status.Phase)
	}
	if retryMsg.Status.Attempt != 2 {
		t.Errorf("Expected attempt 2, got %d", retryMsg.Status.Attempt)
	}
}

// TestRouter_ProcessMessage_NoMatchingRuleNoDefault verifies that when no rule matches
// and there is no "default" policy, the error goes directly to x-sump without retry.
func TestRouter_ProcessMessage_NoMatchingRuleNoDefault(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "json.decoder.JSONDecodeError",
					MRO:     []string{"ValueError", "Exception"},
					Message: "Expecting value: line 1 column 1",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		// Policy "retryFast" exists but no rule matches JSONDecodeError, and no "default"
		Resiliency: &config.ResiliencyConfig{
			Policies: map[string]config.PolicyConfig{
				"retryFast": {MaxAttempts: 5, Backoff: config.RetryPolicyExponential, InitialDelay: config.JSONDuration(time.Second), MaxInterval: config.JSONDuration(300 * time.Second)},
			},
			Rules: []config.RetryRule{
				{Errors: []string{"ConnectionError"}, Policy: "retryFast"},
			},
		},
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := envelopes.Envelope{
		ID:      "test-nomatch",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{"input": "bad"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage should return nil: %v", err)
	}

	// Should NOT retry — routes to x-sink (full termination path)
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages (no retry), got %d", len(mt.delayedMessages))
	}

	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sink, got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-x-sink" {
		t.Errorf("Expected x-sink queue, got %s", mt.sentMessages[0].queue)
	}

	var errorMsg envelopes.Envelope
	if err := json.Unmarshal(mt.sentMessages[0].body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if errorMsg.Status.Phase != envelopes.PhaseFailed {
		t.Errorf("Expected phase failed, got %s", errorMsg.Status.Phase)
	}
	if errorMsg.Status.Reason != envelopes.ReasonRuntimeError {
		t.Errorf("Expected reason RuntimeError (no matching policy), got %s", errorMsg.Status.Reason)
	}
}

func TestRouter_ProcessMessage_MaxRetriesExhausted(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "TimeoutError",
					MRO:     []string{"OSError", "Exception"},
					Message: "Connection timed out",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    newRetryConfig(3, nil),
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	// Simulate attempt 3 (max) — the message already had 2 previous attempts
	inputMsg := envelopes.Envelope{
		ID:    "test-exhausted",
		Route: envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Status: &envelopes.Status{
			Phase:       envelopes.PhaseRetrying,
			Actor:       "test-actor",
			Attempt:     3,
			MaxAttempts: 3,
			CreatedAt:   "2025-01-01T00:00:00Z",
			UpdatedAt:   "2025-01-01T00:00:05Z",
		},
		Payload: json.RawMessage(`{"input": "data"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage should return nil: %v", err)
	}

	// Should NOT retry — routes to x-sink (full termination path)
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages, got %d", len(mt.delayedMessages))
	}

	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sink, got %d", len(mt.sentMessages))
	}

	var errorMsg envelopes.Envelope
	if err := json.Unmarshal(mt.sentMessages[0].body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if errorMsg.Status.Phase != envelopes.PhaseFailed {
		t.Errorf("Expected phase failed, got %s", errorMsg.Status.Phase)
	}
	if errorMsg.Status.Reason != envelopes.ReasonPolicyExhausted {
		t.Errorf("Expected reason PolicyExhausted, got %s", errorMsg.Status.Reason)
	}
	if errorMsg.Status.Attempt != 3 {
		t.Errorf("Expected attempt 3, got %d", errorMsg.Status.Attempt)
	}
}

func TestRouter_ProcessMessage_NoResiliency_FailsImmediately(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "RuntimeError",
					Message: "Something failed",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    nil, // No resiliency
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := envelopes.Envelope{
		ID:      "test-legacy",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage should return nil: %v", err)
	}

	// Without resiliency, should go directly to x-sink (full termination path)
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages, got %d", len(mt.delayedMessages))
	}

	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sink, got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-x-sink" {
		t.Errorf("Expected x-sink queue, got %s", mt.sentMessages[0].queue)
	}
}

func TestRouter_ProcessMessage_SendWithDelayFails_FallsBackToSump(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "ConnectionError",
					Message: "Remote host unreachable",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{
		sendWithDelayFn: func(_ context.Context, _ string, _ []byte, _ time.Duration) error {
			return transport.ErrDelayNotSupported
		},
	}

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "rabbitmq",
		Timeout:       5 * time.Second,
		Resiliency:    newRetryConfig(5, nil),
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := envelopes.Envelope{
		ID:      "test-delay-fail",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage should return nil on fallback: %v", err)
	}

	// SendWithDelay failed, should fall back to x-sink (full termination path)
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sink (fallback), got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-x-sink" {
		t.Errorf("Expected x-sink queue, got %s", mt.sentMessages[0].queue)
	}
}

func TestRouter_ProcessMessage_RetryPreservesPayloadAndRoute(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "TimeoutError",
					Message: "API timeout",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    newRetryConfig(5, nil),
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	originalPayload := `{"complex": {"nested": true}, "array": [1,2,3]}`
	inputMsg := envelopes.Envelope{
		ID:      "test-preserve",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next-actor", "final"}},
		Payload: json.RawMessage(originalPayload),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mt.delayedMessages) != 1 {
		t.Fatalf("Expected 1 delayed message, got %d", len(mt.delayedMessages))
	}

	var retryMsg envelopes.Envelope
	if err := json.Unmarshal(mt.delayedMessages[0].body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if retryMsg.Route.Curr != "test-actor" {
		t.Errorf("Expected route.curr=test-actor, got %q", retryMsg.Route.Curr)
	}
	if len(retryMsg.Route.Prev) != 0 {
		t.Errorf("Expected empty prev, got %v", retryMsg.Route.Prev)
	}
	if len(retryMsg.Route.Next) != 2 {
		t.Errorf("Expected 2 next actors, got %d: %v", len(retryMsg.Route.Next), retryMsg.Route.Next)
	}

	var originalParsed, retryParsed any
	_ = json.Unmarshal([]byte(originalPayload), &originalParsed)
	_ = json.Unmarshal(retryMsg.Payload, &retryParsed)

	originalBytes, _ := json.Marshal(originalParsed)
	retryBytes, _ := json.Marshal(retryParsed)
	if string(originalBytes) != string(retryBytes) {
		t.Errorf("Payload should be preserved.\nExpected: %s\nGot: %s", string(originalBytes), string(retryBytes))
	}
}

func TestRouter_SendRetryFailure_PreservesErrorDetailsInPayload(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, newRetryConfig(3, nil))

	msg := &envelopes.Envelope{
		ID:      "msg-fail",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{"original": "data"}`),
		Status: &envelopes.Status{
			Phase:       envelopes.PhaseProcessing,
			Actor:       "test-actor",
			Attempt:     3,
			MaxAttempts: 3,
			CreatedAt:   "2025-01-01T00:00:00Z",
		},
	}

	response := runtime.RuntimeResponse{
		Error: "processing_error",
		Details: runtime.ErrorDetails{
			Type:      "ValueError",
			MRO:       []string{"Exception"},
			Message:   "bad value",
			Traceback: "File ...",
		},
	}

	err := r.sendRetryFailure(context.Background(), msg, response, envelopes.ReasonPolicyExhausted)
	if err != nil {
		t.Fatalf("sendRetryFailure failed: %v", err)
	}

	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 sent message, got %d", len(mt.sentMessages))
	}

	var failedMsg envelopes.Envelope
	if err := json.Unmarshal(mt.sentMessages[0].body, &failedMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if failedMsg.Status.Phase != envelopes.PhaseFailed {
		t.Errorf("Expected phase failed, got %s", failedMsg.Status.Phase)
	}
	if failedMsg.Status.Reason != envelopes.ReasonPolicyExhausted {
		t.Errorf("Expected reason PolicyExhausted, got %s", failedMsg.Status.Reason)
	}
	if failedMsg.Status.Attempt != 3 {
		t.Errorf("Expected attempt 3, got %d", failedMsg.Status.Attempt)
	}
	if failedMsg.Status.Error == nil {
		t.Fatal("Expected error in status")
	}
	if failedMsg.Status.Error.Type != "ValueError" {
		t.Errorf("Expected error type ValueError, got %s", failedMsg.Status.Error.Type)
	}
	if len(failedMsg.Status.Error.MRO) != 1 || failedMsg.Status.Error.MRO[0] != "Exception" {
		t.Errorf("Expected MRO [Exception], got %v", failedMsg.Status.Error.MRO)
	}

	var payload map[string]any
	if err := json.Unmarshal(failedMsg.Payload, &payload); err != nil {
		t.Fatalf("Failed to unmarshal payload: %v", err)
	}
	if payload["error"] != "processing_error" {
		t.Errorf("Expected error in payload, got %v", payload["error"])
	}
	if payload["original_payload"] == nil {
		t.Error("Expected original_payload preserved in error payload")
	}
}

// --- isDurationExhausted unit tests ---

func TestRouter_IsDurationExhausted_ZeroMaxDuration(t *testing.T) {
	msg := &envelopes.Envelope{
		Headers: map[string]interface{}{
			envelopes.HeaderFirstAttempt: time.Now().Add(-1 * time.Hour).UTC().Format(time.RFC3339),
		},
	}
	if isDurationExhausted(msg, 0) {
		t.Error("Expected false when MaxDuration=0 (no limit)")
	}
}

func TestRouter_IsDurationExhausted_HeaderAbsent(t *testing.T) {
	msg := &envelopes.Envelope{Headers: map[string]interface{}{}}
	if isDurationExhausted(msg, 10*time.Minute) {
		t.Error("Expected false when x-asya-first-attempt header is absent")
	}
}

func TestRouter_IsDurationExhausted_NilHeaders(t *testing.T) {
	msg := &envelopes.Envelope{}
	if isDurationExhausted(msg, 10*time.Minute) {
		t.Error("Expected false when msg.Headers is nil")
	}
}

func TestRouter_IsDurationExhausted_HeaderUnparseable(t *testing.T) {
	msg := &envelopes.Envelope{
		Headers: map[string]interface{}{
			envelopes.HeaderFirstAttempt: "not-a-timestamp",
		},
	}
	if isDurationExhausted(msg, 10*time.Minute) {
		t.Error("Expected false when header value is unparseable")
	}
}

func TestRouter_IsDurationExhausted_NotYetExhausted(t *testing.T) {
	msg := &envelopes.Envelope{
		Headers: map[string]interface{}{
			envelopes.HeaderFirstAttempt: time.Now().UTC().Format(time.RFC3339),
		},
	}
	if isDurationExhausted(msg, 10*time.Minute) {
		t.Error("Expected false when first attempt was recent and maxDuration is 10m")
	}
}

func TestRouter_IsDurationExhausted_Exhausted(t *testing.T) {
	msg := &envelopes.Envelope{
		Headers: map[string]interface{}{
			envelopes.HeaderFirstAttempt: time.Now().Add(-2 * time.Hour).UTC().Format(time.RFC3339),
		},
	}
	if !isDurationExhausted(msg, 30*time.Minute) {
		t.Error("Expected true when 2h have elapsed and maxDuration=30m")
	}
}

// --- x-asya-first-attempt header lifecycle tests ---

func TestRouter_ProcessMessage_FirstAttemptHeaderStampedOnFirstAttempt(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "RuntimeError",
					Message: "transient failure",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    newRetryConfig(3, nil),
	}

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtime.NewClient(socketPath, 2*time.Second),
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := envelopes.Envelope{
		ID:      "test-first-stamp",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next"}},
		Payload: json.RawMessage(`{}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	before := time.Now().UTC().Truncate(time.Second)
	err := router.ProcessMessage(context.Background(), transport.QueueMessage{ID: "q1", Body: msgBody})
	after := time.Now().UTC()
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mt.delayedMessages) != 1 {
		t.Fatalf("Expected 1 retry message, got %d", len(mt.delayedMessages))
	}

	var retryMsg envelopes.Envelope
	if err := json.Unmarshal(mt.delayedMessages[0].body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal retry message: %v", err)
	}

	raw, ok := retryMsg.Headers[envelopes.HeaderFirstAttempt].(string)
	if !ok {
		t.Fatal("Expected x-asya-first-attempt header in retry message")
	}
	ts, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		t.Fatalf("x-asya-first-attempt is not valid RFC3339: %v", err)
	}
	if ts.Before(before) || ts.After(after) {
		t.Errorf("x-asya-first-attempt %v outside expected range [%v, %v]", ts, before, after)
	}
}

func TestRouter_ProcessMessage_FirstAttemptHeaderPreservedOnRetry(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "RuntimeError",
					Message: "transient failure",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    newRetryConfig(5, nil),
	}

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtime.NewClient(socketPath, 2*time.Second),
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	originalTimestamp := "2025-01-01T10:00:00Z"
	inputMsg := envelopes.Envelope{
		ID:      "test-header-preserved",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next"}},
		Payload: json.RawMessage(`{}`),
		Headers: map[string]interface{}{
			envelopes.HeaderFirstAttempt: originalTimestamp,
		},
		Status: &envelopes.Status{
			Phase:       envelopes.PhaseRetrying,
			Actor:       "test-actor",
			Attempt:     2,
			MaxAttempts: 5,
			CreatedAt:   "2025-01-01T10:00:00Z",
			UpdatedAt:   "2025-01-01T10:00:01Z",
		},
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{ID: "q2", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mt.delayedMessages) != 1 {
		t.Fatalf("Expected 1 retry message, got %d", len(mt.delayedMessages))
	}

	var retryMsg envelopes.Envelope
	if err := json.Unmarshal(mt.delayedMessages[0].body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal retry message: %v", err)
	}

	raw, ok := retryMsg.Headers[envelopes.HeaderFirstAttempt].(string)
	if !ok {
		t.Fatal("Expected x-asya-first-attempt header preserved in retry message")
	}
	if raw != originalTimestamp {
		t.Errorf("x-asya-first-attempt was overwritten: expected %q, got %q", originalTimestamp, raw)
	}
}

func TestRouter_ProcessMessage_MaxDurationExhaustedBeforeMaxAttempts(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "RuntimeError",
					Message: "transient failure",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency: &config.ResiliencyConfig{
			Policies: map[string]config.PolicyConfig{
				"default": {
					MaxAttempts:  10,
					Backoff:      config.RetryPolicyExponential,
					InitialDelay: config.JSONDuration(time.Second),
					MaxInterval:  config.JSONDuration(300 * time.Second),
					MaxDuration:  config.JSONDuration(1 * time.Hour), // already exceeded (header is 2h ago)
				},
			},
		},
	}

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtime.NewClient(socketPath, 2*time.Second),
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	// x-asya-first-attempt set 2h ago; maxDuration=1h → duration is exhausted
	inputMsg := envelopes.Envelope{
		ID:      "test-max-duration",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next"}},
		Payload: json.RawMessage(`{}`),
		Headers: map[string]interface{}{
			envelopes.HeaderFirstAttempt: time.Now().Add(-2 * time.Hour).UTC().Format(time.RFC3339),
		},
		Status: &envelopes.Status{
			Phase:       envelopes.PhaseRetrying,
			Actor:       "test-actor",
			Attempt:     2, // well below MaxAttempts=10
			MaxAttempts: 10,
			CreatedAt:   time.Now().Add(-2 * time.Hour).UTC().Format(time.RFC3339),
			UpdatedAt:   time.Now().UTC().Format(time.RFC3339),
		},
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{ID: "q3", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Duration exhausted — routes to x-sink (full termination path, not retry)
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no retries when maxDuration exceeded, got %d", len(mt.delayedMessages))
	}
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sink, got %d", len(mt.sentMessages))
	}
	if mt.sentMessages[0].queue != "asya-default-x-sink" {
		t.Errorf("Expected x-sink queue, got %s", mt.sentMessages[0].queue)
	}

	var failedMsg envelopes.Envelope
	if err := json.Unmarshal(mt.sentMessages[0].body, &failedMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}
	if failedMsg.Status.Phase != envelopes.PhaseFailed {
		t.Errorf("Expected phase failed, got %s", failedMsg.Status.Phase)
	}
	if failedMsg.Status.Reason != envelopes.ReasonPolicyExhausted {
		t.Errorf("Expected reason PolicyExhausted, got %s", failedMsg.Status.Reason)
	}
}

func TestRouter_ProcessMessage_PolicyWithOnExhausted(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "RuntimeError",
					Message: "permanent failure",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		// Policy with onExhausted — after exhausting attempts, route to recovery-actor
		Resiliency: newRetryConfig(1, []string{"recovery-actor"}),
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := envelopes.Envelope{
		ID:      "test-thenroute",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{"input": "data"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage should return nil: %v", err)
	}

	// With onExhausted, should go to recovery-actor queue (not x-sump)
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages, got %d", len(mt.delayedMessages))
	}
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to recovery-actor, got %d", len(mt.sentMessages))
	}

	expectedQueue := "asya-default-recovery-actor"
	if mt.sentMessages[0].queue != expectedQueue {
		t.Errorf("Expected queue %s, got %s", expectedQueue, mt.sentMessages[0].queue)
	}

	var routedMsg envelopes.Envelope
	if err := json.Unmarshal(mt.sentMessages[0].body, &routedMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}
	if routedMsg.Status.Reason != envelopes.ReasonPolicyRouted {
		t.Errorf("Expected reason PolicyRouted, got %s", routedMsg.Status.Reason)
	}
}

func TestRouter_ProcessMessage_MaxAttemptsOne_NoRetry(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Type:    "RuntimeError",
					Message: "Something failed",
				},
			},
		}, http.StatusInternalServerError
	})

	mt := &retryMockTransport{}
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "sqs",
		Timeout:       5 * time.Second,
		Resiliency:    newRetryConfig(1, nil), // MaxAttempts=1 means no retry
	}

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mt,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := envelopes.Envelope{
		ID:      "test-maxone",
		Route:   envelopes.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "queue-msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage should return nil: %v", err)
	}

	// MaxAttempts=1 should exhaust immediately (policy_exhausted)
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages with MaxAttempts=1, got %d", len(mt.delayedMessages))
	}
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sink, got %d", len(mt.sentMessages))
	}
}

// --- TestApplyPolicyDispatch ---

func TestApplyPolicyDispatch(t *testing.T) {
	ctx := context.Background()

	makeMsg := func(attempt int, firstAttemptAgo time.Duration) *envelopes.Envelope {
		headers := map[string]interface{}{}
		if firstAttemptAgo > 0 {
			ts := time.Now().Add(-firstAttemptAgo).UTC().Format(time.RFC3339)
			headers[envelopes.HeaderFirstAttempt] = ts
		} else {
			headers[envelopes.HeaderFirstAttempt] = time.Now().UTC().Format(time.RFC3339)
		}
		return &envelopes.Envelope{
			ID:      "test-id",
			Payload: json.RawMessage(`{}`),
			Route:   envelopes.Route{Curr: "test-actor", Next: []string{}},
			Status: &envelopes.Status{
				Attempt:     attempt,
				MaxAttempts: 0,
				Actor:       "test-actor",
			},
			Headers: headers,
		}
	}

	makeResponse := func() runtime.RuntimeResponse {
		return runtime.RuntimeResponse{
			Error: "processing_error",
			Details: runtime.ErrorDetails{
				Type:    "requests.exceptions.ConnectionError",
				MRO:     []string{"builtins.OSError", "builtins.Exception"},
				Message: "connection refused",
			},
		}
	}

	t.Run("retries when attempts remain", func(t *testing.T) {
		tr := &retryMockTransport{}
		router, _ := newTestRouterWithRetry(t, tr, &config.ResiliencyConfig{
			Policies: map[string]config.PolicyConfig{
				"default": {MaxAttempts: 3, Backoff: config.RetryPolicyConstant, InitialDelay: config.JSONDuration(10 * time.Millisecond)},
			},
		})
		msg := makeMsg(1, 0)
		policy := &config.PolicyConfig{MaxAttempts: 3, Backoff: config.RetryPolicyConstant, InitialDelay: config.JSONDuration(10 * time.Millisecond)}

		err := router.applyPolicy(ctx, msg, policy, makeResponse())
		if err != nil {
			t.Fatalf("applyPolicy() error = %v", err)
		}
		if len(tr.delayedMessages) != 1 {
			t.Errorf("expected 1 delayed (retry) message, got %d", len(tr.delayedMessages))
		}
	})

	t.Run("routes to onExhausted when exhausted", func(t *testing.T) {
		tr := &retryMockTransport{}
		router, _ := newTestRouterWithRetry(t, tr, &config.ResiliencyConfig{
			Policies: map[string]config.PolicyConfig{
				"default": {MaxAttempts: 1, OnExhausted: []string{"recovery-actor"}},
			},
		})
		msg := makeMsg(1, 0) // attempt 1 = exhausted for maxAttempts=1

		policy := &config.PolicyConfig{MaxAttempts: 1, OnExhausted: []string{"recovery-actor"}}
		err := router.applyPolicy(ctx, msg, policy, makeResponse())
		if err != nil {
			t.Fatalf("applyPolicy() error = %v", err)
		}
		// Should have sent to recovery-actor, not via delayed retry
		if len(tr.delayedMessages) > 0 {
			t.Error("should NOT retry when exhausted")
		}
		// Check a Send (not SendWithDelay) was made to recovery-actor
		if len(tr.sentMessages) != 1 {
			t.Fatalf("expected 1 sent message (to recovery-actor), got %d", len(tr.sentMessages))
		}
		if tr.sentMessages[0].queue != "asya-default-recovery-actor" {
			t.Errorf("expected onExhausted route to recovery-actor, got queue %s", tr.sentMessages[0].queue)
		}
	})

	t.Run("routes to failure path when exhausted and no onExhausted", func(t *testing.T) {
		tr := &retryMockTransport{}
		router, _ := newTestRouterWithRetry(t, tr, &config.ResiliencyConfig{
			Policies: map[string]config.PolicyConfig{
				"default": {MaxAttempts: 1},
			},
		})
		msg := makeMsg(1, 0)

		policy := &config.PolicyConfig{MaxAttempts: 1}
		err := router.applyPolicy(ctx, msg, policy, makeResponse())
		if err != nil {
			t.Fatalf("applyPolicy() error = %v", err)
		}
		// Should NOT retry
		if len(tr.delayedMessages) > 0 {
			t.Error("should NOT retry when exhausted")
		}
		// Should have sent to failure queue (x-sink or x-sump based on logic)
		if len(tr.sentMessages) != 1 {
			t.Errorf("expected 1 sent message (failure path), got %d", len(tr.sentMessages))
		}
	})

	t.Run("stops retrying when maxDuration exceeded", func(t *testing.T) {
		tr := &retryMockTransport{}
		router, _ := newTestRouterWithRetry(t, tr, &config.ResiliencyConfig{
			Policies: map[string]config.PolicyConfig{
				"default": {MaxAttempts: 10, MaxDuration: config.JSONDuration(1 * time.Second)},
			},
		})
		// Simulate first attempt was 2 seconds ago
		msg := makeMsg(2, 2*time.Second)

		policy := &config.PolicyConfig{MaxAttempts: 10, MaxDuration: config.JSONDuration(1 * time.Second)}
		err := router.applyPolicy(ctx, msg, policy, makeResponse())
		if err != nil {
			t.Fatalf("applyPolicy() error = %v", err)
		}
		// Duration exceeded — should NOT retry
		if len(tr.delayedMessages) > 0 {
			t.Error("should NOT retry when maxDuration exhausted")
		}
	})
}
