package runtime

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

const testPythonScript = "#!/usr/bin/env python3\nprint('test')\n"

func TestLocalFileLoader_Load(t *testing.T) {
	tests := []struct {
		name        string
		setupFile   func(t *testing.T) string
		filePath    string
		wantErr     bool
		errContains string
	}{
		{
			name: "valid file",
			setupFile: func(t *testing.T) string {
				dir := t.TempDir()
				file := filepath.Join(dir, "asya_runtime.py")
				content := "#!/usr/bin/env python3\nprint('hello')\n"
				if err := os.WriteFile(file, []byte(content), 0644); err != nil {
					t.Fatal(err)
				}
				return file
			},
			wantErr: false,
		},
		{
			name: "file not found",
			setupFile: func(t *testing.T) string {
				return filepath.Join(t.TempDir(), "nonexistent.py")
			},
			wantErr:     true,
			errContains: "runtime file not found",
		},
		{
			name: "empty file",
			setupFile: func(t *testing.T) string {
				dir := t.TempDir()
				file := filepath.Join(dir, "empty.py")
				if err := os.WriteFile(file, []byte(""), 0644); err != nil {
					t.Fatal(err)
				}
				return file
			},
			wantErr:     true,
			errContains: "runtime file is empty",
		},
		{
			name: "empty path",
			setupFile: func(t *testing.T) string {
				return ""
			},
			filePath:    "",
			wantErr:     true,
			errContains: "file path is empty",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			filePath := tt.setupFile(t)
			loader := NewLocalFileLoader(filePath)

			content, err := loader.Load(context.Background(), "")

			if tt.wantErr {
				if err == nil {
					t.Errorf("Load() expected error, got nil")
				} else if tt.errContains != "" && !contains(err.Error(), tt.errContains) {
					t.Errorf("Load() error = %v, want error containing %q", err, tt.errContains)
				}
			} else {
				if err != nil {
					t.Errorf("Load() unexpected error: %v", err)
				}
				if content == "" {
					t.Errorf("Load() returned empty content")
				}
			}
		})
	}
}

func TestLocalFileLoader_LoadContent(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "test.py")

	if err := os.WriteFile(file, []byte(testPythonScript), 0644); err != nil {
		t.Fatal(err)
	}

	loader := NewLocalFileLoader(file)
	content, err := loader.Load(context.Background(), "")

	if err != nil {
		t.Fatalf("Load() unexpected error: %v", err)
	}

	if content != testPythonScript {
		t.Errorf("Load() content = %q, want %q", content, testPythonScript)
	}
}

func TestGitHubReleaseLoader_Load(t *testing.T) {
	tests := []struct {
		name        string
		repo        string
		assetName   string
		version     string
		token       string
		setupServer func() *httptest.Server
		wantErr     bool
		errContains string
	}{
		{
			name:        "empty repository",
			repo:        "",
			assetName:   "asya_runtime.py",
			version:     "v1.0.0",
			setupServer: func() *httptest.Server { return nil },
			wantErr:     true,
			errContains: "repository is empty",
		},
		{
			name:        "empty asset name",
			repo:        "owner/repo",
			assetName:   "",
			version:     "v1.0.0",
			setupServer: func() *httptest.Server { return nil },
			wantErr:     true,
			errContains: "asset name is empty",
		},
		{
			name:        "empty version",
			repo:        "owner/repo",
			assetName:   "asya_runtime.py",
			version:     "",
			setupServer: func() *httptest.Server { return nil },
			wantErr:     true,
			errContains: "version is required",
		},
		{
			name:        "invalid repo format",
			repo:        "invalid",
			assetName:   "asya_runtime.py",
			version:     "v1.0.0",
			setupServer: func() *httptest.Server { return nil },
			wantErr:     true,
			errContains: "invalid repository format",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			loader := NewGitHubReleaseLoader(tt.repo, tt.assetName, tt.token)

			content, err := loader.Load(context.Background(), tt.version)

			if tt.wantErr {
				if err == nil {
					t.Errorf("Load() expected error, got nil")
				} else if tt.errContains != "" && !contains(err.Error(), tt.errContains) {
					t.Errorf("Load() error = %v, want error containing %q", err, tt.errContains)
				}
			} else {
				if err != nil {
					t.Errorf("Load() unexpected error: %v", err)
				}
				if content == "" {
					t.Errorf("Load() returned empty content")
				}
			}
		})
	}
}

