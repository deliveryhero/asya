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
