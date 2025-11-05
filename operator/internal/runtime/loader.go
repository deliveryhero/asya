package runtime

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Loader defines the interface for loading runtime scripts.
type Loader interface {
	// Load retrieves the runtime script content.
	// version parameter is used for GitHub releases, ignored for local files.
	Load(ctx context.Context, version string) (string, error)
}

// LocalFileLoader loads runtime script from local filesystem.
type LocalFileLoader struct {
	FilePath string
}

// NewLocalFileLoader creates a new local file loader.
func NewLocalFileLoader(filePath string) *LocalFileLoader {
	return &LocalFileLoader{
		FilePath: filePath,
	}
}

// Load reads the runtime script from local filesystem.
func (l *LocalFileLoader) Load(ctx context.Context, version string) (string, error) {
	if l.FilePath == "" {
		return "", fmt.Errorf("file path is empty")
	}

	// Clean and validate path
	cleanPath := filepath.Clean(l.FilePath)

	// Check if file exists
	if _, err := os.Stat(cleanPath); err != nil {
		if os.IsNotExist(err) {
			return "", fmt.Errorf("runtime file not found: %s", cleanPath)
		}
		return "", fmt.Errorf("failed to stat file %s: %w", cleanPath, err)
	}

	// Read file content
	content, err := os.ReadFile(cleanPath)
	if err != nil {
		return "", fmt.Errorf("failed to read file %s: %w", cleanPath, err)
	}

	if len(content) == 0 {
		return "", fmt.Errorf("runtime file is empty: %s", cleanPath)
	}

	return string(content), nil
}

// GitHubReleaseLoader loads runtime script from GitHub releases.
type GitHubReleaseLoader struct {
	Repo      string // Repository in format "owner/repo"
	AssetName string // Asset filename (e.g., "asya_runtime.py")
	Token     string // Optional GitHub token for private repos
	client    *http.Client
}

// NewGitHubReleaseLoader creates a new GitHub release loader.
func NewGitHubReleaseLoader(repo, assetName, token string) *GitHubReleaseLoader {
	return &GitHubReleaseLoader{
		Repo:      repo,
		AssetName: assetName,
		Token:     token,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// Load downloads the runtime script from GitHub release assets.
func (g *GitHubReleaseLoader) Load(ctx context.Context, version string) (string, error) {
	if g.Repo == "" {
		return "", fmt.Errorf("repository is empty")
	}
	if g.AssetName == "" {
		return "", fmt.Errorf("asset name is empty")
	}
	if version == "" {
		return "", fmt.Errorf("version is required for GitHub releases")
	}

	// Validate repo format
	parts := strings.Split(g.Repo, "/")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return "", fmt.Errorf("invalid repository format: %s (expected 'owner/repo')", g.Repo)
	}

	// Construct GitHub release asset URL
	// https://github.com/{owner}/{repo}/releases/download/{version}/{asset}
	url := fmt.Sprintf("https://github.com/%s/releases/download/%s/%s",
		g.Repo, version, g.AssetName)

	// Create request
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", fmt.Errorf("failed to create request: %w", err)
	}

	// Add auth token if provided
	if g.Token != "" {
		req.Header.Set("Authorization", "token "+g.Token)
	}

	// Execute request
	resp, err := g.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to download from GitHub: %w", err)
	}
	defer resp.Body.Close()

	// Check status code
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return "", fmt.Errorf("GitHub API returned status %d: %s", resp.StatusCode, string(body))
	}

	// Read response body
	content, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response body: %w", err)
	}

	if len(content) == 0 {
		return "", fmt.Errorf("downloaded content is empty")
	}

	return string(content), nil
}

// LoaderConfig holds configuration for creating a runtime loader.
type LoaderConfig struct {
	Source      string // "local" or "github"
	LocalPath   string // Path to local file (for local source)
	GitHubRepo  string // GitHub repository (for github source)
	GitHubToken string // Optional GitHub token
	AssetName   string // Asset filename for GitHub releases
	Version     string // Version/tag for GitHub releases
}

// NewLoader creates a loader based on the configuration.
func NewLoader(config LoaderConfig) (Loader, error) {
	switch config.Source {
	case "local":
		if config.LocalPath == "" {
			return nil, fmt.Errorf("local path is required for local source")
		}
		return NewLocalFileLoader(config.LocalPath), nil

	case "github":
		if config.GitHubRepo == "" {
			return nil, fmt.Errorf("GitHub repository is required for github source")
		}
		if config.AssetName == "" {
			return nil, fmt.Errorf("asset name is required for github source")
		}
		return NewGitHubReleaseLoader(config.GitHubRepo, config.AssetName, config.GitHubToken), nil

	default:
		return nil, fmt.Errorf("unknown source type: %s (expected 'local' or 'github')", config.Source)
	}
}
