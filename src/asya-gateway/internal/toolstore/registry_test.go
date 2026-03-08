package toolstore

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
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

func TestNewRegistryFromDir(t *testing.T) {
	dir := t.TempDir()

	// Write a flows.yaml with two flows
	flowsYAML := `
flows:
  - name: classify-text
    entrypoint: text-classifier
    description: "Classifies text into categories"
    mcp:
      progress: true
      inputSchema:
        type: object
        properties:
          text:
            type: string
    a2a:
      tags: [nlp, classification]
      input_modes: [text/plain]
      output_modes: [application/json]
  - name: summarize
    entrypoint: summarizer
    description: "Summarizes long texts"
    mcp: {}
`
	if err := os.WriteFile(filepath.Join(dir, "flows.yaml"), []byte(flowsYAML), 0o600); err != nil {
		t.Fatalf("write flows.yaml: %v", err)
	}

	r, err := NewRegistryFromDir(dir)
	if err != nil {
		t.Fatalf("NewRegistryFromDir: %v", err)
	}

	all := r.All()
	if len(all) != 2 {
		t.Fatalf("expected 2 tools, got %d", len(all))
	}

	// Verify classify-text
	ct := r.GetByName("classify-text")
	if ct == nil {
		t.Fatal("tool 'classify-text' not found")
	}
	if ct.Actor != "text-classifier" {
		t.Errorf("expected actor 'text-classifier', got %q", ct.Actor)
	}
	if !ct.MCPEnabled {
		t.Error("expected MCPEnabled=true for classify-text")
	}
	if !ct.Progress {
		t.Error("expected Progress=true for classify-text")
	}
	if !ct.A2AEnabled {
		t.Error("expected A2AEnabled=true for classify-text")
	}
	if len(ct.A2ATags) != 2 {
		t.Errorf("expected 2 A2A tags, got %d", len(ct.A2ATags))
	}

	// Verify summarize
	sm := r.GetByName("summarize")
	if sm == nil {
		t.Fatal("tool 'summarize' not found")
	}
	if sm.Actor != "summarizer" {
		t.Errorf("expected actor 'summarizer', got %q", sm.Actor)
	}
	if !sm.MCPEnabled {
		t.Error("expected MCPEnabled=true for summarize")
	}
	if sm.A2AEnabled {
		t.Error("expected A2AEnabled=false for summarize (no a2a block)")
	}

	// Verify MCP filter
	mcpTools := r.MCPTools()
	if len(mcpTools) != 2 {
		t.Errorf("expected 2 MCP tools, got %d", len(mcpTools))
	}

	// Verify A2A filter
	a2aSkills := r.A2ASkills()
	if len(a2aSkills) != 1 {
		t.Errorf("expected 1 A2A skill, got %d", len(a2aSkills))
	}
}

func TestNewRegistryFromDirMultipleFiles(t *testing.T) {
	dir := t.TempDir()

	file1 := `flows:
  - name: flow-a
    entrypoint: actor-a
    mcp: {}
`
	file2 := `flows:
  - name: flow-b
    entrypoint: actor-b
    a2a:
      tags: [test]
`
	if err := os.WriteFile(filepath.Join(dir, "a.yaml"), []byte(file1), 0o600); err != nil {
		t.Fatalf("write a.yaml: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "b.yaml"), []byte(file2), 0o600); err != nil {
		t.Fatalf("write b.yaml: %v", err)
	}

	r, err := NewRegistryFromDir(dir)
	if err != nil {
		t.Fatalf("NewRegistryFromDir: %v", err)
	}

	if len(r.All()) != 2 {
		t.Errorf("expected 2 tools across 2 files, got %d", len(r.All()))
	}
}

func TestNewRegistryFromDirNonYAMLIgnored(t *testing.T) {
	dir := t.TempDir()

	flowsYAML := `flows:
  - name: valid-flow
    entrypoint: valid-actor
    mcp: {}
`
	if err := os.WriteFile(filepath.Join(dir, "flows.yaml"), []byte(flowsYAML), 0o600); err != nil {
		t.Fatalf("write flows.yaml: %v", err)
	}
	// Non-YAML files should be skipped
	if err := os.WriteFile(filepath.Join(dir, "README"), []byte("not yaml"), 0o600); err != nil {
		t.Fatalf("write README: %v", err)
	}

	r, err := NewRegistryFromDir(dir)
	if err != nil {
		t.Fatalf("NewRegistryFromDir: %v", err)
	}

	if len(r.All()) != 1 {
		t.Errorf("expected 1 tool, got %d (non-YAML files should be ignored)", len(r.All()))
	}
}

func TestNewRegistryFromDirValidation(t *testing.T) {
	dir := t.TempDir()

	// Flow missing entrypoint should error
	badYAML := `flows:
  - name: missing-entrypoint
`
	if err := os.WriteFile(filepath.Join(dir, "bad.yaml"), []byte(badYAML), 0o600); err != nil {
		t.Fatalf("write bad.yaml: %v", err)
	}

	_, err := NewRegistryFromDir(dir)
	if err == nil {
		t.Fatal("expected error for flow missing entrypoint, got nil")
	}
}
