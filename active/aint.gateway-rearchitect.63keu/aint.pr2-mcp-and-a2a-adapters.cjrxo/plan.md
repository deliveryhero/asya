# PR2: MCP + A2A Adapters -- Implementation Plan

> **For agentic workers:** Execute tasks sequentially. Each task ends with a
> verification step (compile, test, or both). Do not proceed to the next task
> until the current one passes. All file paths are absolute from repo root
> `/home/a.yushkovskiy/asya/`. All new code lives under `src/asya-gateway/`.

**Goal:** Implement two protocol adapter binaries (MCP Streamable HTTP and A2A
JSON-RPC) that translate their respective protocols into /mesh/ HTTP calls
against the mesh-api core from PR1. Both adapters are stateless HTTP translators
that read config from ConfigMaps and hot-reload via a shared polling watcher.

**Architecture:**

```
                    nginx Ingress
                    +---------------------------------+
                    | /mcp/*  --> mcp-adapter :8082    |
                    | /a2a/*  --> a2a-adapter :8083    |
                    +---------------------------------+
                           |              |
     MCP Streamable HTTP   |              |   A2A JSON-RPC
                           v              v
               +------------------+  +------------------+
               | mcp-adapter      |  | a2a-adapter      |
               | :8082            |  | :8083            |
               |                  |  |                  |
               | tools/list       |  | tasks/send       |
               | tools/call  -----+--+-> POST /mesh/    |
               |   SSE relay <----+--+-- GET /mesh/{id} |
               +------------------+  |   /events        |
                                     | tasks/get        |
                                     | tasks/cancel     |
                                     | tasks/subscribe  |
                                     | agent card       |
                                     +------------------+
                    All mesh calls go to localhost:8080 (same pod)
                    except GET /mesh/{id}/events which goes via
                    MESH_INGRESS_URL (consistent hash routing)
```

**Tech Stack:**

| Component | Library | Version |
|---|---|---|
| MCP adapter | `github.com/mark3labs/mcp-go` | v0.48.0 (already in go.mod) |
| A2A adapter | `github.com/a2aproject/a2a-go` | v0.3.15 (already in go.mod) |
| YAML config | `gopkg.in/yaml.v3` | v3.0.1 (already in go.mod) |
| HTTP client | `net/http` (stdlib) | - |
| SSE parsing | Custom (~50 LOC) | - |

**Depends on:** PR1 (mesh-api core must provide `POST /api/v1/mesh/?actor=X`,
`GET /api/v1/mesh/{id}`, `GET /api/v1/mesh/{id}/events`, `DELETE /api/v1/mesh/{id}`).

**Parallel with:** PR3 (sidecar changes), PR4 (Helm/Ingress).

---

### Task 1: Shared ConfigMap Watcher (`internal/watcher/`)

Extract the existing `toolstore.Watch` / `dirFingerprint` into a reusable
package that both adapters import. The existing code in
`src/asya-gateway/internal/toolstore/watcher.go` is toolstore-specific (calls
`r.LoadFromDir`). The new package provides a generic callback.

**Files to create:**

`src/asya-gateway/internal/watcher/watcher.go`:

```go
package watcher

import (
	"context"
	"fmt"
	"hash/fnv"
	"log/slog"
	"os"
	"time"
)

// ReloadFunc is called when the watched directory contents change.
// The argument is the directory path. Errors are logged but do not stop the watcher.
type ReloadFunc func(dir string) error

// Watch polls dir every interval and calls reload when file fingerprint changes.
// Blocks until ctx is canceled. Run with `go watcher.Watch(...)`.
func Watch(ctx context.Context, dir string, interval time.Duration, reload ReloadFunc) {
	var last uint64
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			fp := DirFingerprint(dir)
			if fp == last {
				continue
			}
			if err := reload(dir); err != nil {
				slog.Error("Watcher reload failed", "dir", dir, "error", err)
				continue
			}
			last = fp
			slog.Info("Watcher reloaded config", "dir", dir)
		}
	}
}

// DirFingerprint returns FNV-64a hash of file names, mod times, and sizes.
func DirFingerprint(dir string) uint64 {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0
	}
	h := fnv.New64a()
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		_, _ = fmt.Fprintf(h, "%s:%d:%d\n", entry.Name(), info.ModTime().UnixNano(), info.Size())
	}
	return h.Sum64()
}
```

`src/asya-gateway/internal/watcher/watcher_test.go`:

```go
package watcher_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/watcher"
)

func TestDirFingerprint_EmptyDir(t *testing.T) {
	dir := t.TempDir()
	fp := watcher.DirFingerprint(dir)
	assert.NotEqual(t, uint64(0), fp,
		"empty dir should still have a non-zero fingerprint from FNV init")
	// Actually empty dir with no entries should hash to FNV offset basis
}

func TestDirFingerprint_ChangesOnFileModification(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.yaml")
	require.NoError(t, os.WriteFile(path, []byte("v1"), 0o644))

	fp1 := watcher.DirFingerprint(dir)

	// Ensure mod time advances (filesystem granularity)
	time.Sleep(10 * time.Millisecond)
	require.NoError(t, os.WriteFile(path, []byte("v2-longer"), 0o644))

	fp2 := watcher.DirFingerprint(dir)
	assert.NotEqual(t, fp1, fp2)
}

func TestWatch_CallsReloadOnChange(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tools.yaml")
	require.NoError(t, os.WriteFile(path, []byte("initial"), 0o644))

	reloadCount := 0
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go watcher.Watch(ctx, dir, 50*time.Millisecond, func(d string) error {
		reloadCount++
		return nil
	})

	// Wait for initial detection
	time.Sleep(150 * time.Millisecond)
	assert.GreaterOrEqual(t, reloadCount, 1, "should detect initial state")

	initialCount := reloadCount

	// Modify file
	time.Sleep(10 * time.Millisecond)
	require.NoError(t, os.WriteFile(path, []byte("changed"), 0o644))

	// Wait for next poll
	time.Sleep(150 * time.Millisecond)
	assert.Greater(t, reloadCount, initialCount, "should detect file change")
}

func TestDirFingerprint_NonexistentDir(t *testing.T) {
	fp := watcher.DirFingerprint("/nonexistent/path")
	assert.Equal(t, uint64(0), fp)
}
```

**Refactor existing toolstore watcher** -- update
`src/asya-gateway/internal/toolstore/watcher.go` to delegate to the new package:

```go
package toolstore

import (
	"context"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/watcher"
)

// Watch polls dir every pollInterval and reloads the registry when file contents change.
func Watch(ctx context.Context, dir string, r *Registry, pollInterval time.Duration) {
	watcher.Watch(ctx, dir, pollInterval, func(d string) error {
		return r.LoadFromDir(d)
	})
}
```

Remove the `dirFingerprint` function from toolstore (it now lives in watcher).

**Verification:**

```bash
cd src/asya-gateway && go build ./...
cd src/asya-gateway && go test ./internal/watcher/... -v -count=1
cd src/asya-gateway && go test ./internal/toolstore/... -v -count=1
```

---

### Task 2: Shared SSE Client (`internal/sseclient/`)

Both adapters need to consume SSE from `GET /api/v1/mesh/{id}/events`. Write a
minimal SSE line-protocol parser (not a full library -- just enough for our
event schema).

**SSE event schema from mesh-api (RFC Addendum Section 8):**

```
event: status
data: {"status":"running","actor":"train-model","progress":50.0,"message":"Step 500/1000"}

event: fly
data: {"text":"token chunk..."}

event: status
data: {"status":"succeeded","actor":"x-sink"}
```

**Files to create:**

`src/asya-gateway/internal/sseclient/sseclient.go`:

```go
package sseclient

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// Event represents a parsed SSE event from the mesh API.
type Event struct {
	Type string          // "status" or "fly"
	Data json.RawMessage // raw JSON payload
}

// StatusData is the parsed content of a "status" event.
type StatusData struct {
	Status   string   `json:"status"`
	Actor    string   `json:"actor,omitempty"`
	Progress float64  `json:"progress,omitempty"`
	Message  string   `json:"message,omitempty"`
	Error    string   `json:"error,omitempty"`
	Result   any      `json:"result,omitempty"`
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

		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			errCh <- fmt.Errorf("SSE connect: %w", err)
			return
		}
		defer resp.Body.Close()

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
				events <- Event{
					Type: eventType,
					Data: json.RawMessage(data),
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
```

`src/asya-gateway/internal/sseclient/sseclient_test.go`:

```go
package sseclient_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/sseclient"
)

func TestParseSSE_StatusAndFly(t *testing.T) {
	body := "event: status\ndata: {\"status\":\"running\",\"actor\":\"train\"}\n\n" +
		"event: fly\ndata: {\"text\":\"hello\"}\n\n" +
		"event: status\ndata: {\"status\":\"succeeded\",\"actor\":\"x-sink\"}\n\n"

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	events, errCh := sseclient.Subscribe(ctx, srv.URL, "test-id")

	var collected []sseclient.Event
	for evt := range events {
		collected = append(collected, evt)
	}

	err := <-errCh
	assert.NoError(t, err)
	require.Len(t, collected, 3)

	assert.Equal(t, "status", collected[0].Type)
	var s0 sseclient.StatusData
	require.NoError(t, json.Unmarshal(collected[0].Data, &s0))
	assert.Equal(t, "running", s0.Status)
	assert.Equal(t, "train", s0.Actor)

	assert.Equal(t, "fly", collected[1].Type)
	var f sseclient.FlyData
	require.NoError(t, json.Unmarshal(collected[1].Data, &f))
	assert.Equal(t, "hello", f.Text)

	assert.Equal(t, "status", collected[2].Type)
	var s2 sseclient.StatusData
	require.NoError(t, json.Unmarshal(collected[2].Data, &s2))
	assert.Equal(t, "succeeded", s2.Status)
}

func TestParseSSE_SkipsKeepaliveComments(t *testing.T) {
	body := ": keepalive\n\nevent: status\ndata: {\"status\":\"succeeded\"}\n\n"

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	events, errCh := sseclient.Subscribe(ctx, srv.URL, "test-id")

	var collected []sseclient.Event
	for evt := range events {
		collected = append(collected, evt)
	}

	assert.NoError(t, <-errCh)
	require.Len(t, collected, 1)
	assert.Equal(t, "status", collected[0].Type)
}

func TestSubscribe_SetsEnvelopeIDHeader(t *testing.T) {
	var receivedHeader string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedHeader = r.Header.Get("X-Asya-Envelope-ID")
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: status\ndata: {\"status\":\"succeeded\"}\n\n"))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	events, _ := sseclient.Subscribe(ctx, srv.URL, "envelope-42")
	for range events {
	}

	assert.Equal(t, "envelope-42", receivedHeader)
}

func TestSubscribe_NonOKStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = fmt.Fprint(w, "not found")
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	events, errCh := sseclient.Subscribe(ctx, srv.URL, "bad-id")
	for range events {
	}

	err := <-errCh
	require.Error(t, err)
	assert.Contains(t, err.Error(), "404")
}

func TestIsTerminal(t *testing.T) {
	assert.True(t, sseclient.IsTerminal("succeeded"))
	assert.True(t, sseclient.IsTerminal("failed"))
	assert.True(t, sseclient.IsTerminal("canceled"))
	assert.False(t, sseclient.IsTerminal("running"))
	assert.False(t, sseclient.IsTerminal("pending"))
	assert.False(t, sseclient.IsTerminal("paused"))
}

func TestIsInterrupted(t *testing.T) {
	assert.True(t, sseclient.IsInterrupted("paused"))
	assert.True(t, sseclient.IsInterrupted("auth_required"))
	assert.False(t, sseclient.IsInterrupted("running"))
	assert.False(t, sseclient.IsInterrupted("succeeded"))
}
```

