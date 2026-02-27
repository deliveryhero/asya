package router

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/progress"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
)

const (
	testQueueSink = "x-sink"
	testQueueSump = "x-sump"
)

// mockTransport implements transport.Transport for testing
type mockTransport struct {
	sentMessages []struct {
		queue string
		body  []byte
	}
}

func (m *mockTransport) Receive(ctx context.Context, queueName string) (transport.QueueMessage, error) {
	return transport.QueueMessage{}, nil
}

func (m *mockTransport) Send(ctx context.Context, queueName string, body []byte) error {
	m.sentMessages = append(m.sentMessages, struct {
		queue string
		body  []byte
	}{queueName, body})
	return nil
}

func (m *mockTransport) Ack(ctx context.Context, msg transport.QueueMessage) error {
	return nil
}

func (m *mockTransport) Requeue(ctx context.Context, msg transport.QueueMessage) error {
	return nil
}

func (m *mockTransport) SendWithDelay(ctx context.Context, queueName string, body []byte, delay time.Duration) error {
	return nil
}

// mockHTTPServer mocks HTTP server for gateway testing
type mockHTTPServer struct {
	server    *httptest.Server
	requests  map[string]*mockHTTPRequest
	responses map[string]mockHTTPResponse
	mu        sync.Mutex
	URL       string
}

type mockHTTPRequest struct {
	Path   string
	Method string
	Body   []byte
}

type mockHTTPResponse struct {
	StatusCode int
	Body       []byte
}

func (m *mockHTTPServer) Start(t *testing.T) {
	m.requests = make(map[string]*mockHTTPRequest)
	m.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		defer func() {
			_ = r.Body.Close()
		}()

		m.mu.Lock()
		m.requests[r.URL.Path] = &mockHTTPRequest{
			Path:   r.URL.Path,
			Method: r.Method,
			Body:   body,
		}

		resp, ok := m.responses[r.URL.Path]
		if !ok {
			resp = mockHTTPResponse{StatusCode: 200, Body: []byte(`{}`)}
		}
		m.mu.Unlock()

		w.WriteHeader(resp.StatusCode)
		_, _ = w.Write(resp.Body)
	}))
	m.URL = m.server.URL
}

func (m *mockHTTPServer) Close() {
	if m.server != nil {
		m.server.Close()
	}
}

func (m *mockHTTPServer) GetRequest(path string) *mockHTTPRequest {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.requests[path]
}

func (m *mockTransport) Close() error {
	return nil
}

func TestRouter_RouteValidation(t *testing.T) {
	tests := []struct {
		name                 string
		actorName            string
		inputRoute           messages.Route
		expectedWarnContains string
		shouldRejectAndError bool
		shouldCallRuntime    bool
		expectedDestQueue    string
	}{
		{
			name:      "route matches sidecar queue - processes normally",
			actorName: "test-actor",
			inputRoute: messages.Route{
				Prev: []string{},
				Curr: "test-actor",
				Next: []string{"next-actor"},
			},
			shouldRejectAndError: false,
			shouldCallRuntime:    true,
			expectedDestQueue:    "asya-default-next-actor",
		},
		{
			name:      "route does not match sidecar queue - sends to error queue",
			actorName: "test-actor",
			inputRoute: messages.Route{
				Prev: []string{},
				Curr: "wrong-actor",
				Next: []string{"next-actor"},
			},
			expectedWarnContains: "Route mismatch: message routed to wrong actor",
			shouldRejectAndError: true,
			shouldCallRuntime:    false,
			expectedDestQueue:    "asya-default-x-sump",
		},
		{
			name:      "route current index out of sync - sends to error queue",
			actorName: "test-actor",
			inputRoute: messages.Route{
				Prev: []string{"test-actor"},
				Curr: "next-actor",
				Next: []string{},
			},
			expectedWarnContains: "Route mismatch: message routed to wrong actor",
			shouldRejectAndError: true,
			shouldCallRuntime:    false,
			expectedDestQueue:    "asya-default-x-sump",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var logBuf bytes.Buffer
			logger := slog.New(slog.NewTextHandler(&logBuf, &slog.HandlerOptions{
				Level: slog.LevelWarn,
			}))
			slog.SetDefault(logger)

			runtimeCalled := false
			socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
				runtimeCalled = true
				return []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "processed"}`),
						Route:   tt.inputRoute.IncrementCurrent(),
					},
				}, http.StatusOK
			})

			cfg := &config.Config{
				ActorName:     tt.actorName,
				Namespace:     "default",
				SinkQueue:     "x-sink",
				SumpQueue:     "x-sump",
				Timeout:       2 * time.Second,
				TransportType: "rabbitmq",
			}

			mockTransport := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           cfg,
				transport:     mockTransport,
				runtimeClient: runtimeClient,
				actorName:     cfg.ActorName,
				sinkQueue:     cfg.SinkQueue,
				sumpQueue:     cfg.SumpQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			inputMsg := messages.Message{
				ID:      "test-msg-123",
				Route:   tt.inputRoute,
				Payload: json.RawMessage(`{"input": "test"}`),
			}
			msgBody, err := json.Marshal(inputMsg)
			if err != nil {
				t.Fatalf("Failed to marshal test message: %v", err)
			}

			queueMsg := transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			}

			ctx := context.Background()
			err = router.ProcessMessage(ctx, queueMsg)
			if err != nil {
				t.Fatalf("ProcessMessage failed: %v", err)
			}

			time.Sleep(50 * time.Millisecond)

			if tt.shouldCallRuntime && !runtimeCalled {
				t.Error("Expected runtime to be called, but it was not")
			}
			if !tt.shouldCallRuntime && runtimeCalled {
				t.Error("Expected runtime NOT to be called, but it was")
			}

			logOutput := logBuf.String()
			if tt.shouldRejectAndError {
				if !strings.Contains(logOutput, tt.expectedWarnContains) {
					t.Errorf("Expected warning containing %q, got log output:\n%s",
						tt.expectedWarnContains, logOutput)
				}

				if len(mockTransport.sentMessages) != 1 {
					t.Fatalf("Expected 1 message to error queue, got %d", len(mockTransport.sentMessages))
				}

				if mockTransport.sentMessages[0].queue != tt.expectedDestQueue {
					t.Errorf("Message sent to queue %q, expected %q",
						mockTransport.sentMessages[0].queue, tt.expectedDestQueue)
				}

				var errorMsg map[string]interface{}
				if err := json.Unmarshal(mockTransport.sentMessages[0].body, &errorMsg); err != nil {
					t.Fatalf("Failed to parse error message: %v", err)
				}

				payload, ok := errorMsg["payload"].(map[string]interface{})
				if !ok {
					t.Fatalf("Expected payload to be a map, got %T", errorMsg["payload"])
				}

				if errorMsg, ok := payload["error"].(string); !ok || !strings.Contains(errorMsg, "Route mismatch") {
					t.Errorf("Error message should contain 'Route mismatch', got: %v", payload["error"])
				}
			} else {
				if strings.Contains(logOutput, "Route mismatch") {
					t.Errorf("Unexpected warning in log output:\n%s", logOutput)
				}

				if len(mockTransport.sentMessages) != 1 {
					t.Fatalf("Expected 1 message routed, got %d", len(mockTransport.sentMessages))
				}

				if mockTransport.sentMessages[0].queue != tt.expectedDestQueue {
					t.Errorf("Message sent to queue %q, expected %q",
						mockTransport.sentMessages[0].queue, tt.expectedDestQueue)
				}
			}
		})
	}
}

func TestRouter_ResolveQueueName(t *testing.T) {
	tests := []struct {
		name          string
		transportType string
		config        *config.Config
		actorName     string
		expected      string
	}{
		{
			name:          "rabbitmq - identity mapping",
			transportType: "rabbitmq",
			config: &config.Config{
				TransportType: "rabbitmq",
				Namespace:     "default",
			},
			actorName: "my-actor",
			expected:  "asya-default-my-actor",
		},
		{
			name:          "sqs - with base URL",
			transportType: "sqs",
			config: &config.Config{
				TransportType: "sqs",
				Namespace:     "default",
				SQSBaseURL:    "https://sqs.us-east-1.amazonaws.com/123456789",
			},
			actorName: "image-processor",
			expected:  "asya-default-image-processor",
		},
		{
			name:          "sqs - without base URL (fallback to identity)",
			transportType: "sqs",
			config: &config.Config{
				TransportType: "sqs",
				Namespace:     "default",
				SQSBaseURL:    "",
			},
			actorName: "image-processor",
			expected:  "asya-default-image-processor",
		},
		{
			name:          "unknown transport - fallback to identity",
			transportType: "unknown",
			config: &config.Config{
				TransportType: "unknown",
				Namespace:     "default",
			},
			actorName: "some-actor",
			expected:  "some-actor",
		},
		{
			name:          "end queue - x-sink",
			transportType: "rabbitmq",
			config: &config.Config{
				TransportType: "rabbitmq",
				Namespace:     "default",
			},
			actorName: "x-sink",
			expected:  "asya-default-x-sink",
		},
		{
			name:          "end queue - x-sump with SQS",
			transportType: "sqs",
			config: &config.Config{
				TransportType: "sqs",
				Namespace:     "default",
				SQSBaseURL:    "https://sqs.us-west-2.amazonaws.com/987654321",
			},
			actorName: "x-sump",
			expected:  "asya-default-x-sump",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			router := &Router{
				cfg: tt.config,
			}

			result := router.resolveQueueName(tt.actorName)

			if result != tt.expected {
				t.Errorf("resolveQueueName(%q) = %q, expected %q",
					tt.actorName, result, tt.expected)
			}
		})
	}
}

func TestRouter_DynamicRouteModification(t *testing.T) {
	// Test that progress reporting handles runtime adding actors to route
	// This can cause progress percentage to jump down (e.g., from 50% to 30%)
	tests := []struct {
		name                string
		initialActors       []string
		runtimeOutputActors []string
		description         string
	}{
		{
			name:                "runtime adds more actors - progress jumps down",
			initialActors:       []string{"actor1", "actor2"},
			runtimeOutputActors: []string{"actor1", "actor2", "actor3", "actor4", "actor5"},
			description:         "Runtime expands route from 2 to 5 actors",
		},
		{
			name:                "runtime keeps same actors - progress normal",
			initialActors:       []string{"actor1", "actor2", "actor3"},
			runtimeOutputActors: []string{"actor1", "actor2", "actor3"},
			description:         "Runtime preserves original route",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
				return []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "processed"}`),
						Route: messages.Route{
							Prev: tt.runtimeOutputActors[:1],
							Curr: tt.runtimeOutputActors[1],
							Next: tt.runtimeOutputActors[2:],
						},
					},
				}, http.StatusOK
			})

			// Setup test components
			cfg := &config.Config{
				ActorName: tt.initialActors[0],
				Namespace: "default",
				SinkQueue: "x-sink",
				SumpQueue: "x-sump",
				Timeout:   2 * time.Second,
			}

			mockTransport := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           cfg,
				transport:     mockTransport,
				runtimeClient: runtimeClient,
				actorName:     cfg.ActorName,
				sinkQueue:     cfg.SinkQueue,
				sumpQueue:     cfg.SumpQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			// Create test message with initial route
			inputMsg := messages.Message{
				ID: "test-dynamic-route",
				Route: messages.Route{
					Prev: []string{},
					Curr: tt.initialActors[0],
					Next: tt.initialActors[1:],
				},
				Payload: json.RawMessage(`{"input": "test"}`),
			}
			msgBody, err := json.Marshal(inputMsg)
			if err != nil {
				t.Fatalf("Failed to marshal test message: %v", err)
			}

			queueMsg := transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			}

			// Process message
			ctx := context.Background()
			err = router.ProcessMessage(ctx, queueMsg)
			if err != nil {
				t.Fatalf("ProcessMessage failed: %v", err)
			}

			// Verify message was routed successfully
			if len(mockTransport.sentMessages) != 1 {
				t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
			}

			// Parse the sent message to verify route was updated
			var sentMsg messages.Message
			err = json.Unmarshal(mockTransport.sentMessages[0].body, &sentMsg)
			if err != nil {
				t.Fatalf("Failed to unmarshal sent message: %v", err)
			}

			// Verify the route was updated with the modified actors list
			// With prev/curr/next format: total = len(prev) + 1 (curr) + len(next)
			totalActors := len(sentMsg.Route.Prev) + 1 + len(sentMsg.Route.Next)
			if totalActors != len(tt.runtimeOutputActors) {
				t.Errorf("Expected route with %d actors, got %d (prev=%v, curr=%q, next=%v)",
					len(tt.runtimeOutputActors), totalActors, sentMsg.Route.Prev, sentMsg.Route.Curr, sentMsg.Route.Next)
			}

			// Verify curr is the second actor (runtime shifted the route)
			if sentMsg.Route.Curr != tt.runtimeOutputActors[1] {
				t.Errorf("Expected curr=%q (from runtime shift), got curr=%q",
					tt.runtimeOutputActors[1], sentMsg.Route.Curr)
			}

			// Progress: prev/(total) * 100
			// If route expands: 1/5 = 20%, if same: 1/2 = 50%
			expectedProgress := (float64(len(sentMsg.Route.Prev)) * 100.0) / float64(totalActors)
			t.Logf("%s - Progress would be: %.1f%%", tt.description, expectedProgress)
		})
	}
}

