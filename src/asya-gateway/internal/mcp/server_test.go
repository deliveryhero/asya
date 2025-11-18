package mcp

import (
	"context"
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/envelopestore"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// MockQueueClient implements queue.Client for testing
type MockQueueClient struct{}

func (m *MockQueueClient) SendEnvelope(ctx context.Context, envelope *types.Envelope) error {
	return nil
}

func (m *MockQueueClient) Receive(ctx context.Context, queueName string) (queue.QueueMessage, error) {
	return nil, nil
}

func (m *MockQueueClient) Ack(ctx context.Context, msg queue.QueueMessage) error {
	return nil
}

func (m *MockQueueClient) Close() error {
	return nil
}

func TestNewServer_WithoutConfig(t *testing.T) {
	// Test server creation with nil config (uses hardcoded tools)
	jobStore := envelopestore.NewStore()
	queueClient := &MockQueueClient{}

	server := NewServer(jobStore, queueClient, nil)

	if server == nil {
		t.Fatal("NewServer returned nil")
	}

	if server.mcpServer == nil {
		t.Fatal("MCP server not initialized")
	}

	if server.registry == nil {
		t.Error("Registry should be created even when config is nil (for REST API support)")
	}

	// Verify at least the hardcoded tool is registered
	mcpServer := server.GetMCPServer()
	if mcpServer == nil {
		t.Fatal("GetMCPServer returned nil")
	}

	tools := mcpServer.ListTools()
	if len(tools) == 0 {
		t.Error("Expected at least one hardcoded tool to be registered")
	}

	if _, exists := tools["processImageWorkflow"]; !exists {
		t.Error("Hardcoded tool 'processImageWorkflow' not found")
	}
}

func TestNewServer_WithConfig(t *testing.T) {
	// Create test configuration
	cfg := &config.Config{
		Tools: []config.Tool{
			{
				Name:        "test_tool",
				Description: "A test tool",
				Parameters: map[string]config.Parameter{
					"input": {
						Type:        "string",
						Description: "Test input",
						Required:    true,
					},
				},
				Route: config.RouteSpec{
					Actors: []string{"actor1", "actor2"},
				},
			},
		},
	}

	if err := cfg.Validate(); err != nil {
		t.Fatalf("Config validation failed: %v", err)
	}

	jobStore := envelopestore.NewStore()
	queueClient := &MockQueueClient{}

	server := NewServer(jobStore, queueClient, cfg)

	if server == nil {
		t.Fatal("NewServer returned nil")
	}

	if server.registry == nil {
		t.Fatal("Registry should not be nil when config is provided")
	}

	// Verify tool from config is registered
	mcpServer := server.GetMCPServer()
	tools := mcpServer.ListTools()

	if len(tools) == 0 {
		t.Fatal("No tools registered from config")
	}

	if _, exists := tools["test_tool"]; !exists {
		t.Error("Tool from config not registered")
	}

	// Verify hardcoded tools are NOT registered when config is provided
	if _, exists := tools["processImageWorkflow"]; exists {
		t.Error("Hardcoded tool should not be registered when config is provided")
	}
}

func TestNewServer_WithMultipleTools(t *testing.T) {
	cfg := &config.Config{
		Tools: []config.Tool{
			{
				Name:        "tool1",
				Description: "First tool",
				Parameters: map[string]config.Parameter{
					"param1": {Type: "string", Required: true},
				},
				Route: config.RouteSpec{Actors: []string{"actor1"}},
			},
			{
				Name:        "tool2",
				Description: "Second tool",
				Parameters: map[string]config.Parameter{
					"param2": {Type: "number", Required: false},
				},
				Route: config.RouteSpec{Actors: []string{"actor2", "actor3"}},
			},
			{
				Name:        "tool3",
				Description: "Third tool",
				Parameters: map[string]config.Parameter{
					"param3": {Type: "boolean", Required: true},
				},
				Route: config.RouteSpec{Actors: []string{"actor4"}},
			},
		},
	}

	if err := cfg.Validate(); err != nil {
		t.Fatalf("Config validation failed: %v", err)
	}

	jobStore := envelopestore.NewStore()
	queueClient := &MockQueueClient{}

	server := NewServer(jobStore, queueClient, cfg)

	mcpServer := server.GetMCPServer()
	tools := mcpServer.ListTools()

	if len(tools) != 3 {
		t.Errorf("Expected 3 tools, got %d", len(tools))
	}

	expectedTools := []string{"tool1", "tool2", "tool3"}
	for _, toolName := range expectedTools {
		if _, exists := tools[toolName]; !exists {
			t.Errorf("Tool %q not registered", toolName)
		}
	}
}

func TestNewServer_WithRouteTemplates(t *testing.T) {
	cfg := &config.Config{
		Routes: map[string][]string{
			"standard-pipeline": {"parser", "processor", "finalizer"},
			"simple-flow":       {"handler"},
		},
		Tools: []config.Tool{
			{
				Name:        "tool_with_template",
				Description: "Tool using template",
				Parameters: map[string]config.Parameter{
					"data": {Type: "string", Required: true},
				},
				Route: config.RouteSpec{Template: "standard-pipeline"},
			},
			{
				Name:        "tool_with_simple_flow",
				Description: "Tool using simple flow",
				Parameters: map[string]config.Parameter{
					"value": {Type: "number", Required: true},
				},
				Route: config.RouteSpec{Template: "simple-flow"},
			},
		},
	}

	if err := cfg.Validate(); err != nil {
		t.Fatalf("Config validation failed: %v", err)
	}

	jobStore := envelopestore.NewStore()
	queueClient := &MockQueueClient{}

	server := NewServer(jobStore, queueClient, cfg)

	if server.registry == nil {
		t.Fatal("Registry should not be nil")
	}

	mcpServer := server.GetMCPServer()
	tools := mcpServer.ListTools()

	if len(tools) != 2 {
		t.Errorf("Expected 2 tools, got %d", len(tools))
	}

	// Verify route templates are resolved
	opts1, err := server.registry.GetToolOptions("tool_with_template")
	if err != nil {
		t.Errorf("Failed to get tool options: %v", err)
	} else if opts1 == nil {
		t.Error("Tool options should not be nil")
	}

	opts2, err := server.registry.GetToolOptions("tool_with_simple_flow")
	if err != nil {
		t.Errorf("Failed to get tool options: %v", err)
	} else if opts2 == nil {
		t.Error("Tool options should not be nil")
	}
}

func TestNewServer_WithDefaults(t *testing.T) {
	progressTrue := true
	timeout := 300

	cfg := &config.Config{
		Defaults: &config.ToolDefaults{
			Progress: &progressTrue,
			Timeout:  &timeout,
		},
		Tools: []config.Tool{
			{
				Name:        "tool_with_defaults",
				Description: "Tool using defaults",
				Parameters: map[string]config.Parameter{
					"data": {Type: "string", Required: true},
				},
				Route: config.RouteSpec{Actors: []string{"actor1"}},
			},
		},
	}

	if err := cfg.Validate(); err != nil {
		t.Fatalf("Config validation failed: %v", err)
	}

	jobStore := envelopestore.NewStore()
	queueClient := &MockQueueClient{}

	server := NewServer(jobStore, queueClient, cfg)

	if server.registry == nil {
		t.Fatal("Registry should not be nil")
	}

	opts, err := server.registry.GetToolOptions("tool_with_defaults")
	if err != nil {
		t.Fatalf("Failed to get tool options: %v", err)
	}

	if !opts.Progress {
		t.Error("Expected progress to be true from defaults")
	}

	if opts.Timeout.Seconds() != 300 {
		t.Errorf("Expected timeout 300s from defaults, got %.0fs", opts.Timeout.Seconds())
	}
}

func TestNewServer_InvalidConfig(t *testing.T) {
	tests := []struct {
		name   string
		config *config.Config
	}{
		{
			name: "empty route",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:        "invalid_tool",
						Description: "Tool with empty route",
						Parameters:  map[string]config.Parameter{},
						Route:       config.RouteSpec{Actors: []string{}},
					},
				},
			},
		},
		{
			name: "no tools",
			config: &config.Config{
				Tools: []config.Tool{},
			},
		},
		{
			name: "duplicate tool names",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:  "duplicate",
						Route: config.RouteSpec{Actors: []string{"actor1"}},
					},
					{
						Name:  "duplicate",
						Route: config.RouteSpec{Actors: []string{"actor2"}},
					},
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := tt.config.Validate(); err == nil {
				t.Errorf("Expected validation error for %s, got nil", tt.name)
			}
		})
	}
}
