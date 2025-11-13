package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoad(t *testing.T) {
	tests := []struct {
		name    string
		yaml    string
		wantErr bool
	}{
		{
			name: "minimal valid config",
			yaml: `
tools:
  - name: echo
    description: Echo tool
    parameters:
      envelope:
        type: string
        required: true
    route: [echo-actor]
`,
			wantErr: false,
		},
		{
			name: "config with defaults",
			yaml: `
defaults:
  progress: true
  timeout: 300

tools:
  - name: test
    parameters:
      input:
        type: string
        required: true
    route: [actor]
`,
			wantErr: false,
		},
		{
			name: "config with route templates",
			yaml: `
routes:
  pipeline: [actor1, actor2, actor3]

tools:
  - name: test
    parameters:
      input:
        type: string
    route: pipeline
`,
			wantErr: false,
		},
		{
			name: "invalid - no tools",
			yaml: `
defaults:
  timeout: 300
`,
			wantErr: true,
		},
		{
			name: "invalid - duplicate tool names",
			yaml: `
tools:
  - name: duplicate
    parameters:
      input:
        type: string
    route: [actor]
  - name: duplicate
    parameters:
      input:
        type: string
    route: [actor]
`,
			wantErr: true,
		},
		{
			name: "invalid - empty route",
			yaml: `
tools:
  - name: test
    parameters:
      input:
        type: string
    route: []
`,
			wantErr: true,
		},
		{
			name: "invalid - unknown template",
			yaml: `
tools:
  - name: test
    parameters:
      input:
        type: string
    route: unknown-template
`,
			wantErr: true,
		},
		{
			name: "all parameter types",
			yaml: `
tools:
  - name: complex
    parameters:
      str_param:
        type: string
        required: true
      num_param:
        type: number
        default: 42
      bool_param:
        type: boolean
        default: false
      array_param:
        type: array
        items:
          type: string
      enum_param:
        type: string
        options: [a, b, c]
    route: [actor]
`,
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			config, err := Load(strings.NewReader(tt.yaml))
			if (err != nil) != tt.wantErr {
				t.Errorf("Load() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !tt.wantErr && config == nil {
				t.Error("Load() returned nil config for valid input")
			}
		})
	}
}

func TestLoadFromFile(t *testing.T) {
	// Create temporary file
	tmpDir := t.TempDir()
	configFile := filepath.Join(tmpDir, "routes.yaml")

	yaml := `
tools:
  - name: test
    description: Test tool
    parameters:
      input:
        type: string
        required: true
    route: [test-actor]
    progress: true
    timeout: 60
`

	if err := os.WriteFile(configFile, []byte(yaml), 0644); err != nil {
		t.Fatalf("Failed to write test file: %v", err)
	}

	config, err := LoadFromFile(configFile)
	if err != nil {
		t.Fatalf("LoadFromFile() error = %v", err)
	}

	if len(config.Tools) != 1 {
		t.Errorf("Expected 1 tool, got %d", len(config.Tools))
	}

	tool := config.Tools[0]
	if tool.Name != "test" {
		t.Errorf("Expected tool name 'test', got %q", tool.Name)
	}

	if tool.Progress == nil || !*tool.Progress {
		t.Error("Expected progress to be true")
	}

	if tool.Timeout == nil || *tool.Timeout != 60 {
		t.Errorf("Expected timeout 60, got %v", tool.Timeout)
	}
}

func TestLoadFromDir(t *testing.T) {
	tmpDir := t.TempDir()

	// Create multiple config files
	files := map[string]string{
		"tools1.yaml": `
tools:
  - name: tool1
    parameters:
      input:
        type: string
    route: [actor1]
`,
		"tools2.yaml": `
tools:
  - name: tool2
    parameters:
      input:
        type: string
    route: [actor2]
`,
		"routes.yaml": `
routes:
  pipeline: [actor1, actor2]

tools:
  - name: tool3
    parameters:
      input:
        type: string
    route: pipeline
`,
	}

	for filename, content := range files {
		path := filepath.Join(tmpDir, filename)
		if err := os.WriteFile(path, []byte(content), 0644); err != nil {
			t.Fatalf("Failed to write %s: %v", filename, err)
		}
	}

	config, err := LoadFromDir(tmpDir)
	if err != nil {
		t.Fatalf("LoadFromDir() error = %v", err)
	}

	if len(config.Tools) != 3 {
		t.Errorf("Expected 3 tools, got %d", len(config.Tools))
	}

	if len(config.Routes) != 1 {
		t.Errorf("Expected 1 route template, got %d", len(config.Routes))
	}
}