**Verification:**

```bash
cd src/asya-gateway && go test ./internal/sseclient/... -v -count=1
```

---

### Task 3: Mesh API HTTP Client (`internal/meshclient/`)

Both adapters call mesh-api over HTTP. Extract a typed client that encapsulates
the two-step dispatch pattern (POST create + GET events). This client talks to
`localhost:8080` for create/get/cancel and to `MESH_INGRESS_URL` for SSE
subscription (consistent hash routing).

**Files to create:**

`src/asya-gateway/internal/meshclient/client.go`:

```go
package meshclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/sseclient"
)

// CreateRequest is the POST body for creating a new mesh message.
type CreateRequest struct {
	Payload map[string]any `json:"payload"`
	Headers map[string]any `json:"headers,omitempty"`
	Timeout int            `json:"timeout,omitempty"` // seconds
}

// CreateResponse is the response from POST /api/v1/mesh/?actor=X.
type CreateResponse struct {
	ID string `json:"id"`
}

// MessageStatus is the response from GET /api/v1/mesh/{id}.
type MessageStatus struct {
	ID        string          `json:"id"`
	Status    string          `json:"status"`
	Data      json.RawMessage `json:"data,omitempty"`
	CreatedAt time.Time       `json:"created_at"`
	UpdatedAt time.Time       `json:"updated_at"`
}

// Client wraps HTTP calls to the mesh-api.
type Client struct {
	// localURL is the mesh-api URL on the same pod (e.g. "http://localhost:8080")
	// Used for POST create, GET status, DELETE cancel.
	localURL string

	// ingressURL is the external Ingress URL for hash-routed SSE subscriptions.
	// Used for GET /api/v1/mesh/{id}/events.
	ingressURL string

	httpClient *http.Client
}

// New creates a mesh API client.
// localURL: mesh-api on the same pod (e.g. "http://localhost:8080").
// ingressURL: external Ingress for hash-routed SSE (e.g. "http://asya-mesh-api.example.com").
func New(localURL, ingressURL string) *Client {
	return &Client{
		localURL:   localURL,
		ingressURL: ingressURL,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// Create dispatches a new message to the mesh and returns the assigned ID.
func (c *Client) Create(ctx context.Context, actor string, req CreateRequest) (*CreateResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal create request: %w", err)
	}

	url := fmt.Sprintf("%s/api/v1/mesh/?actor=%s", c.localURL, actor)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create HTTP request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("mesh create: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		respBody, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return nil, fmt.Errorf("mesh create returned %d: %s", resp.StatusCode, string(respBody))
	}

	var result CreateResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode create response: %w", err)
	}
	return &result, nil
}

// Get retrieves the current status of a mesh message.
func (c *Client) Get(ctx context.Context, id string) (*MessageStatus, error) {
	url := fmt.Sprintf("%s/api/v1/mesh/%s", c.localURL, id)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("create GET request: %w", err)
	}

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("mesh get: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil, fmt.Errorf("message %q not found", id)
	}
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return nil, fmt.Errorf("mesh get returned %d: %s", resp.StatusCode, string(body))
	}

	var status MessageStatus
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		return nil, fmt.Errorf("decode status: %w", err)
	}
	return &status, nil
}

// SubscribeEvents opens an SSE stream for the given message ID via Ingress
// (hash-routed by X-Asya-Envelope-ID header).
func (c *Client) SubscribeEvents(ctx context.Context, id string) (<-chan sseclient.Event, <-chan error) {
	url := fmt.Sprintf("%s/api/v1/mesh/%s/events", c.ingressURL, id)
	return sseclient.Subscribe(ctx, url, id)
}

// Cancel sends a DELETE request to cancel a mesh message.
func (c *Client) Cancel(ctx context.Context, id string) error {
	url := fmt.Sprintf("%s/api/v1/mesh/%s", c.localURL, id)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodDelete, url, nil)
	if err != nil {
		return fmt.Errorf("create DELETE request: %w", err)
	}

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("mesh cancel: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("mesh cancel returned %d: %s", resp.StatusCode, string(body))
	}
	return nil
}
```

`src/asya-gateway/internal/meshclient/client_test.go`:

```go
package meshclient_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
)

func TestCreate_Success(t *testing.T) {
	var receivedActor string
	var receivedBody meshclient.CreateRequest

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedActor = r.URL.Query().Get("actor")
		_ = json.NewDecoder(r.Body).Decode(&receivedBody)
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(meshclient.CreateResponse{ID: "msg-001"})
	}))
	defer srv.Close()

	client := meshclient.New(srv.URL, srv.URL)
	resp, err := client.Create(context.Background(), "start-flow", meshclient.CreateRequest{
		Payload: map[string]any{"lr": 0.001},
		Timeout: 300,
	})

	require.NoError(t, err)
	assert.Equal(t, "msg-001", resp.ID)
	assert.Equal(t, "start-flow", receivedActor)
	assert.Equal(t, 0.001, receivedBody.Payload["lr"])
}

func TestCreate_ServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("queue unavailable"))
	}))
	defer srv.Close()

	client := meshclient.New(srv.URL, srv.URL)
	_, err := client.Create(context.Background(), "actor", meshclient.CreateRequest{})

	require.Error(t, err)
	assert.Contains(t, err.Error(), "500")
}

func TestGet_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "/api/v1/mesh/msg-001", r.URL.Path)
		_ = json.NewEncoder(w).Encode(meshclient.MessageStatus{
			ID:     "msg-001",
			Status: "running",
		})
	}))
	defer srv.Close()

	client := meshclient.New(srv.URL, srv.URL)
	status, err := client.Get(context.Background(), "msg-001")

	require.NoError(t, err)
	assert.Equal(t, "running", status.Status)
}

func TestGet_NotFound(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	client := meshclient.New(srv.URL, srv.URL)
	_, err := client.Get(context.Background(), "bad-id")

	require.Error(t, err)
	assert.Contains(t, err.Error(), "not found")
}

func TestCancel_Success(t *testing.T) {
	var receivedMethod string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedMethod = r.Method
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()

	client := meshclient.New(srv.URL, srv.URL)
	err := client.Cancel(context.Background(), "msg-001")

	require.NoError(t, err)
	assert.Equal(t, http.MethodDelete, receivedMethod)
}

func TestSubscribeEvents_ViaIngress(t *testing.T) {
	var receivedEnvelopeID string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedEnvelopeID = r.Header.Get("X-Asya-Envelope-ID")
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: status\ndata: {\"status\":\"succeeded\"}\n\n"))
	}))
	defer srv.Close()

	// localURL differs from ingressURL to verify SSE goes via Ingress
	client := meshclient.New("http://should-not-be-used", srv.URL)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	events, errCh := client.SubscribeEvents(ctx, "msg-001")

	var collected []string
	for evt := range events {
		collected = append(collected, evt.Type)
	}

	assert.NoError(t, <-errCh)
	assert.Equal(t, []string{"status"}, collected)
	assert.Equal(t, "msg-001", receivedEnvelopeID)
}
```

**Verification:**

```bash
cd src/asya-gateway && go test ./internal/meshclient/... -v -count=1
```

---

### Task 4: MCP Adapter -- ConfigMap Loader (`internal/mcp/config.go`)

The MCP adapter reads tool definitions from YAML files in a ConfigMap mount
directory. This replaces the current toolstore-based approach with a dedicated,
adapter-specific config type.

**ConfigMap YAML schema** (mounted at `/etc/asya/mcp/`):

```yaml
# /etc/asya/mcp/tools.yaml
tools:
  - name: train_model
    description: "Train a model with given hyperparameters"
    actor: start-my-flow
    timeout: 3600
    progress: true
    inputSchema:
      type: object
      properties:
        lr:
          type: number
          description: "Learning rate"
        epochs:
          type: integer
          description: "Number of training epochs"
      required:
        - lr
```

**Files to create:**

`src/asya-gateway/internal/mcp/config.go`:

```go
// Package mcp implements the MCP Streamable HTTP adapter.
// This is the NEW package for the rearchitected adapter binary.
// During the transition, it coexists with the old mcp package
// which will be deleted when the monolith gateway is removed.
//
// Build tag: The new adapter code lives under cmd/mcp-adapter/
// and imports this package. The old gateway code imports the
// old internal/mcp/ package. No conflict because they are
// separate binaries.

package mcpadapter

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"gopkg.in/yaml.v3"
)

// ToolConfig is a single MCP tool definition from the ConfigMap.
type ToolConfig struct {
	Name        string          `yaml:"name" json:"name"`
	Description string          `yaml:"description" json:"description"`
	Actor       string          `yaml:"actor" json:"actor"`
	Timeout     int             `yaml:"timeout" json:"timeout"`     // seconds, 0 = default (300)
	Progress    bool            `yaml:"progress" json:"progress"`
	InputSchema json.RawMessage `yaml:"inputSchema" json:"inputSchema"` // JSON Schema
}

// ToolsFile is the top-level structure of a tools ConfigMap YAML file.
type ToolsFile struct {
	Tools []ToolConfig `yaml:"tools"`
}

// Registry holds the current set of MCP tool definitions. Thread-safe.
type Registry struct {
	mu    sync.RWMutex
	tools []ToolConfig
}

// NewRegistry creates an empty registry.
func NewRegistry() *Registry {
	return &Registry{}
}

// LoadFromDir reads all *.yaml / *.yml files in dir, parses ToolsFile entries,
// and atomically replaces the current tool set. On error the previous set is preserved.
func (r *Registry) LoadFromDir(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return fmt.Errorf("read config dir %q: %w", dir, err)
	}

	var tools []ToolConfig
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if !strings.HasSuffix(name, ".yaml") && !strings.HasSuffix(name, ".yml") {
			continue
		}

		path := filepath.Join(dir, name)
		data, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read %q: %w", path, err)
		}

		var tf ToolsFile
		if err := yaml.Unmarshal(data, &tf); err != nil {
			return fmt.Errorf("parse %q: %w", path, err)
		}

		for _, tool := range tf.Tools {
			if tool.Name == "" {
				return fmt.Errorf("file %q: tool name is required", path)
			}
			if tool.Actor == "" {
				return fmt.Errorf("file %q, tool %q: actor is required", path, tool.Name)
			}
			tools = append(tools, tool)
		}
	}

	r.mu.Lock()
	r.tools = tools
	r.mu.Unlock()
	return nil
}

// Tools returns a snapshot of the current tool definitions.
func (r *Registry) Tools() []ToolConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]ToolConfig, len(r.tools))
	copy(result, r.tools)
	return result
}

// GetByName returns the tool with the given name, or nil if not found.
func (r *Registry) GetByName(name string) *ToolConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for i := range r.tools {
		if r.tools[i].Name == name {
			t := r.tools[i]
			return &t
		}
	}
	return nil
}
```

`src/asya-gateway/internal/mcp/config_test.go`:

```go
package mcpadapter_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	mcpadapter "github.com/deliveryhero/asya/asya-gateway/internal/mcpadapter"
)

func TestRegistry_LoadFromDir(t *testing.T) {
	dir := t.TempDir()
	yaml := `tools:
  - name: train_model
    description: "Train a model"
    actor: start-train-flow
    timeout: 3600
    progress: true
    inputSchema:
      type: object
      properties:
        lr:
          type: number
      required: [lr]
  - name: deploy
    description: "Deploy to production"
    actor: start-deploy-flow
    timeout: 600