func TestRouter_ResolveQueueName_Integration(t *testing.T) {
	// Test that resolveQueueName is properly used in routing flow
	tests := []struct {
		name             string
		transportType    string
		config           *config.Config
		inputActors      []string
		expectedQueues   []string
		shouldRouteToEnd bool
	}{
		{
			name:          "RabbitMQ - multi-actor route",
			transportType: "rabbitmq",
			config: &config.Config{
				TransportType: "rabbitmq",
				Namespace:     "default",
				ActorName:     "actor1",
				SinkQueue:     "x-sink",
				SumpQueue:     "x-sump",
				Timeout:       2 * time.Second,
			},
			inputActors:      []string{"actor1", "actor2", "actor3"},
			expectedQueues:   []string{"asya-default-actor2"},
			shouldRouteToEnd: false,
		},
		{
			name:          "SQS - route to next actor",
			transportType: "sqs",
			config: &config.Config{
				TransportType: "sqs",
				Namespace:     "default",
				SQSBaseURL:    "https://sqs.us-east-1.amazonaws.com/123",
				ActorName:     "processor",
				SinkQueue:     "x-sink",
				SumpQueue:     "x-sump",
				Timeout:       2 * time.Second,
			},
			inputActors:      []string{"processor", "validator"},
			expectedQueues:   []string{"asya-default-validator"},
			shouldRouteToEnd: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
				return []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "processed"}`),
						Route: messages.Route{
							Prev: tt.inputActors[:1],
							Curr: tt.inputActors[1],
							Next: tt.inputActors[2:],
						},
					},
				}, http.StatusOK
			})

			// Setup test components
			mockTransport := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           tt.config,
				transport:     mockTransport,
				runtimeClient: runtimeClient,
				actorName:     tt.config.ActorName,
				sinkQueue:     tt.config.SinkQueue,
				sumpQueue:     tt.config.SumpQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			// Create test message
			inputMsg := messages.Message{
				ID: "test-123",
				Route: messages.Route{
					Prev: []string{},
					Curr: tt.inputActors[0],
					Next: tt.inputActors[1:],
				},
				Payload: json.RawMessage(`{"input": "test"}`),
			}
			msgBody, err := json.Marshal(inputMsg)
			if err != nil {
				t.Fatalf("Failed to marshal test message: %v", err)
			}

			queueMsg := transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			}

			// Process message
			ctx := context.Background()
			err = router.ProcessMessage(ctx, queueMsg)
			if err != nil {
				t.Fatalf("ProcessMessage failed: %v", err)
			}

			// Verify the correct queue was used
			if len(mockTransport.sentMessages) != len(tt.expectedQueues) {
				t.Fatalf("Expected %d messages sent, got %d",
					len(tt.expectedQueues), len(mockTransport.sentMessages))
			}

			for i, expectedQueue := range tt.expectedQueues {
				if mockTransport.sentMessages[i].queue != expectedQueue {
					t.Errorf("Message %d sent to queue %q, expected %q",
						i, mockTransport.sentMessages[i].queue, expectedQueue)
				}
			}
		})
	}
}

func TestNewRouter(t *testing.T) {
	tests := []struct {
		name           string
		gatewayURL     string
		expectProgress bool
	}{
		{
			name:           "with gateway URL - progress reporter created",
			gatewayURL:     "http://gateway:8080",
			expectProgress: true,
		},
		{
			name:           "without gateway URL - no progress reporter",
			gatewayURL:     "",
			expectProgress: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &config.Config{
				ActorName:  "test-actor",
				Namespace:  "default",
				SinkQueue:  "x-sink",
				SumpQueue:  "x-sump",
				Timeout:    2 * time.Second,
				GatewayURL: tt.gatewayURL,
			}

			mockTransport := &mockTransport{}
			runtimeClient := &runtime.Client{}
			m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

			router := NewRouter(cfg, mockTransport, runtimeClient, m)

			if router == nil {
				t.Fatal("NewRouter returned nil")
			}

			if router.actorName != "test-actor" {
				t.Errorf("Expected actorName to be 'test-actor', got %q", router.actorName)
			}

			if router.sinkQueue != testQueueSink {
				t.Errorf("Expected sinkQueue to be %q, got %q", testQueueSink, router.sinkQueue)
			}

			if router.sumpQueue != testQueueSump {
				t.Errorf("Expected sumpQueue to be %q, got %q", testQueueSump, router.sumpQueue)
			}

			if tt.expectProgress && router.progressReporter == nil {
				t.Error("Expected progress reporter to be created")
			}

			if !tt.expectProgress && router.progressReporter != nil {
				t.Error("Expected no progress reporter")
			}
		})
	}
}

func TestRouter_SendToSinkQueue(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mockTransport,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	msg := messages.Message{
		ID: "test-msg-123",
		Route: messages.Route{
			Prev: []string{"actor1"},
			Curr: "actor2",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"result": "success"}`),
	}

	ctx := context.Background()
	err := router.sendToSinkQueue(ctx, msg)
	if err != nil {
		t.Fatalf("sendToSinkQueue failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-default-"+testQueueSink {
		t.Errorf("Message sent to queue %q, expected %q", mockTransport.sentMessages[0].queue, "asya-default-"+testQueueSink)
	}

	var sentMsg messages.Message
	err = json.Unmarshal(mockTransport.sentMessages[0].body, &sentMsg)
	if err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	if sentMsg.ID != "test-msg-123" {
		t.Errorf("Expected message ID 'test-msg-123', got %q", sentMsg.ID)
	}
}

func TestRouter_SendToSumpQueue(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mockTransport,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	originalMsg := messages.Message{
		ID: "test-msg-456",
		Route: messages.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"data": "test"}`),
	}

	originalBody, _ := json.Marshal(originalMsg)

	ctx := context.Background()
	err := router.sendToSumpQueue(ctx, originalBody, "Runtime processing failed")
	if err != nil {
		t.Fatalf("sendToSumpQueue failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-default-"+testQueueSump {
		t.Errorf("Message sent to queue %q, expected %q", mockTransport.sentMessages[0].queue, "asya-default-"+testQueueSump)
	}

	var errorMsg map[string]any
	err = json.Unmarshal(mockTransport.sentMessages[0].body, &errorMsg)
	if err != nil {
		t.Fatalf("Failed to unmarshal sent error message: %v", err)
	}

	if errorMsg["id"] != "test-msg-456" {
		t.Errorf("Expected error message ID 'test-msg-456', got %v", errorMsg["id"])
	}

	// Error should be inside payload (nested format)
	payload, ok := errorMsg["payload"].(map[string]any)
	if !ok {
		t.Fatalf("Expected payload to be a map, got %T", errorMsg["payload"])
	}

	if payload["error"] != "Runtime processing failed" {
		t.Errorf("Expected error message 'Runtime processing failed', got %v", payload["error"])
	}

	// Original payload should be preserved inside payload
	originalPayloadBytes, err := json.Marshal(payload["original_payload"])
	if err != nil {
		t.Fatalf("Failed to marshal original_payload: %v", err)
	}
	expectedPayload := `{"data":"test"}`
	if string(originalPayloadBytes) != expectedPayload {
		t.Errorf("Expected original_payload %q, got %q", expectedPayload, string(originalPayloadBytes))
	}

	// Verify route field exists
	if errorMsg["route"] == nil {
		t.Error("Expected route field in error message")
	}
}

func TestRouter_SendToSumpQueue_WithInvalidOriginalMessage(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mockTransport,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	invalidJSON := []byte(`{invalid json`)

	ctx := context.Background()
	err := router.sendToSumpQueue(ctx, invalidJSON, "Parse error")
	if err != nil {
		t.Fatalf("sendToSumpQueue failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
	}

	var errorMsg map[string]any
	err = json.Unmarshal(mockTransport.sentMessages[0].body, &errorMsg)
	if err != nil {
		t.Fatalf("Failed to unmarshal sent error message: %v", err)
	}

	if errorMsg["id"] != "" {
		t.Errorf("Expected empty ID for invalid JSON, got %v", errorMsg["id"])
	}

	// Error should be inside payload (nested format)
	payload, ok := errorMsg["payload"].(map[string]any)
	if !ok {
		t.Fatalf("Expected payload to be a map, got %T", errorMsg["payload"])
	}

	if payload["error"] != "Parse error" {
		t.Errorf("Expected error message 'Parse error', got %v", payload["error"])
	}

	// original_payload should be nil when original message is invalid JSON
	if payload["original_payload"] != nil {
		t.Errorf("Expected nil original_payload for invalid JSON, got %T", payload["original_payload"])
	}
}

func TestRouter_Run(t *testing.T) {
	mockTransport := &mockTransport{}

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return nil, http.StatusNoContent
	})

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	ctx, cancel := context.WithCancel(context.Background())

	cancel()

	err := router.Run(ctx)
	if err != context.Canceled {
		t.Errorf("Expected context.Canceled error, got: %v", err)
	}
}

func TestRouter_ProcessMessage_ParseError(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mockTransport,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	invalidJSON := []byte(`{invalid json`)
	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: invalidJSON,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage should not return error (sends to error queue): %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to error queue, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-default-"+testQueueSump {
		t.Errorf("Message sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-default-"+testQueueSump)
	}
}

func TestRouter_ProcessMessage_MissingMessageID(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mockTransport,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	msgWithoutID := []byte(`{"route": {"prev": [], "curr": "test-actor", "next": []}, "payload": {"test": "data"}}`)
	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgWithoutID,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage should not return error (sends to error queue): %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to error queue, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-default-"+testQueueSump {
		t.Errorf("Message sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-default-"+testQueueSump)
	}

	var errorMsg map[string]interface{}
	if err := json.Unmarshal(mockTransport.sentMessages[0].body, &errorMsg); err != nil {
		t.Fatalf("Failed to parse error message: %v", err)
	}

	// Error should be inside payload (nested format)
	payload, ok := errorMsg["payload"].(map[string]interface{})
	if !ok {
		t.Fatalf("Expected payload to be a map, got %T", errorMsg["payload"])
	}

	if errorMsg, ok := payload["error"].(string); !ok || !strings.Contains(errorMsg, "missing required 'id' field") {
		t.Errorf("Error message should contain 'missing required 'id' field', got: %v", payload["error"])
	}
}

func TestRouter_ProcessMessage_EmptyResponse(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return nil, http.StatusNoContent
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := messages.Message{
		ID: "test-123",
		Route: messages.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to x-sink, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-default-"+testQueueSink {
		t.Errorf("Message sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-default-"+testQueueSink)
	}
}

func TestRouter_ProcessMessage_EndActor(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"status": "logged"}`),
				Route: messages.Route{
					Prev: []string{},
					Curr: "x-sink",
					Next: []string{},
				},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "x-sink",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		IsEndActor:    true,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := messages.Message{
		ID: "test-123",
		Route: messages.Route{
			Prev: []string{},
			Curr: "x-sink",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"result": "success"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 0 {
		t.Errorf("End actor should not send any messages, got %d", len(mockTransport.sentMessages))
	}
}

func TestRouter_EndActor_WithInvalidRoute(t *testing.T) {
	tests := []struct {
		name  string
		route messages.Route
		desc  string
	}{
		{
			name: "current points to wrong actor",
			route: messages.Route{
				Prev: []string{},
				Curr: "test-echo",
				Next: []string{},
			},
			desc: "Route points to test-echo but end actor is x-sink",
		},
		{
			name: "current out of bounds",
			route: messages.Route{
				Prev: []string{"test-echo"},
				Curr: "",
				Next: []string{},
			},
			desc: "Route current index is out of bounds",
		},
		{
			name: "empty route",
			route: messages.Route{
				Prev: []string{},
				Curr: "",
				Next: []string{},
			},
			desc: "Route has no actors",
		},
		{
			name: "multi-actor route pointing elsewhere",
			route: messages.Route{
				Prev: []string{"actor1"},
				Curr: "actor2",
				Next: []string{"actor3"},
			},
			desc: "Route points to actor2 but end actor is x-sink",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
				return []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"status": "processed"}`),
					},
				}, http.StatusOK
			})

			cfg := &config.Config{
				ActorName:     "x-sink",
				Namespace:     "default",
				SinkQueue:     "x-sink",
				SumpQueue:     "x-sump",
				Timeout:       2 * time.Second,
				TransportType: "rabbitmq",
				IsEndActor:    true,
			}

			mockTransport := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
			m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

			router := &Router{
				cfg:           cfg,
				transport:     mockTransport,
				runtimeClient: runtimeClient,
				actorName:     cfg.ActorName,
				sinkQueue:     cfg.SinkQueue,
				sumpQueue:     cfg.SumpQueue,
				metrics:       m,
			}

			inputMsg := messages.Message{
				ID:      "test-invalid-route",
				Route:   tt.route,
				Payload: json.RawMessage(`{"data": "test"}`),
			}
			msgBody, _ := json.Marshal(inputMsg)

			queueMsg := transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			}

			ctx := context.Background()
			err := router.ProcessMessage(ctx, queueMsg)
			if err != nil {
				t.Fatalf("ProcessMessage failed for %s: %v", tt.desc, err)
			}

			if len(mockTransport.sentMessages) != 0 {
				t.Errorf("End actor should not send any messages even with invalid route, got %d", len(mockTransport.sentMessages))
			}
		})
	}
}

func TestRouter_EndActor_WithGatewayReporting(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": {"value": 42}, "s3_info": {"s3_uri": "s3://test/result"}}`),
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "x-sink",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		IsEndActor:    true,
		GatewayURL:    mockServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputMsg := messages.Message{
		ID: "test-gateway-report",
		Route: messages.Route{
			Prev: []string{"actor1"},
			Curr: "actor2",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"data": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 0 {
		t.Errorf("End actor should not send any messages, got %d", len(mockTransport.sentMessages))
	}

	expectedPath := "/tasks/test-gateway-report/final"
	req := mockServer.GetRequest(expectedPath)
	if req == nil {
		t.Fatalf("Expected gateway request to %s, but none received", expectedPath)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(req.Body, &payload); err != nil {
		t.Fatalf("Failed to parse gateway request: %v", err)
	}

	if payload["status"] != statusSucceeded {
		t.Errorf("Expected status '%s', got %v", statusSucceeded, payload["status"])
	}

	if payload["id"] != "test-gateway-report" {
		t.Errorf("Expected id 'test-gateway-report', got %v", payload["id"])
	}
}

func TestRouter_EndActor_RuntimeError(t *testing.T) {
	// Use a non-existent socket path to simulate runtime connection failure
	socketPath := fmt.Sprintf("/tmp/rt-noexist-%d.sock", time.Now().UnixNano())

	cfg := &config.Config{
		ActorName:     "x-sump",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		IsEndActor:    true,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := messages.Message{
		ID: "test-end-error",
		Route: messages.Route{
			Prev: []string{},
			Curr: "some-actor",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"error": "failed"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err == nil {
		t.Fatal("Expected error from end actor runtime failure")
	}

	if !strings.Contains(err.Error(), "runtime error in end actor") {
		t.Errorf("Expected 'runtime error in end actor', got: %v", err)
	}

	if len(mockTransport.sentMessages) != 0 {
		t.Errorf("End actor should not send messages even on error, got %d", len(mockTransport.sentMessages))
	}
}

func TestRouter_EndActor_DoesNotIncrementCurrent(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		// Runtime tries to return a route with incremented current
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"status": "logged"}`),
				Route: messages.Route{
					Prev: []string{"actor1", "actor2", "x-sink"},
					Curr: "",
					Next: []string{},
				},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "x-sink",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		IsEndActor:    true,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := messages.Message{
		ID: "test-no-increment",
		Route: messages.Route{
			Prev: []string{"actor1", "actor2"},
			Curr: "x-sink",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"result": "success"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// End actors must NOT send any messages (no routing, no increment)
	if len(mockTransport.sentMessages) != 0 {
		t.Errorf("End actor should not send any messages (no routing), got %d messages", len(mockTransport.sentMessages))
	}
}

func TestRouter_ProcessMessage_RuntimeError(t *testing.T) {
	// Use a non-existent socket path to simulate runtime connection failure
	socketPath := fmt.Sprintf("/tmp/rt-noexist-%d.sock", time.Now().UnixNano())

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := messages.Message{
		ID: "test-123",
		Route: messages.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage should not return error (sends to error queue): %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to error queue, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-default-"+testQueueSump {
		t.Errorf("Message sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-default-"+testQueueSump)
	}
}

func TestRouter_ProcessMessage_ErrorResponse(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Error: "Processing failed",
				Details: runtime.ErrorDetails{
					Type:    "validation_error",
					Message: "Invalid input",
				},
			},
		}, http.StatusInternalServerError
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := messages.Message{
		ID: "test-123",
		Route: messages.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to error queue, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-default-"+testQueueSump {
		t.Errorf("Message sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-default-"+testQueueSump)
	}

	var errorMsg map[string]any
	_ = json.Unmarshal(mockTransport.sentMessages[0].body, &errorMsg)

	// Error should be inside payload (nested format)
	payload, ok := errorMsg["payload"].(map[string]any)
	if !ok {
		t.Fatalf("Expected payload to be a map, got %T", errorMsg["payload"])
	}

	if payload["error"] != "Processing failed" {
		t.Errorf("Expected error 'Processing failed', got %v", payload["error"])
	}

	// Details should be inside payload
	details, ok := payload["details"].(map[string]any)
	if !ok {
		t.Fatalf("Expected details field to be a map, got %T", payload["details"])
	}

	if details["type"] != "validation_error" {
		t.Errorf("Expected error type 'validation_error', got %v", details["type"])
	}

	if details["message"] != "Invalid input" {
		t.Errorf("Expected error message 'Invalid input', got %v", details["message"])
	}

	// Original payload should be preserved inside payload
	originalPayloadBytes, _ := json.Marshal(payload["original_payload"])
	expectedPayload := `{"input":"test"}`
	if string(originalPayloadBytes) != expectedPayload {
		t.Errorf("Expected original_payload %q, got %q", expectedPayload, string(originalPayloadBytes))
	}
}

func TestRouter_ReportFinalStatus_Sink(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	cfg := &config.Config{
		ActorName:  "x-sink",
		Namespace:  "default",
		SinkQueue:  "x-sink",
		SumpQueue:  "x-sump",
		Timeout:    2 * time.Second,
		GatewayURL: mockServer.URL,
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, nil, m)

	response := runtime.RuntimeResponse{
		Payload: json.RawMessage(`{}`),
	}

	ctx := context.Background()
	err := router.reportFinalStatus(ctx, "test-msg-123", response.Payload, 100*time.Millisecond)
	if err != nil {
		t.Fatalf("reportFinalStatus failed: %v", err)
	}

	expectedPath := "/tasks/test-msg-123/final"
	req := mockServer.GetRequest(expectedPath)
	if req == nil {
		t.Fatalf("Expected request to %s, but none received", expectedPath)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(req.Body, &payload); err != nil {
		t.Fatalf("Failed to parse request body: %v", err)
	}

	if payload["status"] != statusSucceeded {
		t.Errorf("Expected status '%s', got %v", statusSucceeded, payload["status"])
	}

	if payload["id"] != "test-msg-123" {
		t.Errorf("Expected id 'test-msg-123', got %v", payload["id"])
	}

	if payload["progress"] != 1.0 {
		t.Errorf("Expected progress 1.0, got %v", payload["progress"])
	}
}

func TestRouter_ReportFinalStatus_Sump(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	cfg := &config.Config{
		ActorName:  "x-sump",
		Namespace:  "default",
		SinkQueue:  "x-sink",
		SumpQueue:  "x-sump",
		Timeout:    2 * time.Second,
		GatewayURL: mockServer.URL,
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, nil, m)

	response := runtime.RuntimeResponse{
		Payload: json.RawMessage(`{}`),
	}

	ctx := context.Background()
	err := router.reportFinalStatus(ctx, "test-error-456", response.Payload, 50*time.Millisecond)
	if err != nil {
		t.Fatalf("reportFinalStatus failed: %v", err)
	}

	expectedPath := "/tasks/test-error-456/final"
	req := mockServer.GetRequest(expectedPath)
	if req == nil {
		t.Fatalf("Expected request to %s, but none received", expectedPath)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(req.Body, &payload); err != nil {
		t.Fatalf("Failed to parse request body: %v", err)
	}

	if payload["status"] != "failed" {
		t.Errorf("Expected status 'failed', got %v", payload["status"])
	}
}

func TestRouter_ReportFinalStatusWithMessage_Sump_ExtractsErrorDetails(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"status": "processed"}`),
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "x-sump",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		IsEndActor:    true,
		GatewayURL:    mockServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	errorPayload := map[string]interface{}{
		"error": "Processing failed due to invalid input",
		"details": map[string]interface{}{
			"type":    "validation_error",
			"message": "Field 'name' is required",
			"code":    400,
		},
		"original_payload": map[string]interface{}{
			"data": "test",
		},
	}
	errorPayloadBytes, _ := json.Marshal(errorPayload)

	inputMsg := messages.Message{
		ID: "test-error-details-789",
		Route: messages.Route{
			Prev: []string{"actor1"},
			Curr: "actor2",
			Next: []string{},
		},
		Payload: json.RawMessage(errorPayloadBytes),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	expectedPath := "/tasks/test-error-details-789/final"
	req := mockServer.GetRequest(expectedPath)
	if req == nil {
		t.Fatalf("Expected request to %s, but none received", expectedPath)
	}

	var finalPayload map[string]interface{}
	if err := json.Unmarshal(req.Body, &finalPayload); err != nil {
		t.Fatalf("Failed to parse gateway request: %v", err)
	}

	if finalPayload["status"] != statusFailed {
		t.Errorf("Expected status '%s', got %v", statusFailed, finalPayload["status"])
	}

	if finalPayload["error"] != "Processing failed due to invalid input" {
		t.Errorf("Expected error message 'Processing failed due to invalid input', got %v", finalPayload["error"])
	}

	details, ok := finalPayload["error_details"].(map[string]interface{})
	if !ok {
		t.Fatalf("Expected error_details to be a map, got %T", finalPayload["error_details"])
	}

	if details["type"] != "validation_error" {
		t.Errorf("Expected error type 'validation_error', got %v", details["type"])
	}

	if details["message"] != "Field 'name' is required" {
		t.Errorf("Expected error message 'Field 'name' is required', got %v", details["message"])
	}

	if details["code"] != float64(400) {
		t.Errorf("Expected error code 400, got %v", details["code"])
	}

	if finalPayload["current_actor_idx"] != float64(1) {
		t.Errorf("Expected current_actor_idx 1, got %v", finalPayload["current_actor_idx"])
	}

	if finalPayload["current_actor_name"] != "actor2" {
		t.Errorf("Expected current_actor_name 'actor2', got %v", finalPayload["current_actor_name"])
	}
}

func TestRouter_ReportFinalStatusWithMessage_Sump_NoErrorDetails(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"status": "processed"}`),
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "x-sump",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		IsEndActor:    true,
		GatewayURL:    mockServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputMsg := messages.Message{
		ID: "test-no-error-details",
		Route: messages.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Payload: json.RawMessage(`{"some": "data"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	expectedPath := "/tasks/test-no-error-details/final"
	req := mockServer.GetRequest(expectedPath)
	if req == nil {
		t.Fatalf("Expected request to %s, but none received", expectedPath)
	}

	var finalPayload map[string]interface{}
	if err := json.Unmarshal(req.Body, &finalPayload); err != nil {
		t.Fatalf("Failed to parse gateway request: %v", err)
	}

	if finalPayload["status"] != statusFailed {
		t.Errorf("Expected status '%s', got %v", statusFailed, finalPayload["status"])
	}

	if finalPayload["error"] != "" && finalPayload["error"] != nil {
		t.Errorf("Expected no error message, got %v", finalPayload["error"])
	}

	if finalPayload["error_details"] != nil {
		t.Errorf("Expected no error_details, got %v", finalPayload["error_details"])
	}
}

func TestRouter_ReportFinalStatus_NoGateway(t *testing.T) {
	cfg := &config.Config{
		ActorName:  "x-sink",
		Namespace:  "default",
		SinkQueue:  "x-sink",
		SumpQueue:  "x-sump",
		Timeout:    2 * time.Second,
		GatewayURL: "",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, nil, m)

	response := runtime.RuntimeResponse{
		Payload: json.RawMessage(`{"result": {"value": 42}}`),
	}

	ctx := context.Background()
	err := router.reportFinalStatus(ctx, "test-no-gw", response.Payload, 10*time.Millisecond)
	if err != nil {
		t.Errorf("reportFinalStatus should not error when gateway not configured, got: %v", err)
	}
}

func TestRouter_ProcessMessage_FanOut(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Route:   messages.Route{Prev: []string{"test-actor"}, Curr: "next-actor", Next: []string{}},
				Payload: json.RawMessage(`{"index": 0, "message": "Fan-out message 0"}`),
			},
			{
				Route:   messages.Route{Prev: []string{"test-actor"}, Curr: "next-actor", Next: []string{}},
				Payload: json.RawMessage(`{"index": 1, "message": "Fan-out message 1"}`),
			},
			{
				Route:   messages.Route{Prev: []string{"test-actor"}, Curr: "next-actor", Next: []string{}},
				Payload: json.RawMessage(`{"index": 2, "message": "Fan-out message 2"}`),
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       m,
	}

	inputMsg := messages.Message{
		ID: "test-fanout-123",
		Route: messages.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Payload: json.RawMessage(`{"count": 3}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 3 {
		t.Fatalf("Expected 3 fan-out messages, got %d", len(mockTransport.sentMessages))
	}

	for i := 0; i < 3; i++ {
		msg := mockTransport.sentMessages[i]

		if msg.queue != "asya-default-next-actor" {
			t.Errorf("Message %d sent to %q, expected %q", i, msg.queue, "asya-default-next-actor")
		}

		var parsedMsg messages.Message
		if err := json.Unmarshal(msg.body, &parsedMsg); err != nil {
			t.Fatalf("Failed to unmarshal message %d: %v", i, err)
		}

		// First item keeps original ID, subsequent items get UUID4
		if i == 0 {
			if parsedMsg.ID != "test-fanout-123" {
				t.Errorf("Message %d has ID %q, expected %q", i, parsedMsg.ID, "test-fanout-123")
			}
		} else {
			if parsedMsg.ID == "" || parsedMsg.ID == "test-fanout-123" || strings.HasPrefix(parsedMsg.ID, "test-fanout-123-") {
				t.Errorf("Message %d has ID %q, expected a unique UUID", i, parsedMsg.ID)
			}
		}

		// First item has no parent_id, subsequent items have parent_id set to original ID
		if i == 0 {
			if parsedMsg.ParentID != nil {
				t.Errorf("Message %d should have nil parent_id, got %q", i, *parsedMsg.ParentID)
			}
		} else {
			if parsedMsg.ParentID == nil {
				t.Errorf("Message %d should have parent_id set, got nil", i)
			} else if *parsedMsg.ParentID != "test-fanout-123" {
				t.Errorf("Message %d has parent_id %q, expected %q", i, *parsedMsg.ParentID, "test-fanout-123")
			}
		}

		if parsedMsg.Route.Curr != "next-actor" {
			t.Errorf("Message %d route.curr = %q, expected next-actor", i, parsedMsg.Route.Curr)
		}

		var payload map[string]interface{}
		if err := json.Unmarshal(parsedMsg.Payload, &payload); err != nil {
			t.Fatalf("Failed to unmarshal payload %d: %v", i, err)
		}

		if int(payload["index"].(float64)) != i {
			t.Errorf("Message %d has index %v, expected %d", i, payload["index"], i)
		}
	}
}

func TestRouter_ProcessMessage_FanOut_CreatesGatewayTasks(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Route:   messages.Route{Prev: []string{"test-actor"}, Curr: "next-actor", Next: []string{}},
				Payload: json.RawMessage(`{"index": 0}`),
			},
			{
				Route:   messages.Route{Prev: []string{"test-actor"}, Curr: "next-actor", Next: []string{}},
				Payload: json.RawMessage(`{"index": 1}`),
			},
			{
				Route:   messages.Route{Prev: []string{"test-actor"}, Curr: "next-actor", Next: []string{}},
				Payload: json.RawMessage(`{"index": 2}`),
			},
		}, http.StatusOK
	})

	// Track task creation calls
	var createdTasks []struct {
		id       string
		parentID string
		prev     []string
		curr     string
		next     []string
	}
	createTaskCalled := 0

	// Mock HTTP server for gateway
	gatewayServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/tasks" && r.Method == http.MethodPost {
			createTaskCalled++
			var req struct {
				ID       string   `json:"id"`
				ParentID string   `json:"parent_id"`
				Prev     []string `json:"prev"`
				Curr     string   `json:"curr"`
				Next     []string `json:"next"`
			}
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Errorf("Failed to decode task create request: %v", err)
			}
			createdTasks = append(createdTasks, struct {
				id       string
				parentID string
				prev     []string
				curr     string
				next     []string
			}{req.ID, req.ParentID, req.Prev, req.Curr, req.Next})
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(map[string]string{"status": "created"})
		} else {
			w.WriteHeader(http.StatusOK)
		}
	}))
	defer gatewayServer.Close()

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    gatewayServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	progressReporter := progress.NewReporter(gatewayServer.URL, cfg.ActorName)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:              cfg,
		transport:        mockTransport,
		runtimeClient:    runtimeClient,
		actorName:        cfg.ActorName,
		sinkQueue:        cfg.SinkQueue,
		sumpQueue:        cfg.SumpQueue,
		gatewayURL:       cfg.GatewayURL,
		progressReporter: progressReporter,
		metrics:          m,
	}

	inputMsg := messages.Message{
		ID: "test-fanout-456",
		Route: messages.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Payload: json.RawMessage(`{"count": 3}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err := router.ProcessMessage(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify task creation was called for fanout children (indices 1 and 2)
	expectedCalls := 2
	if createTaskCalled != expectedCalls {
		t.Errorf("CreateTask called %d times, expected %d", createTaskCalled, expectedCalls)
	}

	// Verify created tasks
	if len(createdTasks) != 2 {
		t.Fatalf("Expected 2 created tasks, got %d", len(createdTasks))
	}

	// First fanout child (index 1): UUID4 ID, parent is original
	if createdTasks[0].id == "" || createdTasks[0].id == "test-fanout-456" || strings.HasPrefix(createdTasks[0].id, "test-fanout-456-") {
		t.Errorf("First task ID = %q, want a unique UUID", createdTasks[0].id)
	}
	if createdTasks[0].parentID != "test-fanout-456" {
		t.Errorf("First task ParentID = %q, want test-fanout-456", createdTasks[0].parentID)
	}

	// Second fanout child (index 2): UUID4 ID, parent is original
	if createdTasks[1].id == "" || createdTasks[1].id == "test-fanout-456" || strings.HasPrefix(createdTasks[1].id, "test-fanout-456-") {
		t.Errorf("Second task ID = %q, want a unique UUID", createdTasks[1].id)
	}
	if createdTasks[1].parentID != "test-fanout-456" {
		t.Errorf("Second task ParentID = %q, want test-fanout-456", createdTasks[1].parentID)
	}
	// IDs should be distinct
	if createdTasks[0].id == createdTasks[1].id {
		t.Errorf("Fanout children have duplicate IDs: %q", createdTasks[0].id)
	}
}

func TestRouter_CheckGatewayHealth_Success(t *testing.T) {
	healthCheckCalled := false

	// Mock HTTP server for gateway
	gatewayServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" && r.Method == http.MethodGet {
			healthCheckCalled = true
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte("OK"))
		} else {
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer gatewayServer.Close()

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    gatewayServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient("/tmp/test.sock", 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	ctx := context.Background()
	err := router.CheckGatewayHealth(ctx)

	if err != nil {
		t.Errorf("CheckGatewayHealth returned error: %v", err)
	}

	if !healthCheckCalled {
		t.Error("Health check was not called")
	}
}

func TestRouter_CheckGatewayHealth_Failure(t *testing.T) {
	// Mock HTTP server that returns 500
	gatewayServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("Internal server error"))
	}))
	defer gatewayServer.Close()

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    gatewayServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient("/tmp/test.sock", 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	ctx := context.Background()
	err := router.CheckGatewayHealth(ctx)

	// Should return error
	if err == nil {
		t.Error("CheckGatewayHealth should return error when gateway is unhealthy")
	}
}

func TestRouter_CheckGatewayHealth_NoGatewayConfigured(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    "", // No gateway configured
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient("/tmp/test.sock", 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	ctx := context.Background()
	err := router.CheckGatewayHealth(ctx)

	// Should not return error when gateway is not configured
	if err != nil {
		t.Errorf("CheckGatewayHealth should not return error when gateway is not configured, got: %v", err)
	}
}

func TestRouter_CheckGatewayHealth_NetworkError(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    "http://invalid-host-that-does-not-exist:99999",
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient("/tmp/test.sock", 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	ctx := context.Background()
	err := router.CheckGatewayHealth(ctx)

	// Should return error for network failure
	if err == nil {
		t.Error("CheckGatewayHealth should return error for network failure")
	}
}

// --- Status lifecycle tests ---

func TestRouter_EnsureAndUpdateStatus_NewMessage(t *testing.T) {
	router := &Router{actorName: "test-actor"}
	msg := &messages.Message{
		ID:      "msg-1",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{}`),
	}

	router.ensureAndUpdateStatus(msg)

	if msg.Status == nil {
		t.Fatal("Status should not be nil after ensureAndUpdateStatus")
	}
	if msg.Status.Phase != messages.PhaseProcessing {
		t.Errorf("Phase = %q, want %q", msg.Status.Phase, messages.PhaseProcessing)
	}
	if msg.Status.Actor != "test-actor" {
		t.Errorf("Actor = %q, want %q", msg.Status.Actor, "test-actor")
	}
	if msg.Status.Attempt != 1 {
		t.Errorf("Attempt = %d, want 1", msg.Status.Attempt)
	}
	if msg.Status.CreatedAt == "" {
		t.Error("CreatedAt should not be empty")
	}
}

func TestRouter_EnsureAndUpdateStatus_ExistingStatus(t *testing.T) {
	router := &Router{actorName: "actor-b"}
	msg := &messages.Message{
		ID:      "msg-1",
		Route:   messages.Route{Prev: []string{"actor-a"}, Curr: "actor-b", Next: []string{}},
		Payload: json.RawMessage(`{}`),
		Status: &messages.Status{
			Phase:     messages.PhasePending,
			Reason:    "some-reason",
			Actor:     "actor-a",
			Attempt:   1,
			CreatedAt: "2025-01-01T00:00:00Z",
			UpdatedAt: "2025-01-01T00:00:00Z",
			Error:     &messages.StatusError{Message: "old error"},
		},
	}

	router.ensureAndUpdateStatus(msg)

	if msg.Status.Phase != messages.PhaseProcessing {
		t.Errorf("Phase = %q, want %q", msg.Status.Phase, messages.PhaseProcessing)
	}
	if msg.Status.Reason != "" {
		t.Errorf("Reason should be cleared, got %q", msg.Status.Reason)
	}
	if msg.Status.Actor != "actor-b" {
		t.Errorf("Actor = %q, want %q", msg.Status.Actor, "actor-b")
	}
	if msg.Status.CreatedAt != "2025-01-01T00:00:00Z" {
		t.Errorf("CreatedAt should be preserved, got %q", msg.Status.CreatedAt)
	}
	if msg.Status.UpdatedAt == "2025-01-01T00:00:00Z" {
		t.Error("UpdatedAt should be updated to current time")
	}
	if msg.Status.Error != nil {
		t.Error("Error should be cleared")
	}
}

func TestRouter_EnsureAndUpdateStatus_ActorTransition(t *testing.T) {
	router := &Router{actorName: "actor-b"}
	msg := &messages.Message{
		ID:      "msg-1",
		Route:   messages.Route{Prev: []string{"actor-a"}, Curr: "actor-b", Next: []string{}},
		Payload: json.RawMessage(`{}`),
		Status: &messages.Status{
			Phase:   messages.PhasePending,
			Actor:   "actor-a",
			Attempt: 3,
		},
	}

	router.ensureAndUpdateStatus(msg)

	if msg.Status.Attempt != 1 {
		t.Errorf("Attempt should reset to 1 on actor change, got %d", msg.Status.Attempt)
	}
	if msg.Status.Actor != "actor-b" {
		t.Errorf("Actor = %q, want %q", msg.Status.Actor, "actor-b")
	}
}

func TestRouter_EnsureAndUpdateStatus_SameActorRetry(t *testing.T) {
	router := &Router{actorName: "actor-a"}
	msg := &messages.Message{
		ID:      "msg-1",
		Route:   messages.Route{Prev: []string{}, Curr: "actor-a", Next: []string{}},
		Payload: json.RawMessage(`{}`),
		Status: &messages.Status{
			Phase:   messages.PhasePending,
			Actor:   "actor-a",
			Attempt: 3,
		},
	}

	router.ensureAndUpdateStatus(msg)

	if msg.Status.Attempt != 3 {
		t.Errorf("Attempt should be preserved for same actor, got %d", msg.Status.Attempt)
	}
}

func TestRouter_RouteResponse_NextActor_HasStatus(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": "ok"}`),
				Route:   messages.Route{Prev: []string{"actor1"}, Curr: "actor2", Next: []string{}},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "actor1",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}
	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := messages.Message{
		ID:      "test-status-next",
		Route:   messages.Route{Prev: []string{}, Curr: "actor1", Next: []string{"actor2"}},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	ctx := context.Background()
	err := router.ProcessMessage(ctx, transport.QueueMessage{ID: "msg-1", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
	}

	var sentMsg messages.Message
	if err := json.Unmarshal(mockTransport.sentMessages[0].body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	if sentMsg.Status == nil {
		t.Fatal("Status should be present on routed message")
	}
	if sentMsg.Status.Phase != messages.PhasePending {
		t.Errorf("Status.Phase = %q, want %q", sentMsg.Status.Phase, messages.PhasePending)
	}
	if sentMsg.Status.Actor != "actor2" {
		t.Errorf("Status.Actor = %q, want %q", sentMsg.Status.Actor, "actor2")
	}
}

func TestRouter_RouteResponse_Sink_HasStatus(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		// Runtime returns route with current=1, which is past the end of a single-actor route
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": "done"}`),
				Route:   messages.Route{Prev: []string{"actor1"}, Curr: "", Next: []string{}},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "actor1",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}
	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := messages.Message{
		ID:      "test-sink-status",
		Route:   messages.Route{Prev: []string{}, Curr: "actor1", Next: []string{}},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	ctx := context.Background()
	err := router.ProcessMessage(ctx, transport.QueueMessage{ID: "msg-1", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to x-sink, got %d", len(mockTransport.sentMessages))
	}

	var sentMsg messages.Message
	if err := json.Unmarshal(mockTransport.sentMessages[0].body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	if sentMsg.Status == nil {
		t.Fatal("Status should be present on x-sink message")
	}
	if sentMsg.Status.Phase != messages.PhaseSucceeded {
		t.Errorf("Status.Phase = %q, want %q", sentMsg.Status.Phase, messages.PhaseSucceeded)
	}
	if sentMsg.Status.Reason != messages.ReasonCompleted {
		t.Errorf("Status.Reason = %q, want %q", sentMsg.Status.Reason, messages.ReasonCompleted)
	}
}

func TestRouter_SendToSumpQueue_HasStatus(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}
	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mockTransport,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	originalMsg := messages.Message{
		ID:      "test-error-status",
		Route:   messages.Route{Prev: []string{}, Curr: "test-actor", Next: []string{}},
		Payload: json.RawMessage(`{"data": "test"}`),
		Status: &messages.Status{
			Phase:     messages.PhaseProcessing,
			Actor:     "test-actor",
			CreatedAt: "2025-01-01T00:00:00Z",
		},
	}
	originalBody, _ := json.Marshal(originalMsg)

	ctx := context.Background()
	err := router.sendToSumpQueue(ctx, originalBody, "Runtime processing failed")
	if err != nil {
		t.Fatalf("sendToSumpQueue failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
	}

	var errorMsg map[string]any
	if err := json.Unmarshal(mockTransport.sentMessages[0].body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal error message: %v", err)
	}

	status, ok := errorMsg["status"].(map[string]any)
	if !ok {
		t.Fatal("Status should be present in error message")
	}
	if status["phase"] != messages.PhaseFailed {
		t.Errorf("Status.phase = %q, want %q", status["phase"], messages.PhaseFailed)
	}
	if status["actor"] != "test-actor" {
		t.Errorf("Status.actor = %q, want %q", status["actor"], "test-actor")
	}
	if status["created_at"] != "2025-01-01T00:00:00Z" {
		t.Errorf("Status.created_at = %q, want preserved value", status["created_at"])
	}
}

func TestRouter_SendToSinkQueue_HasStatus(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}
	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mockTransport,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	msg := messages.Message{
		ID:      "test-sink-queue-status",
		Route:   messages.Route{Prev: []string{"actor1"}, Curr: "", Next: []string{}},
		Payload: json.RawMessage(`{"result": "success"}`),
	}

	ctx := context.Background()
	err := router.sendToSinkQueue(ctx, msg)
	if err != nil {
		t.Fatalf("sendToSinkQueue failed: %v", err)
	}

	var sentMsg messages.Message
	if err := json.Unmarshal(mockTransport.sentMessages[0].body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if sentMsg.Status == nil {
		t.Fatal("Status should be present")
	}
	if sentMsg.Status.Phase != messages.PhaseSucceeded {
		t.Errorf("Status.Phase = %q, want %q", sentMsg.Status.Phase, messages.PhaseSucceeded)
	}
	if sentMsg.Status.Reason != messages.ReasonCompleted {
		t.Errorf("Status.Reason = %q, want %q", sentMsg.Status.Reason, messages.ReasonCompleted)
	}
}

// --- Route Override Tests ---

func TestRouter_LookupRouteOverride(t *testing.T) {
	router := &Router{
		cfg: &config.Config{ActorName: "model-v2"},
	}

	tests := []struct {
		name       string
		actorName  string
		headers    map[string]interface{}
		wantTarget string
		wantOK     bool
	}{
		{
			name:      "override found",
			actorName: "model",
			headers: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model": "model-v2",
				},
			},
			wantTarget: "model-v2",
			wantOK:     true,
		},
		{
			name:      "no override header",
			actorName: "model",
			headers:   map[string]interface{}{},
			wantOK:    false,
		},
		{
			name:      "nil headers",
			actorName: "model",
			headers:   nil,
			wantOK:    false,
		},
		{
			name:      "override for different actor - ignored",
			actorName: "model",
			headers: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"postprocess": "postprocess-v2",
				},
			},
			wantOK: false,
		},
		{
			name:      "empty target string - ignored",
			actorName: "model",
			headers: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model": "",
				},
			},
			wantOK: false,
		},
		{
			name:      "non-string target - ignored",
			actorName: "model",
			headers: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model": 42,
				},
			},
			wantOK: false,
		},
		{
			name:      "malformed override value - not a map",
			actorName: "model",
			headers: map[string]interface{}{
				"x-asya-route-override": "not-a-map",
			},
			wantOK: false,
		},
		{
			name:      "multiple overrides - correct one selected",
			actorName: "model",
			headers: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model":       "model-v2",
					"postprocess": "postprocess-v2",
				},
			},
			wantTarget: "model-v2",
			wantOK:     true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			target, ok := router.lookupRouteOverride(tt.actorName, tt.headers)
			if ok != tt.wantOK {
				t.Errorf("lookupRouteOverride() ok = %v, want %v", ok, tt.wantOK)
			}
			if target != tt.wantTarget {
				t.Errorf("lookupRouteOverride() target = %q, want %q", target, tt.wantTarget)
			}
		})
	}
}

func TestRouter_IsOverrideTarget(t *testing.T) {
	router := &Router{
		cfg: &config.Config{ActorName: "model-v2"},
	}

	tests := []struct {
		name       string
		routeActor string
		headers    map[string]interface{}
		want       bool
	}{
		{
			name:       "override maps to this actor",
			routeActor: "model",
			headers: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model": "model-v2",
				},
			},
			want: true,
		},
		{
			name:       "override maps to different actor",
			routeActor: "model",
			headers: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model": "model-v3",
				},
			},
			want: false,
		},
		{
			name:       "no override",
			routeActor: "model",
			headers:    map[string]interface{}{},
			want:       false,
		},
		{
			name:       "nil headers",
			routeActor: "model",
			headers:    nil,
			want:       false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := router.isOverrideTarget(tt.routeActor, tt.headers)
			if got != tt.want {
				t.Errorf("isOverrideTarget() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRouter_RouteOverride_Integration(t *testing.T) {
	tests := []struct {
		name              string
		actorName         string
		inputHeaders      map[string]interface{}
		inputRoute        messages.Route
		expectedDestQueue string
		expectResolved    bool
	}{
		{
			name:      "override routes to alternate queue",
			actorName: "prep",
			inputHeaders: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model": "model-v2",
				},
			},
			inputRoute: messages.Route{
				Prev: []string{},
				Curr: "prep",
				Next: []string{"model", "post"},
			},
			expectedDestQueue: "asya-default-model-v2",
			expectResolved:    true,
		},
		{
			name:      "no override - normal routing",
			actorName: "prep",
			inputHeaders: map[string]interface{}{
				"trace_id": "abc-123",
			},
			inputRoute: messages.Route{
				Prev: []string{},
				Curr: "prep",
				Next: []string{"model", "post"},
			},
			expectedDestQueue: "asya-default-model",
			expectResolved:    false,
		},
		{
			name:      "override for non-matching actor - ignored",
			actorName: "prep",
			inputHeaders: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"postprocess": "postprocess-v2",
				},
			},
			inputRoute: messages.Route{
				Prev: []string{},
				Curr: "prep",
				Next: []string{"model", "post"},
			},
			expectedDestQueue: "asya-default-model",
			expectResolved:    false,
		},
		{
			name:         "nil headers - normal routing",
			actorName:    "prep",
			inputHeaders: nil,
			inputRoute: messages.Route{
				Prev: []string{},
				Curr: "prep",
				Next: []string{"model"},
			},
			expectedDestQueue: "asya-default-model",
			expectResolved:    false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Convert inputHeaders to map[string]json.RawMessage for RuntimeResponse
			var runtimeHeaders map[string]json.RawMessage
			if tt.inputHeaders != nil {
				runtimeHeaders = make(map[string]json.RawMessage, len(tt.inputHeaders))
				for k, v := range tt.inputHeaders {
					raw, _ := json.Marshal(v)
					runtimeHeaders[k] = raw
				}
			}

			socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
				return []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "ok"}`),
						Route:   tt.inputRoute.IncrementCurrent(),
						Headers: runtimeHeaders,
					},
				}, http.StatusOK
			})

			cfg := &config.Config{
				ActorName:     tt.actorName,
				Namespace:     "default",
				SinkQueue:     testQueueSink,
				SumpQueue:     testQueueSump,
				TransportType: "rabbitmq",
				Timeout:       2 * time.Second,
			}

			mockTr := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           cfg,
				transport:     mockTr,
				runtimeClient: runtimeClient,
				actorName:     cfg.ActorName,
				sinkQueue:     cfg.SinkQueue,
				sumpQueue:     cfg.SumpQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			inputMsg := messages.Message{
				ID:      "test-override-123",
				Route:   tt.inputRoute,
				Payload: json.RawMessage(`{"input": "test"}`),
				Headers: tt.inputHeaders,
			}
			msgBody, err := json.Marshal(inputMsg)
			if err != nil {
				t.Fatalf("Failed to marshal: %v", err)
			}

			err = router.ProcessMessage(context.Background(), transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			})
			if err != nil {
				t.Fatalf("ProcessMessage failed: %v", err)
			}

			if len(mockTr.sentMessages) != 1 {
				t.Fatalf("Expected 1 sent message, got %d", len(mockTr.sentMessages))
			}

			if mockTr.sentMessages[0].queue != tt.expectedDestQueue {
				t.Errorf("Sent to queue %q, expected %q",
					mockTr.sentMessages[0].queue, tt.expectedDestQueue)
			}

			var sentMsg messages.Message
			if err := json.Unmarshal(mockTr.sentMessages[0].body, &sentMsg); err != nil {
				t.Fatalf("Failed to unmarshal sent message: %v", err)
			}

			if tt.expectResolved {
				resolved, ok := sentMsg.Headers["x-asya-route-resolved"]
				if !ok {
					t.Fatal("Expected x-asya-route-resolved header")
				}
				resolvedMap, ok := resolved.(map[string]interface{})
				if !ok {
					t.Fatalf("x-asya-route-resolved should be a map, got %T", resolved)
				}
				if len(resolvedMap) == 0 {
					t.Error("x-asya-route-resolved should have at least one entry")
				}
			} else {
				if sentMsg.Headers != nil {
					if _, ok := sentMsg.Headers["x-asya-route-resolved"]; ok {
						t.Error("x-asya-route-resolved should NOT be set when no override is applied")
					}
				}
			}
		})
	}
}

func TestRouter_RouteOverride_ActorValidation(t *testing.T) {
	tests := []struct {
		name              string
		actorName         string
		inputRoute        messages.Route
		inputHeaders      map[string]interface{}
		shouldCallRuntime bool
		expectedDestQueue string
	}{
		{
			name:      "override matches actor - accepted",
			actorName: "model-v2",
			inputRoute: messages.Route{
				Prev: []string{"prep"},
				Curr: "model",
				Next: []string{"post"},
			},
			inputHeaders: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model": "model-v2",
				},
			},
			shouldCallRuntime: true,
			expectedDestQueue: "asya-default-post",
		},
		{
			name:      "override maps to different actor - rejected",
			actorName: "model-v2",
			inputRoute: messages.Route{
				Prev: []string{"prep"},
				Curr: "model",
				Next: []string{"post"},
			},
			inputHeaders: map[string]interface{}{
				"x-asya-route-override": map[string]interface{}{
					"model": "model-v3",
				},
			},
			shouldCallRuntime: false,
			expectedDestQueue: "asya-default-x-sump",
		},
		{
			name:      "no override and mismatch - rejected",
			actorName: "model-v2",
			inputRoute: messages.Route{
				Prev: []string{"prep"},
				Curr: "model",
				Next: []string{"post"},
			},
			inputHeaders:      nil,
			shouldCallRuntime: false,
			expectedDestQueue: "asya-default-x-sump",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runtimeCalled := false
			socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
				runtimeCalled = true
				return []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "ok"}`),
						Route:   tt.inputRoute.IncrementCurrent(),
					},
				}, http.StatusOK
			})

			cfg := &config.Config{
				ActorName:     tt.actorName,
				Namespace:     "default",
				SinkQueue:     testQueueSink,
				SumpQueue:     testQueueSump,
				TransportType: "rabbitmq",
				Timeout:       2 * time.Second,
			}

			mockTr := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           cfg,
				transport:     mockTr,
				runtimeClient: runtimeClient,
				actorName:     cfg.ActorName,
				sinkQueue:     cfg.SinkQueue,
				sumpQueue:     cfg.SumpQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			inputMsg := messages.Message{
				ID:      "test-validation-123",
				Route:   tt.inputRoute,
				Payload: json.RawMessage(`{"input": "test"}`),
				Headers: tt.inputHeaders,
			}
			msgBody, err := json.Marshal(inputMsg)
			if err != nil {
				t.Fatalf("Failed to marshal: %v", err)
			}

			err = router.ProcessMessage(context.Background(), transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			})
			if err != nil {
				t.Fatalf("ProcessMessage failed: %v", err)
			}

			time.Sleep(50 * time.Millisecond) // Wait for runtime call to complete

			if tt.shouldCallRuntime && !runtimeCalled {
				t.Error("Expected runtime to be called, but it was not")
			}
			if !tt.shouldCallRuntime && runtimeCalled {
				t.Error("Expected runtime NOT to be called, but it was")
			}

			if len(mockTr.sentMessages) != 1 {
				t.Fatalf("Expected 1 sent message, got %d", len(mockTr.sentMessages))
			}
			if mockTr.sentMessages[0].queue != tt.expectedDestQueue {
				t.Errorf("Sent to queue %q, expected %q",
					mockTr.sentMessages[0].queue, tt.expectedDestQueue)
			}
		})
	}
}

