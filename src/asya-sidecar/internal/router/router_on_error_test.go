package router

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
)

func TestRouter_RouteToFlowErrorHandler(t *testing.T) {
	tests := []struct {
		name                 string
		msg                  *envelopes.Envelope
		onError              string
		response             runtime.RuntimeResponse
		expectedQueue        string
		expectedCurr         string
		expectedNext         []string
		expectedErrorMsg     string
		expectedErrorType    string
		expectedErrorMRO     []string
		expectOnErrorCleared bool
	}{
		{
			name: "routes to flow error handler and clears _on_error header",
			msg: &envelopes.Envelope{
				ID: "msg-001",
				Route: envelopes.Route{
					Prev: []string{},
					Curr: "actor-a",
					Next: []string{"actor-b", "actor-c"},
				},
				Headers: map[string]interface{}{
					"_on_error": "except-dispatch-router",
					"trace_id":  "abc-123",
				},
				Payload: json.RawMessage(`{"input": "data"}`),
				Status: &envelopes.Status{
					Phase:     envelopes.PhaseProcessing,
					Actor:     "actor-a",
					CreatedAt: "2025-01-01T00:00:00Z",
					UpdatedAt: "2025-01-01T00:00:01Z",
				},
			},
			onError: "except-dispatch-router",
			response: runtime.RuntimeResponse{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Message:   "value cannot be negative",
					Type:      "ValueError",
					Traceback: "Traceback (most recent call last):\n  File ...",
					MRO:       []string{"ValueError", "Exception", "BaseException"},
				},
			},
			expectedQueue:        "asya-default-except-dispatch-router",
			expectedCurr:         "actor-a",
			expectedNext:         []string{"except-dispatch-router"},
			expectedErrorMsg:     "value cannot be negative",
			expectedErrorType:    "ValueError",
			expectedErrorMRO:     []string{"ValueError", "Exception", "BaseException"},
			expectOnErrorCleared: true,
		},
		{
			name: "preserves original payload in routed message",
			msg: &envelopes.Envelope{
				ID: "msg-002",
				Route: envelopes.Route{
					Prev: []string{},
					Curr: "validate",
					Next: []string{"transform"},
				},
				Headers: map[string]interface{}{
					"_on_error": "error-handler",
				},
				Payload: json.RawMessage(`{"order_id": 42, "items": [1, 2, 3]}`),
			},
			onError: "error-handler",
			response: runtime.RuntimeResponse{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Message: "validation failed",
					Type:    "RuntimeError",
				},
			},
			expectedQueue:        "asya-default-error-handler",
			expectedCurr:         "validate",
			expectedNext:         []string{"error-handler"},
			expectedErrorMsg:     "validation failed",
			expectedErrorType:    "RuntimeError",
			expectOnErrorCleared: true,
		},
		{
			name: "handles message without prior status",
			msg: &envelopes.Envelope{
				ID: "msg-003",
				Route: envelopes.Route{
					Prev: []string{},
					Curr: "process",
					Next: []string{},
				},
				Headers: map[string]interface{}{
					"_on_error": "fallback-handler",
				},
				Payload: json.RawMessage(`{"data": "test"}`),
			},
			onError: "fallback-handler",
			response: runtime.RuntimeResponse{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Message: "unexpected error",
					Type:    "Exception",
				},
			},
			expectedQueue:        "asya-default-fallback-handler",
			expectedCurr:         "process",
			expectedNext:         []string{"fallback-handler"},
			expectedErrorMsg:     "unexpected error",
			expectedErrorType:    "Exception",
			expectOnErrorCleared: true,
		},
		{
			name: "replaces next actors with error handler",
			msg: &envelopes.Envelope{
				ID: "msg-004",
				Route: envelopes.Route{
					Prev: []string{"step1"},
					Curr: "step2",
					Next: []string{"step3", "step4"},
				},
				Headers: map[string]interface{}{
					"_on_error": "err-dispatch",
				},
				Payload: json.RawMessage(`{"value": 100}`),
				Status: &envelopes.Status{
					Phase:     envelopes.PhaseProcessing,
					Actor:     "step2",
					CreatedAt: "2025-06-01T12:00:00Z",
				},
			},
			onError: "err-dispatch",
			response: runtime.RuntimeResponse{
				Error: "processing_error",
				Details: runtime.ErrorDetails{
					Message: "step2 failed",
					Type:    "TypeError",
					MRO:     []string{"TypeError", "Exception", "BaseException"},
				},
			},
			expectedQueue:        "asya-default-err-dispatch",
			expectedCurr:         "step2",
			expectedNext:         []string{"err-dispatch"},
			expectedErrorMsg:     "step2 failed",
			expectedErrorType:    "TypeError",
			expectedErrorMRO:     []string{"TypeError", "Exception", "BaseException"},
			expectOnErrorCleared: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &config.Config{
				ActorName:     tt.msg.Route.Curr,
				Namespace:     "default",
				SinkQueue:     "x-sink",
				SumpQueue:     "x-sump",
				TransportType: "rabbitmq",
			}

			mt := &mockTransport{}
			m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

			router := &Router{
				cfg:       cfg,
				transport: mt,
				actorName: cfg.ActorName,
				sinkQueue: cfg.SinkQueue,
				sumpQueue: cfg.SumpQueue,
				metrics:   m,
			}

			ctx := context.Background()
			startTime := time.Now()
			err := router.routeToFlowErrorHandler(ctx, tt.msg, tt.onError, tt.response, startTime)
			if err != nil {
				t.Fatalf("routeToFlowErrorHandler returned error: %v", err)
			}

			// Verify exactly one message was sent
			if len(mt.sentMessages) != 1 {
				t.Fatalf("Expected 1 message sent, got %d", len(mt.sentMessages))
			}

			// Verify destination queue
			if mt.sentMessages[0].queue != tt.expectedQueue {
				t.Errorf("Message sent to queue %q, expected %q",
					mt.sentMessages[0].queue, tt.expectedQueue)
			}

			// Parse the sent message
			var sentMsg envelopes.Envelope
			if err := json.Unmarshal(mt.sentMessages[0].body, &sentMsg); err != nil {
				t.Fatalf("Failed to unmarshal sent message: %v", err)
			}

			// Verify route curr (unchanged - runtime shifts it)
			if sentMsg.Route.Curr != tt.expectedCurr {
				t.Errorf("Route curr = %q, expected %q", sentMsg.Route.Curr, tt.expectedCurr)
			}

			// Verify route next contains only the error handler
			if len(sentMsg.Route.Next) != len(tt.expectedNext) {
				t.Fatalf("Expected %d next actors in route, got %d: %v",
					len(tt.expectedNext), len(sentMsg.Route.Next), sentMsg.Route.Next)
			}
			for i, expected := range tt.expectedNext {
				if sentMsg.Route.Next[i] != expected {
					t.Errorf("Route next[%d] = %q, expected %q", i, sentMsg.Route.Next[i], expected)
				}
			}

			// Verify _on_error header is cleared
			if tt.expectOnErrorCleared {
				if _, exists := tt.msg.Headers["_on_error"]; exists {
					t.Error("Expected _on_error header to be cleared from message, but it still exists")
				}
			}

			// Verify status is set with error details
			if sentMsg.Status == nil {
				t.Fatal("Expected status to be set on sent message")
			}

			if sentMsg.Status.Phase != envelopes.PhaseFailed {
				t.Errorf("Expected status phase %q, got %q", envelopes.PhaseFailed, sentMsg.Status.Phase)
			}

			if sentMsg.Status.Error == nil {
				t.Fatal("Expected status.error to be set")
			}

			if sentMsg.Status.Error.Message != tt.expectedErrorMsg {
				t.Errorf("Expected status.error.message %q, got %q",
					tt.expectedErrorMsg, sentMsg.Status.Error.Message)
			}

			if sentMsg.Status.Error.Type != tt.expectedErrorType {
				t.Errorf("Expected status.error.type %q, got %q",
					tt.expectedErrorType, sentMsg.Status.Error.Type)
			}

			// Verify MRO if expected
			if tt.expectedErrorMRO != nil {
				if sentMsg.Status.Error.MRO == nil {
					t.Fatal("Expected status.error.mro to be set")
				}
				if len(sentMsg.Status.Error.MRO) != len(tt.expectedErrorMRO) {
					t.Fatalf("Expected %d MRO entries, got %d",
						len(tt.expectedErrorMRO), len(sentMsg.Status.Error.MRO))
				}
				for i, expected := range tt.expectedErrorMRO {
					if sentMsg.Status.Error.MRO[i] != expected {
						t.Errorf("MRO[%d] = %q, expected %q", i, sentMsg.Status.Error.MRO[i], expected)
					}
				}
			}

			// Verify original payload is preserved (compare JSON semantically)
			var expectedPayload, actualPayload interface{}
			if err := json.Unmarshal(tt.msg.Payload, &expectedPayload); err != nil {
				t.Fatalf("Failed to unmarshal expected payload: %v", err)
			}
			if err := json.Unmarshal(sentMsg.Payload, &actualPayload); err != nil {
				t.Fatalf("Failed to unmarshal actual payload: %v", err)
			}
			expectedBytes, _ := json.Marshal(expectedPayload)
			actualBytes, _ := json.Marshal(actualPayload)
			if string(expectedBytes) != string(actualBytes) {
				t.Errorf("Expected payload %s, got %s", string(expectedBytes), string(actualBytes))
			}
		})
	}
}