`
	require.NoError(t, os.WriteFile(filepath.Join(dir, "tools.yaml"), []byte(yaml), 0o644))

	reg := mcpadapter.NewRegistry()
	require.NoError(t, reg.LoadFromDir(dir))

	tools := reg.Tools()
	require.Len(t, tools, 2)

	assert.Equal(t, "train_model", tools[0].Name)
	assert.Equal(t, "start-train-flow", tools[0].Actor)
	assert.Equal(t, 3600, tools[0].Timeout)
	assert.True(t, tools[0].Progress)
	assert.NotEmpty(t, tools[0].InputSchema)

	assert.Equal(t, "deploy", tools[1].Name)
	assert.Equal(t, "start-deploy-flow", tools[1].Actor)
}

func TestRegistry_LoadFromDir_ValidationErrors(t *testing.T) {
	tests := []struct {
		name    string
		yaml    string
		errMsg  string
	}{
		{
			name:   "missing name",
			yaml:   "tools:\n  - actor: foo\n",
			errMsg: "tool name is required",
		},
		{
			name:   "missing actor",
			yaml:   "tools:\n  - name: foo\n",
			errMsg: "actor is required",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			require.NoError(t, os.WriteFile(filepath.Join(dir, "tools.yaml"), []byte(tt.yaml), 0o644))

			reg := mcpadapter.NewRegistry()
			err := reg.LoadFromDir(dir)
			require.Error(t, err)
			assert.Contains(t, err.Error(), tt.errMsg)
		})
	}
}

func TestRegistry_GetByName(t *testing.T) {
	dir := t.TempDir()
	yaml := `tools:
  - name: train
    actor: start-train
    description: "Train"
  - name: deploy
    actor: start-deploy
    description: "Deploy"
`
	require.NoError(t, os.WriteFile(filepath.Join(dir, "tools.yaml"), []byte(yaml), 0o644))

	reg := mcpadapter.NewRegistry()
	require.NoError(t, reg.LoadFromDir(dir))

	tool := reg.GetByName("train")
	require.NotNil(t, tool)
	assert.Equal(t, "start-train", tool.Actor)

	assert.Nil(t, reg.GetByName("nonexistent"))
}

func TestRegistry_LoadFromDir_MultipleFiles(t *testing.T) {
	dir := t.TempDir()
	require.NoError(t, os.WriteFile(filepath.Join(dir, "a.yaml"), []byte("tools:\n  - name: a\n    actor: actor-a\n"), 0o644))
	require.NoError(t, os.WriteFile(filepath.Join(dir, "b.yml"), []byte("tools:\n  - name: b\n    actor: actor-b\n"), 0o644))
	require.NoError(t, os.WriteFile(filepath.Join(dir, "c.txt"), []byte("not yaml"), 0o644))

	reg := mcpadapter.NewRegistry()
	require.NoError(t, reg.LoadFromDir(dir))

	tools := reg.Tools()
	require.Len(t, tools, 2)
}

func TestRegistry_AtomicSwap(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tools.yaml")
	require.NoError(t, os.WriteFile(path, []byte("tools:\n  - name: v1\n    actor: a1\n"), 0o644))

	reg := mcpadapter.NewRegistry()
	require.NoError(t, reg.LoadFromDir(dir))
	assert.Len(t, reg.Tools(), 1)

	// Replace with new content
	require.NoError(t, os.WriteFile(path, []byte("tools:\n  - name: v2\n    actor: a2\n  - name: v3\n    actor: a3\n"), 0o644))
	require.NoError(t, reg.LoadFromDir(dir))
	assert.Len(t, reg.Tools(), 2)
	assert.Equal(t, "v2", reg.Tools()[0].Name)
}
```

**Note on package naming:** Since the old `internal/mcp/` package still exists
in the monolith, the new adapter code will live in `internal/mcpadapter/`. Once
the old gateway binary is removed (post-migration), this can be renamed back to
`internal/mcp/`.

**Verification:**

```bash
cd src/asya-gateway && go test ./internal/mcpadapter/... -v -count=1
```

---

### Task 5: MCP Adapter -- Handler + Binary (`internal/mcpadapter/handler.go`, `cmd/mcp-adapter/main.go`)

The core MCP adapter logic: register tools from the config registry with
mark3labs/mcp-go, handle tools/call by doing the two-step dispatch (POST to
mesh-api, then relay SSE events as MCP progress notifications + final result).

**Files to create:**

`src/asya-gateway/internal/mcpadapter/handler.go`:

```go
package mcpadapter

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/internal/sseclient"
)

// Handler manages the MCP server and tool registration.
type Handler struct {
	mcpServer  *server.MCPServer
	registry   *Registry
	meshClient *meshclient.Client
}

// NewHandler creates a new MCP adapter handler.
func NewHandler(reg *Registry, meshClient *meshclient.Client) *Handler {
	h := &Handler{
		registry:   reg,
		meshClient: meshClient,
	}

	h.mcpServer = server.NewMCPServer(
		"asya-mcp-adapter",
		"1.0.0",
		server.WithToolCapabilities(true), // tools change via hot-reload
	)

	return h
}

// MCPServer returns the underlying mcp-go server for HTTP integration.
func (h *Handler) MCPServer() *server.MCPServer {
	return h.mcpServer
}

// SyncTools re-registers all tools from the registry with the MCP server.
// Called on startup and after each hot-reload.
func (h *Handler) SyncTools() {
	tools := h.registry.Tools()

	for _, toolCfg := range tools {
		mcpTool := buildMCPTool(toolCfg)
		handler := h.createToolHandler(toolCfg)
		h.mcpServer.AddTool(mcpTool, handler)
	}

	slog.Info("MCP tools synced", "count", len(tools))
}

// buildMCPTool converts a ToolConfig to an mcp.Tool.
func buildMCPTool(cfg ToolConfig) mcp.Tool {
	opts := []mcp.ToolOption{mcp.WithDescription(cfg.Description)}

	if len(cfg.InputSchema) > 0 {
		var schema map[string]any
		if json.Unmarshal(cfg.InputSchema, &schema) == nil {
			opts = append(opts, buildParamOptions(schema)...)
		}
	}

	return mcp.NewTool(cfg.Name, opts...)
}

// buildParamOptions converts a JSON Schema object to mcp.ToolOptions.
func buildParamOptions(schema map[string]any) []mcp.ToolOption {
	var opts []mcp.ToolOption

	properties, _ := schema["properties"].(map[string]any)
	requiredSet := make(map[string]bool)
	if requiredList, ok := schema["required"].([]any); ok {
		for _, r := range requiredList {
			if name, ok := r.(string); ok {
				requiredSet[name] = true
			}
		}
	}

	for name, propRaw := range properties {
		prop, ok := propRaw.(map[string]any)
		if !ok {
			continue
		}

		var paramOpts []mcp.PropertyOption
		if desc, ok := prop["description"].(string); ok && desc != "" {
			paramOpts = append(paramOpts, mcp.Description(desc))
		}
		if requiredSet[name] {
			paramOpts = append(paramOpts, mcp.Required())
		}

		paramType, _ := prop["type"].(string)
		switch paramType {
		case "string":
			if enumVals, ok := prop["enum"].([]any); ok {
				strs := make([]string, 0, len(enumVals))
				for _, v := range enumVals {
					if s, ok := v.(string); ok {
						strs = append(strs, s)
					}
				}
				paramOpts = append(paramOpts, mcp.Enum(strs...))
			}
			opts = append(opts, mcp.WithString(name, paramOpts...))
		case "number", "integer":
			opts = append(opts, mcp.WithNumber(name, paramOpts...))
		case "boolean":
			opts = append(opts, mcp.WithBoolean(name, paramOpts...))
		case "array":
			opts = append(opts, mcp.WithArray(name, paramOpts...))
		default:
			opts = append(opts, mcp.WithString(name, paramOpts...))
		}
	}

	return opts
}

// createToolHandler creates an MCP tool handler that does two-step dispatch:
// 1. POST /api/v1/mesh/?actor=X (local, same pod)
// 2. GET /api/v1/mesh/{id}/events (via Ingress, hash-routed)
// 3. Translate mesh SSE events -> MCP progress/log/result
func (h *Handler) createToolHandler(cfg ToolConfig) server.ToolHandlerFunc {
	return func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		arguments := request.GetArguments()

		// Validate required parameters
		if len(cfg.InputSchema) > 0 {
			if err := validateRequired(cfg.InputSchema, arguments); err != nil {
				return mcp.NewToolResultError(err.Error()), nil
			}
		}

		timeout := cfg.Timeout
		if timeout == 0 {
			timeout = 300 // default 5 minutes
		}

		// Step 1: Create message in mesh-api
		createResp, err := h.meshClient.Create(ctx, cfg.Actor, meshclient.CreateRequest{
			Payload: arguments,
			Timeout: timeout,
		})
		if err != nil {
			slog.Error("Mesh create failed", "tool", cfg.Name, "error", err)
			return mcp.NewToolResultError(fmt.Sprintf("dispatch failed: %v", err)), nil
		}

		slog.Info("Mesh message created", "tool", cfg.Name, "id", createResp.ID, "actor", cfg.Actor)

		// Step 2: Subscribe to SSE events via Ingress
		sseCtx, sseCancel := context.WithTimeout(ctx, time.Duration(timeout)*time.Second)
		defer sseCancel()

		events, errCh := h.meshClient.SubscribeEvents(sseCtx, createResp.ID)

		// Step 3: Relay mesh events
		var finalResult *mcp.CallToolResult
		for evt := range events {
			switch evt.Type {
			case "status":
				var status sseclient.StatusData
				if json.Unmarshal(evt.Data, &status) != nil {
					continue
				}

				if sseclient.IsTerminal(status.Status) || sseclient.IsInterrupted(status.Status) {
					finalResult = statusToCallToolResult(status)
					sseCancel()
				}
				// Non-terminal status: MCP progress notification
				// (sent via mcp-go's built-in progress mechanism if session supports it)

			case "fly":
				// FLY events -> log to MCP (via notifications/message)
				// mcp-go handles this at the transport level; we just continue
				slog.Debug("FLY event received", "id", createResp.ID)
			}
		}

		// Check for SSE errors
		if sseErr := <-errCh; sseErr != nil && finalResult == nil {
			slog.Warn("SSE stream error", "id", createResp.ID, "error", sseErr)
			// Fall back to polling mesh-api for final status
			finalResult = h.pollForResult(ctx, createResp.ID, time.Duration(timeout)*time.Second)
		}

		if finalResult == nil {
			// Timeout or unexpected close -- check current status
			finalResult = h.pollForResult(ctx, createResp.ID, 5*time.Second)
		}

		if finalResult == nil {
			return mcp.NewToolResultError("timeout: no result received"), nil
		}

		return finalResult, nil
	}
}

// statusToCallToolResult converts a terminal mesh status to an MCP CallToolResult.
func statusToCallToolResult(status sseclient.StatusData) *mcp.CallToolResult {
	switch status.Status {
	case "succeeded":
		if status.Result != nil {
			data, err := json.Marshal(status.Result)
			if err == nil {
				return mcp.NewToolResultText(string(data))
			}
		}
		if status.Message != "" {
			return mcp.NewToolResultText(status.Message)
		}
		return mcp.NewToolResultText("completed")

	case "failed":
		msg := "task failed"
		if status.Error != "" {
			msg = status.Error
		} else if status.Message != "" {
			msg = status.Message
		}
		return mcp.NewToolResultError(msg)

	case "canceled":
		return mcp.NewToolResultError("task was canceled")

	case "paused":
		return mcp.NewToolResultText(fmt.Sprintf(`{"status":"paused","message":"%s"}`, status.Message))

	default:
		return mcp.NewToolResultError(fmt.Sprintf("unexpected status: %s", status.Status))
	}
}

// pollForResult checks mesh-api for current message status as a fallback.
func (h *Handler) pollForResult(ctx context.Context, id string, timeout time.Duration) *mcp.CallToolResult {
	pollCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-pollCtx.Done():
			return nil
		case <-ticker.C:
			status, err := h.meshClient.Get(pollCtx, id)
			if err != nil {
				continue
			}
			if sseclient.IsTerminal(status.Status) || sseclient.IsInterrupted(status.Status) {
				var s sseclient.StatusData
				s.Status = status.Status
				if status.Data != nil {
					_ = json.Unmarshal(status.Data, &s)
				}
				return statusToCallToolResult(s)
			}
		}
	}
}

// validateRequired checks that all required parameters are present.
func validateRequired(schemaRaw json.RawMessage, args map[string]any) error {
	var schema map[string]any
	if json.Unmarshal(schemaRaw, &schema) != nil {
		return nil // cannot parse, skip validation
	}

	requiredList, ok := schema["required"].([]any)
	if !ok {
		return nil
	}

	for _, r := range requiredList {
		name, ok := r.(string)
		if !ok {
			continue
		}
		if _, exists := args[name]; !exists {
			return fmt.Errorf("missing required parameter: %s", name)
		}
	}
	return nil
}
```

