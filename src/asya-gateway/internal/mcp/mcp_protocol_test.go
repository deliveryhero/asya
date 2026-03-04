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

// Transport test helpers
type transportFactory struct {
	name    string
	factory func(*mcpserver.MCPServer) http.Handler
}

var streamableHTTPTransport = transportFactory{
	name: "Streamable HTTP",
	factory: func(s *mcpserver.MCPServer) http.Handler {
		return mcpserver.NewStreamableHTTPServer(s)
	},
}

// TestMCPProtocol_Initialize verifies the MCP initialize handshake via Streamable HTTP
func TestMCPProtocol_Initialize(t *testing.T) {
	testInitialize(t, streamableHTTPTransport.name, streamableHTTPTransport.factory)
}

func testInitialize(t *testing.T, transportName string, serverFactory func(*mcpserver.MCPServer) http.Handler) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	mcpSrv := NewServer(taskStore, queueClient, nil)
	handler := serverFactory(mcpSrv.GetMCPServer())

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
	req := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("[%s] Initialize request failed: status=%d, body=%s", transportName, rr.Code, rr.Body.String())
	}

	var response map[string]interface{}
	if err := json.NewDecoder(rr.Body).Decode(&response); err != nil {
		t.Fatalf("[%s] Failed to decode initialize response: %v", transportName, err)
	}

	if response["jsonrpc"] != "2.0" {
		t.Errorf("[%s] Expected jsonrpc='2.0', got %v", transportName, response["jsonrpc"])
	}

	if response["id"] != float64(1) {
		t.Errorf("[%s] Expected id=1, got %v", transportName, response["id"])
	}

	result, ok := response["result"].(map[string]interface{})
	if !ok {
		t.Fatalf("[%s] Expected result object, got %T", transportName, response["result"])
	}

	if result["protocolVersion"] == nil {
		t.Errorf("[%s] Missing protocolVersion in initialize result", transportName)
	}

	serverInfo, ok := result["serverInfo"].(map[string]interface{})
	if !ok {
		t.Fatalf("[%s] Missing or invalid serverInfo in result", transportName)
	}

	if serverInfo["name"] != "asya-gateway" {
		t.Errorf("[%s] Expected server name 'asya-gateway', got %v", transportName, serverInfo["name"])
	}

	if serverInfo["version"] != "0.1.0" {
		t.Errorf("[%s] Expected server version '0.1.0', got %v", transportName, serverInfo["version"])
	}

	capabilities, ok := result["capabilities"].(map[string]interface{})
	if !ok {
		t.Fatalf("[%s] Missing or invalid capabilities in result", transportName)
	}

	if capabilities["tools"] == nil {
		t.Errorf("[%s] Missing tools capability", transportName)
	}
}

// TestMCPProtocol_InvalidMethod verifies error handling for invalid methods via Streamable HTTP
func TestMCPProtocol_InvalidMethod(t *testing.T) {
	testInvalidMethod(t, streamableHTTPTransport.name, streamableHTTPTransport.factory)
}

func testInvalidMethod(t *testing.T, transportName string, serverFactory func(*mcpserver.MCPServer) http.Handler) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	mcpSrv := NewServer(taskStore, queueClient, nil)
	handler := serverFactory(mcpSrv.GetMCPServer())

	invalidRequest := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "invalid/method",
		"params":  map[string]interface{}{},
	}

	body, _ := json.Marshal(invalidRequest)
	req := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Logf("[%s] Invalid method returned non-200 status: %d (expected behavior)", transportName, rr.Code)
		return
	}

	var response map[string]interface{}
	if err := json.NewDecoder(rr.Body).Decode(&response); err != nil {
		t.Logf("[%s] Invalid method returned non-JSON response (acceptable for invalid methods)", transportName)
		return
	}

	if response["error"] == nil {
		t.Errorf("[%s] Expected error for invalid method, got successful response", transportName)
	}
}

// TestMCPProtocol_BothTransportsWork verifies both transports can coexist
func TestMCPProtocol_BothTransportsWork(t *testing.T) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	mcpSrv := NewServer(taskStore, queueClient, nil)

	streamableHandler := mcpserver.NewStreamableHTTPServer(mcpSrv.GetMCPServer())
	sseHandler := mcpserver.NewSSEServer(mcpSrv.GetMCPServer())

	if streamableHandler == nil {
		t.Fatal("Failed to create Streamable HTTP handler")
	}

	if sseHandler == nil {
		t.Fatal("Failed to create SSE handler")
	}

	t.Run("StreamableHTTP", func(t *testing.T) {
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
		req := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rr := httptest.NewRecorder()

		streamableHandler.ServeHTTP(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Streamable HTTP initialize failed: status=%d", rr.Code)
		}

		var response map[string]interface{}
		if err := json.NewDecoder(rr.Body).Decode(&response); err != nil {
			t.Fatalf("Failed to decode response: %v", err)
		}

		if response["result"] == nil {
			t.Error("Expected result in Streamable HTTP response")
		}
	})
}
