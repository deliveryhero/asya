package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
)

// ErrorDetails represents additional information on error occurred in runtime
type ErrorDetails struct {
	Message   string   `json:"message,omitempty"`
	Type      string   `json:"type,omitempty"`
	MRO       []string `json:"mro,omitempty"`
	Traceback string   `json:"traceback,omitempty"`
}

// RuntimeResponse represents the response from the actor runtime
type RuntimeResponse struct {
	Payload json.RawMessage  `json:"payload,omitempty"` // payload output from handler
	Route   messages.Route   `json:"route,omitempty"`   // route output from handler
	Status  *messages.Status `json:"status,omitempty"`  // status from runtime (passed through)
	Error   string           `json:"error,omitempty"`
	Details ErrorDetails     `json:"details,omitempty"`
}

// httpInvokeResponse is the wire format for a successful POST /invoke response.
type httpInvokeResponse struct {
	Frames []RuntimeResponse `json:"frames"`
}

// IsError returns true if the response indicates an error
func (r *RuntimeResponse) IsError() bool {
	return r.Error != ""
}

// Client handles communication with the actor runtime via HTTP over Unix socket
type Client struct {
	socketPath string
	timeout    time.Duration
	httpClient *http.Client
}

// NewClient creates a new runtime client
func NewClient(socketPath string, timeout time.Duration) *Client {
	transport := &http.Transport{
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			var dialer net.Dialer
			return dialer.DialContext(ctx, "unix", socketPath)
		},
	}

	return &Client{
		socketPath: socketPath,
		timeout:    timeout,
		httpClient: &http.Client{
			Transport: transport,
		},
	}
}

// CallRuntime sends a message to the runtime via HTTP POST /invoke and returns response frames.
// Returns responses collected from the response body, empty slice for abort (204), or error.
//
// HTTP protocol:
//
//	Sidecar -> Runtime:  POST /invoke with JSON body
//	Runtime -> Sidecar:  200 {"frames": [...]}       (success)
//	Runtime -> Sidecar:  204 (empty)                 (abort / handler returned None)
//	Runtime -> Sidecar:  400 {"error": "...", ...}   (bad request)
//	Runtime -> Sidecar:  500 {"error": "...", ...}   (handler error)
func (c *Client) CallRuntime(ctx context.Context, data []byte) ([]RuntimeResponse, error) {
	ctx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://localhost/invoke", bytes.NewReader(data))
	if err != nil {
		return nil, fmt.Errorf("failed to create HTTP request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to send request to runtime: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read runtime response body: %w", err)
	}

	switch resp.StatusCode {
	case http.StatusNoContent:
		return nil, nil

	case http.StatusOK:
		var invokeResp httpInvokeResponse
		if err := json.Unmarshal(body, &invokeResp); err != nil {
			return nil, fmt.Errorf("failed to parse runtime success response: %w", err)
		}
		return invokeResp.Frames, nil

	default:
		var errResp RuntimeResponse
		if err := json.Unmarshal(body, &errResp); err != nil {
			return nil, fmt.Errorf("runtime returned HTTP %d with unparseable body: %s", resp.StatusCode, string(body))
		}
		return []RuntimeResponse{errResp}, nil
	}
}
