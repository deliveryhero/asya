package runtime

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
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
	Payload json.RawMessage            `json:"payload,omitempty"` // payload output from handler
	Route   messages.Route             `json:"route,omitempty"`   // route output from handler
	Status  *messages.Status           `json:"status,omitempty"`  // status from runtime (passed through)
	Error   string                     `json:"error,omitempty"`
	Details ErrorDetails               `json:"details,omitempty"`
	Headers map[string]json.RawMessage `json:"headers,omitempty"` // headers set by handler
}

// httpInvokeResponse is the wire format for a successful POST /invoke response.
type httpInvokeResponse struct {
	Frames []RuntimeResponse `json:"frames"`
}

// IsError returns true if the response indicates an error
func (r *RuntimeResponse) IsError() bool {
	return r.Error != ""
}

// RuntimeError wraps an error response from the runtime SSE stream
type RuntimeError struct {
	Response RuntimeResponse
}

func (e *RuntimeError) Error() string {
	if e.Response.Details.Message != "" {
		return e.Response.Details.Message
	}
	return e.Response.Error
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
// The timeout parameter specifies the per-call timeout duration for this invocation.
//
// The onUpstream callback is invoked for each upstream SSE event (partial results forwarded
// to the gateway). Pass nil to silently drop upstream events.
//
// HTTP protocol:
//
//	Sidecar -> Runtime:  POST /invoke with JSON body
//	Runtime -> Sidecar:  200 {"frames": [...]}                 (batch JSON, non-generator)
//	Runtime -> Sidecar:  200 text/event-stream                 (SSE, generator)
//	Runtime -> Sidecar:  204 (empty)                           (abort / handler returned None)
//	Runtime -> Sidecar:  400 {"error": "...", ...}             (bad request)
//	Runtime -> Sidecar:  500 {"error": "...", ...}             (handler error)
func (c *Client) CallRuntime(ctx context.Context, data []byte, timeout time.Duration, onUpstream func(json.RawMessage)) ([]RuntimeResponse, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
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

	contentType := resp.Header.Get("Content-Type")

	switch {
	case resp.StatusCode == http.StatusNoContent:
		return nil, nil

	case strings.HasPrefix(contentType, "text/event-stream"):
		return c.parseSSEStream(resp.Body, onUpstream)

	case resp.StatusCode == http.StatusOK:
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return nil, fmt.Errorf("failed to read runtime response body: %w", err)
		}
		var invokeResp httpInvokeResponse
		if err := json.Unmarshal(body, &invokeResp); err != nil {
			return nil, fmt.Errorf("failed to parse runtime success response: %w", err)
		}
		return invokeResp.Frames, nil

	default:
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return nil, fmt.Errorf("failed to read runtime response body: %w", err)
		}
		var errResp RuntimeResponse
		if err := json.Unmarshal(body, &errResp); err != nil {
			return nil, fmt.Errorf("runtime returned HTTP %d with unparseable body: %s", resp.StatusCode, string(body))
		}
		return []RuntimeResponse{errResp}, nil
	}
}

// parseSSEStream reads an SSE event stream from the runtime, collecting downstream frames
// and forwarding upstream events via the callback.
func (c *Client) parseSSEStream(body io.ReadCloser, onUpstream func(json.RawMessage)) ([]RuntimeResponse, error) {
	scanner := bufio.NewScanner(body)
	var responses []RuntimeResponse
	var eventType string
	var dataLines []string

	for scanner.Scan() {
		line := scanner.Text()

		switch {
		case strings.HasPrefix(line, "event: "):
			eventType = line[7:]
		case strings.HasPrefix(line, "data: "):
			dataLines = append(dataLines, line[6:])
		case line == "":
			if eventType == "" {
				continue
			}
			data := strings.Join(dataLines, "\n")
			dataLines = nil

			switch eventType {
			case "downstream":
				var frame RuntimeResponse
				if err := json.Unmarshal([]byte(data), &frame); err != nil {
					return nil, fmt.Errorf("parse downstream frame: %w", err)
				}
				responses = append(responses, frame)
			case "upstream":
				if onUpstream != nil {
					onUpstream(json.RawMessage(data))
				}
			case "done":
				return responses, nil
			case "error":
				var errResp RuntimeResponse
				if err := json.Unmarshal([]byte(data), &errResp); err != nil {
					return nil, fmt.Errorf("parse error frame: %w", err)
				}
				return nil, &RuntimeError{Response: errResp}
			}
			eventType = ""
		}
	}
	return responses, scanner.Err()
}
