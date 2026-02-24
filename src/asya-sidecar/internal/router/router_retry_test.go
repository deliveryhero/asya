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
	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
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

// newRetryConfig creates a resiliency config for tests with sensible defaults
func newRetryConfig(maxAttempts int, nonRetryable []string) *config.ResiliencyConfig {
	return &config.ResiliencyConfig{
		Retry: config.RetryConfig{
			Policy:             config.RetryPolicyExponential,
			MaxAttempts:        maxAttempts,
			InitialInterval:    time.Second,
			MaxInterval:        300 * time.Second,
			BackoffCoefficient: 2.0,
			Jitter:             false,
		},
		NonRetryableErrors: nonRetryable,
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

// --- isNonRetryableError tests ---

func TestRouter_IsNonRetryableError_DirectTypeMatch(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, newRetryConfig(3, []string{"ValueError", "KeyError"}))

	if !r.isNonRetryableError("ValueError", nil) {
		t.Error("Expected ValueError to match nonRetryableErrors directly")
	}
}

func TestRouter_IsNonRetryableError_MROMatch(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, newRetryConfig(3, []string{"ValueError"}))

	// json.decoder.JSONDecodeError inherits from ValueError via MRO
	if !r.isNonRetryableError("json.decoder.JSONDecodeError", []string{"ValueError", "Exception"}) {
		t.Error("Expected json.decoder.JSONDecodeError to match via MRO ancestor ValueError")
	}
}

func TestRouter_IsNonRetryableError_NoMatch(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, newRetryConfig(3, []string{"ValueError"}))

	if r.isNonRetryableError("TimeoutError", []string{"OSError", "Exception"}) {
		t.Error("TimeoutError should not match nonRetryableErrors=[ValueError]")
	}
}

func TestRouter_IsNonRetryableError_NoConfig(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, nil)

	if r.isNonRetryableError("ValueError", []string{"Exception"}) {
		t.Error("Should return false when no resiliency config")
	}
}

func TestRouter_IsNonRetryableError_EmptyBlacklist(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, newRetryConfig(3, nil))

	if r.isNonRetryableError("ValueError", []string{"Exception"}) {
		t.Error("Should return false with empty nonRetryableErrors list")
	}
}

// --- computeRetryDelay tests ---

func TestRouter_ComputeRetryDelay_Exponential(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, &config.ResiliencyConfig{
		Retry: config.RetryConfig{
			Policy:             config.RetryPolicyExponential,
			MaxAttempts:        5,
			InitialInterval:    time.Second,
			MaxInterval:        300 * time.Second,
			BackoffCoefficient: 2.0,
			Jitter:             false,
		},
	})

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
			delay := r.computeRetryDelay(tc.attempt)
			if delay != tc.expectedDelay {
				t.Errorf("attempt %d: expected %v, got %v", tc.attempt, tc.expectedDelay, delay)
			}
		})
	}
}

func TestRouter_ComputeRetryDelay_Constant(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, &config.ResiliencyConfig{
		Retry: config.RetryConfig{
			Policy:             config.RetryPolicyConstant,
			MaxAttempts:        5,
			InitialInterval:    3 * time.Second,
			MaxInterval:        300 * time.Second,
			BackoffCoefficient: 2.0,
			Jitter:             false,
		},
	})

	for attempt := 1; attempt <= 5; attempt++ {
		delay := r.computeRetryDelay(attempt)
		if delay != 3*time.Second {
			t.Errorf("attempt %d: expected constant 3s, got %v", attempt, delay)
		}
	}
}

func TestRouter_ComputeRetryDelay_WithJitter(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, &config.ResiliencyConfig{
		Retry: config.RetryConfig{
			Policy:             config.RetryPolicyExponential,
			MaxAttempts:        5,
			InitialInterval:    time.Second,
			MaxInterval:        300 * time.Second,
			BackoffCoefficient: 2.0,
			Jitter:             true,
		},
	})

	baseDelay := time.Second // attempt 1 base delay
	minDelay := time.Duration(float64(baseDelay) * 0.5)
	maxDelay := time.Duration(float64(baseDelay) * 1.5)

	// Run multiple times to verify jitter produces varied results
	seenDifferent := false
	var first time.Duration
	for i := 0; i < 20; i++ {
		delay := r.computeRetryDelay(1)
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

func TestRouter_ComputeRetryDelay_MaxIntervalCap(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, &config.ResiliencyConfig{
		Retry: config.RetryConfig{
			Policy:             config.RetryPolicyExponential,
			MaxAttempts:        20,
			InitialInterval:    time.Second,
			MaxInterval:        10 * time.Second,
			BackoffCoefficient: 3.0,
			Jitter:             false,
		},
	})

	// attempt 5: 1 * 3^4 = 81s, capped at 10s
	delay := r.computeRetryDelay(5)
	if delay != 10*time.Second {
		t.Errorf("Expected delay capped at 10s, got %v", delay)
	}
}

// --- ensureAndUpdateStatus with resiliency tests ---

