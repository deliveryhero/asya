package toolstore

import (
	"context"
	"encoding/json"
	"testing"
)

func TestEmptyRegistry(t *testing.T) {
	r := NewInMemoryRegistry()
	tools := r.All()

	if len(tools) != 0 {
		t.Errorf("expected 0 tools, got %d", len(tools))
	}
}

func TestUpsertAndGetByName(t *testing.T) {
	r := NewInMemoryRegistry()
	ctx := context.Background()

	tool := Tool{
		Name:        "test-tool",
		Actor:       "test-actor",
		Description: "A test tool",
		Parameters:  json.RawMessage(`{"type": "object"}`),
		Progress:    true,
		MCPEnabled:  true,
		A2AEnabled:  false,
	}

	// Upsert
	if err := r.Upsert(ctx, tool); err != nil {
		t.Fatalf("failed to upsert tool: %v", err)
	}

	// Retrieve
	retrieved := r.GetByName("test-tool")
	if retrieved == nil {
		t.Fatal("tool not found")
	}

	if retrieved.Name != "test-tool" {
		t.Errorf("expected name 'test-tool', got '%s'", retrieved.Name)
	}
	if retrieved.Actor != "test-actor" {
		t.Errorf("expected actor 'test-actor', got '%s'", retrieved.Actor)
	}
	if !retrieved.MCPEnabled {
		t.Error("expected MCPEnabled to be true")
	}
}

func TestMCPToolsFilter(t *testing.T) {
	r := NewInMemoryRegistry()
	ctx := context.Background()

	tool1 := Tool{Name: "mcp-tool", Actor: "actor1", MCPEnabled: true}
	tool2 := Tool{Name: "non-mcp-tool", Actor: "actor2", MCPEnabled: false}

	if err := r.Upsert(ctx, tool1); err != nil {
		t.Fatalf("failed to upsert tool1: %v", err)
	}
	if err := r.Upsert(ctx, tool2); err != nil {
		t.Fatalf("failed to upsert tool2: %v", err)
	}

	mcpTools := r.MCPTools()
	if len(mcpTools) != 1 {
		t.Fatalf("expected 1 MCP tool, got %d", len(mcpTools))
	}

	if mcpTools[0].Name != "mcp-tool" {
		t.Errorf("expected 'mcp-tool', got '%s'", mcpTools[0].Name)
	}
}

func TestA2ASkillsFilter(t *testing.T) {
	r := NewInMemoryRegistry()
	ctx := context.Background()

	tool1 := Tool{Name: "a2a-tool", Actor: "actor1", A2AEnabled: true}
	tool2 := Tool{Name: "non-a2a-tool", Actor: "actor2", A2AEnabled: false}

	if err := r.Upsert(ctx, tool1); err != nil {
		t.Fatalf("failed to upsert tool1: %v", err)
	}
	if err := r.Upsert(ctx, tool2); err != nil {
		t.Fatalf("failed to upsert tool2: %v", err)
	}

	a2aSkills := r.A2ASkills()
	if len(a2aSkills) != 1 {
		t.Fatalf("expected 1 A2A skill, got %d", len(a2aSkills))
	}

	if a2aSkills[0].Name != "a2a-tool" {
		t.Errorf("expected 'a2a-tool', got '%s'", a2aSkills[0].Name)
	}
}

func TestUpsertDisableA2A(t *testing.T) {
	r := NewInMemoryRegistry()
	ctx := context.Background()

	// Create tool with A2A enabled
	tool := Tool{Name: "changeable-tool", Actor: "actor1", A2AEnabled: true}
	if err := r.Upsert(ctx, tool); err != nil {
		t.Fatalf("failed to upsert tool: %v", err)
	}

	// Verify it's in A2ASkills
	a2aSkills := r.A2ASkills()
	if len(a2aSkills) != 1 {
		t.Fatalf("expected 1 A2A skill, got %d", len(a2aSkills))
	}

	// Update to disable A2A
	tool.A2AEnabled = false
	if err := r.Upsert(ctx, tool); err != nil {
		t.Fatalf("failed to update tool: %v", err)
	}

	// Verify it's removed from A2ASkills
	a2aSkills = r.A2ASkills()
	if len(a2aSkills) != 0 {
		t.Fatalf("expected 0 A2A skills, got %d", len(a2aSkills))
	}
}

func TestValidationEmptyName(t *testing.T) {
	r := NewInMemoryRegistry()
	ctx := context.Background()

	tool := Tool{Name: "", Actor: "actor1"}
	err := r.Upsert(ctx, tool)

	if err == nil {
		t.Fatal("expected error for empty name, got nil")
	}
	if err.Error() != "tool name is required" {
		t.Errorf("expected 'tool name is required', got '%s'", err.Error())
	}
}

func TestValidationEmptyActor(t *testing.T) {
	r := NewInMemoryRegistry()
	ctx := context.Background()

	tool := Tool{Name: "test-tool", Actor: ""}
	err := r.Upsert(ctx, tool)

	if err == nil {
		t.Fatal("expected error for empty actor, got nil")
	}
	if err.Error() != "tool actor is required" {
		t.Errorf("expected 'tool actor is required', got '%s'", err.Error())
	}
}