func TestRouter_RouteOverride_FanOut(t *testing.T) {
	overrideJSON := json.RawMessage(`{"model":"model-v2"}`)
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		inputRoute := messages.Route{
			Prev: []string{},
			Curr: "prep",
			Next: []string{"model", "post"},
		}
		shiftedRoute := inputRoute.IncrementCurrent()
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": "item-0"}`),
				Route:   shiftedRoute,
				Headers: map[string]json.RawMessage{
					"x-asya-route-override": overrideJSON,
				},
			},
			{
				Payload: json.RawMessage(`{"result": "item-1"}`),
				Route:   shiftedRoute,
				Headers: map[string]json.RawMessage{
					"x-asya-route-override": overrideJSON,
				},
			},
			{
				Payload: json.RawMessage(`{"result": "item-2"}`),
				Route:   shiftedRoute,
				Headers: map[string]json.RawMessage{
					"x-asya-route-override": overrideJSON,
				},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "prep",
		Namespace:     "default",
		SinkQueue:     testQueueSink,
		SumpQueue:     testQueueSump,
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTr := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mockTr,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := messages.Message{
		ID: "test-fanout-override-123",
		Route: messages.Route{
			Prev: []string{},
			Curr: "prep",
			Next: []string{"model", "post"},
		},
		Payload: json.RawMessage(`{"input": "test"}`),
		Headers: map[string]interface{}{
			"x-asya-route-override": map[string]interface{}{
				"model": "model-v2",
			},
		},
	}
	msgBody, err := json.Marshal(inputMsg)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	err = router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTr.sentMessages) != 3 {
		t.Fatalf("Expected 3 fanout messages, got %d", len(mockTr.sentMessages))
	}

	for i, sent := range mockTr.sentMessages {
		if sent.queue != "asya-default-model-v2" {
			t.Errorf("Fanout message %d sent to %q, expected %q",
				i, sent.queue, "asya-default-model-v2")
		}

		var sentMsg messages.Message
		if err := json.Unmarshal(sent.body, &sentMsg); err != nil {
			t.Fatalf("Failed to unmarshal fanout message %d: %v", i, err)
		}

		resolved, ok := sentMsg.Headers["x-asya-route-resolved"]
		if !ok {
			t.Errorf("Fanout message %d missing x-asya-route-resolved", i)
			continue
		}
		resolvedMap, ok := resolved.(map[string]interface{})
		if !ok {
			t.Errorf("Fanout message %d x-asya-route-resolved is not a map", i)
			continue
		}
		entry, ok := resolvedMap["model"]
		if !ok {
			t.Errorf("Fanout message %d x-asya-route-resolved missing 'model' entry", i)
			continue
		}
		entryMap, ok := entry.(map[string]interface{})
		if !ok {
			t.Errorf("Fanout message %d resolution entry is not a map", i)
			continue
		}
		if entryMap["target"] != "model-v2" {
			t.Errorf("Fanout message %d resolution target = %v, want model-v2", i, entryMap["target"])
		}
		if entryMap["by"] != "prep" {
			t.Errorf("Fanout message %d resolution by = %v, want prep", i, entryMap["by"])
		}
	}

	var msg0 messages.Message
	if err := json.Unmarshal(mockTr.sentMessages[0].body, &msg0); err != nil {
		t.Fatalf("unmarshal msg 0: %v", err)
	}
	if msg0.ID != "test-fanout-override-123" {
		t.Errorf("Fanout index 0 should keep original ID, got %q", msg0.ID)
	}
	if msg0.ParentID != nil {
		t.Errorf("Fanout index 0 should have nil ParentID, got %v", *msg0.ParentID)
	}

	for i := 1; i < 3; i++ {
		var msgN messages.Message
		if err := json.Unmarshal(mockTr.sentMessages[i].body, &msgN); err != nil {
			t.Fatalf("unmarshal msg %d: %v", i, err)
		}
		if msgN.ID == "test-fanout-override-123" {
			t.Errorf("Fanout index %d should have new UUID, got original ID", i)
		}
		if msgN.ParentID == nil || *msgN.ParentID != "test-fanout-override-123" {
			t.Errorf("Fanout index %d ParentID should be original ID", i)
		}
	}
}