func TestRouter_EnsureAndUpdateStatus_SetsMaxAttemptsFromResiliency(t *testing.T) {
	r := &Router{
		actorName: "actor-a",
		cfg: &config.Config{
			Resiliency: newRetryConfig(5, nil),
		},
	}

	msg := &messages.Message{
		ID:      "msg-1",
		Route:   messages.Route{Prev: []string{}, Curr: "actor-a", Next: []string{}},
		Payload: json.RawMessage(`{}`),
	}

	r.ensureAndUpdateStatus(msg)

	if msg.Status.MaxAttempts != 5 {
		t.Errorf("Expected MaxAttempts=5 from resiliency config, got %d", msg.Status.MaxAttempts)
	}
}

func TestRouter_EnsureAndUpdateStatus_DefaultMaxAttemptsWithoutResiliency(t *testing.T) {
	r := &Router{
		actorName: "actor-a",
		cfg:       &config.Config{},
	}

	msg := &messages.Message{
		ID:      "msg-1",
		Route:   messages.Route{Prev: []string{}, Curr: "actor-a", Next: []string{}},
		Payload: json.RawMessage(`{}`),
	}

	r.ensureAndUpdateStatus(msg)

	if msg.Status.MaxAttempts != 1 {
		t.Errorf("Expected default MaxAttempts=1, got %d", msg.Status.MaxAttempts)
	}
}

func TestRouter_EnsureAndUpdateStatus_UpdatesMaxAttemptsOnTransition(t *testing.T) {
	r := &Router{
		actorName: "actor-b",
		cfg: &config.Config{
			Resiliency: newRetryConfig(7, nil),
		},
	}

	msg := &messages.Message{
		ID:      "msg-1",
		Route:   messages.Route{Prev: []string{"actor-a"}, Curr: "actor-b", Next: []string{}},
		Payload: json.RawMessage(`{}`),
		Status: &messages.Status{
			Phase:       messages.PhasePending,
			Actor:       "actor-a",
			Attempt:     3,
			MaxAttempts: 5,
		},
	}

	r.ensureAndUpdateStatus(msg)

	if msg.Status.MaxAttempts != 7 {
		t.Errorf("Expected MaxAttempts=7 after actor transition, got %d", msg.Status.MaxAttempts)
	}
	if msg.Status.Attempt != 1 {
		t.Errorf("Expected Attempt reset to 1 on actor transition, got %d", msg.Status.Attempt)
	}
}

// --- retryMessage tests ---

