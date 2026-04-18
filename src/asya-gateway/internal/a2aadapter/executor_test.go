package a2aadapter_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2asrv"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
)

// collectingQueue captures all events written by the executor for test assertions.
// Implements eventqueue.Queue with a simple slice accumulator.
type collectingQueue struct {
	events []a2alib.Event
}

func (q *collectingQueue) Write(_ context.Context, event a2alib.Event) error {
	q.events = append(q.events, event)
	return nil
}

func (q *collectingQueue) WriteVersioned(_ context.Context, event a2alib.Event, _ a2alib.TaskVersion) error {
	q.events = append(q.events, event)
	return nil
}

func (q *collectingQueue) Read(_ context.Context) (a2alib.Event, a2alib.TaskVersion, error) {
	return nil, 0, nil
}

func (q *collectingQueue) Close() error {
	return nil
}

func TestExecutor_Execute_Success(t *testing.T) {
	sseBody := "event: status\ndata: {\"status\":\"running\",\"actor\":\"train\"}\n\n" +
		"event: fly\ndata: {\"text\":\"token1\"}\n\n" +
		"event: status\ndata: {\"status\":\"succeeded\",\"result\":{\"accuracy\":0.95}}\n\n"

	var receivedActor string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodPost:
			receivedActor = r.URL.Query().Get("actor")
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
	executor := a2aadapter.NewExecutor(reg, mc, nil)

	// Use a collecting queue to capture events written by the executor
	cq := &collectingQueue{}

	reqCtx := &a2asrv.RequestContext{
		TaskID:    "task-001",
		ContextID: "ctx-001",
		Message: a2alib.NewMessage(a2alib.MessageRoleUser,
			&a2alib.TextPart{Text: "run experiment"}),
	}

	err := executor.Execute(context.Background(), reqCtx, cq)
	require.NoError(t, err)
	assert.Equal(t, "start-research", receivedActor)

	require.NotEmpty(t, cq.events)

	// First event should be submitted
	if su, ok := cq.events[0].(*a2alib.TaskStatusUpdateEvent); ok {
		assert.Equal(t, a2alib.TaskStateSubmitted, su.Status.State)
	}

	// Last event should be terminal completed
	lastEvt := cq.events[len(cq.events)-1]
	if su, ok := lastEvt.(*a2alib.TaskStatusUpdateEvent); ok {
		assert.True(t, su.Final)
		assert.Equal(t, a2alib.TaskStateCompleted, su.Status.State)
	}
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
	executor := a2aadapter.NewExecutor(reg, mc, nil)

	cq := &collectingQueue{}
	reqCtx := &a2asrv.RequestContext{
		TaskID: "task-cancel",
	}

	err := executor.Cancel(context.Background(), reqCtx, cq)
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
	executor := a2aadapter.NewExecutor(reg, mc, nil)

	cq := &collectingQueue{}
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

	err := executor.Execute(context.Background(), reqCtx, cq)
	require.NoError(t, err)
	assert.Equal(t, "x-resume", receivedActor)
}

func TestExecutor_MessageToPayload_TextOnly(t *testing.T) {
	msg := a2alib.NewMessage(a2alib.MessageRoleUser,
		&a2alib.TextPart{Text: "hello"})

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
	executor := a2aadapter.NewExecutor(reg, mc, nil)

	cq := &collectingQueue{}
	_ = executor.Execute(context.Background(), &a2asrv.RequestContext{
		TaskID:    "t1",
		ContextID: "c1",
		Message:   msg,
	}, cq)

	require.NotNil(t, capturedPayload)
	assert.Equal(t, "hello", capturedPayload["query"])
	assert.NotNil(t, capturedPayload["a2a"])
}

func TestExecutor_FailedTask(t *testing.T) {
	sseBody := "event: status\ndata: {\"status\":\"failed\",\"error\":\"OOM\"}\n\n"

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodPost:
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(map[string]string{"id": "msg-fail"})
		case strings.HasSuffix(r.URL.Path, "/events"):
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte(sseBody))
		}
	}))
	defer srv.Close()

	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{Name: "agent", Actor: "start-agent", Timeout: 10},
	})

	mc := meshclient.New(srv.URL, srv.URL)
	executor := a2aadapter.NewExecutor(reg, mc, nil)

	cq := &collectingQueue{}
	err := executor.Execute(context.Background(), &a2asrv.RequestContext{
		TaskID:    "task-fail",
		ContextID: "ctx-fail",
		Message:   a2alib.NewMessage(a2alib.MessageRoleUser, &a2alib.TextPart{Text: "run"}),
	}, cq)
	require.NoError(t, err)

	require.NotEmpty(t, cq.events)

	lastEvt := cq.events[len(cq.events)-1]
	if su, ok := lastEvt.(*a2alib.TaskStatusUpdateEvent); ok {
		assert.True(t, su.Final)
		assert.Equal(t, a2alib.TaskStateFailed, su.Status.State)
	}
}