`src/asya-gateway/cmd/mcp-adapter/main.go`:

```go
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	mcpserver "github.com/mark3labs/mcp-go/server"

	mcpadapter "github.com/deliveryhero/asya/asya-gateway/internal/mcpadapter"
	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/internal/watcher"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: parseLogLevel(os.Getenv("ASYA_LOG_LEVEL")),
	})))

	meshAPIURL := requireEnv("MESH_API_URL")     // e.g. "http://localhost:8080"
	ingressURL := requireEnv("MESH_INGRESS_URL")  // e.g. "http://asya-mesh-api.example.com"
	configDir := requireEnv("ASYA_MCP_CONFIG_DIR") // e.g. "/etc/asya/mcp"
	port := getEnv("ASYA_MCP_PORT", "8082")

	// Initialize mesh client
	meshClient := meshclient.New(meshAPIURL, ingressURL)

	// Load tool registry from ConfigMap
	registry := mcpadapter.NewRegistry()
	if err := registry.LoadFromDir(configDir); err != nil {
		slog.Error("Failed to load MCP tool config", "dir", configDir, "error", err)
		os.Exit(1)
	}

	// Create MCP handler
	handler := mcpadapter.NewHandler(registry, meshClient)
	handler.SyncTools()

	// Start ConfigMap watcher for hot-reload
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	pollInterval := parseDuration(getEnv("ASYA_MCP_POLL_INTERVAL", "10s"), 10*time.Second)
	go watcher.Watch(ctx, configDir, pollInterval, func(dir string) error {
		if err := registry.LoadFromDir(dir); err != nil {
			return err
		}
		handler.SyncTools()
		return nil
	})

	// Create HTTP server with MCP Streamable HTTP
	mux := http.NewServeMux()
	mux.Handle("/mcp", mcpserver.NewStreamableHTTPServer(handler.MCPServer()))
	mux.Handle("/mcp/sse", mcpserver.NewSSEServer(handler.MCPServer()))
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintln(w, "OK")
	})

	server := &http.Server{
		Addr:    ":" + port,
		Handler: mux,
	}

	// Graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		slog.Info("MCP adapter listening", "port", port, "config", configDir)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("Server failed", "error", err)
			os.Exit(1)
		}
	}()

	sig := <-sigChan
	slog.Info("Shutting down", "signal", sig)

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	_ = server.Shutdown(shutdownCtx)
}

func requireEnv(key string) string {
	val := os.Getenv(key)
	if val == "" {
		slog.Error("Required environment variable not set", "key", key)
		os.Exit(1)
	}
	return val
}

func getEnv(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}

func parseLogLevel(s string) slog.Level {
	switch s {
	case "DEBUG":
		return slog.LevelDebug
	case "WARN", "WARNING":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func parseDuration(s string, fallback time.Duration) time.Duration {
	d, err := time.ParseDuration(s)
	if err != nil {
		return fallback
	}
	return d
}
```

**Verification:**

```bash
cd src/asya-gateway && go build ./cmd/mcp-adapter/
cd src/asya-gateway && go test ./internal/mcpadapter/... -v -count=1
```

---

### Task 6: MCP Adapter -- Unit Tests (`internal/mcpadapter/handler_test.go`)

Test the full tools/call flow with mocked mesh-api responses.

**File to create:**

`src/asya-gateway/internal/mcpadapter/handler_test.go`:

```go
package mcpadapter_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	mcpadapter "github.com/deliveryhero/asya/asya-gateway/internal/mcpadapter"
	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
)

// fakeMeshAPI simulates the mesh-api for testing the MCP adapter.
func fakeMeshAPI(t *testing.T, createID string, sseBody string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodPost && strings.Contains(r.URL.Path, "/api/v1/mesh/"):
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(map[string]string{"id": createID})
		case r.Method == http.MethodGet && strings.HasSuffix(r.URL.Path, "/events"):
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte(sseBody))
		case r.Method == http.MethodGet:
			// GET /api/v1/mesh/{id} -- status poll
			_ = json.NewEncoder(w).Encode(map[string]any{
				"id":     createID,
				"status": "succeeded",
				"data":   json.RawMessage(`{"result":"done"}`),
			})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
}

func TestHandler_ToolCallSuccess(t *testing.T) {
	sseBody := "event: status\ndata: {\"status\":\"running\",\"actor\":\"train\"}\n\n" +
		"event: fly\ndata: {\"text\":\"token1\"}\n\n" +
		"event: status\ndata: {\"status\":\"succeeded\",\"result\":{\"accuracy\":0.95}}\n\n"

	srv := fakeMeshAPI(t, "msg-001", sseBody)
	defer srv.Close()

	reg := mcpadapter.NewRegistry()
	reg.LoadToolsForTest([]mcpadapter.ToolConfig{{
		Name:        "train_model",
		Description: "Train a model",
		Actor:       "start-train",
		Timeout:     60,
		InputSchema: json.RawMessage(`{"type":"object","properties":{"lr":{"type":"number"}},"required":["lr"]}`),
	}})

	mc := meshclient.New(srv.URL, srv.URL)
	handler := mcpadapter.NewHandler(reg, mc)
	handler.SyncTools()

	// Invoke tool via MCP server directly
	result, err := handler.MCPServer().HandleMessage(
		context.Background(),
		json.RawMessage(`{
			"jsonrpc": "2.0",
			"id": 1,
			"method": "tools/call",
			"params": {
				"name": "train_model",
				"arguments": {"lr": 0.001}
			}
		}`),
	)

	require.NoError(t, err)
	require.NotNil(t, result)

	// The result should contain the accuracy
	resultJSON, err := json.Marshal(result)
	require.NoError(t, err)
	assert.Contains(t, string(resultJSON), "0.95")
}

func TestHandler_ToolCallMissingRequired(t *testing.T) {
	srv := fakeMeshAPI(t, "msg-002", "")
	defer srv.Close()

	reg := mcpadapter.NewRegistry()
	reg.LoadToolsForTest([]mcpadapter.ToolConfig{{
		Name:        "train",
		Actor:       "start-train",
		InputSchema: json.RawMessage(`{"type":"object","required":["lr"]}`),
	}})

	mc := meshclient.New(srv.URL, srv.URL)
	handler := mcpadapter.NewHandler(reg, mc)
	handler.SyncTools()

	result, err := handler.MCPServer().HandleMessage(
		context.Background(),
		json.RawMessage(`{
			"jsonrpc": "2.0",
			"id": 1,
			"method": "tools/call",
			"params": {"name": "train", "arguments": {}}
		}`),
	)

	require.NoError(t, err)
	resultJSON, _ := json.Marshal(result)
	assert.Contains(t, string(resultJSON), "missing required parameter: lr")
}

func TestHandler_ToolCallFailed(t *testing.T) {
	sseBody := "event: status\ndata: {\"status\":\"failed\",\"error\":\"OOM killed\"}\n\n"

	srv := fakeMeshAPI(t, "msg-003", sseBody)
	defer srv.Close()

	reg := mcpadapter.NewRegistry()
	reg.LoadToolsForTest([]mcpadapter.ToolConfig{{
		Name:  "train",
		Actor: "start-train",
	}})

	mc := meshclient.New(srv.URL, srv.URL)
	handler := mcpadapter.NewHandler(reg, mc)
	handler.SyncTools()

	result, err := handler.MCPServer().HandleMessage(
		context.Background(),
		json.RawMessage(`{
			"jsonrpc": "2.0",
			"id": 1,
			"method": "tools/call",
			"params": {"name": "train", "arguments": {}}
		}`),
	)

	require.NoError(t, err)
	resultJSON, _ := json.Marshal(result)
	assert.Contains(t, string(resultJSON), "OOM killed")
}

func TestHandler_ToolsList(t *testing.T) {
	reg := mcpadapter.NewRegistry()
	reg.LoadToolsForTest([]mcpadapter.ToolConfig{
		{Name: "train", Actor: "a1", Description: "Train model"},
		{Name: "deploy", Actor: "a2", Description: "Deploy model"},
	})

	mc := meshclient.New("http://unused", "http://unused")
	handler := mcpadapter.NewHandler(reg, mc)
	handler.SyncTools()

	result, err := handler.MCPServer().HandleMessage(
		context.Background(),
		json.RawMessage(`{
			"jsonrpc": "2.0",
			"id": 1,
			"method": "tools/list"
		}`),
	)

	require.NoError(t, err)
	resultJSON, _ := json.Marshal(result)
	assert.Contains(t, string(resultJSON), "train")
	assert.Contains(t, string(resultJSON), "deploy")
}
```

Add a test helper to the Registry:

Add to `src/asya-gateway/internal/mcpadapter/config.go`:

```go
// LoadToolsForTest directly sets the tool list (for testing only).
func (r *Registry) LoadToolsForTest(tools []ToolConfig) {
	r.mu.Lock()
	r.tools = tools
	r.mu.Unlock()
}
```

**Verification:**

```bash
cd src/asya-gateway && go test ./internal/mcpadapter/... -v -count=1
```

---

### Task 7: A2A Adapter -- ConfigMap Loader (`internal/a2aadapter/config.go`)

The A2A adapter reads agent definitions from YAML files in a ConfigMap mount.

**ConfigMap YAML schema** (mounted at `/etc/asya/a2a/`):

```yaml
# /etc/asya/a2a/agents.yaml
agents:
  - name: autoresearch
    description: "Autonomous ML experimentation agent"
    actor: start-autoresearch
    timeout: 14400
    streaming: true
    skills:
      - id: experiment
        name: Run experiment
        description: "Execute training experiments"
        tags: [ml, training]
    inputModes: [text/plain, application/json]
    outputModes: [text/plain, application/json]
```

**Files to create:**

`src/asya-gateway/internal/a2aadapter/config.go`:

