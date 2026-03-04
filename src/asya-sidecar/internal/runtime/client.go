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

	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
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
	Route   envelopes.Route            `json:"route,omitempty"`   // route output from handler
	Status  *envelopes.Status          `json:"status,omitempty"`  // status from runtime (passed through)
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

// CallRuntime sends a message to the runtime via HTTP POST /invoke and streams response frames
// via the onDownstream callback. Each frame is delivered with its zero-based index.
//
// The timeout parameter specifies the per-call timeout duration for this invocation.
//
// The onUpstream callback is invoked for each upstream SSE event (partial results forwarded
// to the gateway). Pass nil to silently drop upstream events.
//
// The onDownstream callback is invoked for each response frame (downstream event, JSON batch
// frame, or error response). The index parameter is the zero-based position of the frame.
//
// HTTP protocol:
//
//	Sidecar -> Runtime:  POST /invoke with JSON body
//	Runtime -> Sidecar:  200 {"frames": [...]}                 (batch JSON, non-generator)
//	Runtime -> Sidecar:  200 text/event-stream                 (SSE, generator)
//	Runtime -> Sidecar:  204 (empty)                           (abort / handler returned None)
//	Runtime -> Sidecar:  400 {"error": "...", ...}             (bad request)
//	Runtime -> Sidecar:  500 {"error": "...", ...}             (handler error)
func (c *Client) CallRuntime(ctx context.Context, data []byte, timeout time.Duration, onUpstream func(json.RawMessage), onDownstream func(RuntimeResponse, int)) error {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://localhost/invoke", bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("failed to create HTTP request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send request to runtime: %w", err)
	}
	defer func() {
		cancel() // cancel context before draining body to avoid blocking on SSE keep-alive
		_ = resp.Body.Close()
	}()

	contentType := resp.Header.Get("Content-Type")

	switch {
	case resp.StatusCode == http.StatusNoContent:
		return nil

	case strings.HasPrefix(contentType, "text/event-stream"):
		return c.parseSSEStream(resp.Body, onUpstream, onDownstream)

	case resp.StatusCode == http.StatusOK:
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return fmt.Errorf("failed to read runtime response body: %w", err)
		}
		var invokeResp httpInvokeResponse
		if err := json.Unmarshal(body, &invokeResp); err != nil {
			return fmt.Errorf("failed to parse runtime success response: %w", err)
		}
		for i, frame := range invokeResp.Frames {
			onDownstream(frame, i)
		}
		return nil

	default:
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return fmt.Errorf("failed to read runtime response body: %w", err)
		}
		var errResp RuntimeResponse
		if err := json.Unmarshal(body, &errResp); err != nil {
			return fmt.Errorf("runtime returned HTTP %d with unparseable body: %s", resp.StatusCode, string(body))
		}
		onDownstream(errResp, 0)
		return nil
	}
}

// parseSSEStream reads an SSE event stream from the runtime, dispatching downstream frames
// via callback and forwarding upstream events via the onUpstream callback.
func (c *Client) parseSSEStream(body io.ReadCloser, onUpstream func(json.RawMessage), onDownstream func(RuntimeResponse, int)) error {
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 64*1024), 16*1024*1024) // 16MB max SSE line length
	var downstreamIndex int
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
					return fmt.Errorf("parse downstream frame: %w", err)
				}
				onDownstream(frame, downstreamIndex)
				downstreamIndex++
			case "upstream":
				if onUpstream != nil {
					onUpstream(json.RawMessage(data))
				}
			case "done":
				return nil
			case "error":
				var errResp RuntimeResponse
				if err := json.Unmarshal([]byte(data), &errResp); err != nil {
					return fmt.Errorf("parse error frame: %w", err)
				}
				return &RuntimeError{Response: errResp}
			}
			eventType = ""
		}
	}
	return scanner.Err()
}