func TestRouter_RouteOverride_ResolvedHeaderAuditTrail(t *testing.T) {
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": "ok"}`),
				Route: messages.Route{
					Prev: []string{"prep"},
					Curr: "model",
					Next: []string{"post"},
				},
				Headers: map[string]json.RawMessage{
					"x-asya-route-override": json.RawMessage(`{"model":"model-v2"}`),
				},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "prep",
		Namespace:     "default",
		SinkQueue:     testQueueSink,
		SumpQueue:     testQueueSump,
		Timeout:       2 * time.Second,
		TransportType: "sqs",
	}

	mockTr := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mockTr,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := messages.Message{
		ID: "test-audit-123",
		Route: messages.Route{
			Prev: []string{},
			Curr: "prep",
			Next: []string{"model", "post"},
		},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTr.sentMessages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(mockTr.sentMessages))
	}

	if mockTr.sentMessages[0].queue != "asya-default-model-v2" {
		t.Errorf("Queue = %q, want asya-default-model-v2", mockTr.sentMessages[0].queue)
	}

	var sentMsg messages.Message
	if err := json.Unmarshal(mockTr.sentMessages[0].body, &sentMsg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	resolved, ok := sentMsg.Headers["x-asya-route-resolved"]
	if !ok {
		t.Fatal("Missing x-asya-route-resolved")
	}

	resolvedMap, ok := resolved.(map[string]interface{})
	if !ok {
		t.Fatalf("x-asya-route-resolved is %T, want map", resolved)
	}

	entry, ok := resolvedMap["model"]
	if !ok {
		t.Fatal("Missing 'model' entry in x-asya-route-resolved")
	}

	entryMap, ok := entry.(map[string]interface{})
	if !ok {
		t.Fatalf("Resolution entry is %T, want map", entry)
	}

	if entryMap["target"] != "model-v2" {
		t.Errorf("target = %v, want model-v2", entryMap["target"])
	}
	if entryMap["by"] != "prep" {
		t.Errorf("by = %v, want prep", entryMap["by"])
	}

	override, ok := sentMsg.Headers["x-asya-route-override"]
	if !ok {
		t.Fatal("x-asya-route-override should propagate through pipeline")
	}
	overrideMap, ok := override.(map[string]interface{})
	if !ok {
		t.Fatalf("x-asya-route-override is %T, want map", override)
	}
	if overrideMap["model"] != "model-v2" {
		t.Errorf("Override should be preserved, got %v", overrideMap["model"])
	}
}

