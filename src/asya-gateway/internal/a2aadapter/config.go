// Package a2aadapter implements the A2A JSON-RPC adapter.
// Coexists with the old internal/a2a/ package during migration.
package a2aadapter

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"gopkg.in/yaml.v3"
)

// SkillConfig is a single A2A skill within an agent definition.
type SkillConfig struct {
	ID          string   `yaml:"id" json:"id"`
	Name        string   `yaml:"name" json:"name"`
	Description string   `yaml:"description" json:"description"`
	Tags        []string `yaml:"tags" json:"tags"`
}

// AgentConfig is a single A2A agent definition from the ConfigMap.
type AgentConfig struct {
	Name        string        `yaml:"name" json:"name"`
	Description string        `yaml:"description" json:"description"`
	Actor       string        `yaml:"actor" json:"actor"`
	Timeout     int           `yaml:"timeout" json:"timeout"` // seconds, 0 = default (300)
	Streaming   bool          `yaml:"streaming" json:"streaming"`
	Skills      []SkillConfig `yaml:"skills" json:"skills"`
	InputModes  []string      `yaml:"inputModes" json:"inputModes"`
	OutputModes []string      `yaml:"outputModes" json:"outputModes"`
}

// AgentsFile is the top-level structure of an agents ConfigMap YAML file.
type AgentsFile struct {
	Agents []AgentConfig `yaml:"agents"`
}

// AgentRegistry holds the current set of A2A agent definitions. Thread-safe.
type AgentRegistry struct {
	mu     sync.RWMutex
	agents []AgentConfig
}

// NewAgentRegistry creates an empty registry.
func NewAgentRegistry() *AgentRegistry {
	return &AgentRegistry{}
}

// LoadFromDir reads all *.yaml / *.yml files in dir, parses AgentsFile entries,
// and atomically replaces the current agent set.
func (r *AgentRegistry) LoadFromDir(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return fmt.Errorf("read config dir %q: %w", dir, err)
	}

	var agents []AgentConfig
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

		var af AgentsFile
		if err := yaml.Unmarshal(data, &af); err != nil {
			return fmt.Errorf("parse %q: %w", path, err)
		}

		for _, agent := range af.Agents {
			if agent.Name == "" {
				return fmt.Errorf("file %q: agent name is required", path)
			}
			if agent.Actor == "" {
				return fmt.Errorf("file %q, agent %q: actor is required", path, agent.Name)
			}
			agents = append(agents, agent)
		}
	}

	r.mu.Lock()
	r.agents = agents
	r.mu.Unlock()
	return nil
}

// Agents returns a snapshot of the current agent definitions.
func (r *AgentRegistry) Agents() []AgentConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]AgentConfig, len(r.agents))
	copy(result, r.agents)
	return result
}

// GetByName returns the agent with the given name, or nil if not found.
func (r *AgentRegistry) GetByName(name string) *AgentConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for i := range r.agents {
		if r.agents[i].Name == name {
			a := r.agents[i]
			return &a
		}
	}
	return nil
}

// ResolveActor determines which actor to route to.
// Priority: skill hint in metadata -> single-agent default -> error.
func (r *AgentRegistry) ResolveActor(skillHint string) (*AgentConfig, error) {
	agents := r.Agents()

	// Explicit skill hint
	if skillHint != "" {
		for i := range agents {
			for _, s := range agents[i].Skills {
				if s.ID == skillHint {
					return &agents[i], nil
				}
			}
		}
		return nil, fmt.Errorf("skill %q not found", skillHint)
	}

	// Single agent default
	if len(agents) == 1 {
		return &agents[0], nil
	}

	// No agents
	if len(agents) == 0 {
		return nil, fmt.Errorf("no A2A agents registered")
	}

	// Multiple agents, no hint
	names := make([]string, len(agents))
	for i, a := range agents {
		names[i] = a.Name
	}
	return nil, fmt.Errorf("skill not specified. Available agents: %v", names)
}

// LoadAgentsForTest directly sets the agent list (for testing only).
func (r *AgentRegistry) LoadAgentsForTest(agents []AgentConfig) {
	r.mu.Lock()
	r.agents = agents
	r.mu.Unlock()
}
