package runtime

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
)

func TestClient_CallRuntime_Success(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test.sock"
	defer os.Remove(socketPath)

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer listener.Close()

	serverReady := make(chan bool, 1)
	serverDone := make(chan bool, 1)
	go func() {
		serverReady <- true
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer conn.Close()

		_, err = RecvSocketData(conn)
		if err != nil {
			return
		}

		// Python runtime always returns array
		responses := []RuntimeResponse{
			{
				Payload: json.RawMessage(`{"processed": true}`),
				Route: messages.Route{
					Steps:   []string{"test", "next"},
					Current: 1,
				},
			},
		}
		data, _ := json.Marshal(responses)
		SendSocketData(conn, data)
		serverDone <- true
	}()

	<-serverReady

	client := NewClient(socketPath, 2*time.Second)
	messageData := []byte(`{"route":{"steps":["test","next"],"current":0},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}

	if len(results) != 1 {
		t.Errorf("Expected 1 result, got %d", len(results))
	}

	if results[0].IsError() {
		t.Errorf("Expected success, got error: %s", results[0].Error)
	}

	select {
	case <-serverDone:
	case <-time.After(1 * time.Second):
		t.Error("Server didn't complete in time")
	}
}

func TestClient_CallRuntime_Error(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-error.sock"
	defer os.Remove(socketPath)

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer listener.Close()

	go func() {
		conn, _ := listener.Accept()
		defer conn.Close()

		RecvSocketData(conn)

		// Python runtime returns array with error
		responses := []RuntimeResponse{
			{
				Error: "processing_error",
				Details: ErrorDetails{
					Message:   "Test error message",
					Type:      "ValueError",
					Traceback: "ValueError: Test error message\n",
				},
			},
		}
		data, _ := json.Marshal(responses)
		SendSocketData(conn, data)
	}()

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"steps":["test"],"current":0},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}

	if len(results) != 1 {
		t.Errorf("Expected 1 result, got %d", len(results))
	}

	if !results[0].IsError() {
		t.Error("Expected error response")
	}

	if results[0].Error != "processing_error" {
		t.Errorf("Expected processing_error, got %s", results[0].Error)
	}
}

func TestClient_CallRuntime_Timeout(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-timeout.sock"
	defer os.Remove(socketPath)

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer listener.Close()

	go func() {
		conn, _ := listener.Accept()
		defer conn.Close()
		time.Sleep(2 * time.Second)
	}()

	client := NewClient(socketPath, 100*time.Millisecond)
	messageData := []byte(`{"route":{"steps":["test"],"current":0},"payload":{"data":"test"}}`)

	_, err = client.CallRuntime(context.Background(), messageData)
	if err == nil {
		t.Error("Expected timeout error but got nil")
	}
}

func TestClient_CallRuntime_FanOut(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-fanout.sock"
	defer os.Remove(socketPath)

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer listener.Close()

	go func() {
		conn, _ := listener.Accept()
		defer conn.Close()

		RecvSocketData(conn)

		// Python runtime returns array with multiple responses
		responses := []RuntimeResponse{
			{
				Payload: json.RawMessage(`{"id": 1}`),
				Route: messages.Route{
					Steps:   []string{"fan"},
					Current: 1,
				},
			},
			{
				Payload: json.RawMessage(`{"id": 2}`),
				Route: messages.Route{
					Steps:   []string{"fan"},
					Current: 1,
				},
			},
			{
				Payload: json.RawMessage(`{"id": 3}`),
				Route: messages.Route{
					Steps:   []string{"fan"},
					Current: 1,
				},
			},
		}
		data, _ := json.Marshal(responses)
		SendSocketData(conn, data)
	}()

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"steps":["fan"],"current":0},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}

	if len(results) != 3 {
		t.Errorf("Expected 3 results for fan-out, got %d", len(results))
	}

	for i, result := range results {
		if result.IsError() {
			t.Errorf("Result %d should not be an error", i)
		}
	}
}

func TestClient_CallRuntime_EmptyArray(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-empty-test.sock"
	defer os.Remove(socketPath)

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer listener.Close()

	go func() {
		conn, _ := listener.Accept()
		defer conn.Close()

		RecvSocketData(conn)

		// Python runtime returns empty array
		responses := []RuntimeResponse{}
		data, _ := json.Marshal(responses)
		SendSocketData(conn, data)
	}()

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"steps":["test"],"current":0},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}

	if len(results) != 0 {
		t.Errorf("Expected empty results, got %d", len(results))
	}
}

func TestClient_CallRuntime_ParsingError(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-parse-error.sock"
	defer os.Remove(socketPath)

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer listener.Close()

	go func() {
		conn, _ := listener.Accept()
		defer conn.Close()

		RecvSocketData(conn)

		// Python runtime returns error for invalid JSON
		responses := []RuntimeResponse{
			{
				Error: "msg_parsing_error",
				Details: ErrorDetails{
					Message:   "Missing required field 'payload' in message",
					Type:      "ValueError",
					Traceback: "ValueError: Missing required field 'payload' in message\n",
				},
			},
		}
		data, _ := json.Marshal(responses)
		SendSocketData(conn, data)
	}()

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"steps":["test"],"current":0}}`)

	results, err := client.CallRuntime(context.Background(), messageData)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}

	if len(results) != 1 {
		t.Errorf("Expected 1 result, got %d", len(results))
	}

	if !results[0].IsError() {
		t.Error("Expected error response")
	}

	if results[0].Error != "msg_parsing_error" {
		t.Errorf("Expected msg_parsing_error, got %s", results[0].Error)
	}
}

func TestClient_CallRuntime_ConnectionError(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-conn-error.sock"
	defer os.Remove(socketPath)

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create socket: %v", err)
	}
	defer listener.Close()

	go func() {
		conn, _ := listener.Accept()
		defer conn.Close()

		RecvSocketData(conn)

		// Python runtime returns error for connection issues
		responses := []RuntimeResponse{
			{
				Error: "connection_error",
				Details: ErrorDetails{
					Message:   "Connection closed while reading",
					Type:      "ConnectionError",
					Traceback: "ConnectionError: Connection closed while reading\n",
				},
			},
		}
		data, _ := json.Marshal(responses)
		SendSocketData(conn, data)
	}()

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"steps":["test"],"current":0},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}

	if len(results) != 1 {
		t.Errorf("Expected 1 result, got %d", len(results))
	}

	if !results[0].IsError() {
		t.Error("Expected error response")
	}

	if results[0].Error != "connection_error" {
		t.Errorf("Expected connection_error, got %s", results[0].Error)
	}
}

func TestResponse_IsError(t *testing.T) {
	tests := []struct {
		name     string
		response RuntimeResponse
		expected bool
	}{
		{
			name:     "success response",
			response: RuntimeResponse{Payload: json.RawMessage(`{"ok": true}`)},
			expected: false,
		},
		{
			name:     "error field set",
			response: RuntimeResponse{Error: "processing_error"},
			expected: true,
		},
		{
			name:     "empty response",
			response: RuntimeResponse{},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.response.IsError()
			if result != tt.expected {
				t.Errorf("IsError() = %v, want %v", result, tt.expected)
			}
		})
	}
}
