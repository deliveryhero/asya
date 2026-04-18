package mcpadapter_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/mcpadapter"
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
	result := handler.MCPServer().HandleMessage(
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

	require.NotNil(t, result)

	// The result should contain the accuracy
	resultJSON, err := json.Marshal(result)
	require.NoError(t, err)
	assert.Contains(t, string(resultJSON), "0.95")

	// _meta.task_id must be stamped so callers can correlate with mesh-api
	assert.Contains(t, string(resultJSON), `"task_id"`)
	assert.Contains(t, string(resultJSON), "msg-001")
}

func TestHandler_ToolCallMeta_TaskIdPresentOnError(t *testing.T) {
	sseBody := "event: status\ndata: {\"status\":\"failed\",\"error\":\"boom\"}\n\n"
	srv := fakeMeshAPI(t, "msg-err-001", sseBody)
	defer srv.Close()

	reg := mcpadapter.NewRegistry()
	reg.LoadToolsForTest([]mcpadapter.ToolConfig{{Name: "tool", Actor: "actor"}})

	mc := meshclient.New(srv.URL, srv.URL)
	handler := mcpadapter.NewHandler(reg, mc)
	handler.SyncTools()

	result := handler.MCPServer().HandleMessage(
		context.Background(),
		json.RawMessage(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"tool","arguments":{}}}`),
	)

	require.NotNil(t, result)
	resultJSON, _ := json.Marshal(result)
	// task_id must be in _meta even for failed results
	assert.Contains(t, string(resultJSON), "msg-err-001")
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

	result := handler.MCPServer().HandleMessage(
		context.Background(),
		json.RawMessage(`{
			"jsonrpc": "2.0",
			"id": 1,
			"method": "tools/call",
			"params": {"name": "train", "arguments": {}}
		}`),
	)

	require.NotNil(t, result)
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

	result := handler.MCPServer().HandleMessage(
		context.Background(),
		json.RawMessage(`{
			"jsonrpc": "2.0",
			"id": 1,
			"method": "tools/call",
			"params": {"name": "train", "arguments": {}}
		}`),
	)

	require.NotNil(t, result)
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

	result := handler.MCPServer().HandleMessage(
		context.Background(),
		json.RawMessage(`{
			"jsonrpc": "2.0",
			"id": 1,
			"method": "tools/list"
		}`),
	)

	require.NotNil(t, result)
	resultJSON, _ := json.Marshal(result)
	assert.Contains(t, string(resultJSON), "train")
	assert.Contains(t, string(resultJSON), "deploy")
}
