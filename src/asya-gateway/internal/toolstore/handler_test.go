package toolstore

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestPostCreatesTool(t *testing.T) {
	r := NewInMemoryRegistry()
	h := NewHandler(r)

	reqBody := RegisterRequest{
		Name:        "new-tool",
		Actor:       "test-actor",
		Description: "Test tool",
		Progress:    true,
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		t.Fatalf("failed to marshal request: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/mesh/expose", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.HandleExpose(rec, req)

	if rec.Code != http.StatusCreated {
		t.Errorf("expected status %d, got %d", http.StatusCreated, rec.Code)
	}

	// Verify tool was registered
	tool := r.GetByName("new-tool")
	if tool == nil {
		t.Fatal("tool not registered")
	}
	if tool.Actor != "test-actor" {
		t.Errorf("expected actor 'test-actor', got '%s'", tool.Actor)
	}
	if !tool.MCPEnabled {
		t.Error("expected MCPEnabled to default to true")
	}
}

func TestPostUpdatesTool(t *testing.T) {
	r := NewInMemoryRegistry()
	h := NewHandler(r)

	// Register initial tool
	initialReq := RegisterRequest{
		Name:        "existing-tool",
		Actor:       "actor-v1",
		Description: "Version 1",
	}

	body, _ := json.Marshal(initialReq)
	req := httptest.NewRequest(http.MethodPost, "/mesh/expose", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	h.HandleExpose(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("expected status %d for creation, got %d", http.StatusCreated, rec.Code)
	}

	// Update the tool
	updateReq := RegisterRequest{
		Name:        "existing-tool",
		Actor:       "actor-v2",
		Description: "Version 2",
	}

	body, _ = json.Marshal(updateReq)
	req = httptest.NewRequest(http.MethodPost, "/mesh/expose", bytes.NewReader(body))
	rec = httptest.NewRecorder()
	h.HandleExpose(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("expected status %d for update, got %d", http.StatusOK, rec.Code)
	}

	// Verify tool was updated
	tool := r.GetByName("existing-tool")
	if tool == nil {
		t.Fatal("tool not found")
	}
	if tool.Actor != "actor-v2" {
		t.Errorf("expected actor 'actor-v2', got '%s'", tool.Actor)
	}
	if tool.Description != "Version 2" {
		t.Errorf("expected description 'Version 2', got '%s'", tool.Description)
	}
}

func TestPostWithRouteArrayExtractsActorAndRouteNext(t *testing.T) {
	r := NewInMemoryRegistry()
	h := NewHandler(r)

	reqBody := RegisterRequest{
		Name:        "pipeline-tool",
		Route:       []string{"actor-a", "actor-b", "actor-c"},
		Description: "Multi-actor pipeline",
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		t.Fatalf("failed to marshal request: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/mesh/expose", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.HandleExpose(rec, req)

	if rec.Code != http.StatusCreated {
		t.Errorf("expected status %d, got %d", http.StatusCreated, rec.Code)
	}

	tool := r.GetByName("pipeline-tool")
	if tool == nil {
		t.Fatal("tool not registered")
	}
	if tool.Actor != "actor-a" {
		t.Errorf("expected actor 'actor-a', got '%s'", tool.Actor)
	}
	if len(tool.RouteNext) != 2 {
		t.Fatalf("expected 2 route_next entries, got %d", len(tool.RouteNext))
	}
	if tool.RouteNext[0] != "actor-b" || tool.RouteNext[1] != "actor-c" {
		t.Errorf("expected route_next ['actor-b', 'actor-c'], got %v", tool.RouteNext)
	}
}

func TestGetListsAllTools(t *testing.T) {
	r := NewInMemoryRegistry()
	h := NewHandler(r)

	// Register multiple tools
	tools := []RegisterRequest{
		{Name: "tool1", Actor: "actor1"},
		{Name: "tool2", Actor: "actor2"},
		{Name: "tool3", Actor: "actor3"},
	}

	for _, reqBody := range tools {
		body, _ := json.Marshal(reqBody)
		req := httptest.NewRequest(http.MethodPost, "/mesh/expose", bytes.NewReader(body))
		rec := httptest.NewRecorder()
		h.HandleExpose(rec, req)
	}

	// GET all tools
	req := httptest.NewRequest(http.MethodGet, "/mesh/expose", nil)
	rec := httptest.NewRecorder()
	h.HandleExpose(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("expected status %d, got %d", http.StatusOK, rec.Code)
	}

	var result []Tool
	if err := json.NewDecoder(rec.Body).Decode(&result); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	if len(result) != 3 {
		t.Errorf("expected 3 tools, got %d", len(result))
	}

	// Verify tool names
	names := make(map[string]bool)
	for _, tool := range result {
		names[tool.Name] = true
	}

	for _, expected := range []string{"tool1", "tool2", "tool3"} {
		if !names[expected] {
			t.Errorf("expected tool '%s' in response", expected)
		}
	}
}