func TestRouter_RouteOverride_PreservesExistingAuditTrail(t *testing.T) {
	// When an upstream actor already stamped x-asya-route-resolved and the runtime
	// passes headers through as json.RawMessage, the existing audit trail must be
	// preserved (not overwritten).
	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": "ok"}`),
				Route: messages.Route{
					Prev: []string{"router", "prep"},
					Curr: "model",
					Next: []string{"post"},
				},
				Headers: map[string]json.RawMessage{
					"x-asya-route-override": json.RawMessage(`{"model":"model-v2","post":"post-v2"}`),
					"x-asya-route-resolved": json.RawMessage(`{"prep":{"target":"prep-v2","by":"router"}}`),
				},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "prep",
		Namespace:     "default",
		SinkQueue:     testQueueSink,
		SumpQueue:     testQueueSump,
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTr := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mockTr,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	inputMsg := messages.Message{
		ID: "test-preserve-audit-123",
		Route: messages.Route{
			Prev: []string{},
			Curr: "prep",
			Next: []string{"model", "post"},
		},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	err := router.ProcessMessage(context.Background(), transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTr.sentMessages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(mockTr.sentMessages))
	}

	// Should route to overridden queue
	if mockTr.sentMessages[0].queue != "asya-default-model-v2" {
		t.Errorf("Queue = %q, want asya-default-model-v2", mockTr.sentMessages[0].queue)
	}

	var sentMsg messages.Message
	if err := json.Unmarshal(mockTr.sentMessages[0].body, &sentMsg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	resolved, ok := sentMsg.Headers["x-asya-route-resolved"]
	if !ok {
		t.Fatal("Missing x-asya-route-resolved")
	}
	resolvedMap, ok := resolved.(map[string]interface{})
	if !ok {
		t.Fatalf("x-asya-route-resolved is %T, want map", resolved)
	}

	// Existing audit trail entry from upstream should be preserved
	prepEntry, ok := resolvedMap["prep"]
	if !ok {
		t.Fatal("Existing 'prep' audit trail entry was lost")
	}
	prepMap, ok := prepEntry.(map[string]interface{})
	if !ok {
		t.Fatalf("prep entry is %T, want map", prepEntry)
	}
	if prepMap["target"] != "prep-v2" {
		t.Errorf("Existing prep target = %v, want prep-v2", prepMap["target"])
	}
	if prepMap["by"] != "router" {
		t.Errorf("Existing prep by = %v, want router", prepMap["by"])
	}

	// New audit trail entry for model override should be added
	modelEntry, ok := resolvedMap["model"]
	if !ok {
		t.Fatal("New 'model' audit trail entry missing")
	}
	modelMap, ok := modelEntry.(map[string]interface{})
	if !ok {
		t.Fatalf("model entry is %T, want map", modelEntry)
	}
	if modelMap["target"] != "model-v2" {
		t.Errorf("model target = %v, want model-v2", modelMap["target"])
	}
	if modelMap["by"] != "prep" {
		t.Errorf("model by = %v, want prep", modelMap["by"])
	}
}

func TestRouter_EffectiveTimeout(t *testing.T) {
	tests := []struct {
		name          string
		timeout       time.Duration
		deadlineIn    time.Duration
		wantTimeout   time.Duration
		wantApproxMin time.Duration
		wantApproxMax time.Duration
	}{
		{
			name:        "no deadline - uses actor timeout",
			timeout:     5 * time.Minute,
			deadlineIn:  0,
			wantTimeout: 5 * time.Minute,
		},
		{
			name:        "short actor timeout, no deadline",
			timeout:     2 * time.Minute,
			deadlineIn:  0,
			wantTimeout: 2 * time.Minute,
		},
		{
			name:          "deadline remaining < actor timeout - uses remaining SLA",
			timeout:       5 * time.Minute,
			deadlineIn:    1 * time.Minute,
			wantApproxMin: 59 * time.Second,
			wantApproxMax: 61 * time.Second,
		},
		{
			name:        "deadline in far future - uses actor timeout",
			timeout:     2 * time.Minute,
			deadlineIn:  10 * time.Minute,
			wantTimeout: 2 * time.Minute,
		},
		{
			name:          "deadline already passed - returns negative duration",
			timeout:       5 * time.Minute,
			deadlineIn:    -1 * time.Minute,
			wantApproxMin: -61 * time.Second,
			wantApproxMax: -59 * time.Second,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &config.Config{
				Timeout: tt.timeout,
			}

			router := &Router{cfg: cfg}

			msg := &messages.Message{
				ID: "test-msg",
				Route: messages.Route{
					Curr: "test-actor",
				},
			}

			if tt.deadlineIn != 0 {
				deadline := time.Now().Add(tt.deadlineIn).UTC().Format(time.RFC3339)
				msg.Status = &messages.Status{
					DeadlineAt: deadline,
				}
			}

			got := router.effectiveTimeout(msg)

			if tt.wantTimeout > 0 {
				if got != tt.wantTimeout {
					t.Errorf("effectiveTimeout() = %v, want %v", got, tt.wantTimeout)
				}
			} else {
				if got < tt.wantApproxMin || got > tt.wantApproxMax {
					t.Errorf("effectiveTimeout() = %v, want between %v and %v",
						got, tt.wantApproxMin, tt.wantApproxMax)
				}
			}
		})
	}
}

