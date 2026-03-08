package toolstore

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPostReturns405(t *testing.T) {
	r := NewInMemoryRegistry()
	h := NewHandler(r)

	req := httptest.NewRequest(http.MethodPost, "/mesh/expose", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.HandleExpose(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected status %d, got %d", http.StatusMethodNotAllowed, rec.Code)
	}
}

func TestGetListsAllTools(t *testing.T) {
	r := NewInMemoryRegistry()
	h := NewHandler(r)
	ctx := context.Background()

	// Seed tools directly via Upsert
	tools := []Tool{
		{Name: "tool1", Actor: "actor1"},
		{Name: "tool2", Actor: "actor2"},
		{Name: "tool3", Actor: "actor3"},
	}
	for _, tool := range tools {
		if err := r.Upsert(ctx, tool); err != nil {
			t.Fatalf("failed to upsert tool %q: %v", tool.Name, err)
		}
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

	names := make(map[string]bool)
	for _, tool := range result {
		names[tool.Name] = true
	}
	for _, expected := range []string{"tool1", "tool2", "tool3"} {
		if !names[expected] {
			t.Errorf("expected tool %q in response", expected)
		}
	}
}

func TestGetEmptyRegistry(t *testing.T) {
	r := NewInMemoryRegistry()
	h := NewHandler(r)

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

	if len(result) != 0 {
		t.Errorf("expected 0 tools, got %d", len(result))
	}
}
