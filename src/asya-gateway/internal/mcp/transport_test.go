package mcp

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	mcpserver "github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
)

// TestTransport_StreamableHTTP_Initialize tests streamable HTTP transport initialization
func TestTransport_StreamableHTTP_Initialize(t *testing.T) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	mcpSrv := NewServer(taskStore, queueClient, nil)
	handler := mcpserver.NewStreamableHTTPServer(mcpSrv.GetMCPServer())

	server := httptest.NewServer(handler)
	defer server.Close()

	// Test initialize request
	initRequest := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "initialize",
		"params": map[string]interface{}{
			"protocolVersion": "2024-11-05",
			"capabilities":    map[string]interface{}{},
			"clientInfo": map[string]interface{}{
				"name":    "test-client",
				"version": "1.0.0",
			},
		},
	}

	body, _ := json.Marshal(initRequest)
	resp, err := http.Post(server.URL, "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("Failed to send initialize request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("Expected status 200, got %d", resp.StatusCode)
	}

	var response map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}

	// Verify response
	if response["jsonrpc"] != "2.0" {
		t.Errorf("Expected jsonrpc='2.0', got %v", response["jsonrpc"])
	}

	result, ok := response["result"].(map[string]interface{})
	if !ok {
		t.Fatalf("Expected result object, got %T", response["result"])
	}

	serverInfo, ok := result["serverInfo"].(map[string]interface{})
	if !ok {
		t.Fatal("Missing serverInfo in result")
	}

	if serverInfo["name"] != "asya-gateway" {
		t.Errorf("Expected server name 'asya-gateway', got %v", serverInfo["name"])
	}
}

// TestTransport_SSE_ServerCreation tests SSE server can be created and mounted
func TestTransport_SSE_ServerCreation(t *testing.T) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	mcpSrv := NewServer(taskStore, queueClient, nil)
	sseServer := mcpserver.NewSSEServer(mcpSrv.GetMCPServer())

	if sseServer == nil {
		t.Fatal("Failed to create SSE server")
	}

	server := httptest.NewServer(sseServer)
	defer server.Close()
}

// TestTransport_DualEndpoints tests both transports can coexist
func TestTransport_DualEndpoints(t *testing.T) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	mcpSrv := NewServer(taskStore, queueClient, nil)

	streamableHandler := mcpserver.NewStreamableHTTPServer(mcpSrv.GetMCPServer())
	sseHandler := mcpserver.NewSSEServer(mcpSrv.GetMCPServer())

	mux := http.NewServeMux()
	mux.Handle("/mcp", streamableHandler)
	mux.Handle("/mcp/sse", sseHandler)

	server := httptest.NewServer(mux)
	defer server.Close()

	// Test streamable HTTP endpoint exists
	resp, err := http.Post(server.URL+"/mcp", "application/json", bytes.NewReader([]byte(`{"jsonrpc":"2.0","id":1,"method":"ping"}`)))
	if err != nil {
		t.Fatalf("Failed to access streamable HTTP endpoint: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusBadRequest {
		t.Errorf("Streamable HTTP endpoint not responding correctly: status=%d", resp.StatusCode)
	}

	// Test SSE endpoint exists
	resp2, err := http.Get(server.URL + "/mcp/sse")
	if err != nil {
		t.Fatalf("Failed to access SSE endpoint: %v", err)
	}
	defer func() { _ = resp2.Body.Close() }()

	if resp2.StatusCode >= 500 {
		t.Errorf("SSE endpoint returned server error: status=%d", resp2.StatusCode)
	}
}

// TestTransport_ContentTypes tests correct content-type handling
func TestTransport_ContentTypes(t *testing.T) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	mcpSrv := NewServer(taskStore, queueClient, nil)
	handler := mcpserver.NewStreamableHTTPServer(mcpSrv.GetMCPServer())

	server := httptest.NewServer(handler)
	defer server.Close()

	req, _ := http.NewRequest("POST", server.URL, bytes.NewReader([]byte(`{"jsonrpc":"2.0","id":1,"method":"ping"}`)))
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("Request failed: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode >= 500 {
		t.Errorf("Server error with application/json: status=%d", resp.StatusCode)
	}
}