func TestMergeConfigs(t *testing.T) {
	config1 := &Config{
		Tools: []Tool{
			{
				Name: "tool1",
				Parameters: map[string]Parameter{
					"input": {Type: "string"},
				},
				Route: RouteSpec{Actors: []string{"actor1"}},
			},
		},
		Routes: map[string][]string{
			"route1": {"actor1", "actor2"},
		},
	}

	config2 := &Config{
		Tools: []Tool{
			{
				Name: "tool2",
				Parameters: map[string]Parameter{
					"input": {Type: "string"},
				},
				Route: RouteSpec{Actors: []string{"actor2"}},
			},
		},
		Routes: map[string][]string{
			"route2": {"actor3", "actor4"},
		},
		Defaults: &ToolDefaults{
			Progress: boolPtr(true),
		},
	}

	merged, err := MergeConfigs(config1, config2)
	if err != nil {
		t.Fatalf("MergeConfigs() error = %v", err)
	}

	if len(merged.Tools) != 2 {
		t.Errorf("Expected 2 tools, got %d", len(merged.Tools))
	}

	if len(merged.Routes) != 2 {
		t.Errorf("Expected 2 route templates, got %d", len(merged.Routes))
	}

	if merged.Defaults == nil || !*merged.Defaults.Progress {
		t.Error("Expected defaults from config2")
	}
}

func TestMergeConfigs_DuplicateTool(t *testing.T) {
	config1 := &Config{
		Tools: []Tool{
			{
				Name: "duplicate",
				Parameters: map[string]Parameter{
					"input": {Type: "string"},
				},
				Route: RouteSpec{Actors: []string{"actor1"}},
			},
		},
	}

	config2 := &Config{
		Tools: []Tool{
			{
				Name: "duplicate",
				Parameters: map[string]Parameter{
					"input": {Type: "string"},
				},
				Route: RouteSpec{Actors: []string{"actor2"}},
			},
		},
	}

	_, err := MergeConfigs(config1, config2)
	if err == nil {
		t.Error("Expected error for duplicate tool name")
	}
}

func TestToolGetOptions(t *testing.T) {
	tests := []struct {
		name     string
		tool     Tool
		defaults *ToolDefaults
		want     ToolOptions
	}{
		{
			name: "no overrides",
			tool: Tool{
				Name: "test",
				Parameters: map[string]Parameter{
					"input": {Type: "string"},
				},
				Route: RouteSpec{Actors: []string{"actor"}},
			},
			defaults: nil,
			want: ToolOptions{
				Progress: false,
				Timeout:  300000000000, // 5 minutes in nanoseconds
			},
		},
		{
			name: "with defaults",
			tool: Tool{
				Name: "test",
				Parameters: map[string]Parameter{
					"input": {Type: "string"},
				},
				Route: RouteSpec{Actors: []string{"actor"}},
			},
			defaults: &ToolDefaults{
				Progress: boolPtr(true),
				Timeout:  intPtr(600),
			},
			want: ToolOptions{
				Progress: true,
				Timeout:  600000000000, // 10 minutes in nanoseconds
			},
		},
		{
			name: "tool overrides defaults",
			tool: Tool{
				Name: "test",
				Parameters: map[string]Parameter{
					"input": {Type: "string"},
				},
				Route:    RouteSpec{Actors: []string{"actor"}},
				Progress: boolPtr(false),
				Timeout:  intPtr(30),
			},
			defaults: &ToolDefaults{
				Progress: boolPtr(true),
				Timeout:  intPtr(600),
			},
			want: ToolOptions{
				Progress: false,
				Timeout:  30000000000, // 30 seconds in nanoseconds
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tt.tool.GetOptions(tt.defaults)
			if got.Progress != tt.want.Progress {
				t.Errorf("Progress = %v, want %v", got.Progress, tt.want.Progress)
			}
			if got.Timeout != tt.want.Timeout {
				t.Errorf("Timeout = %v, want %v", got.Timeout, tt.want.Timeout)
			}
		})
	}
}

func TestRouteSpecUnmarshalYAML(t *testing.T) {
	tests := []struct {
		name  string
		yaml  string
		check func(*RouteSpec) bool
	}{
		{
			name: "array format",
			yaml: `
tools:
  - name: test
    parameters:
      input:
        type: string
    route: [actor1, actor2, actor3]
`,
			check: func(r *RouteSpec) bool {
				return len(r.Actors) == 3 && r.Template == ""
			},
		},
		{
			name: "template format",
			yaml: `
routes:
  my-template: [actor1, actor2]

tools:
  - name: test
    parameters:
      input:
        type: string
    route: my-template
`,
			check: func(r *RouteSpec) bool {
				return r.Template == "my-template" && len(r.Actors) == 0
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg, err := Load(strings.NewReader(tt.yaml))
			if err != nil {
				t.Fatalf("Load() error = %v", err)
			}
			if len(cfg.Tools) != 1 {
				t.Fatalf("Expected 1 tool, got %d", len(cfg.Tools))
			}
			if !tt.check(&cfg.Tools[0].Route) {
				t.Error("Route check failed")
			}
		})
	}
}

// Helper functions
func boolPtr(b bool) *bool {
	return &b
}

func intPtr(i int) *int {
	return &i
}
