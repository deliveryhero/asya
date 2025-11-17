package router

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/progress"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
)

const (
	testQueueHappyEnd = "happy-end"
	testQueueErrorEnd = "error-end"
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

func (m *mockTransport) Nack(ctx context.Context, msg transport.QueueMessage) error {
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
		inputRoute           envelopes.Route
		expectedWarnContains string
		shouldRejectAndError bool
		shouldCallRuntime    bool
		expectedDestQueue    string
	}{
		{
			name:      "route matches sidecar queue - processes normally",
			actorName: "test-actor",
			inputRoute: envelopes.Route{
				Actors:  []string{"test-actor", "next-actor"},
				Current: 0,
			},
			shouldRejectAndError: false,
			shouldCallRuntime:    true,
			expectedDestQueue:    "asya-next-actor",
		},
		{
			name:      "route does not match sidecar queue - sends to error queue",
			actorName: "test-actor",
			inputRoute: envelopes.Route{
				Actors:  []string{"wrong-actor", "next-actor"},
				Current: 0,
			},
			expectedWarnContains: "Route mismatch: message routed to wrong actor",
			shouldRejectAndError: true,
			shouldCallRuntime:    false,
			expectedDestQueue:    "asya-error-end",
		},
		{
			name:      "route current index out of sync - sends to error queue",
			actorName: "test-actor",
			inputRoute: envelopes.Route{
				Actors:  []string{"test-actor", "next-actor"},
				Current: 1,
			},
			expectedWarnContains: "Route mismatch: message routed to wrong actor",
			shouldRejectAndError: true,
			shouldCallRuntime:    false,
			expectedDestQueue:    "asya-error-end",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var logBuf bytes.Buffer
			logger := slog.New(slog.NewTextHandler(&logBuf, &slog.HandlerOptions{
				Level: slog.LevelWarn,
			}))
			slog.SetDefault(logger)

			socketPath := fmt.Sprintf("/tmp/test-router-%d.sock", time.Now().UnixNano())
			defer func() { _ = os.Remove(socketPath) }()

			listener, err := net.Listen("unix", socketPath)
			if err != nil {
				t.Fatalf("Failed to create socket: %v", err)
			}
			defer func() { _ = listener.Close() }()

			runtimeCalled := false
			go func() {
				conn, err := listener.Accept()
				if err != nil {
					return
				}
				defer func() { _ = conn.Close() }()

				runtimeCalled = true

				_, err = runtime.RecvSocketData(conn)
				if err != nil {
					return
				}

				responses := []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "processed"}`),
						Route: envelopes.Route{
							Actors:  tt.inputRoute.Actors,
							Current: tt.inputRoute.Current + 1,
						},
					},
				}
				data, _ := json.Marshal(responses)
				_ = runtime.SendSocketData(conn, data)
			}()

			cfg := &config.Config{
				ActorName:     tt.actorName,
				HappyEndQueue: "happy-end",
				ErrorEndQueue: "error-end",
				TransportType: "rabbitmq",
			}

			mockTransport := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           cfg,
				transport:     mockTransport,
				runtimeClient: runtimeClient,
				actorName:     cfg.ActorName,
				happyEndQueue: cfg.HappyEndQueue,
				errorEndQueue: cfg.ErrorEndQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			inputEnvelope := envelopes.Envelope{
				ID:      "test-envelope-123",
				Route:   tt.inputRoute,
				Payload: json.RawMessage(`{"input": "test"}`),
			}
			msgBody, err := json.Marshal(inputEnvelope)
			if err != nil {
				t.Fatalf("Failed to marshal test envelope: %v", err)
			}

			queueMsg := transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			}

			ctx := context.Background()
			err = router.ProcessEnvelope(ctx, queueMsg)
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

				var errorEnvelope map[string]interface{}
				if err := json.Unmarshal(mockTransport.sentMessages[0].body, &errorEnvelope); err != nil {
					t.Fatalf("Failed to parse error envelope: %v", err)
				}

				payload, ok := errorEnvelope["payload"].(map[string]interface{})
				if !ok {
					t.Fatalf("Expected payload to be a map, got %T", errorEnvelope["payload"])
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
			},
			actorName: "my-actor",
			expected:  "asya-my-actor",
		},
		{
			name:          "sqs - with base URL",
			transportType: "sqs",
			config: &config.Config{
				TransportType: "sqs",
				SQSBaseURL:    "https://sqs.us-east-1.amazonaws.com/123456789",
			},
			actorName: "image-processor",
			expected:  "asya-image-processor",
		},
		{
			name:          "sqs - without base URL (fallback to identity)",
			transportType: "sqs",
			config: &config.Config{
				TransportType: "sqs",
				SQSBaseURL:    "",
			},
			actorName: "image-processor",
			expected:  "asya-image-processor",
		},
		{
			name:          "unknown transport - fallback to identity",
			transportType: "unknown",
			config: &config.Config{
				TransportType: "unknown",
			},
			actorName: "some-actor",
			expected:  "some-actor",
		},
		{
			name:          "end queue - happy-end",
			transportType: "rabbitmq",
			config: &config.Config{
				TransportType: "rabbitmq",
			},
			actorName: "happy-end",
			expected:  "asya-happy-end",
		},
		{
			name:          "end queue - error-end with SQS",
			transportType: "sqs",
			config: &config.Config{
				TransportType: "sqs",
				SQSBaseURL:    "https://sqs.us-west-2.amazonaws.com/987654321",
			},
			actorName: "error-end",
			expected:  "asya-error-end",
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

	for i, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Setup Unix socket server to mock runtime
			socketPath := fmt.Sprintf("/tmp/test-dyn-route-%d.sock", i)
			_ = os.Remove(socketPath)
			defer func() { _ = os.Remove(socketPath) }()

			listener, err := net.Listen("unix", socketPath)
			if err != nil {
				t.Fatalf("Failed to create socket: %v", err)
			}
			defer func() { _ = listener.Close() }()

			// Start mock runtime server that returns modified route
			go func() {
				conn, err := listener.Accept()
				if err != nil {
					return
				}
				defer func() { _ = conn.Close() }()

				// Receive request
				_, err = runtime.RecvSocketData(conn)
				if err != nil {
					return
				}

				// Send response with route where current is already incremented by runtime
				responses := []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "processed"}`),
						Route: envelopes.Route{
							Actors:  tt.runtimeOutputActors,
							Current: 1, // Runtime increments current in payload mode
						},
					},
				}

				data, _ := json.Marshal(responses)
				_ = runtime.SendSocketData(conn, data)
			}()

			// Setup test components
			cfg := &config.Config{
				ActorName:     tt.initialActors[0],
				HappyEndQueue: "happy-end",
				ErrorEndQueue: "error-end",
			}

			mockTransport := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           cfg,
				transport:     mockTransport,
				runtimeClient: runtimeClient,
				actorName:     cfg.ActorName,
				happyEndQueue: cfg.HappyEndQueue,
				errorEndQueue: cfg.ErrorEndQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			// Create test envelope with initial route
			inputEnvelope := envelopes.Envelope{
				ID: "test-dynamic-route",
				Route: envelopes.Route{
					Actors:  tt.initialActors,
					Current: 0,
				},
				Payload: json.RawMessage(`{"input": "test"}`),
			}
			msgBody, err := json.Marshal(inputEnvelope)
			if err != nil {
				t.Fatalf("Failed to marshal test envelope: %v", err)
			}

			queueMsg := transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			}

			// Process message
			ctx := context.Background()
			err = router.ProcessEnvelope(ctx, queueMsg)
			if err != nil {
				t.Fatalf("ProcessMessage failed: %v", err)
			}

			// Verify message was routed successfully
			if len(mockTransport.sentMessages) != 1 {
				t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
			}

			// Parse the sent message to verify route was updated
			var sentEnvelope envelopes.Envelope
			err = json.Unmarshal(mockTransport.sentMessages[0].body, &sentEnvelope)
			if err != nil {
				t.Fatalf("Failed to unmarshal sent envelope: %v", err)
			}

			// Verify the route was updated with the modified actors list
			if len(sentEnvelope.Route.Actors) != len(tt.runtimeOutputActors) {
				t.Errorf("Expected route with %d actors, got %d",
					len(tt.runtimeOutputActors), len(sentEnvelope.Route.Actors))
			}

			// Verify current index from runtime (runtime increments, sidecar passes through)
			expectedCurrent := 1
			if sentEnvelope.Route.Current != expectedCurrent {
				t.Errorf("Expected current=%d (from runtime), got current=%d",
					expectedCurrent, sentEnvelope.Route.Current)
			}

			// Progress would be calculated as:
			// (current * 100) / totalActors
			// If route expands: (1 * 100) / 5 = 20%
			// If route stays same: (1 * 100) / 2 = 50%
			expectedProgress := (float64(sentEnvelope.Route.Current) * 100.0) / float64(len(sentEnvelope.Route.Actors))
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
				ActorName:     "actor1",
				HappyEndQueue: "happy-end",
				ErrorEndQueue: "error-end",
			},
			inputActors:      []string{"actor1", "actor2", "actor3"},
			expectedQueues:   []string{"asya-actor2"},
			shouldRouteToEnd: false,
		},
		{
			name:          "SQS - route to next actor",
			transportType: "sqs",
			config: &config.Config{
				TransportType: "sqs",
				SQSBaseURL:    "https://sqs.us-east-1.amazonaws.com/123",
				ActorName:     "processor",
				HappyEndQueue: "happy-end",
				ErrorEndQueue: "error-end",
			},
			inputActors:      []string{"processor", "validator"},
			expectedQueues:   []string{"asya-validator"},
			shouldRouteToEnd: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Setup Unix socket server to mock runtime
			tempDir := t.TempDir()
			socketPath := tempDir + "/test.sock"

			listener, err := net.Listen("unix", socketPath)
			if err != nil {
				t.Fatalf("Failed to create socket: %v", err)
			}
			defer func() { _ = listener.Close() }()

			// Start mock runtime server
			go func() {
				conn, err := listener.Accept()
				if err != nil {
					return
				}
				defer func() { _ = conn.Close() }()

				// Receive request
				_, err = runtime.RecvSocketData(conn)
				if err != nil {
					return
				}

				// Send mock response with incremented current (runtime responsibility)
				responses := []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "processed"}`),
						Route: envelopes.Route{
							Actors:  tt.inputActors,
							Current: 1, // Runtime increments current in payload mode
						},
					},
				}

				data, _ := json.Marshal(responses)
				_ = runtime.SendSocketData(conn, data)
			}()

			// Setup test components
			mockTransport := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           tt.config,
				transport:     mockTransport,
				runtimeClient: runtimeClient,
				actorName:     tt.config.ActorName,
				happyEndQueue: tt.config.HappyEndQueue,
				errorEndQueue: tt.config.ErrorEndQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			// Create test envelope
			inputEnvelope := envelopes.Envelope{
				ID: "test-123",
				Route: envelopes.Route{
					Actors:  tt.inputActors,
					Current: 0,
				},
				Payload: json.RawMessage(`{"input": "test"}`),
			}
			msgBody, err := json.Marshal(inputEnvelope)
			if err != nil {
				t.Fatalf("Failed to marshal test envelope: %v", err)
			}

			queueMsg := transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			}

			// Process message
			ctx := context.Background()
			err = router.ProcessEnvelope(ctx, queueMsg)
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
					t.Errorf("Envelope %d sent to queue %q, expected %q",
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
				ActorName:     "test-actor",
				HappyEndQueue: "happy-end",
				ErrorEndQueue: "error-end",
				GatewayURL:    tt.gatewayURL,
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

			if router.happyEndQueue != testQueueHappyEnd {
				t.Errorf("Expected happyEndQueue to be %q, got %q", testQueueHappyEnd, router.happyEndQueue)
			}

			if router.errorEndQueue != testQueueErrorEnd {
				t.Errorf("Expected errorEndQueue to be %q, got %q", testQueueErrorEnd, router.errorEndQueue)
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

func TestRouter_SendToHappyQueue(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		actorName:     cfg.ActorName,
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	envelope := envelopes.Envelope{
		ID: "test-envelope-123",
		Route: envelopes.Route{
			Actors:  []string{"actor1", "actor2"},
			Current: 1,
		},
		Payload: json.RawMessage(`{"result": "success"}`),
	}

	ctx := context.Background()
	err := router.sendToHappyQueue(ctx, envelope)
	if err != nil {
		t.Fatalf("sendToHappyQueue failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-"+testQueueHappyEnd {
		t.Errorf("Envelope sent to queue %q, expected %q", mockTransport.sentMessages[0].queue, "asya-"+testQueueHappyEnd)
	}

	var sentEnvelope envelopes.Envelope
	err = json.Unmarshal(mockTransport.sentMessages[0].body, &sentEnvelope)
	if err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	if sentEnvelope.ID != "test-envelope-123" {
		t.Errorf("Expected envelope ID 'test-envelope-123', got %q", sentEnvelope.ID)
	}
}

func TestRouter_SendToErrorQueue(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		actorName:     cfg.ActorName,
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	originalEnvelope := envelopes.Envelope{
		ID: "test-envelope-456",
		Route: envelopes.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"data": "test"}`),
	}

	originalBody, _ := json.Marshal(originalEnvelope)

	ctx := context.Background()
	err := router.sendToErrorQueue(ctx, originalBody, "Runtime processing failed")
	if err != nil {
		t.Fatalf("sendToErrorQueue failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-"+testQueueErrorEnd {
		t.Errorf("Envelope sent to queue %q, expected %q", mockTransport.sentMessages[0].queue, "asya-"+testQueueErrorEnd)
	}

	var errorMsg map[string]any
	err = json.Unmarshal(mockTransport.sentMessages[0].body, &errorMsg)
	if err != nil {
		t.Fatalf("Failed to unmarshal sent error message: %v", err)
	}

	if errorMsg["id"] != "test-envelope-456" {
		t.Errorf("Expected error message ID 'test-envelope-456', got %v", errorMsg["id"])
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
		t.Error("Expected route field in error envelope")
	}
}

func TestRouter_SendToErrorQueue_WithInvalidOriginalMessage(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		actorName:     cfg.ActorName,
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	invalidJSON := []byte(`{invalid json`)

	ctx := context.Background()
	err := router.sendToErrorQueue(ctx, invalidJSON, "Parse error")
	if err != nil {
		t.Fatalf("sendToErrorQueue failed: %v", err)
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
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		TransportType: "rabbitmq",
	}

	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	socketPath := fmt.Sprintf("/tmp/test-router-run-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		runtimeClient: runtimeClient,
		actorName:     cfg.ActorName,
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	ctx, cancel := context.WithCancel(context.Background())

	cancel()

	err = router.Run(ctx)
	if err != context.Canceled {
		t.Errorf("Expected context.Canceled error, got: %v", err)
	}
}

func TestRouter_ProcessMessage_ParseError(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		actorName:     cfg.ActorName,
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	invalidJSON := []byte(`{invalid json`)
	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: invalidJSON,
	}

	ctx := context.Background()
	err := router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage should not return error (sends to error queue): %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to error queue, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-"+testQueueErrorEnd {
		t.Errorf("Envelope sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-"+testQueueErrorEnd)
	}
}

