package a2a

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandler_MessageSend(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{
		Tools: []config.Tool{
			{
				Name:        "echo",
				Description: "Echo tool",
				Route:       config.RouteSpec{Actors: []string{"echo-actor"}},
			},
		},
	}
	h := NewHandler(store, nil, cfg)

	reqBody := types.A2AJSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "message/send",
		Params: map[string]any{
			"message": map[string]any{
				"role": "user",
				"parts": []any{
					map[string]any{"type": "data", "data": map[string]any{"input": "hello"}},
				},
			},
			"skill": "echo",
		},
	}

	body, _ := json.Marshal(reqBody)
	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200, body: %s", rr.Code, rr.Body.String())
	}

	var resp types.A2AJSONRPCResponse
	if err := json.NewDecoder(rr.Body).Decode(&resp); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if resp.Error != nil {
		t.Fatalf("unexpected error: %+v", resp.Error)
	}

	// Result should be an A2A Task
	resultBytes, _ := json.Marshal(resp.Result)
	var a2aTask types.A2ATask
	if err := json.Unmarshal(resultBytes, &a2aTask); err != nil {
		t.Fatalf("failed to decode A2ATask from result: %v", err)
	}

	if a2aTask.ID == "" {
		t.Error("Task ID should not be empty")
	}
	if a2aTask.Status.State != types.A2AStateSubmitted {
		t.Errorf("State = %s, want submitted", a2aTask.Status.State)
	}
}

func TestHandler_MessageSend_SkillNotFound(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{Tools: []config.Tool{}}
	h := NewHandler(store, nil, cfg)

	reqBody := types.A2AJSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "message/send",
		Params: map[string]any{
			"message": map[string]any{
				"role":  "user",
				"parts": []any{map[string]any{"type": "text", "text": "hi"}},
			},
			"skill": "nonexistent",
		},
	}

	body, _ := json.Marshal(reqBody)
	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	var resp types.A2AJSONRPCResponse
	if err := json.NewDecoder(rr.Body).Decode(&resp); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if resp.Error == nil {
		t.Fatal("expected error for nonexistent skill")
	}
	if resp.Error.Code != types.A2AErrInvalidParams {
		t.Errorf("error code = %d, want %d", resp.Error.Code, types.A2AErrInvalidParams)
	}
}

func TestHandler_MethodNotFound(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{Tools: []config.Tool{}}
	h := NewHandler(store, nil, cfg)

	reqBody := types.A2AJSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "unknown/method",
	}

	body, _ := json.Marshal(reqBody)
	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	var resp types.A2AJSONRPCResponse
	if err := json.NewDecoder(rr.Body).Decode(&resp); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if resp.Error == nil || resp.Error.Code != types.A2AErrMethodNotFound {
		t.Errorf("expected method not found error")
	}
}

func TestHandler_InvalidJSON(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{Tools: []config.Tool{}}
	h := NewHandler(store, nil, cfg)

	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader([]byte("not json")))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	var resp types.A2AJSONRPCResponse
	if err := json.NewDecoder(rr.Body).Decode(&resp); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if resp.Error == nil || resp.Error.Code != types.A2AErrParseError {
		t.Error("expected parse error")
	}
}

func TestHandler_GetNotAllowed(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{Tools: []config.Tool{}}
	h := NewHandler(store, nil, cfg)

	req := httptest.NewRequest(http.MethodGet, "/a2a/", nil)
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("status = %d, want 405", rr.Code)
	}
}
