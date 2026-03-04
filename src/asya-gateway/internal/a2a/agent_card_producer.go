package a2a

import (
	"context"
	"os"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
)

// CardProducer implements a2asrv.AgentCardProducer, building an AgentCard
// dynamically from the tool registry.
type CardProducer struct {
	registry *toolstore.Registry
}

// NewCardProducer creates a new CardProducer.
func NewCardProducer(registry *toolstore.Registry) *CardProducer {
	return &CardProducer{registry: registry}
}

// Card returns the current AgentCard based on registered A2A skills.
func (p *CardProducer) Card(_ context.Context) (*a2alib.AgentCard, error) {
	skills := p.registry.A2ASkills()

	var a2aSkills []a2alib.AgentSkill
	for _, s := range skills {
		a2aSkills = append(a2aSkills, a2alib.AgentSkill{
			ID:          s.Name,
			Name:        s.Name,
			Description: s.Description,
			Tags:        s.A2ATags,
			InputModes:  s.A2AInputModes,
			OutputModes: s.A2AOutputModes,
			Examples:    s.A2AExamples,
		})
	}

	name := getEnvOrDefault("ASYA_A2A_NAME", "Asya Gateway")
	desc := getEnvOrDefault("ASYA_A2A_DESCRIPTION", "AI Actor Mesh for distributed agentic workloads")
	version := getEnvOrDefault("ASYA_A2A_VERSION", "1.0.0")
	publicURL := getEnvOrDefault("ASYA_A2A_PUBLIC_URL", "")

	card := &a2alib.AgentCard{
		Name:        name,
		Description: desc,
		Version:     version,
		URL:         publicURL,
		Capabilities: a2alib.AgentCapabilities{
			Streaming:         true,
			PushNotifications: false,
		},
		DefaultInputModes:  []string{"application/json"},
		DefaultOutputModes: []string{"application/json"},
		Skills:             a2aSkills,
		Provider: &a2alib.AgentProvider{
			Org: "Asya",
			URL: "https://asya.sh",
		},
	}

	if apiKey := os.Getenv("ASYA_A2A_API_KEY"); apiKey != "" {
		card.SecuritySchemes = a2alib.NamedSecuritySchemes{
			a2alib.SecuritySchemeName("apiKey"): a2alib.APIKeySecurityScheme{
				In:   a2alib.APIKeySecuritySchemeInHeader,
				Name: "X-API-Key",
			},
		}
		card.Security = []a2alib.SecurityRequirements{
			{a2alib.SecuritySchemeName("apiKey"): a2alib.SecuritySchemeScopes{}},
		}
	}

	return card, nil
}

func getEnvOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
