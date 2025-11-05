package router

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
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

func (m *mockTransport) Close() error {
	return nil
}

func TestRouter_RouteValidation(t *testing.T) {
	tests := []struct {
		name                 string
		sidecarQueue         string
		inputRoute           messages.Route
		expectedWarnContains string
		shouldWarn           bool
	}{
		{
			name:         "route matches sidecar queue - no warning",
			sidecarQueue: "test-queue",
			inputRoute: messages.Route{
				Steps:   []string{"test-queue", "next-queue"},
				Current: 0,
			},
			shouldWarn: false,
		},
		{
			name:         "route does not match sidecar queue - warning logged",
			sidecarQueue: "test-queue",
			inputRoute: messages.Route{
				Steps:   []string{"wrong-queue", "next-queue"},
				Current: 0,
			},
			expectedWarnContains: "Runtime outputed route with current step not matching the actor's queue name",
			shouldWarn:           true,
		},
		{
			name:         "route current index out of sync - warning logged",
			sidecarQueue: "test-queue",
			inputRoute: messages.Route{
				Steps:   []string{"test-queue", "next-queue"},
				Current: 1, // Should be 0 for test-queue
			},
			expectedWarnContains: "Runtime outputed route with current step not matching the actor's queue name",
			shouldWarn:           true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Capture log output
			var logBuf bytes.Buffer
			logger := slog.New(slog.NewTextHandler(&logBuf, &slog.HandlerOptions{
				Level: slog.LevelWarn,
			}))
			slog.SetDefault(logger)

			// Setup Unix socket server to mock runtime
			tempDir := t.TempDir()
			socketPath := tempDir + "/test.sock"
			defer os.Remove(socketPath)

			listener, err := net.Listen("unix", socketPath)
			if err != nil {
				t.Fatalf("Failed to create socket: %v", err)
			}
			defer listener.Close()

			// Start mock runtime server
			go func() {
				conn, err := listener.Accept()
				if err != nil {
					return
				}
				defer conn.Close()

				// Receive request
				_, err = runtime.RecvSocketData(conn)
				if err != nil {
					return
				}

				// Send mock response
				responses := []runtime.RuntimeResponse{
					{
						Payload: json.RawMessage(`{"result": "processed"}`),
						Route:   tt.inputRoute,
					},
				}
				data, _ := json.Marshal(responses)
				runtime.SendSocketData(conn, data)
			}()

			// Setup test components
			cfg := &config.Config{
				QueueName:     tt.sidecarQueue,
				HappyEndQueue: "happy-end",
				ErrorEndQueue: "error-end",
				ActorName:     "test-actor",
			}

			mockTransport := &mockTransport{}
			runtimeClient := runtime.NewClient(socketPath, 2*time.Second)

			router := &Router{
				cfg:           cfg,
				transport:     mockTransport,
				runtimeClient: runtimeClient,
				sidecarQueue:  cfg.QueueName,
				happyEndQueue: cfg.HappyEndQueue,
				errorEndQueue: cfg.ErrorEndQueue,
				metrics:       metrics.NewMetrics("test", []config.CustomMetricConfig{}),
			}

			// Create test message
			inputMsg := messages.Message{
				JobID:   "test-job-123",
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

			// Process message
			ctx := context.Background()
			err = router.ProcessMessage(ctx, queueMsg)
			if err != nil {
				t.Fatalf("ProcessMessage failed: %v", err)
			}

			// Check log output
			logOutput := logBuf.String()
			if tt.shouldWarn {
				if !strings.Contains(logOutput, tt.expectedWarnContains) {
					t.Errorf("Expected warning containing %q, got log output:\n%s",
						tt.expectedWarnContains, logOutput)
				}
			} else {
				if strings.Contains(logOutput, "Runtime outputed route with current step not matching") {
					t.Errorf("Unexpected warning in log output:\n%s", logOutput)
				}
			}
		})
	}
}
