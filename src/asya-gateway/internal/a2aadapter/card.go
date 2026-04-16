package a2aadapter

import (
	"context"
	"os"

	a2alib "github.com/a2aproject/a2a-go/a2a"
)

// CardProducer implements a2asrv.AgentCardProducer using the agent registry.
type CardProducer struct {
	registry *AgentRegistry
}

// NewCardProducer creates a new CardProducer.
func NewCardProducer(registry *AgentRegistry) *CardProducer {
	return &CardProducer{registry: registry}
}

// Card returns the current AgentCard based on registered agents.
func (p *CardProducer) Card(_ context.Context) (*a2alib.AgentCard, error) {
	agents := p.registry.Agents()

	var a2aSkills []a2alib.AgentSkill
	for _, agent := range agents {
		for _, skill := range agent.Skills {
			a2aSkills = append(a2aSkills, a2alib.AgentSkill{
				ID:          skill.ID,
				Name:        skill.Name,
				Description: skill.Description,
				Tags:        skill.Tags,
			})
		}
		// If agent has no skills, create one from the agent itself
		if len(agent.Skills) == 0 {
			a2aSkills = append(a2aSkills, a2alib.AgentSkill{
				ID:          agent.Name,
				Name:        agent.Name,
				Description: agent.Description,
			})
		}
	}

	name := envOr("ASYA_A2A_NAME", "Asya Gateway")
	desc := envOr("ASYA_A2A_DESCRIPTION", "AI Actor Mesh for distributed agentic workloads")
	version := envOr("ASYA_A2A_VERSION", "1.0.0")
	publicURL := envOr("ASYA_A2A_PUBLIC_URL", "")

	// Determine default I/O modes from first agent with modes set
	defaultInputModes := []string{"application/json"}
	defaultOutputModes := []string{"application/json"}
	for _, agent := range agents {
		if len(agent.InputModes) > 0 {
			defaultInputModes = agent.InputModes
		}
		if len(agent.OutputModes) > 0 {
			defaultOutputModes = agent.OutputModes
		}
		break
	}

	// Determine streaming from any agent
	streaming := false
	for _, agent := range agents {
		if agent.Streaming {
			streaming = true
			break
		}
	}

	return &a2alib.AgentCard{
		Name:        name,
		Description: desc,
		Version:     version,
		URL:         publicURL,
		Capabilities: a2alib.AgentCapabilities{
			Streaming:         streaming,
			PushNotifications: false,
		},
		DefaultInputModes:  defaultInputModes,
		DefaultOutputModes: defaultOutputModes,
		Skills:             a2aSkills,
		Provider: &a2alib.AgentProvider{
			Org: envOr("ASYA_A2A_PROVIDER_ORG", "Asya"),
			URL: envOr("ASYA_A2A_PROVIDER_URL", "https://asya.sh"),
		},
	}, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