func TestRouter_HandleErrorResponse_WithOnErrorHeader(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "rabbitmq",
	}

	mt := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mt,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	// Build a message with _on_error header
	msg := &envelopes.Envelope{
		ID: "msg-with-on-error",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Headers: map[string]interface{}{
			"_on_error": "my-error-handler",
		},
		Payload: json.RawMessage(`{"key": "value"}`),
	}

	response := runtime.RuntimeResponse{
		Error: "processing_error",
		Details: runtime.ErrorDetails{
			Message: "something went wrong",
			Type:    "ValueError",
		},
	}

	ctx := context.Background()
	startTime := time.Now()
	err := router.handleErrorResponse(ctx, msg, response, startTime)
	if err != nil {
		t.Fatalf("handleErrorResponse returned error: %v", err)
	}

	// Should route to flow error handler, not x-sump
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-my-error-handler" {
		t.Errorf("Message sent to queue %q, expected %q",
			mt.sentMessages[0].queue, "asya-default-my-error-handler")
	}

	// Verify it did NOT go to x-sump
	for _, sent := range mt.sentMessages {
		if sent.queue == "asya-default-x-sump" {
			t.Error("Message should NOT be sent to x-sump when _on_error header is set")
		}
	}
}

func TestRouter_HandleErrorResponse_WithoutOnErrorHeader(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "rabbitmq",
	}

	mt := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mt,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	// Build a message WITHOUT _on_error header
	msg := &envelopes.Envelope{
		ID: "msg-no-on-error",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Payload: json.RawMessage(`{"key": "value"}`),
	}

	response := runtime.RuntimeResponse{
		Error: "processing_error",
		Details: runtime.ErrorDetails{
			Message: "something went wrong",
			Type:    "ValueError",
		},
	}

	ctx := context.Background()
	startTime := time.Now()
	err := router.handleErrorResponse(ctx, msg, response, startTime)
	if err != nil {
		t.Fatalf("handleErrorResponse returned error: %v", err)
	}

	// Should route to x-sump (backward compatible)
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-x-sump" {
		t.Errorf("Message sent to queue %q, expected %q",
			mt.sentMessages[0].queue, "asya-default-x-sump")
	}
}