func TestRouter_RetryMessage_SendsToOwnQueue(t *testing.T) {
	mt := &retryMockTransport{}
	r, _ := newTestRouterWithRetry(t, mt, newRetryConfig(5, nil))

	msg := &messages.Message{
		ID:      "msg-retry-1",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next-actor"}},
		Payload: json.RawMessage(`{"data": "test"}`),
		Status: &messages.Status{
			Phase:       messages.PhaseProcessing,
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

	// Verify queue name
	if dm.queue != "asya-default-test-actor" {
		t.Errorf("Expected queue asya-default-test-actor, got %s", dm.queue)
	}

	// Verify delay
	if dm.delay != 2*time.Second {
		t.Errorf("Expected delay 2s, got %v", dm.delay)
	}

	// Verify message content
	var retryMsg messages.Message
	if err := json.Unmarshal(dm.body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal retry message: %v", err)
	}

	if retryMsg.Status.Phase != messages.PhaseRetrying {
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

	// Verify payload is preserved unchanged (compare parsed to avoid whitespace differences)
	var originalPayload, retryPayload any
	_ = json.Unmarshal([]byte(`{"data": "test"}`), &originalPayload)
	_ = json.Unmarshal(retryMsg.Payload, &retryPayload)
	origBytes, _ := json.Marshal(originalPayload)
	retryBytes, _ := json.Marshal(retryPayload)
	if string(origBytes) != string(retryBytes) {
		t.Errorf("Payload should be preserved, got %s", string(retryMsg.Payload))
	}

	// Verify route is preserved unchanged (curr remains test-actor, not yet shifted)
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

	inputMsg := messages.Message{
		ID:      "test-retry-msg",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next"}},
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

	// Should have sent via SendWithDelay, NOT to x-sump
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

	var retryMsg messages.Message
	if err := json.Unmarshal(dm.body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if retryMsg.Status.Phase != messages.PhaseRetrying {
		t.Errorf("Expected phase retrying, got %s", retryMsg.Status.Phase)
	}
	if retryMsg.Status.Attempt != 2 {
		t.Errorf("Expected attempt 2, got %d", retryMsg.Status.Attempt)
	}
	if retryMsg.Status.MaxAttempts != 3 {
		t.Errorf("Expected max_attempts 3, got %d", retryMsg.Status.MaxAttempts)
	}
}

func TestRouter_ProcessMessage_NonRetryableError(t *testing.T) {
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
		Resiliency:    newRetryConfig(5, []string{"ValueError"}),
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

	inputMsg := messages.Message{
		ID:      "test-nonretryable",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
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

	// Should NOT retry — should send directly to x-sump
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages (no retry), got %d", len(mt.delayedMessages))
	}

	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sump, got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-x-sump" {
		t.Errorf("Expected x-sump queue, got %s", mt.sentMessages[0].queue)
	}

	var errorMsg messages.Message
	if err := json.Unmarshal(mt.sentMessages[0].body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if errorMsg.Status.Phase != messages.PhaseFailed {
		t.Errorf("Expected phase failed, got %s", errorMsg.Status.Phase)
	}
	if errorMsg.Status.Reason != messages.ReasonNonRetryableFailure {
		t.Errorf("Expected reason NonRetryableFailure, got %s", errorMsg.Status.Reason)
	}
	if errorMsg.Status.Error == nil {
		t.Fatal("Expected error details in status")
	}
	if errorMsg.Status.Error.Type != "json.decoder.JSONDecodeError" {
		t.Errorf("Expected error type json.decoder.JSONDecodeError, got %s", errorMsg.Status.Error.Type)
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
	inputMsg := messages.Message{
		ID:    "test-exhausted",
		Route: messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Status: &messages.Status{
			Phase:       messages.PhaseRetrying,
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

	// Should NOT retry — should send to x-sump
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages, got %d", len(mt.delayedMessages))
	}

	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sump, got %d", len(mt.sentMessages))
	}

	var errorMsg messages.Message
	if err := json.Unmarshal(mt.sentMessages[0].body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if errorMsg.Status.Phase != messages.PhaseFailed {
		t.Errorf("Expected phase failed, got %s", errorMsg.Status.Phase)
	}
	if errorMsg.Status.Reason != messages.ReasonMaxRetriesExhausted {
		t.Errorf("Expected reason MaxRetriesExhausted, got %s", errorMsg.Status.Reason)
	}
	if errorMsg.Status.Attempt != 3 {
		t.Errorf("Expected attempt 3, got %d", errorMsg.Status.Attempt)
	}
	if errorMsg.Status.MaxAttempts != 3 {
		t.Errorf("Expected max_attempts 3, got %d", errorMsg.Status.MaxAttempts)
	}
}

func TestRouter_ProcessMessage_NoResiliency_LegacyBehavior(t *testing.T) {
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

	inputMsg := messages.Message{
		ID:      "test-legacy",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
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

	// Without resiliency, should go directly to x-sump
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages, got %d", len(mt.delayedMessages))
	}

	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sump, got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-x-sump" {
		t.Errorf("Expected x-sump queue, got %s", mt.sentMessages[0].queue)
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

	inputMsg := messages.Message{
		ID:      "test-delay-fail",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
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

	// SendWithDelay failed, should fall back to x-sump
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sump (fallback), got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-x-sump" {
		t.Errorf("Expected x-sump queue, got %s", mt.sentMessages[0].queue)
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
	inputMsg := messages.Message{
		ID:      "test-preserve",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{"next-actor", "final"}},
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

	var retryMsg messages.Message
	if err := json.Unmarshal(mt.delayedMessages[0].body, &retryMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// Route must be preserved exactly (curr=test-actor, prev=[], next=[next-actor, final])
	if retryMsg.Route.Curr != "test-actor" {
		t.Errorf("Expected route.curr=test-actor, got %q", retryMsg.Route.Curr)
	}
	if len(retryMsg.Route.Prev) != 0 {
		t.Errorf("Expected empty prev, got %v", retryMsg.Route.Prev)
	}
	if len(retryMsg.Route.Next) != 2 {
		t.Errorf("Expected 2 next actors, got %d: %v", len(retryMsg.Route.Next), retryMsg.Route.Next)
	}

	// Payload must be preserved exactly
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

	msg := &messages.Message{
		ID:      "msg-fail",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{"original": "data"}`),
		Status: &messages.Status{
			Phase:       messages.PhaseProcessing,
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

	err := r.sendRetryFailure(context.Background(), msg, response, messages.ReasonMaxRetriesExhausted)
	if err != nil {
		t.Fatalf("sendRetryFailure failed: %v", err)
	}

	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 sent message, got %d", len(mt.sentMessages))
	}

	var failedMsg messages.Message
	if err := json.Unmarshal(mt.sentMessages[0].body, &failedMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// Verify status fields
	if failedMsg.Status.Phase != messages.PhaseFailed {
		t.Errorf("Expected phase failed, got %s", failedMsg.Status.Phase)
	}
	if failedMsg.Status.Reason != messages.ReasonMaxRetriesExhausted {
		t.Errorf("Expected reason MaxRetriesExhausted, got %s", failedMsg.Status.Reason)
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

	// Verify payload has error details (backward compat with x-sump actor)
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

	inputMsg := messages.Message{
		ID:      "test-maxone",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
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

	// MaxAttempts=1 should behave like no retry
	if len(mt.delayedMessages) != 0 {
		t.Errorf("Expected no delayed messages with MaxAttempts=1, got %d", len(mt.delayedMessages))
	}
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sump, got %d", len(mt.sentMessages))
	}
}
