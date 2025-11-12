package controller

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	asyaconfig "github.com/asya/operator/internal/config"
)

const testUsername = "guest"

type rabbitmqQueueResponse struct {
	MessagesReady          int `json:"messages_ready"`
	MessagesUnacknowledged int `json:"messages_unacknowledged"`
}

func TestRabbitMQConfig_GetQueueMetrics_Success(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// r.URL.Path is decoded, so %2F becomes /
		if r.URL.Path != "/api/queues///test-queue" {
			t.Errorf("Expected path /api/queues///test-queue, got %s", r.URL.Path)
		}

		username, _, ok := r.BasicAuth()
		if !ok || username != testUsername {
			t.Errorf("Expected basic auth with username %q", testUsername)
		}

		response := rabbitmqQueueResponse{
			MessagesReady:          150,
			MessagesUnacknowledged: 10,
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()

	config := &asyaconfig.RabbitMQConfig{
		Host:     server.Listener.Addr().String(),
		Username: "guest",
	}

	metrics, err := config.GetQueueMetrics(context.Background(), "test-queue", "default", nil)
	if err != nil {
		t.Fatalf("GetQueueMetrics failed: %v", err)
	}

	if metrics.Queued != 150 {
		t.Errorf("Expected Queued=150, got %d", metrics.Queued)
	}

	if metrics.Processing == nil {
		t.Fatal("Expected Processing to be non-nil")
	}

	if *metrics.Processing != 10 {
		t.Errorf("Expected Processing=10, got %d", *metrics.Processing)
	}
}

func TestRabbitMQConfig_GetQueueMetrics_QueueNotFound(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"error":"Object Not Found","reason":"Not Found"}`))
	}))
	defer server.Close()

	config := &asyaconfig.RabbitMQConfig{
		Host:     server.Listener.Addr().String(),
		Username: "guest",
	}

	metrics, err := config.GetQueueMetrics(context.Background(), "nonexistent-queue", "default", nil)
	if err != nil {
		t.Fatalf("GetQueueMetrics should not error for 404, got: %v", err)
	}

	if metrics.Queued != 0 {
		t.Errorf("Expected Queued=0 for nonexistent queue, got %d", metrics.Queued)
	}

	if metrics.Processing == nil || *metrics.Processing != 0 {
		t.Errorf("Expected Processing=0 for nonexistent queue")
	}
}

func TestRabbitMQConfig_GetQueueMetrics_ServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":"Internal Server Error"}`))
	}))
	defer server.Close()

	config := &asyaconfig.RabbitMQConfig{
		Host:     server.Listener.Addr().String(),
		Username: "guest",
	}

	_, err := config.GetQueueMetrics(context.Background(), "test-queue", "default", nil)
	if err == nil {
		t.Fatal("Expected error for 500 response")
	}
}

func TestRabbitMQConfig_GetQueueMetrics_InvalidJSON(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{invalid json`))
	}))
	defer server.Close()

	config := &asyaconfig.RabbitMQConfig{
		Host:     server.Listener.Addr().String(),
		Username: "guest",
	}

	_, err := config.GetQueueMetrics(context.Background(), "test-queue", "default", nil)
	if err == nil {
		t.Fatal("Expected error for invalid JSON")
	}
}

func TestRabbitMQConfig_GetQueueMetrics_ZeroMessages(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		response := rabbitmqQueueResponse{
			MessagesReady:          0,
			MessagesUnacknowledged: 0,
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()

	config := &asyaconfig.RabbitMQConfig{
		Host:     server.Listener.Addr().String(),
		Username: "guest",
	}

	metrics, err := config.GetQueueMetrics(context.Background(), "empty-queue", "default", nil)
	if err != nil {
		t.Fatalf("GetQueueMetrics failed: %v", err)
	}

	if metrics.Queued != 0 {
		t.Errorf("Expected Queued=0, got %d", metrics.Queued)
	}

	if metrics.Processing == nil || *metrics.Processing != 0 {
		t.Errorf("Expected Processing=0")
	}
}

// Note: SQS GetQueueMetrics tests require AWS SDK mocking which is complex.
// These tests are better suited for integration tests with LocalStack.
// The implementation is tested indirectly through E2E tests.
