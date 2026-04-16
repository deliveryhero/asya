// Package mcpadapter implements the MCP Streamable HTTP adapter.
// This is the new package for the rearchitected adapter binary.
// During the transition, it coexists with the old internal/mcp/ package
// which will be deleted when the monolith gateway is removed.
package mcpadapter

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"gopkg.in/yaml.v3"
)

// ToolConfig is a single MCP tool definition from the ConfigMap.
type ToolConfig struct {
	Name        string          `yaml:"name" json:"name"`
	Description string          `yaml:"description" json:"description"`
	Actor       string          `yaml:"actor" json:"actor"`
	Timeout     int             `yaml:"timeout" json:"timeout"` // seconds, 0 = default (300)
	Progress    bool            `yaml:"progress" json:"progress"`
	InputSchema json.RawMessage `yaml:"-" json:"inputSchema"` // JSON Schema (populated from RawInputSchema)
	// RawInputSchema holds the YAML-parsed input schema as a generic map.
	// After loading, it is converted to InputSchema (json.RawMessage).
	RawInputSchema any `yaml:"inputSchema" json:"-"`
}

// ToolsFile is the top-level structure of a tools ConfigMap YAML file.
type ToolsFile struct {
	Tools []ToolConfig `yaml:"tools"`
}

// Registry holds the current set of MCP tool definitions. Thread-safe.
type Registry struct {
	mu    sync.RWMutex
	tools []ToolConfig
}

// NewRegistry creates an empty registry.
func NewRegistry() *Registry {
	return &Registry{}
}

// LoadFromDir reads all *.yaml / *.yml files in dir, parses ToolsFile entries,
// and atomically replaces the current tool set. On error the previous set is preserved.
func (r *Registry) LoadFromDir(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return fmt.Errorf("read config dir %q: %w", dir, err)
	}

	var tools []ToolConfig
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if !strings.HasSuffix(name, ".yaml") && !strings.HasSuffix(name, ".yml") {
			continue
		}

		path := filepath.Join(dir, name)
		data, err := os.ReadFile(path) // nosemgrep
		if err != nil {
			return fmt.Errorf("read %q: %w", path, err)
		}

		var tf ToolsFile
		if err := yaml.Unmarshal(data, &tf); err != nil {
			return fmt.Errorf("parse %q: %w", path, err)
		}

		for _, tool := range tf.Tools {
			if tool.Name == "" {
				return fmt.Errorf("file %q: tool name is required", path)
			}
			if tool.Actor == "" {
				return fmt.Errorf("file %q, tool %q: actor is required", path, tool.Name)
			}
			// Convert YAML-parsed schema map to JSON bytes
			if tool.RawInputSchema != nil {
				jsonBytes, err := json.Marshal(tool.RawInputSchema)
				if err != nil {
					return fmt.Errorf("file %q, tool %q: marshal inputSchema: %w", path, tool.Name, err)
				}
				tool.InputSchema = jsonBytes
				tool.RawInputSchema = nil
			}
			tools = append(tools, tool)
		}
	}

	r.mu.Lock()
	r.tools = tools
	r.mu.Unlock()
	return nil
}

// Tools returns a snapshot of the current tool definitions.
func (r *Registry) Tools() []ToolConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]ToolConfig, len(r.tools))
	copy(result, r.tools)
	return result
}

// GetByName returns the tool with the given name, or nil if not found.
func (r *Registry) GetByName(name string) *ToolConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for i := range r.tools {
		if r.tools[i].Name == name {
			t := r.tools[i]
			return &t
		}
	}
	return nil
}

// LoadToolsForTest directly sets the tool list (for testing only).
func (r *Registry) LoadToolsForTest(tools []ToolConfig) {
	r.mu.Lock()
	r.tools = tools
	r.mu.Unlock()
}
