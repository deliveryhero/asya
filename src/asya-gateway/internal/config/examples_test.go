package config

import (
	"path/filepath"
	"testing"
)

// TestExampleConfigs validates that the example configs are valid
func TestExampleConfigs(t *testing.T) {
	examples := []struct {
		name     string
		file     string
		minTools int
	}{
		{
			name:     "minimal config",
			file:     "../../config/examples/routes-minimal.yaml",
			minTools: 2,
		},
		{
			name:     "comprehensive config",
			file:     "../../config/examples/routes.yaml",
			minTools: 8,
		},
	}

	for _, tt := range examples {
		t.Run(tt.name, func(t *testing.T) {
			cfg, err := LoadFromFile(filepath.Clean(tt.file))
			if err != nil {
				t.Fatalf("Failed to load %s: %v", tt.name, err)
			}

			if len(cfg.Tools) < tt.minTools {
				t.Errorf("Expected at least %d tools, got %d", tt.minTools, len(cfg.Tools))
			}

			// Validate each tool can resolve its route
			for _, tool := range cfg.Tools {
				_, err := tool.Route.GetActors(cfg.Routes)
				if err != nil {
					t.Errorf("Tool %q has invalid route: %v", tool.Name, err)
				}
			}
		})
	}
}