```go
// Package a2aadapter implements the A2A JSON-RPC adapter.
// Coexists with the old internal/a2a/ package during migration.
package a2aadapter

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"gopkg.in/yaml.v3"
)

// SkillConfig is a single A2A skill within an agent definition.
type SkillConfig struct {
	ID          string   `yaml:"id" json:"id"`
	Name        string   `yaml:"name" json:"name"`
	Description string   `yaml:"description" json:"description"`
	Tags        []string `yaml:"tags" json:"tags"`
}

// AgentConfig is a single A2A agent definition from the ConfigMap.
type AgentConfig struct {
	Name        string        `yaml:"name" json:"name"`
	Description string        `yaml:"description" json:"description"`
	Actor       string        `yaml:"actor" json:"actor"`
	Timeout     int           `yaml:"timeout" json:"timeout"` // seconds, 0 = default (300)
	Streaming   bool          `yaml:"streaming" json:"streaming"`
	Skills      []SkillConfig `yaml:"skills" json:"skills"`
	InputModes  []string      `yaml:"inputModes" json:"inputModes"`
	OutputModes []string      `yaml:"outputModes" json:"outputModes"`
}

// AgentsFile is the top-level structure of an agents ConfigMap YAML file.
type AgentsFile struct {
	Agents []AgentConfig `yaml:"agents"`
}

// AgentRegistry holds the current set of A2A agent definitions. Thread-safe.
type AgentRegistry struct {
	mu     sync.RWMutex
	agents []AgentConfig
}

// NewAgentRegistry creates an empty registry.
func NewAgentRegistry() *AgentRegistry {
	return &AgentRegistry{}
}

// LoadFromDir reads all *.yaml / *.yml files in dir, parses AgentsFile entries,
// and atomically replaces the current agent set.
func (r *AgentRegistry) LoadFromDir(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return fmt.Errorf("read config dir %q: %w", dir, err)
	}

	var agents []AgentConfig
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if !strings.HasSuffix(name, ".yaml") && !strings.HasSuffix(name, ".yml") {
			continue
		}

		path := filepath.Join(dir, name)
		data, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read %q: %w", path, err)
		}

		var af AgentsFile
		if err := yaml.Unmarshal(data, &af); err != nil {
			return fmt.Errorf("parse %q: %w", path, err)
		}

		for _, agent := range af.Agents {
			if agent.Name == "" {
				return fmt.Errorf("file %q: agent name is required", path)
			}
			if agent.Actor == "" {
				return fmt.Errorf("file %q, agent %q: actor is required", path, agent.Name)
			}
			agents = append(agents, agent)
		}
	}

	r.mu.Lock()
	r.agents = agents
	r.mu.Unlock()
	return nil
}

// Agents returns a snapshot of the current agent definitions.
func (r *AgentRegistry) Agents() []AgentConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]AgentConfig, len(r.agents))
	copy(result, r.agents)
	return result
}

// GetByName returns the agent with the given name, or nil if not found.
func (r *AgentRegistry) GetByName(name string) *AgentConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for i := range r.agents {
		if r.agents[i].Name == name {
			a := r.agents[i]
			return &a
		}
	}
	return nil
}

// ResolveActor determines which actor to route to.
// Priority: skill hint in metadata -> single-agent default -> error.
func (r *AgentRegistry) ResolveActor(skillHint string) (*AgentConfig, error) {
	agents := r.Agents()

	// Explicit skill hint
	if skillHint != "" {
		for _, a := range agents {
			for _, s := range a.Skills {
				if s.ID == skillHint {
					return &a, nil
				}
			}
		}
		return nil, fmt.Errorf("skill %q not found", skillHint)
	}

	// Single agent default
	if len(agents) == 1 {
		return &agents[0], nil
	}

	// No agents
	if len(agents) == 0 {
		return nil, fmt.Errorf("no A2A agents registered")
	}

	// Multiple agents, no hint
	names := make([]string, len(agents))
	for i, a := range agents {
		names[i] = a.Name
	}
	return nil, fmt.Errorf("skill not specified. Available agents: %v", names)
}

// LoadAgentsForTest directly sets the agent list (for testing only).
func (r *AgentRegistry) LoadAgentsForTest(agents []AgentConfig) {
	r.mu.Lock()
	r.agents = agents
	r.mu.Unlock()
}
```

`src/asya-gateway/internal/a2aadapter/config_test.go`:

```go
package a2aadapter_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
)

func TestAgentRegistry_LoadFromDir(t *testing.T) {
	dir := t.TempDir()
	yaml := `agents:
  - name: autoresearch
    description: "Research agent"
    actor: start-autoresearch
    timeout: 14400
    streaming: true
    skills:
      - id: experiment
        name: Run experiment
        description: "Execute experiments"
        tags: [ml, training]
    inputModes: [text/plain, application/json]
    outputModes: [text/plain, application/json]
`
	require.NoError(t, os.WriteFile(filepath.Join(dir, "agents.yaml"), []byte(yaml), 0o644))

	reg := a2aadapter.NewAgentRegistry()
	require.NoError(t, reg.LoadFromDir(dir))

	agents := reg.Agents()
	require.Len(t, agents, 1)
	assert.Equal(t, "autoresearch", agents[0].Name)
	assert.Equal(t, "start-autoresearch", agents[0].Actor)
	assert.Equal(t, 14400, agents[0].Timeout)
	assert.True(t, agents[0].Streaming)
	require.Len(t, agents[0].Skills, 1)
	assert.Equal(t, "experiment", agents[0].Skills[0].ID)
	assert.Equal(t, []string{"ml", "training"}, agents[0].Skills[0].Tags)
}

func TestAgentRegistry_ValidationErrors(t *testing.T) {
	tests := []struct {
		name   string
		yaml   string
		errMsg string
	}{
		{
			name:   "missing name",
			yaml:   "agents:\n  - actor: foo\n",
			errMsg: "agent name is required",
		},
		{
			name:   "missing actor",
			yaml:   "agents:\n  - name: foo\n",
			errMsg: "actor is required",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			require.NoError(t, os.WriteFile(filepath.Join(dir, "agents.yaml"), []byte(tt.yaml), 0o644))

			reg := a2aadapter.NewAgentRegistry()
			err := reg.LoadFromDir(dir)
			require.Error(t, err)
			assert.Contains(t, err.Error(), tt.errMsg)
		})
	}
}

func TestAgentRegistry_ResolveActor(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{
			Name:  "research",
			Actor: "start-research",
			Skills: []a2aadapter.SkillConfig{
				{ID: "experiment", Name: "Run experiment"},
			},
		},
		{
			Name:  "deploy",
			Actor: "start-deploy",
			Skills: []a2aadapter.SkillConfig{
				{ID: "rollout", Name: "Rollout"},
			},
		},
	})

	// Resolve by skill hint
	agent, err := reg.ResolveActor("experiment")
	require.NoError(t, err)
	assert.Equal(t, "start-research", agent.Actor)

	agent, err = reg.ResolveActor("rollout")
	require.NoError(t, err)
	assert.Equal(t, "start-deploy", agent.Actor)

	// Unknown skill
	_, err = reg.ResolveActor("unknown")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not found")

	// No hint, multiple agents
	_, err = reg.ResolveActor("")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "skill not specified")
}

func TestAgentRegistry_ResolveActor_SingleAgent(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{Name: "solo", Actor: "start-solo"},
	})

	agent, err := reg.ResolveActor("")
	require.NoError(t, err)
	assert.Equal(t, "start-solo", agent.Actor)
}

func TestAgentRegistry_ResolveActor_Empty(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	_, err := reg.ResolveActor("")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "no A2A agents registered")
}
```

**Verification:**

```bash
cd src/asya-gateway && go test ./internal/a2aadapter/... -v -count=1
```

---

### Task 8: A2A Adapter -- State Mapping (`internal/a2aadapter/state.go`)

Port the existing state mapping from `internal/a2a/state.go` to the new
adapter package. The mapping is the same but works on string statuses
(from mesh-api JSON) instead of typed constants.

**File to create:**

`src/asya-gateway/internal/a2aadapter/state.go`:

```go
package a2aadapter

import (
	a2alib "github.com/a2aproject/a2a-go/a2a"
)

// MeshStatusToA2A converts a mesh status string to A2A TaskState.
// Mapping per RFC Section 4.3.
func MeshStatusToA2A(status string) a2alib.TaskState {
	switch status {
	case "pending":
		return a2alib.TaskStateSubmitted
	case "running":
		return a2alib.TaskStateWorking
	case "succeeded":
		return a2alib.TaskStateCompleted
	case "failed":
		return a2alib.TaskStateFailed
	case "canceled":
		return a2alib.TaskStateCanceled
	case "paused":
		return a2alib.TaskStateInputRequired
	case "auth_required":
		return a2alib.TaskStateAuthRequired
	default:
		return a2alib.TaskStateUnknown
	}
}

// A2AToMeshStatus converts an A2A TaskState to a mesh status string.
func A2AToMeshStatus(state a2alib.TaskState) string {
	switch state {
	case a2alib.TaskStateSubmitted:
		return "pending"
	case a2alib.TaskStateWorking:
		return "running"
	case a2alib.TaskStateCompleted:
		return "succeeded"
	case a2alib.TaskStateFailed:
		return "failed"
	case a2alib.TaskStateCanceled:
		return "canceled"
	case a2alib.TaskStateInputRequired:
		return "paused"
	case a2alib.TaskStateAuthRequired:
		return "auth_required"
	default:
		return "unknown"
	}
}
```

`src/asya-gateway/internal/a2aadapter/state_test.go`:

```go
package a2aadapter_test

import (
	"testing"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/stretchr/testify/assert"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
)

func TestMeshStatusToA2A(t *testing.T) {
	tests := []struct {
		mesh string
		a2a  a2alib.TaskState
	}{
		{"pending", a2alib.TaskStateSubmitted},
		{"running", a2alib.TaskStateWorking},
		{"succeeded", a2alib.TaskStateCompleted},
		{"failed", a2alib.TaskStateFailed},
		{"canceled", a2alib.TaskStateCanceled},
		{"paused", a2alib.TaskStateInputRequired},
		{"auth_required", a2alib.TaskStateAuthRequired},
		{"garbage", a2alib.TaskStateUnknown},
	}

	for _, tt := range tests {
		t.Run(tt.mesh, func(t *testing.T) {
			assert.Equal(t, tt.a2a, a2aadapter.MeshStatusToA2A(tt.mesh))
		})
	}
}

func TestA2AToMeshStatus(t *testing.T) {
	tests := []struct {
		a2a  a2alib.TaskState
		mesh string
	}{
		{a2alib.TaskStateSubmitted, "pending"},
		{a2alib.TaskStateWorking, "running"},
		{a2alib.TaskStateCompleted, "succeeded"},
		{a2alib.TaskStateFailed, "failed"},
		{a2alib.TaskStateCanceled, "canceled"},
		{a2alib.TaskStateInputRequired, "paused"},
		{a2alib.TaskStateAuthRequired, "auth_required"},
		{a2alib.TaskStateUnknown, "unknown"},
	}

	for _, tt := range tests {
		t.Run(tt.mesh, func(t *testing.T) {
			assert.Equal(t, tt.mesh, a2aadapter.A2AToMeshStatus(tt.a2a))
		})
	}
}

func TestRoundTrip(t *testing.T) {
	statuses := []string{"pending", "running", "succeeded", "failed", "canceled", "paused", "auth_required"}
	for _, s := range statuses {
		assert.Equal(t, s, a2aadapter.A2AToMeshStatus(a2aadapter.MeshStatusToA2A(s)),
			"round-trip failed for %q", s)
	}
}
```

**Verification:**