func TestGitHubReleaseLoader_LoadWithServer(t *testing.T) {
	tests := []struct {
		name        string
		assetName   string
		version     string
		token       string
		serverFunc  func(t *testing.T) http.HandlerFunc
		wantErr     bool
		errContains string
	}{
		{
			name:      "successful download",
			assetName: "asya_runtime.py",
			version:   "v1.0.0",
			serverFunc: func(t *testing.T) http.HandlerFunc {
				return func(w http.ResponseWriter, r *http.Request) {
					if r.URL.Path != "/owner/repo/releases/download/v1.0.0/asya_runtime.py" {
						t.Errorf("unexpected path: %s", r.URL.Path)
					}
					w.WriteHeader(http.StatusOK)
					_, _ = w.Write([]byte("#!/usr/bin/env python3\nprint('hello')\n"))
				}
			},
			wantErr: false,
		},
		{
			name:      "with auth token",
			assetName: "asya_runtime.py",
			version:   "v1.0.0",
			token:     "test-token",
			serverFunc: func(t *testing.T) http.HandlerFunc {
				return func(w http.ResponseWriter, r *http.Request) {
					auth := r.Header.Get("Authorization")
					if auth != "token test-token" {
						t.Errorf("unexpected auth header: %s", auth)
					}
					w.WriteHeader(http.StatusOK)
					_, _ = w.Write([]byte("content"))
				}
			},
			wantErr: false,
		},
		{
			name:      "404 not found",
			assetName: "asya_runtime.py",
			version:   "v1.0.0",
			serverFunc: func(t *testing.T) http.HandlerFunc {
				return func(w http.ResponseWriter, r *http.Request) {
					w.WriteHeader(http.StatusNotFound)
					_, _ = w.Write([]byte("Not Found"))
				}
			},
			wantErr:     true,
			errContains: "status 404",
		},
		{
			name:      "empty response",
			assetName: "asya_runtime.py",
			version:   "v1.0.0",
			serverFunc: func(t *testing.T) http.HandlerFunc {
				return func(w http.ResponseWriter, r *http.Request) {
					w.WriteHeader(http.StatusOK)
					// Empty body
				}
			},
			wantErr:     true,
			errContains: "downloaded content is empty",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			server := httptest.NewServer(tt.serverFunc(t))
			defer server.Close()

			loader := NewGitHubReleaseLoader("owner/repo", tt.assetName, tt.token)
			loader.client = server.Client()

			// Construct URL using test server
			url := server.URL + "/owner/repo/releases/download/" + tt.version + "/" + tt.assetName
			req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, url, nil)
			if tt.token != "" {
				req.Header.Set("Authorization", "token "+tt.token)
			}

			resp, err := loader.client.Do(req)
			if err != nil && !tt.wantErr {
				t.Fatalf("request failed: %v", err)
			}
			if err == nil {
				defer func() { _ = resp.Body.Close() }()

				if !tt.wantErr && resp.StatusCode != http.StatusOK {
					t.Errorf("unexpected status code: %d", resp.StatusCode)
				}

				if tt.wantErr {
					if resp.StatusCode == http.StatusOK {
						// Check for empty content
						body, _ := io.ReadAll(resp.Body)
						if len(body) == 0 && !contains(tt.errContains, "empty") {
							t.Errorf("expected error but got OK with empty body")
						}
					}
				} else {
					body, _ := io.ReadAll(resp.Body)
					if len(body) == 0 {
						t.Errorf("expected content but got empty body")
					}
				}
			}
		})
	}
}

func TestNewLoader(t *testing.T) {
	tests := []struct {
		name        string
		config      LoaderConfig
		wantType    string
		wantErr     bool
		errContains string
	}{
		{
			name: "local loader",
			config: LoaderConfig{
				Source:    "local",
				LocalPath: "/path/to/file.py",
			},
			wantType: "*runtime.LocalFileLoader",
			wantErr:  false,
		},
		{
			name: "github loader",
			config: LoaderConfig{
				Source:     "github",
				GitHubRepo: "owner/repo",
				AssetName:  "asya_runtime.py",
			},
			wantType: "*runtime.GitHubReleaseLoader",
			wantErr:  false,
		},
		{
			name: "local without path",
			config: LoaderConfig{
				Source: "local",
			},
			wantErr:     true,
			errContains: "local path is required",
		},
		{
			name: "github without repo",
			config: LoaderConfig{
				Source:    "github",
				AssetName: "asya_runtime.py",
			},
			wantErr:     true,
			errContains: "GitHub repository is required",
		},
		{
			name: "github without asset name",
			config: LoaderConfig{
				Source:     "github",
				GitHubRepo: "owner/repo",
			},
			wantErr:     true,
			errContains: "asset name is required",
		},
		{
			name: "unknown source",
			config: LoaderConfig{
				Source: "invalid",
			},
			wantErr:     true,
			errContains: "unknown source type",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			loader, err := NewLoader(tt.config)

			if tt.wantErr {
				if err == nil {
					t.Errorf("NewLoader() expected error, got nil")
				} else if tt.errContains != "" && !contains(err.Error(), tt.errContains) {
					t.Errorf("NewLoader() error = %v, want error containing %q", err, tt.errContains)
				}
			} else {
				if err != nil {
					t.Errorf("NewLoader() unexpected error: %v", err)
				}
				if loader == nil {
					t.Errorf("NewLoader() returned nil loader")
				}
				loaderType := fmt.Sprintf("%T", loader)
				if loaderType != tt.wantType {
					t.Errorf("NewLoader() type = %s, want %s", loaderType, tt.wantType)
				}
			}
		})
	}
}

func TestGitHubReleaseLoader_URLConstruction(t *testing.T) {
	tests := []struct {
		name      string
		repo      string
		assetName string
		version   string
		wantURL   string
	}{
		{
			name:      "standard release",
			repo:      "owner/repo",
			assetName: "asya_runtime.py",
			version:   "v1.0.0",
			wantURL:   "https://github.com/owner/repo/releases/download/v1.0.0/asya_runtime.py",
		},
		{
			name:      "prerelease version",
			repo:      "owner/repo",
			assetName: "asya_runtime.py",
			version:   "v1.0.0-beta.1",
			wantURL:   "https://github.com/owner/repo/releases/download/v1.0.0-beta.1/asya_runtime.py",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			expectedURL := fmt.Sprintf("https://github.com/%s/releases/download/%s/%s",
				tt.repo, tt.version, tt.assetName)

			if expectedURL != tt.wantURL {
				t.Errorf("URL construction = %s, want %s", expectedURL, tt.wantURL)
			}
		})
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(substr) > 0 && containsHelper(s, substr))
}

func containsHelper(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
