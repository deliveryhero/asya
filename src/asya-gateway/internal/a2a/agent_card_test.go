package a2a

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandleAgentCard(t *testing.T) {
	cfg := &config.Config{
		Tools: []config.Tool{
			{
				Name:        "echo",
				Description: "Echo tool",
				Route:       config.RouteSpec{Actors: []string{"echo-actor"}},
			},
			{
				Name:        "analyze",
				Description: "Analyze data",
				Route:       config.RouteSpec{Actors: []string{"analyzer"}},
			},
		},
	}

	handler := NewAgentCardHandler(cfg)

	req := httptest.NewRequest(http.MethodGet, "/.well-known/a2a/agent-card", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusOK)
	}

	ct := rr.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("Content-Type = %s, want application/json", ct)
	}

	var card types.AgentCard
	if err := json.NewDecoder(rr.Body).Decode(&card); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if card.Name != "asya-gateway" {
		t.Errorf("Name = %s, want asya-gateway", card.Name)
	}
	if len(card.Skills) != 2 {
		t.Errorf("Skills count = %d, want 2", len(card.Skills))
	}
	if !card.Capabilities.Streaming {
		t.Error("Streaming capability should be true")
	}
}

func TestHandleAgentCard_MethodNotAllowed(t *testing.T) {
	handler := NewAgentCardHandler(&config.Config{Tools: []config.Tool{}})
	req := httptest.NewRequest(http.MethodPost, "/.well-known/a2a/agent-card", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("status = %d, want %d", rr.Code, http.StatusMethodNotAllowed)
	}
}
