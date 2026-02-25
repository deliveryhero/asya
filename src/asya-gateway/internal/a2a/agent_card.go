package a2a

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// AgentCardHandler serves the A2A Agent Card at /.well-known/a2a/agent-card
type AgentCardHandler struct {
	config *config.Config
}

// NewAgentCardHandler creates a handler that generates an Agent Card from tool config.
func NewAgentCardHandler(cfg *config.Config) *AgentCardHandler {
	return &AgentCardHandler{config: cfg}
}

func (h *AgentCardHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	skills := make([]types.AgentSkill, 0, len(h.config.Tools))
	for _, tool := range h.config.Tools {
		skills = append(skills, types.AgentSkill{
			ID:          tool.Name,
			Name:        tool.Name,
			Description: tool.Description,
		})
	}

	card := types.AgentCard{
		Name:             "asya-gateway",
		Description:      "Asya Actor Mesh Gateway - A2A compliant",
		Version:          "0.1.0",
		URL:              "/a2a/",
		ProtocolVersions: []string{"0.2.1"},
		Capabilities: types.AgentCaps{
			Streaming:         true,
			PushNotifications: false,
		},
		Skills: skills,
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(card); err != nil {
		slog.Error("Failed to encode agent card response", "error", err)
	}
}
