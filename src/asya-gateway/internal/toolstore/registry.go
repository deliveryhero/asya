package toolstore

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"

	"gopkg.in/yaml.v3"
)

// Registry manages tools with an in-memory atomic cache.
// The cache is loaded from a directory of YAML files (ConfigMap mount)
// or populated via Upsert for tests.
type Registry struct {
	cache atomic.Value // *[]Tool
}

// NewInMemoryRegistry creates an empty registry (for tests and no-config mode).
func NewInMemoryRegistry() *Registry {
	r := &Registry{}
	r.cache.Store(&[]Tool{})
	return r
}

// NewRegistryFromDir creates a registry loaded from YAML files in dir.
func NewRegistryFromDir(dir string) (*Registry, error) {
	r := &Registry{}
	r.cache.Store(&[]Tool{})
	if err := r.LoadFromDir(dir); err != nil {
		return nil, err
	}
	return r, nil
}

// LoadFromDir reads all *.yaml / *.yml files in dir, parses FlowsFile,
// converts each flow to a Tool, and atomically replaces the cache.
// On error the previous cache is preserved.
func (r *Registry) LoadFromDir(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return fmt.Errorf("read config dir %q: %w", dir, err)
	}

	tools := make([]Tool, 0)
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if !strings.HasSuffix(name, ".yaml") && !strings.HasSuffix(name, ".yml") {
			continue
		}

		path := filepath.Join(dir, name)
		data, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read %q: %w", path, err)
		}

		var ff FlowsFile
		if err := yaml.Unmarshal(data, &ff); err != nil {
			return fmt.Errorf("parse %q: %w", path, err)
		}

		for _, fc := range ff.Flows {
			t, err := flowConfigToTool(fc)
			if err != nil {
				return fmt.Errorf("file %q, flow %q: %w", path, fc.Name, err)
			}
			tools = append(tools, t)
		}
	}

	r.cache.Store(&tools)
	return nil
}

// Upsert validates a tool and adds/replaces it in the in-memory cache.
// Used in tests and for single-tool injection without YAML files.
func (r *Registry) Upsert(_ context.Context, tool Tool) error {
	if tool.Name == "" {
		return fmt.Errorf("tool name is required")
	}
	if tool.Actor == "" {
		return fmt.Errorf("tool actor is required")
	}

	tools := r.All()
	newTools := make([]Tool, 0, len(tools)+1)
	found := false

	for _, t := range tools {
		if t.Name == tool.Name {
			newTools = append(newTools, tool)
			found = true
		} else {
			newTools = append(newTools, t)
		}
	}

	if !found {
		newTools = append(newTools, tool)
	}

	r.cache.Store(&newTools)
	return nil
}

// All returns all tools from the cache.
func (r *Registry) All() []Tool {
	val := r.cache.Load()
	if val == nil {
		return nil
	}
	tools, ok := val.(*[]Tool)
	if !ok {
		return nil
	}
	return *tools
}

// GetByName returns a tool by name, or nil if not found.
func (r *Registry) GetByName(name string) *Tool {
	for _, t := range r.All() {
		if t.Name == name {
			return &t
		}
	}
	return nil
}

// MCPTools returns all tools with MCP enabled.
func (r *Registry) MCPTools() []Tool {
	all := r.All()
	result := make([]Tool, 0, len(all))
	for _, t := range all {
		if t.MCPEnabled {
			result = append(result, t)
		}
	}
	return result
}

// A2ASkills returns all tools with A2A enabled.
func (r *Registry) A2ASkills() []Tool {
	all := r.All()
	result := make([]Tool, 0, len(all))
	for _, t := range all {
		if t.A2AEnabled {
			result = append(result, t)
		}
	}
	return result
}
