package sseclient

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

var sseClient = &http.Client{
	Timeout: 0, // SSE streams are long-lived; per-request context handles cancellation
	Transport: &http.Transport{
		IdleConnTimeout:   120 * time.Second,
		DisableKeepAlives: false,
	},
}

// Event represents a parsed SSE event from the mesh API.
type Event struct {
	Type string          // "status" or "fly"
	Data json.RawMessage // raw JSON payload
}

// StatusData is the parsed content of a "status" event.
type StatusData struct {
	Status   string  `json:"status"`
	Actor    string  `json:"actor,omitempty"`
	Progress float64 `json:"progress,omitempty"`
	Message  string  `json:"message,omitempty"`
	Error    string  `json:"error,omitempty"`
	Result   any     `json:"result,omitempty"`
}

// FlyData is the parsed content of a "fly" event.
type FlyData struct {
	Text     string         `json:"text,omitempty"`
	ToolCall map[string]any `json:"tool_call,omitempty"`
}

// IsTerminal returns true if the status represents a terminal state.
func IsTerminal(status string) bool {
	switch status {
	case "succeeded", "failed", "canceled":
		return true
	default:
		return false
	}
}

// IsInterrupted returns true if the status represents an interrupted state
// (paused, auth_required) that should stop the event stream.
func IsInterrupted(status string) bool {
	switch status {
	case "paused", "auth_required":
		return true
	default:
		return false
	}
}

// Subscribe opens an SSE connection to the given URL and sends parsed events
// to the returned channel. The channel is closed when the stream ends, the
// context is canceled, or an error occurs. The error (if any) is sent on errCh.
//
// The caller must provide the X-Asya-Envelope-ID header for consistent hash
// routing via Ingress.
func Subscribe(ctx context.Context, url string, envelopeID string) (<-chan Event, <-chan error) {
	events := make(chan Event, 32)
	errCh := make(chan error, 1)

	go func() {
		defer close(events)
		defer close(errCh)

		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			errCh <- fmt.Errorf("create SSE request: %w", err)
			return
		}
		req.Header.Set("Accept", "text/event-stream")
		req.Header.Set("X-Asya-Envelope-ID", envelopeID)

		resp, err := sseClient.Do(req)
		if err != nil {
			errCh <- fmt.Errorf("SSE connect: %w", err)
			return
		}
		defer func() { _ = resp.Body.Close() }()

		if resp.StatusCode != http.StatusOK {
			body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
			errCh <- fmt.Errorf("SSE response %d: %s", resp.StatusCode, string(body))
			return
		}

		if err := parseSSE(ctx, resp.Body, events); err != nil {
			errCh <- err
		}
	}()

	return events, errCh
}

// parseSSE reads an SSE stream and sends parsed events to the channel.
func parseSSE(ctx context.Context, r io.Reader, events chan<- Event) error {
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	var eventType string
	var dataLines []string

	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		line := scanner.Text()

		// Empty line = end of event
		if line == "" {
			if eventType != "" && len(dataLines) > 0 {
				data := strings.Join(dataLines, "\n")
				select {
				case events <- Event{
					Type: eventType,
					Data: json.RawMessage(data),
				}:
				case <-ctx.Done():
					return ctx.Err()
				}
			}
			eventType = ""
			dataLines = nil
			continue
		}

		// Comment line (keepalive)
		if strings.HasPrefix(line, ":") {
			continue
		}

		if strings.HasPrefix(line, "event: ") {
			eventType = strings.TrimPrefix(line, "event: ")
		} else if strings.HasPrefix(line, "data: ") {
			dataLines = append(dataLines, strings.TrimPrefix(line, "data: "))
		} else if line == "data:" {
			dataLines = append(dataLines, "")
		}
	}

	return scanner.Err()
}
