package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"path/filepath"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
)

// startMockHTTPRuntime starts an HTTP server on a Unix socket that handles POST /invoke.
// The handler function receives the request body and returns (frames, statusCode).
// For status 200, frames are wrapped in {"frames": [...]}.
// For status 204, no body is sent.
// For error statuses (400, 500), the first frame is marshaled directly as the response body.
func startMockHTTPRuntime(t *testing.T, handler func(body []byte) ([]RuntimeResponse, int)) string {
	t.Helper()

	socketPath := filepath.Join(t.TempDir(), "runtime.sock")

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create Unix socket listener: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/invoke", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		frames, statusCode := handler(body)

		switch statusCode {
		case http.StatusNoContent:
			w.WriteHeader(http.StatusNoContent)

		case http.StatusOK:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			resp := httpInvokeResponse{Frames: frames}
			data, _ := json.Marshal(resp)
			_, _ = w.Write(data)

		default:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(statusCode)
			if len(frames) > 0 {
				data, _ := json.Marshal(frames[0])
				_, _ = w.Write(data)
			}
		}
	})

	server := &http.Server{Handler: mux}

	go func() {
		_ = server.Serve(listener)
	}()

	t.Cleanup(func() {
		_ = server.Close()
	})

	return socketPath
}

func TestClient_CallRuntime_Success(t *testing.T) {
	socketPath := startMockHTTPRuntime(t, func(body []byte) ([]RuntimeResponse, int) {
		return []RuntimeResponse{
			{
				Payload: json.RawMessage(`{"processed": true}`),
				Route: messages.Route{
					Prev: []string{"test"},
					Curr: "next",
					Next: []string{},
				},
			},
		}, http.StatusOK
	})

	client := NewClient(socketPath, 2*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"test","next":["next"]},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}

	if len(results) != 1 {
		t.Errorf("Expected 1 result, got %d", len(results))
	}

	if results[0].IsError() {
		t.Errorf("Expected success, got error: %s", results[0].Error)
	}
}

func TestClient_CallRuntime_Error(t *testing.T) {
	socketPath := startMockHTTPRuntime(t, func(body []byte) ([]RuntimeResponse, int) {
		return []RuntimeResponse{
			{
				Error: "processing_error",
				Details: ErrorDetails{
					Message:   "Test error message",
					Type:      "ValueError",
					Traceback: "ValueError: Test error message\n",
				},
			},
		}, http.StatusInternalServerError
	})

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"test","next":[]},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
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
	socketPath := startMockHTTPRuntime(t, func(body []byte) ([]RuntimeResponse, int) {
		time.Sleep(2 * time.Second) // Hold request without responding
		return []RuntimeResponse{}, http.StatusOK
	})

	client := NewClient(socketPath, 100*time.Millisecond)
	messageData := []byte(`{"route":{"prev":[],"curr":"test","next":[]},"payload":{"data":"test"}}`)

	_, err := client.CallRuntime(context.Background(), messageData, nil)
	if err == nil {
		t.Error("Expected timeout error but got nil")
	}
}

func TestClient_CallRuntime_FanOut(t *testing.T) {
	socketPath := startMockHTTPRuntime(t, func(body []byte) ([]RuntimeResponse, int) {
		return []RuntimeResponse{
			{
				Payload: json.RawMessage(`{"id": 1}`),
				Route: messages.Route{
					Prev: []string{"fan"},
					Curr: "",
					Next: []string{},
				},
			},
			{
				Payload: json.RawMessage(`{"id": 2}`),
				Route: messages.Route{
					Prev: []string{"fan"},
					Curr: "",
					Next: []string{},
				},
			},
			{
				Payload: json.RawMessage(`{"id": 3}`),
				Route: messages.Route{
					Prev: []string{"fan"},
					Curr: "",
					Next: []string{},
				},
			},
		}, http.StatusOK
	})

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"fan","next":[]},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
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

func TestClient_CallRuntime_EmptyResponse(t *testing.T) {
	socketPath := startMockHTTPRuntime(t, func(body []byte) ([]RuntimeResponse, int) {
		return nil, http.StatusNoContent
	})

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"test","next":[]},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}

	if len(results) != 0 {
		t.Errorf("Expected empty results, got %d", len(results))
	}
}

func TestClient_CallRuntime_ParsingError(t *testing.T) {
	socketPath := startMockHTTPRuntime(t, func(body []byte) ([]RuntimeResponse, int) {
		return []RuntimeResponse{
			{
				Error: "msg_parsing_error",
				Details: ErrorDetails{
					Message:   "Missing required field 'payload' in message",
					Type:      "ValueError",
					Traceback: "ValueError: Missing required field 'payload' in message\n",
				},
			},
		}, http.StatusBadRequest
	})

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"test","next":[]}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
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
	socketPath := startMockHTTPRuntime(t, func(body []byte) ([]RuntimeResponse, int) {
		return []RuntimeResponse{
			{
				Error: "connection_error",
				Details: ErrorDetails{
					Message:   "Connection closed while reading",
					Type:      "ConnectionError",
					Traceback: "ConnectionError: Connection closed while reading\n",
				},
			},
		}, http.StatusInternalServerError
	})

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"test","next":[]},"payload":{"data":"test"}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
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

// startMockSSERuntime starts an HTTP server that responds with SSE events.
func startMockSSERuntime(t *testing.T, sseBody string) string {
	t.Helper()

	socketPath := filepath.Join(t.TempDir(), "runtime-sse.sock")

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create Unix socket listener: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/invoke", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(sseBody))
	})

	server := &http.Server{Handler: mux}
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(func() { _ = server.Close() })

	return socketPath
}

