package mesh

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/store"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// mockSender records envelopes sent to actor queues.
type mockSender struct {
	mu   sync.Mutex
	sent []sentEnvelope
}

type sentEnvelope struct {
	actor string
	body  []byte
}

func (m *mockSender) Send(_ context.Context, actor string, body []byte) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sent = append(m.sent, sentEnvelope{actor: actor, body: body})
	return nil
}

func (m *mockSender) lastSent() sentEnvelope {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.sent[len(m.sent)-1]
}

func setupTestHandler() (*Handler, *store.MemoryStore, *mockSender) {
	s := store.NewMemoryStore()
	sender := &mockSender{}
	h := NewHandler(s, sender, "http://internal.test:8081")
	return h, s, sender
}

func setupTestServer(h *Handler) (*httptest.Server, *httptest.Server) {
	extMux := http.NewServeMux()
	h.RegisterExternal(extMux)

	intMux := http.NewServeMux()
	h.RegisterInternal(intMux)

	return httptest.NewServer(extMux), httptest.NewServer(intMux)
}

func TestHandleCreate_Success(t *testing.T) {
	h, s, sender := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	resp, err := http.Post(
		extSrv.URL+"/api/v1/mesh/?actor=echo",
		"application/json",
		strings.NewReader(`{"payload":{"x":1}}`),
	)
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusCreated, resp.StatusCode)

	var result map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	id, ok := result["id"].(string)
	require.True(t, ok)
	require.NotEmpty(t, id)

	// Verify message created in store
	msg, err := s.Get(context.Background(), id)
	require.NoError(t, err)
	assert.Equal(t, types.MessageStatusPending, msg.Status)

	// Verify envelope sent to queue with x-asya-gateway-url header
	last := sender.lastSent()
	assert.Equal(t, "echo", last.actor)

	var envelope map[string]any
	require.NoError(t, json.Unmarshal(last.body, &envelope))
	headers, _ := envelope["headers"].(map[string]any)
	assert.Equal(t, "http://internal.test:8081", headers["x-asya-gateway-url"])
}

func TestHandleCreate_MissingActor(t *testing.T) {
	h, _, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	resp, err := http.Post(
		extSrv.URL+"/api/v1/mesh/",
		"application/json",
		strings.NewReader(`{"payload":{"x":1}}`),
	)
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusBadRequest, resp.StatusCode)
}

func TestHandleGet_Found(t *testing.T) {
	h, s, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "echo"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "test-123",
		Status:    types.MessageStatusRunning,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	resp, err := http.Get(extSrv.URL + "/api/v1/mesh/test-123")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	var result map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	assert.Equal(t, "test-123", result["id"])
	assert.Equal(t, "running", result["status"])
}

func TestHandleGet_NotFound(t *testing.T) {
	h, _, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	resp, err := http.Get(extSrv.URL + "/api/v1/mesh/nonexistent")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

func TestHandleEventsPost_StatusUpdate(t *testing.T) {
	h, s, _ := setupTestHandler()
	_, intSrv := setupTestServer(h)
	defer intSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "echo"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "test-ev-1",
		Status:    types.MessageStatusPending,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	// Subscribe before posting event
	ch := s.Subscribe("test-ev-1")
	defer s.Unsubscribe("test-ev-1", ch)

	// POST status event
	eventBody := `{"type":"status","status":"running","data":{"actor":"echo","progress":50}}`
	resp, err := http.Post(
		intSrv.URL+"/api/v1/mesh/test-ev-1/events",
		"application/json",
		strings.NewReader(eventBody),
	)
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNoContent, resp.StatusCode)

	// Verify store updated
	msg, err := s.Get(context.Background(), "test-ev-1")
	require.NoError(t, err)
	assert.Equal(t, types.MessageStatusRunning, msg.Status)

	// Verify subscriber notified
	select {
	case event := <-ch:
		assert.Equal(t, "status", event.Type)
		assert.Equal(t, types.MessageStatusRunning, event.Status)
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for subscriber event")
	}
}

