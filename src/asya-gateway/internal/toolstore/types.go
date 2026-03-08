package toolstore

import (
	"encoding/json"
	"fmt"
)

// Tool represents a registered flow/skill in the in-memory registry.
type Tool struct {
	Name           string          `json:"name"`
	Actor          string          `json:"actor"`
	Description    string          `json:"description"`
	Parameters     json.RawMessage `json:"parameters"`
	TimeoutSec     *int            `json:"timeout_sec,omitempty"`
	Progress       bool            `json:"progress"`
	MCPEnabled     bool            `json:"mcp_enabled"`
	A2AEnabled     bool            `json:"a2a_enabled"`
	A2ATags        []string        `json:"a2a_tags,omitempty"`
	RouteNext      []string        `json:"route_next,omitempty"`
	A2AInputModes  []string        `json:"a2a_input_modes,omitempty"`
	A2AOutputModes []string        `json:"a2a_output_modes,omitempty"`
	A2AExamples    []string        `json:"a2a_examples,omitempty"`
}

// FlowsFile is the top-level structure of flows.yaml.
type FlowsFile struct {
	Flows []FlowConfig `yaml:"flows"`
}

// FlowConfig describes a single flow entry in flows.yaml.
type FlowConfig struct {
	Name        string         `yaml:"name"`
	Entrypoint  string         `yaml:"entrypoint"`
	RouteNext   []string       `yaml:"route_next,omitempty"`
	Description string         `yaml:"description"`
	TimeoutSec  *int           `yaml:"timeout,omitempty"`
	MCP         *MCPFlowConfig `yaml:"mcp,omitempty"`
	A2A         *A2AFlowConfig `yaml:"a2a,omitempty"`
}

// MCPFlowConfig is the mcp sub-object in FlowConfig.
type MCPFlowConfig struct {
	InputSchema any  `yaml:"inputSchema,omitempty"`
	Progress    bool `yaml:"progress,omitempty"`
}

// A2AFlowConfig is the a2a sub-object in FlowConfig.
type A2AFlowConfig struct {
	Tags        []string `yaml:"tags,omitempty"`
	InputModes  []string `yaml:"input_modes,omitempty"`
	OutputModes []string `yaml:"output_modes,omitempty"`
	Examples    []string `yaml:"examples,omitempty"`
}

// flowConfigToTool converts a FlowConfig to a Tool.
// MCP is enabled when the mcp: block is present.
// A2A is enabled when the a2a: block is present.
func flowConfigToTool(f FlowConfig) (Tool, error) {
	if f.Name == "" {
		return Tool{}, fmt.Errorf("flow name is required")
	}
	if f.Entrypoint == "" {
		return Tool{}, fmt.Errorf("flow %q: entrypoint is required", f.Name)
	}

	t := Tool{
		Name:        f.Name,
		Actor:       f.Entrypoint,
		RouteNext:   f.RouteNext,
		Description: f.Description,
		TimeoutSec:  f.TimeoutSec,
	}

	if f.MCP != nil {
		t.MCPEnabled = true
		t.Progress = f.MCP.Progress
		if f.MCP.InputSchema != nil {
			params, err := json.Marshal(f.MCP.InputSchema)
			if err != nil {
				return Tool{}, fmt.Errorf("flow %q: marshal inputSchema: %w", f.Name, err)
			}
			t.Parameters = json.RawMessage(params)
		} else {
			t.Parameters = json.RawMessage(`{}`)
		}
	}

	if f.A2A != nil {
		t.A2AEnabled = true
		t.A2ATags = f.A2A.Tags
		t.A2AInputModes = f.A2A.InputModes
		t.A2AOutputModes = f.A2A.OutputModes
		t.A2AExamples = f.A2A.Examples
	}

	return t, nil
}