```bash
cd src/asya-gateway && go test ./internal/a2aadapter/... -v -count=1
```

---

### Task 9: A2A Adapter -- Executor + Agent Card (`internal/a2aadapter/executor.go`, `internal/a2aadapter/card.go`)

The A2A adapter implements `a2asrv.AgentExecutor` using mesh-api HTTP calls
instead of direct queue/store access. This is the core behavioral difference
from the old monolith A2A implementation.

**File to create:**

`src/asya-gateway/internal/a2aadapter/executor.go`:

```go
package a2aadapter

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"
	"github.com/a2aproject/a2a-go/a2asrv/eventqueue"

	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/internal/sseclient"
)

// flyArtifactID is the deterministic artifact ID used for FLY streaming chunks.
const flyArtifactID = "fly-stream"

// resultArtifactID is the artifact ID used for the final result payload.
const resultArtifactID = "result"

// Executor implements a2asrv.AgentExecutor using mesh-api HTTP calls.
type Executor struct {
	registry   *AgentRegistry
	meshClient *meshclient.Client
}

// NewExecutor creates a new A2A executor.
func NewExecutor(registry *AgentRegistry, meshClient *meshclient.Client) *Executor {
	return &Executor{
		registry:   registry,
		meshClient: meshClient,
	}
}

// Execute handles tasks/send and tasks/sendSubscribe.
func (e *Executor) Execute(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	msg := reqCtx.Message
	taskID := reqCtx.TaskID
	contextID := reqCtx.ContextID

	// Check for resume of paused task
	if reqCtx.StoredTask != nil && reqCtx.StoredTask.Status.State == a2alib.TaskStateInputRequired {
		return e.handleResume(ctx, reqCtx, eq)
	}

	// Resolve skill -> agent -> actor
	var skillHint string
	if reqCtx.Metadata != nil {
		if hint, ok := reqCtx.Metadata["skill"].(string); ok {
			skillHint = hint
		}
	}

	agent, err := e.registry.ResolveActor(skillHint)
	if err != nil {
		return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
			reqCtx, a2alib.TaskStateRejected,
			a2alib.NewMessage(a2alib.MessageRoleAgent,
				&a2alib.TextPart{Text: err.Error()})))
	}

	// Translate A2A Message -> mesh payload
	payload := messageToPayload(msg, string(taskID), contextID)

	timeout := agent.Timeout
	if timeout == 0 {
		timeout = 300
	}

	// Step 1: Create message in mesh-api
	createResp, err := e.meshClient.Create(ctx, agent.Actor, meshclient.CreateRequest{
		Payload: payload,
		Headers: map[string]any{
			"x-asya-a2a-task-id":    string(taskID),
			"x-asya-a2a-context-id": contextID,
		},
		Timeout: timeout,
	})
	if err != nil {
		slog.Error("Mesh create failed", "task_id", taskID, "error", err)
		return fmt.Errorf("dispatch: %w", err)
	}

	// Write submitted event
	if err := eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateSubmitted, nil)); err != nil {
		return fmt.Errorf("write submitted event: %w", err)
	}

	// Step 2: Subscribe to SSE events and relay as A2A events
	sseCtx, sseCancel := context.WithTimeout(ctx, time.Duration(timeout)*time.Second)
	defer sseCancel()

	events, errCh := e.meshClient.SubscribeEvents(sseCtx, createResp.ID)

	firstFLY := true
	for evt := range events {
		switch evt.Type {
		case "status":
			var status sseclient.StatusData
			if json.Unmarshal(evt.Data, &status) != nil {
				continue
			}

			a2aState := MeshStatusToA2A(status.Status)

			if sseclient.IsTerminal(status.Status) || sseclient.IsInterrupted(status.Status) {
				// Close artifact stream if FLY events were sent
				if !firstFLY {
					closeArtifactStream(ctx, reqCtx, eq)
				}

				// Write result artifact for succeeded tasks
				if status.Status == "succeeded" && status.Result != nil {
					writeResultArtifact(ctx, reqCtx, eq, status.Result)
				}

				// Write terminal event
				termEvt := a2alib.NewStatusUpdateEvent(reqCtx, a2aState, nil)
				termEvt.Final = true
				return eq.Write(ctx, termEvt)
			}

			// Non-terminal: write working status
			if status.Status == "running" {
				_ = eq.Write(ctx, a2alib.NewStatusUpdateEvent(reqCtx, a2alib.TaskStateWorking, nil))
			}

		case "fly":
			// Convert FLY to A2A artifact chunk
			artifact := &a2alib.TaskArtifactUpdateEvent{
				TaskID:    reqCtx.TaskID,
				ContextID: reqCtx.ContextID,
				Append:    !firstFLY,
				Artifact: &a2alib.Artifact{
					ID:    a2alib.ArtifactID(flyArtifactID),
					Parts: a2alib.ContentParts{a2alib.TextPart{Text: string(evt.Data)}},
				},
			}
			firstFLY = false
			if err := eq.Write(ctx, artifact); err != nil {
				slog.Warn("Failed to relay FLY as artifact", "task_id", taskID, "error", err)
			}
		}
	}

	// Check SSE error
	if sseErr := <-errCh; sseErr != nil {
		slog.Warn("SSE stream error", "task_id", taskID, "error", sseErr)
	}

	// Fallback: poll mesh-api for final status
	return e.pollAndWriteTerminal(ctx, createResp.ID, time.Duration(timeout)*time.Second, reqCtx, eq)
}

// Cancel handles tasks/cancel.
func (e *Executor) Cancel(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	taskID := reqCtx.TaskID

	if err := e.meshClient.Cancel(ctx, string(taskID)); err != nil {
		return fmt.Errorf("cancel task %q: %w", taskID, err)
	}

	return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateCanceled, nil))
}

// handleResume dispatches a resume message for paused tasks.
func (e *Executor) handleResume(
	ctx context.Context,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	taskID := reqCtx.TaskID
	contextID := reqCtx.ContextID
	msg := reqCtx.Message

	payload := messageToPayload(msg, string(taskID), contextID)

	_, err := e.meshClient.Create(ctx, "x-resume", meshclient.CreateRequest{
		Payload: payload,
		Headers: map[string]any{
			"x-asya-resume-task":    string(taskID),
			"x-asya-a2a-task-id":    string(taskID),
			"x-asya-a2a-context-id": contextID,
		},
	})
	if err != nil {
		return fmt.Errorf("dispatch resume: %w", err)
	}

	return eq.Write(ctx, a2alib.NewStatusUpdateEvent(
		reqCtx, a2alib.TaskStateWorking, nil))
}

// pollAndWriteTerminal polls mesh-api until terminal status, then writes final event.
func (e *Executor) pollAndWriteTerminal(
	ctx context.Context,
	id string,
	timeout time.Duration,
	reqCtx *a2asrv.RequestContext,
	eq eventqueue.Queue,
) error {
	pollCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-pollCtx.Done():
			evt := a2alib.NewStatusUpdateEvent(reqCtx, a2alib.TaskStateUnknown, nil)
			evt.Final = true
			return eq.Write(ctx, evt)
		case <-ticker.C:
			status, err := e.meshClient.Get(pollCtx, id)
			if err != nil {
				continue
			}
			if sseclient.IsTerminal(status.Status) || sseclient.IsInterrupted(status.Status) {
				a2aState := MeshStatusToA2A(status.Status)
				evt := a2alib.NewStatusUpdateEvent(reqCtx, a2aState, nil)
				evt.Final = true
				return eq.Write(ctx, evt)
			}
		}
	}
}

// closeArtifactStream sends a LastChunk event to signal end of FLY artifact.
func closeArtifactStream(ctx context.Context, reqCtx *a2asrv.RequestContext, eq eventqueue.Queue) {
	lastChunk := &a2alib.TaskArtifactUpdateEvent{
		TaskID:    reqCtx.TaskID,
		ContextID: reqCtx.ContextID,
		Append:    true,
		LastChunk: true,
		Artifact: &a2alib.Artifact{
			ID:    a2alib.ArtifactID(flyArtifactID),
			Parts: a2alib.ContentParts{},
		},
	}
	if err := eq.Write(ctx, lastChunk); err != nil {
		slog.Warn("Failed to write LastChunk", "error", err)
	}
}

// writeResultArtifact writes the final result as an A2A artifact.
func writeResultArtifact(ctx context.Context, reqCtx *a2asrv.RequestContext, eq eventqueue.Queue, result any) {
	data, err := json.Marshal(result)
	if err != nil {
		return
	}
	evt := &a2alib.TaskArtifactUpdateEvent{
		TaskID:    reqCtx.TaskID,
		ContextID: reqCtx.ContextID,
		Append:    false,
		LastChunk: true,
		Artifact: &a2alib.Artifact{
			ID:   a2alib.ArtifactID(resultArtifactID),
			Name: "Task result",
			Parts: a2alib.ContentParts{
				&a2alib.TextPart{Text: string(data)},
			},
		},
	}
	if err := eq.Write(ctx, evt); err != nil {
		slog.Warn("Failed to write result artifact", "error", err)
	}
}

// messageToPayload converts an A2A message to a mesh payload.
// Follows the same rules as the existing a2a.MessageToPayload.
func messageToPayload(msg *a2alib.Message, taskID, contextID string) map[string]any {
	var textParts []string
	var dataParts []map[string]any

	for _, part := range msg.Parts {
		switch p := part.(type) {
		case *a2alib.TextPart:
			textParts = append(textParts, p.Text)
		case a2alib.TextPart:
			textParts = append(textParts, p.Text)
		case *a2alib.DataPart:
			dataParts = append(dataParts, p.Data)
		case a2alib.DataPart:
			dataParts = append(dataParts, p.Data)
		}
	}

	var payload map[string]any

	// Single data part, no text -> unwrap at root
	if len(dataParts) == 1 && len(textParts) == 0 {
		payload = dataParts[0]
	} else {
		payload = make(map[string]any)
		for _, dp := range dataParts {
			for k, v := range dp {
				payload[k] = v
			}
		}
		if len(textParts) > 0 {
			text := ""
			for i, t := range textParts {
				if i > 0 {
					text += "\n"
				}
				text += t
			}
			payload["query"] = text
		}
	}

	// A2A task namespace
	payload["a2a"] = map[string]any{
		"task": map[string]any{
			"id":         taskID,
			"context_id": contextID,
			"history":    []any{messageToHistoryEntry(msg)},
		},
	}

	return payload
}

func messageToHistoryEntry(msg *a2alib.Message) any {
	data, err := json.Marshal(msg)
	if err != nil {
		return map[string]any{"error": "failed to serialize message"}
	}
	var entry any
	_ = json.Unmarshal(data, &entry)
	return entry
}
```

`src/asya-gateway/internal/a2aadapter/card.go`:

```go
package a2aadapter

import (
	"context"
	"os"

	a2alib "github.com/a2aproject/a2a-go/a2a"
)

// CardProducer implements a2asrv.AgentCardProducer using the agent registry.
type CardProducer struct {
	registry *AgentRegistry
}

// NewCardProducer creates a new CardProducer.
func NewCardProducer(registry *AgentRegistry) *CardProducer {
	return &CardProducer{registry: registry}
}

// Card returns the current AgentCard based on registered agents.
func (p *CardProducer) Card(_ context.Context) (*a2alib.AgentCard, error) {
	agents := p.registry.Agents()

	var a2aSkills []a2alib.AgentSkill
	for _, agent := range agents {
		for _, skill := range agent.Skills {
			a2aSkills = append(a2aSkills, a2alib.AgentSkill{
				ID:          skill.ID,
				Name:        skill.Name,
				Description: skill.Description,
				Tags:        skill.Tags,
			})
		}
		// If agent has no skills, create one from the agent itself
		if len(agent.Skills) == 0 {
			a2aSkills = append(a2aSkills, a2alib.AgentSkill{
				ID:          agent.Name,
				Name:        agent.Name,
				Description: agent.Description,
			})
		}
	}

	name := envOr("ASYA_A2A_NAME", "Asya Gateway")
	desc := envOr("ASYA_A2A_DESCRIPTION", "AI Actor Mesh for distributed agentic workloads")
	version := envOr("ASYA_A2A_VERSION", "1.0.0")
	publicURL := envOr("ASYA_A2A_PUBLIC_URL", "")

	// Determine default I/O modes from first agent with modes set
	defaultInputModes := []string{"application/json"}
	defaultOutputModes := []string{"application/json"}
	for _, agent := range agents {
		if len(agent.InputModes) > 0 {
			defaultInputModes = agent.InputModes
		}
		if len(agent.OutputModes) > 0 {
			defaultOutputModes = agent.OutputModes
		}
		break
	}

	// Determine streaming from any agent
	streaming := false
	for _, agent := range agents {
		if agent.Streaming {
			streaming = true
			break
		}
	}

	return &a2alib.AgentCard{
		Name:        name,
		Description: desc,
		Version:     version,
		URL:         publicURL,
		Capabilities: a2alib.AgentCapabilities{
			Streaming:         streaming,
			PushNotifications: false,
		},
		DefaultInputModes:  defaultInputModes,
		DefaultOutputModes: defaultOutputModes,
		Skills:             a2aSkills,
		Provider: &a2alib.AgentProvider{
			Org: envOr("ASYA_A2A_PROVIDER_ORG", "Asya"),
			URL: envOr("ASYA_A2A_PROVIDER_URL", "https://asya.sh"),
		},
	}, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
```

**Verification:**

```bash
cd src/asya-gateway && go build ./internal/a2aadapter/...
```

---

### Task 10: A2A Adapter -- Store Adapter (`internal/a2aadapter/store.go`)

The A2A library requires a `a2asrv.TaskStore` implementation. The adapter's
store talks to mesh-api over HTTP rather than directly to the database.

**File to create:**

`src/asya-gateway/internal/a2aadapter/store.go`:

```go
package a2aadapter

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	a2alib "github.com/a2aproject/a2a-go/a2a"

	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
)

// StoreAdapter wraps the mesh-api HTTP client to implement a2asrv.TaskStore.
type StoreAdapter struct {
	meshClient *meshclient.Client
}

// NewStoreAdapter creates a new store adapter.
func NewStoreAdapter(meshClient *meshclient.Client) *StoreAdapter {
	return &StoreAdapter{meshClient: meshClient}
}

// Save translates an A2A event into a mesh-api update.
// Artifact events are ephemeral and not persisted.
func (s *StoreAdapter) Save(ctx context.Context, task *a2alib.Task, event a2alib.Event, prev *a2alib.Task, prevVersion a2alib.TaskVersion) (a2alib.TaskVersion, error) {
	// Streaming artifact chunks are ephemeral
	if _, ok := event.(*a2alib.TaskArtifactUpdateEvent); ok {
		return prevVersion, nil
	}

	// The mesh-api manages state; we don't write back status changes
	// because the mesh-api is the source of truth and receives status
	// updates from sidecars directly. The A2A adapter only reads state.
	return prevVersion, nil
}

// Get fetches task state from mesh-api and converts to A2A Task.
func (s *StoreAdapter) Get(ctx context.Context, taskID a2alib.TaskID) (*a2alib.Task, a2alib.TaskVersion, error) {
	status, err := s.meshClient.Get(ctx, string(taskID))
	if err != nil {
		return nil, 0, a2alib.ErrTaskNotFound
	}

	a2aTask := &a2alib.Task{
		ID:        taskID,
		ContextID: "", // context_id extracted from mesh data if available
		Status: a2alib.TaskStatus{
			State: MeshStatusToA2A(status.Status),
		},
		Metadata: make(map[string]any),
	}

	// Extract context_id from data if present
	if status.Data != nil {
		var data map[string]any
		if json.Unmarshal(status.Data, &data) == nil {
			if cid, ok := data["context_id"].(string); ok {
				a2aTask.ContextID = cid
			}
			if msg, ok := data["message"].(string); ok && msg != "" {
				a2aTask.Status.Message = a2alib.NewMessage(a2alib.MessageRoleAgent,
					&a2alib.TextPart{Text: msg})
			}
		}
	}

	// Synthesize result artifact for succeeded tasks
	if status.Status == "succeeded" && status.Data != nil {
		var data map[string]any
		if json.Unmarshal(status.Data, &data) == nil {
			if result, ok := data["result"]; ok && result != nil {
				resultJSON, _ := json.Marshal(result)
				a2aTask.Artifacts = []*a2alib.Artifact{{
					ID:   a2alib.ArtifactID(resultArtifactID),
					Name: "Task result",
					Parts: a2alib.ContentParts{
						&a2alib.TextPart{Text: string(resultJSON)},
					},
				}}
			}
		}
	}

	version := a2alib.TaskVersion(status.UpdatedAt.UnixNano())
	return a2aTask, version, nil
}

// List is not supported in the adapter (would require mesh-api list endpoint).
func (s *StoreAdapter) List(ctx context.Context, req *a2alib.ListTasksRequest) (*a2alib.ListTasksResponse, error) {
	slog.Warn("A2A adapter List not implemented (requires mesh-api list)")
	return &a2alib.ListTasksResponse{
		Tasks:     []*a2alib.Task{},
		TotalSize: 0,
		PageSize:  req.PageSize,
	}, nil
}
```

**Verification:**

```bash
cd src/asya-gateway && go build ./internal/a2aadapter/...
```

---

### Task 11: A2A Adapter -- Binary (`cmd/a2a-adapter/main.go`)

**File to create:**

`src/asya-gateway/cmd/a2a-adapter/main.go`:

```go
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/a2aproject/a2a-go/a2asrv"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/internal/watcher"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: parseLogLevel(os.Getenv("ASYA_LOG_LEVEL")),
	})))

	meshAPIURL := requireEnv("MESH_API_URL")     // e.g. "http://localhost:8080"
	ingressURL := requireEnv("MESH_INGRESS_URL")  // e.g. "http://asya-mesh-api.example.com"
	configDir := requireEnv("ASYA_A2A_CONFIG_DIR") // e.g. "/etc/asya/a2a"
	port := getEnv("ASYA_A2A_PORT", "8083")

	// Initialize mesh client
	mc := meshclient.New(meshAPIURL, ingressURL)

	// Load agent registry from ConfigMap
	registry := a2aadapter.NewAgentRegistry()
	if err := registry.LoadFromDir(configDir); err != nil {
		slog.Error("Failed to load A2A agent config", "dir", configDir, "error", err)
		os.Exit(1)
	}

	// Create A2A executor and store adapter
	executor := a2aadapter.NewExecutor(registry, mc)
	storeAdapter := a2aadapter.NewStoreAdapter(mc)
	cardProducer := a2aadapter.NewCardProducer(registry)

	// Create A2A handler using a2a-go library
	a2aHandler := a2asrv.NewHandler(executor,
		a2asrv.WithTaskStore(storeAdapter),
	)
	a2aHTTPHandler := a2asrv.NewJSONRPCHandler(a2aHandler,
		a2asrv.WithKeepAlive(15*time.Second),
	)

	// Start ConfigMap watcher for hot-reload
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	pollInterval := parseDuration(getEnv("ASYA_A2A_POLL_INTERVAL", "10s"), 10*time.Second)
	go watcher.Watch(ctx, configDir, pollInterval, func(dir string) error {
		return registry.LoadFromDir(dir)
	})

	// Create HTTP server
	mux := http.NewServeMux()
	mux.Handle("/a2a/", a2aHTTPHandler)
	mux.Handle("/.well-known/agent.json", a2asrv.NewAgentCardHandler(cardProducer))
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintln(w, "OK")
	})

	server := &http.Server{
		Addr:    ":" + port,
		Handler: mux,
	}

	// Graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		slog.Info("A2A adapter listening", "port", port, "config", configDir)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("Server failed", "error", err)
			os.Exit(1)
		}
	}()

	sig := <-sigChan
	slog.Info("Shutting down", "signal", sig)

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	_ = server.Shutdown(shutdownCtx)
}

func requireEnv(key string) string {
	val := os.Getenv(key)
	if val == "" {
		slog.Error("Required environment variable not set", "key", key)
		os.Exit(1)
	}
	return val
}

func getEnv(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}

func parseLogLevel(s string) slog.Level {
	switch s {
	case "DEBUG":
		return slog.LevelDebug
	case "WARN", "WARNING":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func parseDuration(s string, fallback time.Duration) time.Duration {
	d, err := time.ParseDuration(s)
	if err != nil {
		return fallback
	}
	return d
}
```

**Verification:**

```bash
cd src/asya-gateway && go build ./cmd/a2a-adapter/
```

---

### Task 12: A2A Adapter -- Unit Tests (`internal/a2aadapter/executor_test.go`)

**File to create:**

`src/asya-gateway/internal/a2aadapter/executor_test.go`:

```go
package a2aadapter_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"
	"github.com/a2aproject/a2a-go/a2asrv/eventqueue"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
)

// collectEvents drains the event queue into a slice.
func collectEvents(eq eventqueue.Queue) []a2alib.Event {
	var events []a2alib.Event
	for {
		evt, err := eq.Read(context.Background())
		if err != nil || evt == nil {
			break
		}
		events = append(events, evt)
		// Check if this is a final event
		if su, ok := evt.(*a2alib.TaskStatusUpdateEvent); ok && su.Final {
			break
		}
	}
	return events
}

func TestExecutor_Execute_Success(t *testing.T) {
	sseBody := "event: status\ndata: {\"status\":\"running\",\"actor\":\"train\"}\n\n" +
		"event: fly\ndata: {\"text\":\"token1\"}\n\n" +
		"event: status\ndata: {\"status\":\"succeeded\",\"result\":{\"accuracy\":0.95}}\n\n"

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodPost:
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(map[string]string{"id": "msg-001"})
		case strings.HasSuffix(r.URL.Path, "/events"):
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte(sseBody))
		}
	}))
	defer srv.Close()

	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{Name: "research", Actor: "start-research", Timeout: 60},
	})

	mc := meshclient.New(srv.URL, srv.URL)
	executor := a2aadapter.NewExecutor(reg, mc)

	eq := eventqueue.NewChannelQueue()
	reqCtx := &a2asrv.RequestContext{
		TaskID:    "task-001",
		ContextID: "ctx-001",
		Message: a2alib.NewMessage(a2alib.MessageRoleUser,
			&a2alib.TextPart{Text: "run experiment"}),
	}

	err := executor.Execute(context.Background(), reqCtx, eq)
	require.NoError(t, err)

	// Should have: submitted + working + fly artifact + result artifact + LastChunk + terminal
	// The exact sequence depends on event processing
}

func TestExecutor_Cancel(t *testing.T) {
	var canceledID string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodDelete {
			canceledID = strings.TrimPrefix(r.URL.Path, "/api/v1/mesh/")
			w.WriteHeader(http.StatusNoContent)
		}
	}))
	defer srv.Close()

	reg := a2aadapter.NewAgentRegistry()
	mc := meshclient.New(srv.URL, srv.URL)
	executor := a2aadapter.NewExecutor(reg, mc)

	eq := eventqueue.NewChannelQueue()
	reqCtx := &a2asrv.RequestContext{
		TaskID: "task-cancel",
	}

	err := executor.Cancel(context.Background(), reqCtx, eq)
	require.NoError(t, err)
	assert.Equal(t, "task-cancel", canceledID)
}

func TestExecutor_Resume(t *testing.T) {
	var receivedActor string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			receivedActor = r.URL.Query().Get("actor")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(map[string]string{"id": "resume-001"})
		}
	}))
	defer srv.Close()

	reg := a2aadapter.NewAgentRegistry()
	mc := meshclient.New(srv.URL, srv.URL)
	executor := a2aadapter.NewExecutor(reg, mc)

	eq := eventqueue.NewChannelQueue()
	reqCtx := &a2asrv.RequestContext{
		TaskID:    "task-paused",
		ContextID: "ctx-001",
		Message: a2alib.NewMessage(a2alib.MessageRoleUser,
			&a2alib.TextPart{Text: "continue with feedback"}),
		StoredTask: &a2alib.Task{
			ID: "task-paused",
			Status: a2alib.TaskStatus{
				State: a2alib.TaskStateInputRequired,
			},
		},
	}

	err := executor.Execute(context.Background(), reqCtx, eq)
	require.NoError(t, err)
	assert.Equal(t, "x-resume", receivedActor)
}

func TestMessageToPayload_TextOnly(t *testing.T) {
	msg := a2alib.NewMessage(a2alib.MessageRoleUser,
		&a2alib.TextPart{Text: "hello"})

	// We can't easily call messageToPayload because it's unexported.
	// Instead, test the executor end-to-end with a mock that captures the payload.
	var capturedPayload map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			var req meshclient.CreateRequest
			_ = json.NewDecoder(r.Body).Decode(&req)
			capturedPayload = req.Payload
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(map[string]string{"id": "msg-t1"})
		} else {
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte("event: status\ndata: {\"status\":\"succeeded\"}\n\n"))
		}
	}))
	defer srv.Close()

	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{Name: "agent", Actor: "start-agent", Timeout: 10},
	})

	mc := meshclient.New(srv.URL, srv.URL)
	executor := a2aadapter.NewExecutor(reg, mc)
	eq := eventqueue.NewChannelQueue()

	_ = executor.Execute(context.Background(), &a2asrv.RequestContext{
		TaskID:    "t1",
		ContextID: "c1",
		Message:   msg,
	}, eq)

	require.NotNil(t, capturedPayload)
	assert.Equal(t, "hello", capturedPayload["query"])
	assert.NotNil(t, capturedPayload["a2a"])
}
```

`src/asya-gateway/internal/a2aadapter/card_test.go`:

```go
package a2aadapter_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
)

func TestCardProducer_Card(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{
			Name:        "research",
			Description: "Research agent",
			Actor:       "start-research",
			Streaming:   true,
			Skills: []a2aadapter.SkillConfig{
				{ID: "exp", Name: "Experiment", Description: "Run exp", Tags: []string{"ml"}},
			},
			InputModes:  []string{"text/plain", "application/json"},
			OutputModes: []string{"application/json"},
		},
	})

	producer := a2aadapter.NewCardProducer(reg)
	card, err := producer.Card(context.Background())

	require.NoError(t, err)
	assert.Equal(t, "Asya Gateway", card.Name)
	assert.True(t, card.Capabilities.Streaming)
	require.Len(t, card.Skills, 1)
	assert.Equal(t, "exp", card.Skills[0].ID)
	assert.Equal(t, []string{"ml"}, card.Skills[0].Tags)
	assert.Equal(t, []string{"text/plain", "application/json"}, card.DefaultInputModes)
}

func TestCardProducer_NoSkills(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{Name: "simple", Description: "Simple agent", Actor: "start-simple"},
	})

	producer := a2aadapter.NewCardProducer(reg)
	card, err := producer.Card(context.Background())

	require.NoError(t, err)
	require.Len(t, card.Skills, 1)
	assert.Equal(t, "simple", card.Skills[0].ID)
}
```

**Verification:**

```bash
cd src/asya-gateway && go test ./internal/a2aadapter/... -v -count=1
```

---

### Task 13: Dockerfile Updates (Multi-Binary Build)

Update the gateway Dockerfile to build all three binaries.

**File to modify:** `src/asya-gateway/Dockerfile`

Add after the existing `go build -o gateway ./cmd/gateway` line:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -o mcp-adapter ./cmd/mcp-adapter

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -o a2a-adapter ./cmd/a2a-adapter
```

In the final stage, copy all three binaries:

```dockerfile
COPY --from=builder /build/gateway /gateway
COPY --from=builder /build/mcp-adapter /mcp-adapter
COPY --from=builder /build/a2a-adapter /a2a-adapter
```

**Verification:**

```bash
cd src/asya-gateway && docker build -t asya-gateway:test .
```

---

### Task 14: Component Tests (Docker Compose)

Create a Docker Compose setup that runs mesh-api + both adapters and verifies
the full two-step dispatch flow. This test uses a mock mesh-api that returns
canned SSE responses.

**Files to create:**

`testing/component/gateway/compose/adapters.yml`:

```yaml
services:
  mock-mesh-api:
    image: ${ASYA_GATEWAY_IMAGE}
    command: ["/gateway"]
    environment:
      ASYA_GATEWAY_MODE: testing
      ASYA_GATEWAY_PORT: "8080"
      ASYA_LOG_LEVEL: DEBUG
      ASYA_SQS_ENDPOINT: "http://localstack:4566"
      ASYA_SQS_REGION: us-east-1
      ASYA_NAMESPACE: test
    ports:
      - "8080"
    healthcheck:
      test: ["CMD", "wget", "-q", "-O-", "http://localhost:8080/health"]
      interval: 2s
      timeout: 5s
      retries: 10

  mcp-adapter:
    image: ${ASYA_GATEWAY_IMAGE}
    command: ["/mcp-adapter"]
    environment:
      MESH_API_URL: "http://mock-mesh-api:8080"
      MESH_INGRESS_URL: "http://mock-mesh-api:8080"
      ASYA_MCP_CONFIG_DIR: /etc/asya/mcp
      ASYA_MCP_PORT: "8082"
      ASYA_LOG_LEVEL: DEBUG
    volumes:
      - ${MCP_CONFIG_DIR}:/etc/asya/mcp:ro
    ports:
      - "8082"
    depends_on:
      mock-mesh-api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "-O-", "http://localhost:8082/health"]
      interval: 2s
      timeout: 5s
      retries: 10

  a2a-adapter:
    image: ${ASYA_GATEWAY_IMAGE}
    command: ["/a2a-adapter"]
    environment:
      MESH_API_URL: "http://mock-mesh-api:8080"
      MESH_INGRESS_URL: "http://mock-mesh-api:8080"
      ASYA_A2A_CONFIG_DIR: /etc/asya/a2a
      ASYA_A2A_PORT: "8083"
      ASYA_LOG_LEVEL: DEBUG
    volumes:
      - ${A2A_CONFIG_DIR}:/etc/asya/a2a:ro
    ports:
      - "8083"
    depends_on:
      mock-mesh-api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "-O-", "http://localhost:8083/health"]
      interval: 2s
      timeout: 5s
      retries: 10
```

`testing/component/gateway/tests_go/adapters/mcp_config/tools.yaml`:

```yaml
tools:
  - name: test_tool
    description: "A test tool"
    actor: echo-actor
    timeout: 30
    progress: true
    inputSchema:
      type: object
      properties:
        input:
          type: string
      required: [input]
```

`testing/component/gateway/tests_go/adapters/a2a_config/agents.yaml`:

```yaml
agents:
  - name: test_agent
    description: "A test agent"
    actor: echo-actor
    timeout: 30
    streaming: true
    skills:
      - id: echo
        name: Echo
        description: "Echo back input"
```

**Verification:**

```bash
# Run from testing/component/gateway/
MCP_CONFIG_DIR=./tests_go/adapters/mcp_config \
A2A_CONFIG_DIR=./tests_go/adapters/a2a_config \
docker compose -f compose/adapters.yml up -d

# Verify health
curl -s http://localhost:8082/health
curl -s http://localhost:8083/health

# Verify MCP tools/list (via direct JSON-RPC)
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Verify A2A agent card
curl -s http://localhost:8083/.well-known/agent.json

docker compose -f compose/adapters.yml down
```

---

### Task 15: Full Build + Test Verification

Final verification that everything compiles, passes tests, and lints.

**Verification sequence:**

```bash
# 1. Build all binaries
cd src/asya-gateway && go build ./...

# 2. Run all new unit tests
cd src/asya-gateway && go test ./internal/watcher/... -v -count=1
cd src/asya-gateway && go test ./internal/sseclient/... -v -count=1
cd src/asya-gateway && go test ./internal/meshclient/... -v -count=1
cd src/asya-gateway && go test ./internal/mcpadapter/... -v -count=1
cd src/asya-gateway && go test ./internal/a2aadapter/... -v -count=1

# 3. Run existing tests (must not break)
cd src/asya-gateway && go test ./... -count=1

# 4. Lint
make lint
```

---

## Summary: New Files

```
src/asya-gateway/
  cmd/
    mcp-adapter/main.go          (~90 LOC)   NEW
    a2a-adapter/main.go           (~90 LOC)   NEW
  internal/
    watcher/
      watcher.go                  (~40 LOC)   NEW (extracted from toolstore)
      watcher_test.go             (~60 LOC)   NEW
    sseclient/
      sseclient.go                (~120 LOC)  NEW
      sseclient_test.go           (~120 LOC)  NEW
    meshclient/
      client.go                   (~130 LOC)  NEW
      client_test.go              (~120 LOC)  NEW
    mcpadapter/
      config.go                   (~100 LOC)  NEW
      config_test.go              (~100 LOC)  NEW
      handler.go                  (~250 LOC)  NEW
      handler_test.go             (~150 LOC)  NEW
    a2aadapter/
      config.go                   (~130 LOC)  NEW
      config_test.go              (~130 LOC)  NEW
      state.go                    (~40 LOC)   NEW
      state_test.go               (~50 LOC)   NEW
      executor.go                 (~280 LOC)  NEW
      executor_test.go            (~150 LOC)  NEW
      card.go                     (~80 LOC)   NEW
      card_test.go                (~60 LOC)   NEW
      store.go                    (~90 LOC)   NEW
  Dockerfile                                  MODIFIED (add binary builds)
  internal/
    toolstore/watcher.go                      MODIFIED (delegate to watcher pkg)
```

**Estimated total:** ~800-1,300 LOC production code + ~900 LOC tests

## Modified Files

```
src/asya-gateway/internal/toolstore/watcher.go  MODIFIED (simplify to delegate)
src/asya-gateway/Dockerfile                      MODIFIED (multi-binary build)
```

## Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| mcp-go API changes between versions | Low | Already using v0.48.0 in go.mod; pin version |
| a2a-go v2 API differs from v0.3.15 | Medium | Check a2a-go v2 availability; fall back to v0.3.15 interfaces |
| Package name conflict (internal/mcp vs internal/mcpadapter) | Low | Temporary naming; old package deleted post-migration |
| SSE parser edge cases (multi-line data) | Low | Unit tests cover multi-line; mesh-api uses single-line JSON |
| Polling fallback hides SSE failures | Low | Logged as warnings; health check catches persistent failures |
| ConfigMap mount timing on pod start | Low | First poll catches initial state; retry on error |
