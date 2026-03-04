package a2a

import (
	"context"
	"testing"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
)

func TestCardProducer_NoAuth(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "")

	registry := toolstore.NewInMemoryRegistry()
	producer := NewCardProducer(registry)

	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if card.SecuritySchemes != nil {
		t.Fatalf("expected no security schemes, got %v", card.SecuritySchemes)
	}
	if card.Security != nil {
		t.Fatalf("expected no security requirements, got %v", card.Security)
	}
}

func TestCardProducer_APIKeyOnly(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "test-key")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "")

	registry := toolstore.NewInMemoryRegistry()
	producer := NewCardProducer(registry)

	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(card.SecuritySchemes) != 1 {
		t.Fatalf("expected 1 security scheme, got %d", len(card.SecuritySchemes))
	}
	if _, ok := card.SecuritySchemes[a2alib.SecuritySchemeName("apiKey")]; !ok {
		t.Fatal("expected apiKey scheme")
	}
	if len(card.Security) != 1 {
		t.Fatal("expected 1 security requirement")
	}
}

func TestCardProducer_BothSchemes(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "test-key")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "https://example.com/.well-known/jwks.json")
	t.Setenv("ASYA_A2A_JWT_ISSUER", "https://example.com")
	t.Setenv("ASYA_A2A_JWT_AUDIENCE", "test-audience")

	registry := toolstore.NewInMemoryRegistry()
	producer := NewCardProducer(registry)

	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(card.SecuritySchemes) != 2 {
		t.Fatalf("expected 2 security schemes, got %d", len(card.SecuritySchemes))
	}
	if _, ok := card.SecuritySchemes[a2alib.SecuritySchemeName("apiKey")]; !ok {
		t.Fatal("expected apiKey scheme")
	}
	if _, ok := card.SecuritySchemes[a2alib.SecuritySchemeName("bearer")]; !ok {
		t.Fatal("expected bearer scheme")
	}

	// Check bearer scheme details
	bearerScheme, ok := card.SecuritySchemes[a2alib.SecuritySchemeName("bearer")].(a2alib.HTTPAuthSecurityScheme)
	if !ok {
		t.Fatal("expected HTTPAuthSecurityScheme for bearer")
	}
	if bearerScheme.Scheme != "bearer" {
		t.Fatalf("expected scheme 'bearer', got %q", bearerScheme.Scheme)
	}
	if bearerScheme.BearerFormat != "JWT" {
		t.Fatalf("expected bearerFormat 'JWT', got %q", bearerScheme.BearerFormat)
	}

	// OR semantics: 2 security requirements
	if len(card.Security) != 2 {
		t.Fatalf("expected 2 security requirements (OR semantics), got %d", len(card.Security))
	}
}

func TestCardProducer_PartialJWTConfig(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "https://example.com/.well-known/jwks.json")
	t.Setenv("ASYA_A2A_JWT_ISSUER", "")
	t.Setenv("ASYA_A2A_JWT_AUDIENCE", "")

	registry := toolstore.NewInMemoryRegistry()
	producer := NewCardProducer(registry)

	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if card.SecuritySchemes != nil {
		t.Fatalf("expected no security schemes with partial JWT config, got %v", card.SecuritySchemes)
	}
}

func TestCardProducer_SupportsExtendedCard(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "test-key")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "")
	t.Setenv("ASYA_A2A_JWT_ISSUER", "")
	t.Setenv("ASYA_A2A_JWT_AUDIENCE", "")

	registry := toolstore.NewInMemoryRegistry()
	producer := NewCardProducer(registry)

	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if !card.SupportsAuthenticatedExtendedCard {
		t.Fatal("expected SupportsAuthenticatedExtendedCard to be true when auth is configured")
	}
}

func TestCardProducer_NoExtendedCardWithoutAuth(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "")
	t.Setenv("ASYA_A2A_JWT_ISSUER", "")
	t.Setenv("ASYA_A2A_JWT_AUDIENCE", "")

	registry := toolstore.NewInMemoryRegistry()
	producer := NewCardProducer(registry)

	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if card.SupportsAuthenticatedExtendedCard {
		t.Fatal("expected SupportsAuthenticatedExtendedCard to be false when no auth")
	}
}