func TestClient_CallRuntime_SSE_DownstreamEvents(t *testing.T) {
	sse := "event: downstream\ndata: {\"payload\":{\"id\":1},\"route\":{\"prev\":[\"a\"],\"curr\":\"b\",\"next\":[]}}\n\n" +
		"event: downstream\ndata: {\"payload\":{\"id\":2},\"route\":{\"prev\":[\"a\"],\"curr\":\"b\",\"next\":[]}}\n\n" +
		"event: done\ndata: {}\n\n"

	socketPath := startMockSSERuntime(t, sse)
	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"a","next":["b"]},"payload":{}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}
	if len(results) != 2 {
		t.Fatalf("Expected 2 results, got %d", len(results))
	}
	if results[0].Route.Curr != "b" {
		t.Errorf("Expected curr=b, got %s", results[0].Route.Curr)
	}
}

func TestClient_CallRuntime_SSE_UpstreamEvents(t *testing.T) {
	sse := "event: upstream\ndata: {\"payload\":{\"token\":\"hello\"}}\n\n" +
		"event: upstream\ndata: {\"payload\":{\"token\":\"world\"}}\n\n" +
		"event: done\ndata: {}\n\n"

	socketPath := startMockSSERuntime(t, sse)
	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"a","next":[]},"payload":{}}`)

	var upstreamEvents []json.RawMessage
	onUpstream := func(payload json.RawMessage) {
		upstreamEvents = append(upstreamEvents, payload)
	}

	results, err := client.CallRuntime(context.Background(), messageData, onUpstream)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}
	if len(results) != 0 {
		t.Errorf("Expected 0 downstream results, got %d", len(results))
	}
	if len(upstreamEvents) != 2 {
		t.Fatalf("Expected 2 upstream events, got %d", len(upstreamEvents))
	}
}

func TestClient_CallRuntime_SSE_MixedEvents(t *testing.T) {
	sse := "event: upstream\ndata: {\"payload\":{\"token\":\"thinking\"}}\n\n" +
		"event: downstream\ndata: {\"payload\":{\"result\":\"step1\"},\"route\":{\"prev\":[\"a\"],\"curr\":\"b\",\"next\":[]}}\n\n" +
		"event: upstream\ndata: {\"payload\":{\"token\":\"done\"}}\n\n" +
		"event: downstream\ndata: {\"payload\":{\"result\":\"step2\"},\"route\":{\"prev\":[\"a\"],\"curr\":\"b\",\"next\":[]}}\n\n" +
		"event: done\ndata: {}\n\n"

	socketPath := startMockSSERuntime(t, sse)
	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"a","next":["b"]},"payload":{}}`)

	var upstreamEvents []json.RawMessage
	results, err := client.CallRuntime(context.Background(), messageData, func(payload json.RawMessage) {
		upstreamEvents = append(upstreamEvents, payload)
	})
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}
	if len(results) != 2 {
		t.Errorf("Expected 2 downstream results, got %d", len(results))
	}
	if len(upstreamEvents) != 2 {
		t.Errorf("Expected 2 upstream events, got %d", len(upstreamEvents))
	}
}

func TestClient_CallRuntime_SSE_EmptyStream(t *testing.T) {
	sse := "event: done\ndata: {}\n\n"

	socketPath := startMockSSERuntime(t, sse)
	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"a","next":[]},"payload":{}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}
	if len(results) != 0 {
		t.Errorf("Expected 0 results, got %d", len(results))
	}
}

func TestClient_CallRuntime_SSE_MidStreamError(t *testing.T) {
	sse := "event: downstream\ndata: {\"payload\":{\"id\":1},\"route\":{\"prev\":[\"a\"],\"curr\":\"\",\"next\":[]}}\n\n" +
		"event: error\ndata: {\"error\":\"processing_error\",\"details\":{\"message\":\"boom\",\"type\":\"ValueError\"}}\n\n"

	socketPath := startMockSSERuntime(t, sse)
	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"a","next":[]},"payload":{}}`)

	_, err := client.CallRuntime(context.Background(), messageData, nil)
	if err == nil {
		t.Fatal("Expected error, got nil")
	}

	var runtimeErr *RuntimeError
	if !errors.As(err, &runtimeErr) {
		t.Fatalf("Expected RuntimeError, got %T: %v", err, err)
	}
	if runtimeErr.Response.Error != "processing_error" {
		t.Errorf("Expected processing_error, got %s", runtimeErr.Response.Error)
	}
}

func TestClient_CallRuntime_SSE_NilUpstreamHandler(t *testing.T) {
	sse := "event: upstream\ndata: {\"payload\":{\"token\":\"dropped\"}}\n\n" +
		"event: done\ndata: {}\n\n"

	socketPath := startMockSSERuntime(t, sse)
	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"a","next":[]},"payload":{}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}
	if len(results) != 0 {
		t.Errorf("Expected 0 results (upstream dropped), got %d", len(results))
	}
}

func TestClient_CallRuntime_JSON_StillWorks(t *testing.T) {
	socketPath := startMockHTTPRuntime(t, func(body []byte) ([]RuntimeResponse, int) {
		return []RuntimeResponse{
			{Payload: json.RawMessage(`{"ok": true}`)},
		}, http.StatusOK
	})

	client := NewClient(socketPath, 5*time.Second)
	messageData := []byte(`{"route":{"prev":[],"curr":"a","next":[]},"payload":{}}`)

	results, err := client.CallRuntime(context.Background(), messageData, nil)
	if err != nil {
		t.Fatalf("CallRuntime failed: %v", err)
	}
	if len(results) != 1 {
		t.Fatalf("Expected 1 result, got %d", len(results))
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
