package config

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// LoadFromFile loads configuration from a YAML file
func LoadFromFile(path string) (*Config, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("failed to open config file: %w", err)
	}
	defer func() { _ = f.Close() }()

	return Load(f)
}

// Load loads configuration from a reader
func Load(r io.Reader) (*Config, error) {
	var config Config
	decoder := yaml.NewDecoder(r)
	decoder.KnownFields(true) // Strict mode: fail on unknown fields

	if err := decoder.Decode(&config); err != nil {
		return nil, fmt.Errorf("failed to parse YAML: %w", err)
	}

	// Validate configuration
	if err := config.Validate(); err != nil {
		return nil, fmt.Errorf("invalid configuration: %w", err)
	}

	return &config, nil
}

// LoadFromDir loads and merges all .yaml files from a directory
func LoadFromDir(dirPath string) (*Config, error) {
	entries, err := os.ReadDir(dirPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read directory: %w", err)
	}

	var configs []*Config
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}

		// Only process .yaml and .yml files
		name := entry.Name()
		if !strings.HasSuffix(name, ".yaml") && !strings.HasSuffix(name, ".yml") {
			continue
		}

		path := filepath.Join(dirPath, name)
		config, err := LoadFromFile(path)
		if err != nil {
			return nil, fmt.Errorf("failed to load %s: %w", name, err)
		}
		configs = append(configs, config)
	}

	if len(configs) == 0 {
		return nil, fmt.Errorf("no YAML files found in directory")
	}

	// Merge all configs
	return MergeConfigs(configs...)
}

// MergeConfigs merges multiple configurations into one
// Later configs override earlier ones for defaults
// Tools are combined (duplicates cause error)
// Route templates are combined (duplicates cause error)
func MergeConfigs(configs ...*Config) (*Config, error) {
	if len(configs) == 0 {
		return nil, fmt.Errorf("no configs to merge")
	}

	merged := &Config{
		Tools:  []Tool{},
		Routes: make(map[string][]string),
	}

	toolNames := make(map[string]bool)

	for _, config := range configs {
		// Merge tools (no duplicates allowed)
		for _, tool := range config.Tools {
			if toolNames[tool.Name] {
				return nil, fmt.Errorf("duplicate tool name across configs: %q", tool.Name)
			}
			toolNames[tool.Name] = true
			merged.Tools = append(merged.Tools, tool)
		}

		// Merge route templates (no duplicates allowed)
		for name, actors := range config.Routes {
			if _, exists := merged.Routes[name]; exists {
				return nil, fmt.Errorf("duplicate route template across configs: %q", name)
			}
			merged.Routes[name] = actors
		}

		// Use last config's defaults (if set)
		if config.Defaults != nil {
			merged.Defaults = config.Defaults
		}
	}

	// Validate merged config
	if err := merged.Validate(); err != nil {
		return nil, fmt.Errorf("merged config is invalid: %w", err)
	}

	return merged, nil
}

// LoadConfig is the main entry point for loading configuration
// Supports both file and directory paths
func LoadConfig(path string) (*Config, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("config path error: %w", err)
	}

	if info.IsDir() {
		return LoadFromDir(path)
	}

	return LoadFromFile(path)
}
