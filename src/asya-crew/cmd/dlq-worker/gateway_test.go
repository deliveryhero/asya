package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestGatewayClient_ReportFailure_Success(t *testing.T) {
	var receivedBody map[string]interface{}
	var receivedPath string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &receivedBody)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := NewGatewayClient(server.URL)
	err := client.ReportFailure(context.Background(), "task-abc", "DLQ failure")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if receivedPath != "/mesh/task-abc/final" {
		t.Errorf("path = %q, want /mesh/task-abc/final", receivedPath)
	}
	if receivedBody["id"] != "task-abc" {
		t.Errorf("id = %v", receivedBody["id"])
	}
	if receivedBody["status"] != "failed" {
		t.Errorf("status = %v", receivedBody["status"])
	}
	if receivedBody["error"] != "DLQ failure" {
		t.Errorf("error = %v", receivedBody["error"])
	}
	if receivedBody["timestamp"] == nil {
		t.Error("timestamp should be set")
	}
}

func TestGatewayClient_ReportFailure_ServerError(t *testing.T) {
	attempts := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		attempts++
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	client := NewGatewayClient(server.URL)
	err := client.ReportFailure(context.Background(), "task-xyz", "error")
	if err == nil {
		t.Fatal("expected error for 500 responses")
	}
	if attempts != 3 {
		t.Errorf("expected 3 retry attempts, got %d", attempts)
	}
}

func TestGatewayClient_ReportFailure_RecoverOnRetry(t *testing.T) {
	attempts := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		attempts++
		if attempts < 3 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := NewGatewayClient(server.URL)
	err := client.ReportFailure(context.Background(), "task-retry", "error")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if attempts != 3 {
		t.Errorf("expected 3 attempts, got %d", attempts)
	}
}

func TestNoopGateway(t *testing.T) {
	gw := &noopGateway{}
	err := gw.ReportFailure(context.Background(), "any-id", "any-error")
	if err != nil {
		t.Fatalf("noop should never error: %v", err)
	}
}