func TestRouter_ProcessMessage_MissingEnvelopeID(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		TransportType: "rabbitmq",
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:           cfg,
		transport:     mockTransport,
		actorName:     cfg.ActorName,
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	envelopeWithoutID := []byte(`{"route": {"actors": ["test-actor"], "current": 0}, "payload": {"test": "data"}}`)
	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: envelopeWithoutID,
	}

	ctx := context.Background()
	err := router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage should not return error (sends to error queue): %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to error queue, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-"+testQueueErrorEnd {
		t.Errorf("Envelope sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-"+testQueueErrorEnd)
	}

	var errorEnvelope map[string]interface{}
	if err := json.Unmarshal(mockTransport.sentMessages[0].body, &errorEnvelope); err != nil {
		t.Fatalf("Failed to parse error envelope: %v", err)
	}

	// Error should be inside payload (nested format)
	payload, ok := errorEnvelope["payload"].(map[string]interface{})
	if !ok {
		t.Fatalf("Expected payload to be a map, got %T", errorEnvelope["payload"])
	}

	if errorMsg, ok := payload["error"].(string); !ok || !strings.Contains(errorMsg, "missing required 'id' field") {
		t.Errorf("Error message should contain 'missing required 'id' field', got: %v", payload["error"])
	}
}

func TestRouter_ProcessMessage_EmptyResponse(t *testing.T) {
	socketPath := fmt.Sprintf("/tmp/test-empty-response-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		emptyResponse := []runtime.RuntimeResponse{}
		data, _ := json.Marshal(emptyResponse)
		_ = runtime.SendSocketData(conn, data)
	}()

	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	inputEnvelope := envelopes.Envelope{
		ID: "test-123",
		Route: envelopes.Route{
			Actors:  []string{"test-actor"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to happy-end, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-"+testQueueHappyEnd {
		t.Errorf("Envelope sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-"+testQueueHappyEnd)
	}
}

func TestRouter_ProcessMessage_EndActor(t *testing.T) {
	socketPath := fmt.Sprintf("/tmp/test-end-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		responses := []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"status": "logged"}`),
				Route: envelopes.Route{
					Actors:  []string{"happy-end"},
					Current: 0,
				},
			},
		}
		data, _ := json.Marshal(responses)
		_ = runtime.SendSocketData(conn, data)
	}()

	cfg := &config.Config{
		ActorName:     "happy-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	inputEnvelope := envelopes.Envelope{
		ID: "test-123",
		Route: envelopes.Route{
			Actors:  []string{"happy-end"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"result": "success"}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
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
		route envelopes.Route
		desc  string
	}{
		{
			name: "current points to wrong actor",
			route: envelopes.Route{
				Actors:  []string{"test-echo"},
				Current: 0,
			},
			desc: "Route points to test-echo but end actor is happy-end",
		},
		{
			name: "current out of bounds",
			route: envelopes.Route{
				Actors:  []string{"test-echo"},
				Current: 5,
			},
			desc: "Route current index is out of bounds",
		},
		{
			name: "empty route",
			route: envelopes.Route{
				Actors:  []string{},
				Current: 0,
			},
			desc: "Route has no actors",
		},
		{
			name: "multi-actor route pointing elsewhere",
			route: envelopes.Route{
				Actors:  []string{"actor1", "actor2", "actor3"},
				Current: 1,
			},
			desc: "Route points to actor2 but end actor is happy-end",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			socketPath := fmt.Sprintf("/tmp/test-end-invalid-%d.sock", time.Now().UnixNano())
			defer func() { _ = os.Remove(socketPath) }()

			listener, err := net.Listen("unix", socketPath)
			if err != nil {
				t.Fatalf("Failed to create socket: %v", err)
			}
			defer func() { _ = listener.Close() }()

			go func() {
				conn, err := listener.Accept()
				if err != nil {
					return
				}
				defer func() { _ = conn.Close() }()

				_, err = runtime.RecvSocketData(conn)
				if err != nil {
					return
				}

				responses := []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"status": "processed"}`),
					},
				}
				data, _ := json.Marshal(responses)
				_ = runtime.SendSocketData(conn, data)
			}()

			cfg := &config.Config{
				ActorName:     "happy-end",
				HappyEndQueue: "happy-end",
				ErrorEndQueue: "error-end",
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
				happyEndQueue: cfg.HappyEndQueue,
				errorEndQueue: cfg.ErrorEndQueue,
				metrics:       m,
			}

			inputEnvelope := envelopes.Envelope{
				ID:      "test-invalid-route",
				Route:   tt.route,
				Payload: json.RawMessage(`{"data": "test"}`),
			}
			msgBody, _ := json.Marshal(inputEnvelope)

			queueMsg := transport.QueueMessage{
				ID:   "msg-1",
				Body: msgBody,
			}

			ctx := context.Background()
			err = router.ProcessEnvelope(ctx, queueMsg)
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

	socketPath := fmt.Sprintf("/tmp/test-end-gateway-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		responses := []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"result": {"value": 42}, "s3_info": {"s3_uri": "s3://test/result"}}`),
			},
		}
		data, _ := json.Marshal(responses)
		_ = runtime.SendSocketData(conn, data)
	}()

	cfg := &config.Config{
		ActorName:     "happy-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		TransportType: "rabbitmq",
		IsEndActor:    true,
		GatewayURL:    mockServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputEnvelope := envelopes.Envelope{
		ID: "test-gateway-report",
		Route: envelopes.Route{
			Actors:  []string{"actor1", "actor2"},
			Current: 1,
		},
		Payload: json.RawMessage(`{"data": "test"}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 0 {
		t.Errorf("End actor should not send any messages, got %d", len(mockTransport.sentMessages))
	}

	expectedPath := "/envelopes/test-gateway-report/final"
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
	socketPath := fmt.Sprintf("/tmp/test-end-error-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		_ = conn.Close()
	}()

	cfg := &config.Config{
		ActorName:     "error-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	inputEnvelope := envelopes.Envelope{
		ID: "test-end-error",
		Route: envelopes.Route{
			Actors:  []string{"some-actor"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"error": "failed"}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
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
	socketPath := fmt.Sprintf("/tmp/test-end-no-increment-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		// Runtime tries to return a route with incremented current
		responses := []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"status": "logged"}`),
				Route: envelopes.Route{
					Actors:  []string{"actor1", "actor2", "happy-end"},
					Current: 3, // Try to increment current
				},
			},
		}
		data, _ := json.Marshal(responses)
		_ = runtime.SendSocketData(conn, data)
	}()

	cfg := &config.Config{
		ActorName:     "happy-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	inputEnvelope := envelopes.Envelope{
		ID: "test-no-increment",
		Route: envelopes.Route{
			Actors:  []string{"actor1", "actor2", "happy-end"},
			Current: 2, // Current points to happy-end
		},
		Payload: json.RawMessage(`{"result": "success"}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// End actors must NOT send any messages (no routing, no increment)
	if len(mockTransport.sentMessages) != 0 {
		t.Errorf("End actor should not send any messages (no routing), got %d messages", len(mockTransport.sentMessages))
	}
}

func TestRouter_ProcessMessage_RuntimeError(t *testing.T) {
	socketPath := fmt.Sprintf("/tmp/test-runtime-error-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		_ = conn.Close()
	}()

	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	inputEnvelope := envelopes.Envelope{
		ID: "test-123",
		Route: envelopes.Route{
			Actors:  []string{"test-actor"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage should not return error (sends to error queue): %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to error queue, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-"+testQueueErrorEnd {
		t.Errorf("Envelope sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-"+testQueueErrorEnd)
	}
}

func TestRouter_ProcessMessage_ErrorResponse(t *testing.T) {
	socketPath := fmt.Sprintf("/tmp/test-error-response-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		errorResponse := []runtime.RuntimeResponse{
			{
				Error: "Processing failed",
				Details: runtime.ErrorDetails{
					Type:    "validation_error",
					Message: "Invalid input",
				},
			},
		}
		data, _ := json.Marshal(errorResponse)
		_ = runtime.SendSocketData(conn, data)
	}()

	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	inputEnvelope := envelopes.Envelope{
		ID: "test-123",
		Route: envelopes.Route{
			Actors:  []string{"test-actor"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"input": "test"}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent to error queue, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-"+testQueueErrorEnd {
		t.Errorf("Envelope sent to %q, expected %q", mockTransport.sentMessages[0].queue, "asya-"+testQueueErrorEnd)
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

func TestRouter_ReportFinalStatus_HappyEnd(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	cfg := &config.Config{
		ActorName:     "happy-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		GatewayURL:    mockServer.URL,
	}

	mockTransport := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, nil, m)

	response := runtime.RuntimeResponse{
		Payload: json.RawMessage(`{}`),
	}

	ctx := context.Background()
	err := router.reportFinalStatus(ctx, "test-envelope-123", response.Payload, 100*time.Millisecond)
	if err != nil {
		t.Fatalf("reportFinalStatus failed: %v", err)
	}

	expectedPath := "/envelopes/test-envelope-123/final"
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

	if payload["id"] != "test-envelope-123" {
		t.Errorf("Expected id 'test-envelope-123', got %v", payload["id"])
	}

	if payload["progress"] != 1.0 {
		t.Errorf("Expected progress 1.0, got %v", payload["progress"])
	}
}

func TestRouter_ReportFinalStatus_ErrorEnd(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	cfg := &config.Config{
		ActorName:     "error-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		GatewayURL:    mockServer.URL,
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

	expectedPath := "/envelopes/test-error-456/final"
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

func TestRouter_ReportFinalStatusWithEnvelope_ErrorEnd_ExtractsErrorDetails(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	socketPath := fmt.Sprintf("/tmp/test-error-details-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		responses := []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"status": "processed"}`),
			},
		}
		data, _ := json.Marshal(responses)
		_ = runtime.SendSocketData(conn, data)
	}()

	cfg := &config.Config{
		ActorName:     "error-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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

	inputEnvelope := envelopes.Envelope{
		ID: "test-error-details-789",
		Route: envelopes.Route{
			Actors:  []string{"actor1", "actor2"},
			Current: 1,
		},
		Payload: json.RawMessage(errorPayloadBytes),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessEnvelope failed: %v", err)
	}

	expectedPath := "/envelopes/test-error-details-789/final"
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

func TestRouter_ReportFinalStatusWithEnvelope_ErrorEnd_NoErrorDetails(t *testing.T) {
	mockServer := &mockHTTPServer{responses: make(map[string]mockHTTPResponse)}
	mockServer.Start(t)
	defer mockServer.Close()

	socketPath := fmt.Sprintf("/tmp/test-no-error-details-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		responses := []runtime.RuntimeResponse{
			{
				Payload: json.RawMessage(`{"status": "processed"}`),
			},
		}
		data, _ := json.Marshal(responses)
		_ = runtime.SendSocketData(conn, data)
	}()

	cfg := &config.Config{
		ActorName:     "error-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		TransportType: "rabbitmq",
		IsEndActor:    true,
		GatewayURL:    mockServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputEnvelope := envelopes.Envelope{
		ID: "test-no-error-details",
		Route: envelopes.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"some": "data"}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessEnvelope failed: %v", err)
	}

	expectedPath := "/envelopes/test-no-error-details/final"
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
		ActorName:     "happy-end",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		GatewayURL:    "",
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
	socketPath := fmt.Sprintf("/tmp/test-fanout-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		fanoutResponses := []runtime.RuntimeResponse{
			{
				Route:   envelopes.Route{Actors: []string{"test-actor", "next-actor"}, Current: 1},
				Payload: json.RawMessage(`{"index": 0, "message": "Fan-out message 0"}`),
			},
			{
				Route:   envelopes.Route{Actors: []string{"test-actor", "next-actor"}, Current: 1},
				Payload: json.RawMessage(`{"index": 1, "message": "Fan-out message 1"}`),
			},
			{
				Route:   envelopes.Route{Actors: []string{"test-actor", "next-actor"}, Current: 1},
				Payload: json.RawMessage(`{"index": 2, "message": "Fan-out message 2"}`),
			},
		}
		data, _ := json.Marshal(fanoutResponses)
		_ = runtime.SendSocketData(conn, data)
	}()

	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		happyEndQueue: cfg.HappyEndQueue,
		errorEndQueue: cfg.ErrorEndQueue,
		metrics:       m,
	}

	inputEnvelope := envelopes.Envelope{
		ID: "test-fanout-123",
		Route: envelopes.Route{
			Actors:  []string{"test-actor", "next-actor"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"count": 3}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if len(mockTransport.sentMessages) != 3 {
		t.Fatalf("Expected 3 fan-out messages, got %d", len(mockTransport.sentMessages))
	}

	for i := 0; i < 3; i++ {
		msg := mockTransport.sentMessages[i]

		if msg.queue != "asya-next-actor" {
			t.Errorf("Message %d sent to %q, expected %q", i, msg.queue, "asya-next-actor")
		}

		var envelope envelopes.Envelope
		if err := json.Unmarshal(msg.body, &envelope); err != nil {
			t.Fatalf("Failed to unmarshal message %d: %v", i, err)
		}

		// First item keeps original ID, subsequent items get suffix
		var expectedID string
		if i == 0 {
			expectedID = "test-fanout-123"
		} else {
			expectedID = fmt.Sprintf("test-fanout-123-%d", i)
		}
		if envelope.ID != expectedID {
			t.Errorf("Message %d has ID %q, expected %q", i, envelope.ID, expectedID)
		}

		// First item has no parent_id, subsequent items have parent_id set to original ID
		if i == 0 {
			if envelope.ParentID != nil {
				t.Errorf("Message %d should have nil parent_id, got %q", i, *envelope.ParentID)
			}
		} else {
			if envelope.ParentID == nil {
				t.Errorf("Message %d should have parent_id set, got nil", i)
			} else if *envelope.ParentID != "test-fanout-123" {
				t.Errorf("Message %d has parent_id %q, expected %q", i, *envelope.ParentID, "test-fanout-123")
			}
		}

		if envelope.Route.Current != 1 {
			t.Errorf("Message %d route.current = %d, expected 1", i, envelope.Route.Current)
		}

		var payload map[string]interface{}
		if err := json.Unmarshal(envelope.Payload, &payload); err != nil {
			t.Fatalf("Failed to unmarshal payload %d: %v", i, err)
		}

		if int(payload["index"].(float64)) != i {
			t.Errorf("Message %d has index %v, expected %d", i, payload["index"], i)
		}
	}
}

func TestRouter_ProcessMessage_FanOut_CreatesGatewayEnvelopes(t *testing.T) {
	socketPath := fmt.Sprintf("/tmp/test-fanout-gateway-%d.sock", time.Now().UnixNano())
	defer func() { _ = os.Remove(socketPath) }()

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		_, err = runtime.RecvSocketData(conn)
		if err != nil {
			return
		}

		fanoutResponses := []runtime.RuntimeResponse{
			{
				Route:   envelopes.Route{Actors: []string{"test-actor", "next-actor"}, Current: 0},
				Payload: json.RawMessage(`{"index": 0}`),
			},
			{
				Route:   envelopes.Route{Actors: []string{"test-actor", "next-actor"}, Current: 0},
				Payload: json.RawMessage(`{"index": 1}`),
			},
			{
				Route:   envelopes.Route{Actors: []string{"test-actor", "next-actor"}, Current: 0},
				Payload: json.RawMessage(`{"index": 2}`),
			},
		}
		data, _ := json.Marshal(fanoutResponses)
		_ = runtime.SendSocketData(conn, data)
	}()

	// Track envelope creation calls
	var createdEnvelopes []struct {
		id       string
		parentID string
		actors   []string
		current  int
	}
	createEnvelopeCalled := 0

	// Mock HTTP server for gateway
	gatewayServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/envelopes" && r.Method == http.MethodPost {
			createEnvelopeCalled++
			var req struct {
				ID       string   `json:"id"`
				ParentID string   `json:"parent_id"`
				Actors   []string `json:"actors"`
				Current  int      `json:"current"`
			}
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Errorf("Failed to decode envelope create request: %v", err)
			}
			createdEnvelopes = append(createdEnvelopes, struct {
				id       string
				parentID string
				actors   []string
				current  int
			}{req.ID, req.ParentID, req.Actors, req.Current})
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(map[string]string{"status": "created"})
		} else {
			w.WriteHeader(http.StatusOK)
		}
	}))
	defer gatewayServer.Close()

	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		happyEndQueue:    cfg.HappyEndQueue,
		errorEndQueue:    cfg.ErrorEndQueue,
		gatewayURL:       cfg.GatewayURL,
		progressReporter: progressReporter,
		metrics:          m,
	}

	inputEnvelope := envelopes.Envelope{
		ID: "test-fanout-456",
		Route: envelopes.Route{
			Actors:  []string{"test-actor", "next-actor"},
			Current: 0,
		},
		Payload: json.RawMessage(`{"count": 3}`),
	}
	msgBody, _ := json.Marshal(inputEnvelope)

	queueMsg := transport.QueueMessage{
		ID:   "msg-1",
		Body: msgBody,
	}

	ctx := context.Background()
	err = router.ProcessEnvelope(ctx, queueMsg)
	if err != nil {
		t.Fatalf("ProcessEnvelope failed: %v", err)
	}

	// Verify envelope creation was called for fanout children (indices 1 and 2)
	expectedCalls := 2
	if createEnvelopeCalled != expectedCalls {
		t.Errorf("CreateEnvelope called %d times, expected %d", createEnvelopeCalled, expectedCalls)
	}

	// Verify created envelopes
	if len(createdEnvelopes) != 2 {
		t.Fatalf("Expected 2 created envelopes, got %d", len(createdEnvelopes))
	}

	// First fanout child (index 1)
	if createdEnvelopes[0].id != "test-fanout-456-1" {
		t.Errorf("First envelope ID = %q, want test-fanout-456-1", createdEnvelopes[0].id)
	}
	if createdEnvelopes[0].parentID != "test-fanout-456" {
		t.Errorf("First envelope ParentID = %q, want test-fanout-456", createdEnvelopes[0].parentID)
	}

	// Second fanout child (index 2)
	if createdEnvelopes[1].id != "test-fanout-456-2" {
		t.Errorf("Second envelope ID = %q, want test-fanout-456-2", createdEnvelopes[1].id)
	}
	if createdEnvelopes[1].parentID != "test-fanout-456" {
		t.Errorf("Second envelope ParentID = %q, want test-fanout-456", createdEnvelopes[1].parentID)
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
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
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