func TestRouter_HandleErrorResponse_EmptyOnErrorHeader(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "rabbitmq",
	}

	mt := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mt,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	// Build a message with empty _on_error header
	msg := &envelopes.Envelope{
		ID: "msg-empty-on-error",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{},
		},
		Headers: map[string]interface{}{
			"_on_error": "",
		},
		Payload: json.RawMessage(`{"key": "value"}`),
	}

	response := runtime.RuntimeResponse{
		Error: "processing_error",
		Details: runtime.ErrorDetails{
			Message: "error occurred",
			Type:    "Exception",
		},
	}

	ctx := context.Background()
	startTime := time.Now()
	err := router.handleErrorResponse(ctx, msg, response, startTime)
	if err != nil {
		t.Fatalf("handleErrorResponse returned error: %v", err)
	}

	// Empty _on_error should fall through to x-sump
	if len(mt.sentMessages) != 1 {
		t.Fatalf("Expected 1 message sent, got %d", len(mt.sentMessages))
	}

	if mt.sentMessages[0].queue != "asya-default-x-sump" {
		t.Errorf("Message sent to queue %q, expected %q",
			mt.sentMessages[0].queue, "asya-default-x-sump")
	}
}

func TestRouter_RouteToFlowErrorHandler_PreservesCreatedAt(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "my-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "rabbitmq",
	}

	mt := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mt,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	originalCreatedAt := "2025-03-15T10:30:00Z"
	msg := &envelopes.Envelope{
		ID: "msg-created-at",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "my-actor",
			Next: []string{"next"},
		},
		Headers: map[string]interface{}{
			"_on_error": "handler",
		},
		Payload: json.RawMessage(`{}`),
		Status: &envelopes.Status{
			Phase:     envelopes.PhaseProcessing,
			Actor:     "my-actor",
			CreatedAt: originalCreatedAt,
			UpdatedAt: "2025-03-15T10:30:05Z",
		},
	}

	response := runtime.RuntimeResponse{
		Error: "processing_error",
		Details: runtime.ErrorDetails{
			Message: "test error",
			Type:    "TestError",
		},
	}

	ctx := context.Background()
	startTime := time.Now()
	err := router.routeToFlowErrorHandler(ctx, msg, "handler", response, startTime)
	if err != nil {
		t.Fatalf("routeToFlowErrorHandler returned error: %v", err)
	}

	var sentMsg envelopes.Envelope
	if err := json.Unmarshal(mt.sentMessages[0].body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	// Verify created_at is preserved from original status
	if sentMsg.Status.CreatedAt != originalCreatedAt {
		t.Errorf("Expected created_at %q to be preserved, got %q",
			originalCreatedAt, sentMsg.Status.CreatedAt)
	}
}

