package a2a

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func okHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("OK"))
	})
}

func TestAPIKeyMiddleware_ValidKey(t *testing.T) {
	handler := APIKeyMiddleware("secret-key")(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("X-API-Key", "secret-key")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if rec.Body.String() != "OK" {
		t.Fatalf("expected OK body, got %q", rec.Body.String())
	}
}

func TestAPIKeyMiddleware_MissingKey(t *testing.T) {
	handler := APIKeyMiddleware("secret-key")(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}

	var resp map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to decode JSON-RPC error: %v", err)
	}

	errObj, ok := resp["error"].(map[string]any)
	if !ok {
		t.Fatal("missing error object in response")
	}
	code, ok := errObj["code"].(float64)
	if !ok || int(code) != -32005 {
		t.Fatalf("expected error code -32005, got %v", errObj["code"])
	}
}

func TestAPIKeyMiddleware_WrongKey(t *testing.T) {
	handler := APIKeyMiddleware("secret-key")(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("X-API-Key", "wrong-key")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
}

func TestAPIKeyMiddleware_AgentCardBypass(t *testing.T) {
	handler := APIKeyMiddleware("secret-key")(okHandler())

	req := httptest.NewRequest(http.MethodGet, "/.well-known/agent.json", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 for agent card bypass, got %d", rec.Code)
	}
}

func TestAPIKeyMiddleware_EmptyAPIKey(t *testing.T) {
	handler := APIKeyMiddleware("")(okHandler())

	// Empty key configured, empty header provided: should pass (constant-time compare matches)
	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 when both API key and header are empty, got %d", rec.Code)
	}

	// Empty key configured, non-empty header: should fail
	req2 := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req2.Header.Set("X-API-Key", "some-key")
	rec2 := httptest.NewRecorder()

	handler.ServeHTTP(rec2, req2)

	if rec2.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 when API key is empty but header is set, got %d", rec2.Code)
	}
}
