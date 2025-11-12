package config

import (
	"fmt"
	"time"
)

// Config represents the complete tool routes configuration
type Config struct {
	Tools    []Tool              `yaml:"tools"`
	Routes   map[string][]string `yaml:"routes,omitempty"`   // Named route templates
	Defaults *ToolDefaults       `yaml:"defaults,omitempty"` // Global defaults
}

// Tool represents a single MCP tool definition
type Tool struct {
	Name        string               `yaml:"name"`
	Description string               `yaml:"description"`
	Parameters  map[string]Parameter `yaml:"parameters"`
	Route       RouteSpec            `yaml:"route"` // Can be array or string (template)
	Progress    *bool                `yaml:"progress,omitempty"`
	Timeout     *int                 `yaml:"timeout,omitempty"` // seconds
	Metadata    map[string]string    `yaml:"metadata,omitempty"`
}

// Parameter represents a tool parameter definition
type Parameter struct {
	Type        string               `yaml:"type"` // string, number, boolean, object, array
	Description string               `yaml:"description,omitempty"`
	Required    bool                 `yaml:"required,omitempty"`
	Default     interface{}          `yaml:"default,omitempty"`
	Options     []string             `yaml:"options,omitempty"`    // enum values
	Properties  map[string]Parameter `yaml:"properties,omitempty"` // for object type
	Items       *Parameter           `yaml:"items,omitempty"`      // for array type
}

// RouteSpec can be either a string (template reference) or array of strings (explicit actors)
type RouteSpec struct {
	Actors   []string // Resolved route actors
	Template string   // Template name (if used)
}

// ToolDefaults represents global default settings
type ToolDefaults struct {
	Progress *bool `yaml:"progress,omitempty"`
	Timeout  *int  `yaml:"timeout,omitempty"` // seconds
}

// UnmarshalYAML implements custom unmarshaling for RouteSpec
// Allows route to be either: route: [actor1, actor2] OR route: template-name
func (r *RouteSpec) UnmarshalYAML(unmarshal func(interface{}) error) error {
	// Try array first
	var actors []string
	if err := unmarshal(&actors); err == nil {
		r.Actors = actors
		return nil
	}

	// Try string (template reference)
	var template string
	if err := unmarshal(&template); err == nil {
		r.Template = template
		return nil
	}

	return fmt.Errorf("route must be either an array of strings or a template name")
}

// MarshalYAML implements custom marshaling for RouteSpec
func (r RouteSpec) MarshalYAML() (interface{}, error) {
	if r.Template != "" {
		return r.Template, nil
	}
	return r.Actors, nil
}

// GetActors resolves the route actors, using templates if specified
func (r *RouteSpec) GetActors(templates map[string][]string) ([]string, error) {
	if len(r.Actors) > 0 {
		return r.Actors, nil
	}

	if r.Template != "" {
		actors, ok := templates[r.Template]
		if !ok {
			return nil, fmt.Errorf("route template %q not found", r.Template)
		}
		return actors, nil
	}

	return nil, fmt.Errorf("route has no actors or template")
}

// ToolOptions represents runtime options for a tool
type ToolOptions struct {
	Progress bool
	Timeout  time.Duration
	Metadata map[string]string
}

// GetOptions returns the resolved tool options (merging with defaults)
func (t *Tool) GetOptions(defaults *ToolDefaults) ToolOptions {
	opts := ToolOptions{
		Progress: false,           // default to false
		Timeout:  5 * time.Minute, // default 5 minutes
		Metadata: t.Metadata,
	}

	// Apply global defaults
	if defaults != nil {
		if defaults.Progress != nil {
			opts.Progress = *defaults.Progress
		}
		if defaults.Timeout != nil {
			opts.Timeout = time.Duration(*defaults.Timeout) * time.Second
		}
	}

	// Apply tool-specific overrides
	if t.Progress != nil {
		opts.Progress = *t.Progress
	}
	if t.Timeout != nil {
		opts.Timeout = time.Duration(*t.Timeout) * time.Second
	}

	return opts
}

// Validate validates the configuration
func (c *Config) Validate() error {
	if len(c.Tools) == 0 {
		return fmt.Errorf("no tools defined")
	}

	// Check for duplicate tool names
	seen := make(map[string]bool)
	for _, tool := range c.Tools {
		if tool.Name == "" {
			return fmt.Errorf("tool name cannot be empty")
		}
		if seen[tool.Name] {
			return fmt.Errorf("duplicate tool name: %q", tool.Name)
		}
		seen[tool.Name] = true

		// Validate tool
		if err := tool.Validate(c.Routes); err != nil {
			return fmt.Errorf("tool %q: %w", tool.Name, err)
		}
	}

	return nil
}

// Validate validates a single tool definition
func (t *Tool) Validate(templates map[string][]string) error {
	if t.Name == "" {
		return fmt.Errorf("name is required")
	}

	// Validate route
	actors, err := t.Route.GetActors(templates)
	if err != nil {
		return fmt.Errorf("invalid route: %w", err)
	}
	if len(actors) == 0 {
		return fmt.Errorf("route cannot be empty")
	}

	// Validate parameters
	for name, param := range t.Parameters {
		if err := param.Validate(name); err != nil {
			return fmt.Errorf("parameter %q: %w", name, err)
		}
	}

	// Validate timeout
	if t.Timeout != nil && *t.Timeout < 0 {
		return fmt.Errorf("timeout cannot be negative")
	}

	return nil
}

// Validate validates a parameter definition
func (p *Parameter) Validate(name string) error {
	if name == "" {
		return fmt.Errorf("parameter name cannot be empty")
	}

	// Check valid type
	validTypes := map[string]bool{
		"string": true, "number": true, "boolean": true,
		"object": true, "array": true, "integer": true,
	}
	if !validTypes[p.Type] {
		return fmt.Errorf("invalid type %q (must be string, number, integer, boolean, object, or array)", p.Type)
	}

	// Validate object properties
	if p.Type == "object" && len(p.Properties) > 0 {
		for propName, prop := range p.Properties {
			if err := prop.Validate(propName); err != nil {
				return fmt.Errorf("property %q: %w", propName, err)
			}
		}
	}

	// Validate array items
	if p.Type == "array" && p.Items != nil {
		if err := p.Items.Validate("items"); err != nil {
			return fmt.Errorf("items: %w", err)
		}
	}

	return nil
}
