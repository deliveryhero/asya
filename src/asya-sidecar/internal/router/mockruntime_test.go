package router

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
)

// startMockRuntime starts an HTTP server on a Unix socket that handles POST /invoke.
// The handler function receives the request body and returns (responses, httpStatusCode).
// For status 200, responses are wrapped in {"frames": [...]}.
// For status 204, no body is sent.
// For error statuses (400, 500), the first response is marshaled directly.
// Returns the socket path. Server is automatically cleaned up via t.Cleanup.
func startMockRuntime(t *testing.T, handler func(body []byte) ([]runtime.RuntimeResponse, int)) string {
	t.Helper()

	// Use /tmp with a short name to stay under the 108-char Unix socket path limit.
	// t.TempDir() includes the full test name which can exceed this limit.
	socketPath := fmt.Sprintf("/tmp/rt-%d.sock", time.Now().UnixNano())
	t.Cleanup(func() { _ = os.Remove(socketPath) })

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create Unix socket listener: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/invoke", func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		responses, statusCode := handler(body)

		switch statusCode {
		case http.StatusNoContent:
			w.WriteHeader(http.StatusNoContent)

		case http.StatusOK:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			type invokeResponse struct {
				Frames []runtime.RuntimeResponse `json:"frames"`
			}
			data, _ := json.Marshal(invokeResponse{Frames: responses})
			_, _ = w.Write(data)

		default:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(statusCode)
			if len(responses) > 0 {
				data, _ := json.Marshal(responses[0])
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
