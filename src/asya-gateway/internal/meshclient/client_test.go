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
	var receivedPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
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
	assert.Equal(t, "/api/v1/mesh/msg-001/events", receivedPath)
}