func TestRouter_RouteToFlowErrorHandler_SetsActorName(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "failing-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "rabbitmq",
	}

	mt := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mt,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	msg := &envelopes.Envelope{
		ID: "msg-actor-name",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "failing-actor",
			Next: []string{},
		},
		Headers: map[string]interface{}{
			"_on_error": "err-handler",
		},
		Payload: json.RawMessage(`{"data": 1}`),
	}

	response := runtime.RuntimeResponse{
		Error: "processing_error",
		Details: runtime.ErrorDetails{
			Message: "actor failed",
			Type:    "RuntimeError",
		},
	}

	ctx := context.Background()
	startTime := time.Now()
	err := router.routeToFlowErrorHandler(ctx, msg, "err-handler", response, startTime)
	if err != nil {
		t.Fatalf("routeToFlowErrorHandler returned error: %v", err)
	}

	var sentMsg envelopes.Envelope
	if err := json.Unmarshal(mt.sentMessages[0].body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	// The status actor should be set to the router's actor name (the failing actor)
	if sentMsg.Status.Actor != "failing-actor" {
		t.Errorf("Expected status.actor %q, got %q", "failing-actor", sentMsg.Status.Actor)
	}
}

func TestRouter_RouteToFlowErrorHandler_ErrorTraceback(t *testing.T) {
	cfg := &config.Config{
		ActorName:     "actor-x",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		TransportType: "rabbitmq",
	}

	mt := &mockTransport{}
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})

	router := &Router{
		cfg:       cfg,
		transport: mt,
		actorName: cfg.ActorName,
		sinkQueue: cfg.SinkQueue,
		sumpQueue: cfg.SumpQueue,
		metrics:   m,
	}

	traceback := "Traceback (most recent call last):\n  File \"handler.py\", line 10, in process\n    raise ValueError(\"bad input\")\nValueError: bad input"

	msg := &envelopes.Envelope{
		ID: "msg-traceback",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "actor-x",
			Next: []string{"actor-y"},
		},
		Headers: map[string]interface{}{
			"_on_error": "tb-handler",
		},
		Payload: json.RawMessage(`{}`),
	}

	response := runtime.RuntimeResponse{
		Error: "processing_error",
		Details: runtime.ErrorDetails{
			Message:   "bad input",
			Type:      "ValueError",
			Traceback: traceback,
			MRO:       []string{"ValueError", "Exception", "BaseException"},
		},
	}

	ctx := context.Background()
	startTime := time.Now()
	err := router.routeToFlowErrorHandler(ctx, msg, "tb-handler", response, startTime)
	if err != nil {
		t.Fatalf("routeToFlowErrorHandler returned error: %v", err)
	}

	var sentMsg envelopes.Envelope
	if err := json.Unmarshal(mt.sentMessages[0].body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	if sentMsg.Status.Error.Traceback != traceback {
		t.Errorf("Expected traceback to be preserved, got %q", sentMsg.Status.Error.Traceback)
	}

	if len(sentMsg.Status.Error.MRO) != 3 {
		t.Fatalf("Expected 3 MRO entries, got %d", len(sentMsg.Status.Error.MRO))
	}

	expectedMRO := []string{"ValueError", "Exception", "BaseException"}
	for i, expected := range expectedMRO {
		if sentMsg.Status.Error.MRO[i] != expected {
			t.Errorf("MRO[%d] = %q, expected %q", i, sentMsg.Status.Error.MRO[i], expected)
		}
	}
}