func TestRouter_ProcessMessage_SLAExpired(t *testing.T) {
	runtimeCalled := false

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		runtimeCalled = true
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": "ok"}`),
				Route: messages.Route{
					Prev: []string{},
					Curr: "",
					Next: []string{},
				},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     testQueueSink,
		SumpQueue:     testQueueSump,
		Timeout:       5 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTp := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 5*time.Second)
	router := &Router{
		cfg:           cfg,
		transport:     mockTp,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	msg := messages.Message{
		ID: "expired-msg",
		Route: messages.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Payload: json.RawMessage(`{"test": "data"}`),
		Status: &messages.Status{
			Phase:      messages.PhasePending,
			Actor:      "test-actor",
			CreatedAt:  time.Now().Add(-10 * time.Minute).UTC().Format(time.RFC3339),
			DeadlineAt: time.Now().Add(-1 * time.Minute).UTC().Format(time.RFC3339),
			UpdatedAt:  time.Now().Add(-10 * time.Minute).UTC().Format(time.RFC3339),
		},
	}

	msgBody, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Failed to marshal message: %v", err)
	}

	queueMsg := transport.QueueMessage{
		ID:   "q-1",
		Body: msgBody,
	}

	err = router.ProcessMessage(context.Background(), queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage() error = %v", err)
	}

	if runtimeCalled {
		t.Error("Runtime should NOT be called for expired SLA")
	}

	if len(mockTp.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to sink, got %d", len(mockTp.sentMessages))
	}

	sentMsg := mockTp.sentMessages[0]
	expectedQueue := "asya-default-x-sink"
	if sentMsg.queue != expectedQueue {
		t.Errorf("Message sent to %s, want %s", sentMsg.queue, expectedQueue)
	}

	var sentMsgData messages.Message
	if err := json.Unmarshal(sentMsg.body, &sentMsgData); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	if sentMsgData.Status == nil {
		t.Fatal("Sent message has no status")
	}

	if sentMsgData.Status.Phase != messages.PhaseFailed {
		t.Errorf("Status phase = %s, want %s", sentMsgData.Status.Phase, messages.PhaseFailed)
	}

	if sentMsgData.Status.Reason != messages.ReasonTimeout {
		t.Errorf("Status reason = %s, want %s", sentMsgData.Status.Reason, messages.ReasonTimeout)
	}
}