func TestHandleEventsPost_MonotonicReject(t *testing.T) {
	h, s, _ := setupTestHandler()
	_, intSrv := setupTestServer(h)
	defer intSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "echo"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "test-mono-1",
		Status:    types.MessageStatusSucceeded,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	// Try updating succeeded -> running (should be silently ignored)
	eventBody := `{"type":"status","status":"running","data":{"actor":"echo"}}`
	resp, err := http.Post(
		intSrv.URL+"/api/v1/mesh/test-mono-1/events",
		"application/json",
		strings.NewReader(eventBody),
	)
	require.NoError(t, err)
	defer resp.Body.Close()
	// Should return 204 (silently ignored, not an error)
	assert.Equal(t, http.StatusNoContent, resp.StatusCode)

	// Status should still be succeeded
	msg, _ := s.Get(context.Background(), "test-mono-1")
	assert.Equal(t, types.MessageStatusSucceeded, msg.Status)
}

func TestHandleEventsPost_FlyEvent(t *testing.T) {
	h, s, _ := setupTestHandler()
	_, intSrv := setupTestServer(h)
	defer intSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "echo"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "test-fly-1",
		Status:    types.MessageStatusRunning,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	ch := s.Subscribe("test-fly-1")
	defer s.Unsubscribe("test-fly-1", ch)

	// POST fly event
	eventBody := `{"type":"fly","data":{"text":"hello token"}}`
	resp, err := http.Post(
		intSrv.URL+"/api/v1/mesh/test-fly-1/events",
		"application/json",
		strings.NewReader(eventBody),
	)
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNoContent, resp.StatusCode)

	// Verify subscriber receives fly event
	select {
	case event := <-ch:
		assert.Equal(t, "fly", event.Type)
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for fly event")
	}

	// Status should be unchanged (FLY is ephemeral)
	msg, _ := s.Get(context.Background(), "test-fly-1")
	assert.Equal(t, types.MessageStatusRunning, msg.Status)
}

func TestHandleEventsGet_SSE(t *testing.T) {
	h, s, _ := setupTestHandler()
	extSrv, intSrv := setupTestServer(h)
	defer extSrv.Close()
	defer intSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "echo"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "test-sse-1",
		Status:    types.MessageStatusRunning,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	// Start SSE connection in goroutine
	var sseEvents []string
	done := make(chan struct{})
	go func() {
		defer close(done)
		resp, err := http.Get(extSrv.URL + "/api/v1/mesh/test-sse-1/events")
		if err != nil {
			return
		}
		defer resp.Body.Close()

		scanner := bufio.NewScanner(resp.Body)
		for scanner.Scan() {
			line := scanner.Text()
			if strings.HasPrefix(line, "data: ") {
				sseEvents = append(sseEvents, line[6:])
			}
		}
	}()

	// Brief pause to let SSE connection establish
	time.Sleep(50 * time.Millisecond)

	// Publish terminal event via internal endpoint
	eventBody := `{"type":"status","status":"succeeded","data":{"actor":"x-sink"}}`
	resp, err := http.Post(
		intSrv.URL+"/api/v1/mesh/test-sse-1/events",
		"application/json",
		strings.NewReader(eventBody),
	)
	require.NoError(t, err)
	resp.Body.Close()

	// Wait for SSE to close (terminal event)
	select {
	case <-done:
		// SSE should have at least the catch-up event + terminal event
		require.GreaterOrEqual(t, len(sseEvents), 2)
	case <-time.After(3 * time.Second):
		t.Fatal("timed out waiting for SSE to close")
	}
}

func TestHandleEventsGet_TerminalCatchUp(t *testing.T) {
	h, s, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "x-sink"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "test-term-1",
		Status:    types.MessageStatusSucceeded,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	resp, err := http.Get(extSrv.URL + "/api/v1/mesh/test-term-1/events")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Equal(t, "text/event-stream", resp.Header.Get("Content-Type"))

	// Should get a single SSE event and the connection should close
	var events []string
	scanner := bufio.NewScanner(resp.Body)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "event: ") {
			events = append(events, line)
		}
	}
	assert.Equal(t, 1, len(events))
	assert.Equal(t, "event: status", events[0])
}

