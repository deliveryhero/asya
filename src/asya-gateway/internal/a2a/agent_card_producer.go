package a2a

import (
	"context"
	"fmt"
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
			Org: getEnvOrDefault("ASYA_A2A_PROVIDER_ORG", "Asya"),
			URL: getEnvOrDefault("ASYA_A2A_PROVIDER_URL", "https://asya.sh"),
		},
	}

	schemes := a2alib.NamedSecuritySchemes{}
	var security []a2alib.SecurityRequirements

	if apiKey := os.Getenv("ASYA_A2A_API_KEY"); apiKey != "" {
		schemes[a2alib.SecuritySchemeName("apiKey")] = a2alib.APIKeySecurityScheme{
			In:   a2alib.APIKeySecuritySchemeInHeader,
			Name: "X-API-Key",
		}
		security = append(security, a2alib.SecurityRequirements{
			a2alib.SecuritySchemeName("apiKey"): a2alib.SecuritySchemeScopes{},
		})
	}

	if os.Getenv("ASYA_A2A_JWT_JWKS_URL") != "" && os.Getenv("ASYA_A2A_JWT_ISSUER") != "" && os.Getenv("ASYA_A2A_JWT_AUDIENCE") != "" {
		schemes[a2alib.SecuritySchemeName("bearer")] = a2alib.HTTPAuthSecurityScheme{
			Scheme:       "bearer",
			BearerFormat: "JWT",
		}
		security = append(security, a2alib.SecurityRequirements{
			a2alib.SecuritySchemeName("bearer"): a2alib.SecuritySchemeScopes{},
		})
	}

	if len(schemes) > 0 {
		card.SecuritySchemes = schemes
		card.Security = security
		card.SupportsAuthenticatedExtendedCard = true
	}

	return card, nil
}

// ExtendedCardProducer implements a2asrv.AgentCardProducer for the extended
// (authenticated) agent card. It includes additional internal details like
// actor names and timeout configuration per skill.
type ExtendedCardProducer struct {
	publicProducer *CardProducer
	registry       *toolstore.Registry
}

// NewExtendedCardProducer creates a new ExtendedCardProducer.
func NewExtendedCardProducer(registry *toolstore.Registry) *ExtendedCardProducer {
	return &ExtendedCardProducer{
		publicProducer: NewCardProducer(registry),
		registry:       registry,
	}
}

// Card returns the extended AgentCard with internal skill details.
func (p *ExtendedCardProducer) Card(ctx context.Context) (*a2alib.AgentCard, error) {
	card, err := p.publicProducer.Card(ctx)
	if err != nil {
		return nil, err
	}

	// Enrich skills with internal metadata via x-prefixed tags
	skills := p.registry.A2ASkills()
	enrichedSkills := make([]a2alib.AgentSkill, 0, len(skills))
	for _, s := range skills {
		tags := append([]string{}, s.A2ATags...)
		tags = append(tags, "x-actor:"+s.Actor)
		if s.TimeoutSec != nil {
			tags = append(tags, fmt.Sprintf("x-timeout:%d", *s.TimeoutSec))
		}
		if s.Progress {
			tags = append(tags, "x-progress:true")
		}

		enrichedSkills = append(enrichedSkills, a2alib.AgentSkill{
			ID:          s.Name,
			Name:        s.Name,
			Description: s.Description,
			Tags:        tags,
			InputModes:  s.A2AInputModes,
			OutputModes: s.A2AOutputModes,
			Examples:    s.A2AExamples,
		})
	}
	card.Skills = enrichedSkills

	return card, nil
}

func getEnvOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
