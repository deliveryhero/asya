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

	events, errCh := sseclient.Subscribe(ctx, srv.URL)

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

	events, errCh := sseclient.Subscribe(ctx, srv.URL)

	var collected []sseclient.Event
	for evt := range events {
		collected = append(collected, evt)
	}

	assert.NoError(t, <-errCh)
	require.Len(t, collected, 1)
	assert.Equal(t, "status", collected[0].Type)
}

func TestSubscribe_SetsAcceptHeader(t *testing.T) {
	var receivedAccept string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedAccept = r.Header.Get("Accept")
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: status\ndata: {\"status\":\"succeeded\"}\n\n"))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	events, _ := sseclient.Subscribe(ctx, srv.URL)
	for range events {
	}

	assert.Equal(t, "text/event-stream", receivedAccept)
}

func TestSubscribe_NonOKStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = fmt.Fprint(w, "not found")
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	events, errCh := sseclient.Subscribe(ctx, srv.URL)
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