func TestExtendedCardProducer_EnrichesSkills(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "test-key")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "")
	t.Setenv("ASYA_A2A_JWT_ISSUER", "")
	t.Setenv("ASYA_A2A_JWT_AUDIENCE", "")

	registry := toolstore.NewInMemoryRegistry()
	timeout := 30
	tool := toolstore.Tool{
		Name:        "test-skill",
		Actor:       "text-analyzer",
		Description: "Analyzes text",
		A2AEnabled:  true,
		TimeoutSec:  &timeout,
		Progress:    true,
		A2ATags:     []string{"analysis"},
	}
	if err := registry.Upsert(context.Background(), tool); err != nil {
		t.Fatalf("failed to upsert tool: %v", err)
	}

	producer := NewExtendedCardProducer(registry)
	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(card.Skills) != 1 {
		t.Fatalf("expected 1 skill, got %d", len(card.Skills))
	}

	skill := card.Skills[0]
	if skill.Name != "test-skill" {
		t.Fatalf("expected skill name 'test-skill', got %q", skill.Name)
	}

	// Check that tags include internal details via x-prefixed tags
	expectedTags := map[string]bool{
		"analysis":              false,
		"x-actor:text-analyzer": false,
		"x-timeout:30":          false,
		"x-progress:true":       false,
	}
	for _, tag := range skill.Tags {
		if _, ok := expectedTags[tag]; ok {
			expectedTags[tag] = true
		}
	}
	for tag, found := range expectedTags {
		if !found {
			t.Fatalf("expected tag %q not found in skill tags: %v", tag, skill.Tags)
		}
	}

	// Verify provider details
	if card.Provider == nil {
		t.Fatal("expected provider to be set")
	}
	if card.Provider.Org != "Asya" {
		t.Fatalf("expected provider org 'Asya', got %q", card.Provider.Org)
	}
}

func TestExtendedCardProducer_NoTimeoutOrProgress(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "")
	t.Setenv("ASYA_A2A_JWT_ISSUER", "")
	t.Setenv("ASYA_A2A_JWT_AUDIENCE", "")

	registry := toolstore.NewInMemoryRegistry()
	tool := toolstore.Tool{
		Name:        "simple-skill",
		Actor:       "simple-actor",
		Description: "A simple skill",
		A2AEnabled:  true,
		A2ATags:     []string{"simple"},
	}
	if err := registry.Upsert(context.Background(), tool); err != nil {
		t.Fatalf("failed to upsert tool: %v", err)
	}

	producer := NewExtendedCardProducer(registry)
	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(card.Skills) != 1 {
		t.Fatalf("expected 1 skill, got %d", len(card.Skills))
	}

	// Should have original tag + x-actor, but no x-timeout or x-progress
	skill := card.Skills[0]
	expectedTags := []string{"simple", "x-actor:simple-actor"}
	if len(skill.Tags) != len(expectedTags) {
		t.Fatalf("expected %d tags, got %d: %v", len(expectedTags), len(skill.Tags), skill.Tags)
	}
}

func TestCardProducer_JWTOnly(t *testing.T) {
	t.Setenv("ASYA_A2A_API_KEY", "")
	t.Setenv("ASYA_A2A_JWT_JWKS_URL", "https://example.com/.well-known/jwks.json")
	t.Setenv("ASYA_A2A_JWT_ISSUER", "https://example.com")
	t.Setenv("ASYA_A2A_JWT_AUDIENCE", "test-audience")

	registry := toolstore.NewInMemoryRegistry()
	producer := NewCardProducer(registry)

	card, err := producer.Card(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(card.SecuritySchemes) != 1 {
		t.Fatalf("expected 1 security scheme, got %d", len(card.SecuritySchemes))
	}
	if _, ok := card.SecuritySchemes[a2alib.SecuritySchemeName("bearer")]; !ok {
		t.Fatal("expected bearer scheme")
	}
	if len(card.Security) != 1 {
		t.Fatal("expected 1 security requirement")
	}
}