func TestRouter_ProcessMessage_SLANotExpired(t *testing.T) {
	runtimeCalled := false

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		runtimeCalled = true
		return []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": "ok"}`),
				Route: messages.Route{
					Prev: []string{"test-actor"},
					Curr: "next-actor",
					Next: []string{},
				},
			},
		}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     testQueueSink,
		SumpQueue:     testQueueSump,
		Timeout:       5 * time.Second,
		TransportType: "rabbitmq",
	}

	mockTp := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 5*time.Second)
	router := &Router{
		cfg:           cfg,
		transport:     mockTp,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		sinkQueue:     cfg.SinkQueue,
		sumpQueue:     cfg.SumpQueue,
		metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
	}

	msg := messages.Message{
		ID: "valid-msg",
		Route: messages.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Payload: json.RawMessage(`{"test": "data"}`),
		Status: &messages.Status{
			Phase:      messages.PhasePending,
			Actor:      "test-actor",
			CreatedAt:  time.Now().UTC().Format(time.RFC3339),
			DeadlineAt: time.Now().Add(5 * time.Minute).UTC().Format(time.RFC3339),
			UpdatedAt:  time.Now().UTC().Format(time.RFC3339),
		},
	}

	msgBody, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Failed to marshal message: %v", err)
	}

	queueMsg := transport.QueueMessage{
		ID:   "q-1",
		Body: msgBody,
	}

	err = router.ProcessMessage(context.Background(), queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage() error = %v", err)
	}

	if !runtimeCalled {
		t.Error("Runtime SHOULD be called for non-expired SLA")
	}

	if len(mockTp.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to next queue, got %d", len(mockTp.sentMessages))
	}

	sentMsg := mockTp.sentMessages[0]
	expectedQueue := "asya-default-next-actor"
	if sentMsg.queue != expectedQueue {
		t.Errorf("Message sent to %s, want %s", sentMsg.queue, expectedQueue)
	}
}