func TestHandleCancel_Success(t *testing.T) {
	h, s, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "echo"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "test-cancel-1",
		Status:    types.MessageStatusRunning,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	req, _ := http.NewRequest(http.MethodDelete, extSrv.URL+"/api/v1/mesh/test-cancel-1", nil)
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNoContent, resp.StatusCode)

	// Verify status is canceled
	msg, _ := s.Get(context.Background(), "test-cancel-1")
	assert.Equal(t, types.MessageStatusCanceled, msg.Status)
}

func TestHandleCancel_AlreadyTerminal(t *testing.T) {
	h, s, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "x-sink"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "test-cancel-2",
		Status:    types.MessageStatusSucceeded,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	req, _ := http.NewRequest(http.MethodDelete, extSrv.URL+"/api/v1/mesh/test-cancel-2", nil)
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNoContent, resp.StatusCode)

	// Status should still be succeeded (idempotent)
	msg, _ := s.Get(context.Background(), "test-cancel-2")
	assert.Equal(t, types.MessageStatusSucceeded, msg.Status)
}

func TestHandleList_FilterByStatus(t *testing.T) {
	h, s, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	ctx := context.Background()
	for i, status := range []types.MessageStatus{
		types.MessageStatusPending,
		types.MessageStatusRunning,
		types.MessageStatusRunning,
	} {
		data, _ := json.Marshal(types.MessageData{Actor: "echo"})
		require.NoError(t, s.Create(ctx, &types.Message{
			ID:        fmt.Sprintf("list-%d", i),
			Status:    status,
			Data:      data,
			CreatedAt: time.Now().UTC().Add(time.Duration(i) * time.Second),
			UpdatedAt: time.Now().UTC(),
		}))
	}

	resp, err := http.Get(extSrv.URL + "/api/v1/mesh/?status=running&limit=10")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	var result map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	msgs := result["messages"].([]any)
	assert.Len(t, msgs, 2)
}

func TestHandleCreate_StampsGatewayURL(t *testing.T) {
	h, _, sender := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	resp, err := http.Post(
		extSrv.URL+"/api/v1/mesh/?actor=echo",
		"application/json",
		strings.NewReader(`{"payload":{"test":true}}`),
	)
	require.NoError(t, err)
	resp.Body.Close()

	last := sender.lastSent()
	var envelope map[string]any
	require.NoError(t, json.Unmarshal(last.body, &envelope))

	headers, ok := envelope["headers"].(map[string]any)
	require.True(t, ok)
	assert.Equal(t, "http://internal.test:8081", headers["x-asya-gateway-url"])
}

func TestHandleCancel_NotFound(t *testing.T) {
	h, _, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	req, _ := http.NewRequest(http.MethodDelete, extSrv.URL+"/api/v1/mesh/nonexistent", nil)
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

func TestHandleList_Empty(t *testing.T) {
	h, _, _ := setupTestHandler()
	extSrv, _ := setupTestServer(h)
	defer extSrv.Close()

	resp, err := http.Get(extSrv.URL + "/api/v1/mesh/")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	var result map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	msgs := result["messages"].([]any)
	assert.Len(t, msgs, 0)
}

func TestInternalGet_HeartbeatCheck(t *testing.T) {
	h, s, _ := setupTestHandler()
	_, intSrv := setupTestServer(h)
	defer intSrv.Close()

	data, _ := json.Marshal(types.MessageData{Actor: "echo"})
	require.NoError(t, s.Create(context.Background(), &types.Message{
		ID:        "heartbeat-1",
		Status:    types.MessageStatusRunning,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}))

	resp, err := http.Get(intSrv.URL + "/api/v1/mesh/heartbeat-1")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	var result map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	assert.Equal(t, "running", result["status"])
}
