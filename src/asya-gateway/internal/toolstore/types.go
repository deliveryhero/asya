package toolstore

import (
	"encoding/json"
	"time"
)

// Tool represents a registered tool/skill in the DB-backed registry.
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
	CreatedAt      time.Time       `json:"created_at"`
	UpdatedAt      time.Time       `json:"updated_at"`
}

// RegisterRequest is the JSON body for POST /mesh/expose.
type RegisterRequest struct {
	Name        string          `json:"name"`
	Actor       string          `json:"actor"`
	Route       []string        `json:"route,omitempty"`
	Description string          `json:"description"`
	Parameters  json.RawMessage `json:"parameters,omitempty"`
	TimeoutSec  *int            `json:"timeout_sec,omitempty"`
	Progress    bool            `json:"progress"`
	MCPEnabled  *bool           `json:"mcp_enabled,omitempty"`
	A2A         *A2AConfig      `json:"a2a,omitempty"`
}

// A2AConfig is the a2a sub-object in RegisterRequest.
type A2AConfig struct {
	Enabled     bool     `json:"enabled"`
	Tags        []string `json:"tags,omitempty"`
	InputModes  []string `json:"input_modes,omitempty"`
	OutputModes []string `json:"output_modes,omitempty"`
	Examples    []string `json:"examples,omitempty"`
}