// TestRouter_ProcessMessage_SLAGuard verifies the defense-in-depth guard
// before CallRuntime that catches tight or expired SLA deadlines.
func TestRouter_ProcessMessage_SLAGuard(t *testing.T) {
	tests := []struct {
		name       string
		timeout    time.Duration
		deadlineIn time.Duration
	}{
		{
			name:       "zero timeout with future deadline",
			timeout:    0,
			deadlineIn: 5 * time.Minute,
		},
		{
			name:       "deadline within guard margin",
			timeout:    30 * time.Second,
			deadlineIn: 500 * time.Millisecond, // < 1s slaGuardMargin
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runtimeCalled := false

			socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
				runtimeCalled = true
				return []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "ok"}`),
						Route: messages.Route{
							Prev: []string{},
							Curr: "",
							Next: []string{},
						},
					},
				}, http.StatusOK
			})

			cfg := &config.Config{
				ActorName:     "test-actor",
				Namespace:     "default",
				SinkQueue:     testQueueSink,
				SumpQueue:     testQueueSump,
				Timeout:       tt.timeout,
				TransportType: "rabbitmq",
			}

			mockTp := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 5*time.Second)
			router := &Router{
				cfg:           cfg,
				transport:     mockTp,
				runtimeClient: runtimeClient,
				actorName:     cfg.ActorName,
				sinkQueue:     cfg.SinkQueue,
				sumpQueue:     cfg.SumpQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			msg := messages.Message{
				ID: "guard-msg",
				Route: messages.Route{
					Prev: []string{},
					Curr: "test-actor",
					Next: []string{"next-actor"},
				},
				Payload: json.RawMessage(`{"test": "data"}`),
				Status: &messages.Status{
					Phase:      messages.PhasePending,
					Actor:      "test-actor",
					CreatedAt:  time.Now().UTC().Format(time.RFC3339),
					DeadlineAt: time.Now().Add(tt.deadlineIn).UTC().Format(time.RFC3339),
					UpdatedAt:  time.Now().UTC().Format(time.RFC3339),
				},
			}

			msgBody, err := json.Marshal(msg)
			if err != nil {
				t.Fatalf("Failed to marshal message: %v", err)
			}

			queueMsg := transport.QueueMessage{
				ID:   "q-1",
				Body: msgBody,
			}

			err = router.ProcessMessage(context.Background(), queueMsg)
			if err != nil {
				t.Fatalf("ProcessMessage() error = %v", err)
			}

			if runtimeCalled {
				t.Error("Runtime should NOT be called when SLA guard fires")
			}

			if len(mockTp.sentMessages) != 1 {
				t.Fatalf("Expected 1 message sent to sink, got %d", len(mockTp.sentMessages))
			}

			sentMsg := mockTp.sentMessages[0]
			expectedQueue := "asya-default-x-sink"
			if sentMsg.queue != expectedQueue {
				t.Errorf("Message sent to %s, want %s", sentMsg.queue, expectedQueue)
			}

			var sentMsgData messages.Message
			if err := json.Unmarshal(sentMsg.body, &sentMsgData); err != nil {
				t.Fatalf("Failed to unmarshal sent message: %v", err)
			}

			if sentMsgData.Status == nil {
				t.Fatal("Sent message has no status")
			}

			if sentMsgData.Status.Phase != messages.PhaseFailed {
				t.Errorf("Status phase = %s, want %s", sentMsgData.Status.Phase, messages.PhaseFailed)
			}

			if sentMsgData.Status.Reason != messages.ReasonTimeout {
				t.Errorf("Status reason = %s, want %s", sentMsgData.Status.Reason, messages.ReasonTimeout)
			}
		})
	}
}
