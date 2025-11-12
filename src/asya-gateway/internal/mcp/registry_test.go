package mcp

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// MockQueueClientWithError for testing queue failures
type MockQueueClientWithError struct {
	sendErr error
}

func (m *MockQueueClientWithError) SendEnvelope(ctx context.Context, envelope *types.Envelope) error {
	if m.sendErr != nil {
		return m.sendErr
	}
	return nil
}

func (m *MockQueueClientWithError) Receive(ctx context.Context, queueName string) (queue.QueueMessage, error) {
	return nil, nil
}

func (m *MockQueueClientWithError) Ack(ctx context.Context, msg queue.QueueMessage) error {
	return nil
}

func (m *MockQueueClientWithError) Close() error {
	return nil
}

// MockJobStore for testing
type MockJobStore struct {
	createErr error
	updateErr error
	envelopes map[string]*types.Envelope
}

func NewMockJobStore() *MockJobStore {
	return &MockJobStore{
		envelopes: make(map[string]*types.Envelope),
	}
}

func (m *MockJobStore) Create(env *types.Envelope) error {
	if m.createErr != nil {
		return m.createErr
	}
	m.envelopes[env.ID] = env
	return nil
}

func (m *MockJobStore) Update(update types.EnvelopeUpdate) error {
	if m.updateErr != nil {
		return m.updateErr
	}
	if env, ok := m.envelopes[update.ID]; ok {
		env.Status = update.Status
		env.Error = update.Error
	}
	return nil
}

func (m *MockJobStore) Get(id string) (*types.Envelope, error) {
	if env, ok := m.envelopes[id]; ok {
		return env, nil
	}
	return nil, fmt.Errorf("envelope not found")
}

func (m *MockJobStore) AddProgress(id string, progress types.ProgressUpdate) error {
	return nil
}

func (m *MockJobStore) Delete(id string) error {
	delete(m.envelopes, id)
	return nil
}

func (m *MockJobStore) UpdateProgress(update types.EnvelopeUpdate) error {
	return m.Update(update)
}

func (m *MockJobStore) Subscribe(id string) chan types.EnvelopeUpdate {
	return make(chan types.EnvelopeUpdate)
}

func (m *MockJobStore) Unsubscribe(id string, ch chan types.EnvelopeUpdate) {
	close(ch)
}

func (m *MockJobStore) IsActive(id string) bool {
	env, exists := m.envelopes[id]
	if !exists {
		return false
	}
	return env.Status == types.EnvelopeStatusPending || env.Status == types.EnvelopeStatusRunning
}

func (m *MockJobStore) GetUpdates(id string, since *time.Time) ([]types.EnvelopeUpdate, error) {
	return []types.EnvelopeUpdate{}, nil
}

// TestNewRegistry tests registry initialization
func TestNewRegistry(t *testing.T) {
	cfg := &config.Config{
		Tools: []config.Tool{
			{Name: "test_tool", Description: "Test"},
		},
	}
	jobStore := jobs.NewStore()
	queueClient := &MockQueueClient{}

	registry := NewRegistry(cfg, jobStore, queueClient)

	if registry == nil {
		t.Fatal("Expected non-nil registry")
	}
	if registry.config != cfg {
		t.Error("Config not set correctly")
	}
	if registry.jobStore != jobStore {
		t.Error("JobStore not set correctly")
	}
	if registry.queueClient != queueClient {
		t.Error("QueueClient not set correctly")
	}
	if registry.handlers == nil {
		t.Error("Handlers map not initialized")
	}
}

// TestBuildParameterOptions tests parameter option building for all types
func TestBuildParameterOptions(t *testing.T) {
	registry := NewRegistry(&config.Config{}, jobs.NewStore(), &MockQueueClient{})

	tests := []struct {
		name      string
		paramName string
		param     config.Parameter
		wantErr   bool
		errMsg    string
	}{
		{
			name:      "string parameter - basic",
			paramName: "test_string",
			param:     config.Parameter{Type: "string", Description: "Test string"},
			wantErr:   false,
		},
		{
			name:      "string parameter - with enum",
			paramName: "test_enum",
			param:     config.Parameter{Type: "string", Options: []string{"option1", "option2"}},
			wantErr:   false,
		},
		{
			name:      "string parameter - required",
			paramName: "required_string",
			param:     config.Parameter{Type: "string", Required: true},
			wantErr:   false,
		},
		{
			name:      "number parameter",
			paramName: "test_number",
			param:     config.Parameter{Type: "number", Description: "Test number"},
			wantErr:   false,
		},
		{
			name:      "integer parameter",
			paramName: "test_integer",
			param:     config.Parameter{Type: "integer", Description: "Test integer"},
			wantErr:   false,
		},
		{
			name:      "boolean parameter",
			paramName: "test_bool",
			param:     config.Parameter{Type: "boolean", Description: "Test boolean"},
			wantErr:   false,
		},
		{
			name:      "array parameter - no items",
			paramName: "test_array",
			param:     config.Parameter{Type: "array", Description: "Test array"},
			wantErr:   false,
		},
		{
			name:      "array parameter - string items",
			paramName: "test_string_array",
			param:     config.Parameter{Type: "array", Items: &config.Parameter{Type: "string"}},
			wantErr:   false,
		},
		{
			name:      "array parameter - number items",
			paramName: "test_number_array",
			param:     config.Parameter{Type: "array", Items: &config.Parameter{Type: "number"}},
			wantErr:   false,
		},
		{
			name:      "array parameter - integer items",
			paramName: "test_integer_array",
			param:     config.Parameter{Type: "array", Items: &config.Parameter{Type: "integer"}},
			wantErr:   false,
		},
		{
			name:      "object parameter",
			paramName: "test_object",
			param:     config.Parameter{Type: "object", Description: "Test object"},
			wantErr:   false,
		},
		{
			name:      "invalid parameter type",
			paramName: "test_invalid",
			param:     config.Parameter{Type: "invalid_type"},
			wantErr:   true,
			errMsg:    "unsupported parameter type: invalid_type",
		},
		{
			name:      "empty parameter name",
			paramName: "",
			param:     config.Parameter{Type: "string"},
			wantErr:   false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			option, err := registry.buildParameterOptions(tt.paramName, tt.param)

			if tt.wantErr {
				if err == nil {
					t.Errorf("Expected error but got none")
				} else if tt.errMsg != "" && err.Error() != tt.errMsg {
					t.Errorf("Expected error message %q, got %q", tt.errMsg, err.Error())
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
			}
			if option == nil {
				t.Error("Expected non-nil option")
			}
		})
	}
}

// TestRegisterAll tests tool registration
func TestRegisterAll(t *testing.T) {
	tests := []struct {
		name    string
		config  *config.Config
		wantErr bool
		errMsg  string
	}{
		{
			name: "single tool registration",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:        "test_tool",
						Description: "Test tool",
						Parameters: map[string]config.Parameter{
							"input": {Type: "string", Required: true},
						},
						Route: config.RouteSpec{Actors: []string{"actor1"}},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "multiple tools registration",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:        "tool1",
						Description: "First tool",
						Route:       config.RouteSpec{Actors: []string{"actor1"}},
					},
					{
						Name:        "tool2",
						Description: "Second tool",
						Route:       config.RouteSpec{Actors: []string{"actor2"}},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "tool with invalid parameter type",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:        "invalid_tool",
						Description: "Tool with invalid param",
						Parameters: map[string]config.Parameter{
							"bad_param": {Type: "unknown_type"},
						},
						Route: config.RouteSpec{Actors: []string{"actor1"}},
					},
				},
			},
			wantErr: true,
			errMsg:  "failed to register tool \"invalid_tool\": parameter \"bad_param\": unsupported parameter type: unknown_type",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			registry := NewRegistry(tt.config, jobs.NewStore(), &MockQueueClient{})
			mcpServer := server.NewMCPServer("test-server", "1.0.0")

			err := registry.RegisterAll(mcpServer)

			if tt.wantErr {
				if err == nil {
					t.Errorf("Expected error but got none")
				} else if tt.errMsg != "" && err.Error() != tt.errMsg {
					t.Errorf("Expected error %q, got %q", tt.errMsg, err.Error())
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
			}

			if registry.mcpServer != mcpServer {
				t.Error("MCP server not set correctly")
			}

			if !tt.wantErr {
				if len(registry.handlers) != len(tt.config.Tools) {
					t.Errorf("Expected %d handlers, got %d", len(tt.config.Tools), len(registry.handlers))
				}
			}
		})
	}
}

// TestGetToolHandler tests handler retrieval
func TestGetToolHandler(t *testing.T) {
	cfg := &config.Config{
		Tools: []config.Tool{
			{
				Name:        "test_tool",
				Description: "Test tool",
				Route:       config.RouteSpec{Actors: []string{"actor1"}},
			},
		},
	}

	registry := NewRegistry(cfg, jobs.NewStore(), &MockQueueClient{})
	mcpServer := server.NewMCPServer("test-server", "1.0.0")
	_ = registry.RegisterAll(mcpServer)

	t.Run("existing tool", func(t *testing.T) {
		handler := registry.GetToolHandler("test_tool")
		if handler == nil {
			t.Error("Expected non-nil handler for existing tool")
		}
	})

	t.Run("non-existing tool", func(t *testing.T) {
		handler := registry.GetToolHandler("non_existing_tool")
		if handler != nil {
			t.Error("Expected nil handler for non-existing tool")
		}
	})
}

// TestCreateToolHandler tests the tool handler creation and execution
func TestCreateToolHandler(t *testing.T) {
	tests := []struct {
		name        string
		toolDef     config.Tool
		request     mcp.CallToolRequest
		jobStoreErr error
		wantErr     bool
		wantErrMsg  string
	}{
		{
			name: "valid tool call - all parameters",
			toolDef: config.Tool{
				Name:        "test_tool",
				Description: "Test tool",
				Parameters: map[string]config.Parameter{
					"param1": {Type: "string", Required: true},
					"param2": {Type: "number", Required: false},
				},
				Route: config.RouteSpec{Actors: []string{"actor1", "actor2"}},
			},
			request: createCallToolRequest(map[string]interface{}{
				"param1": "value1",
				"param2": 42,
			}),
			wantErr: false,
		},
		{
			name: "valid tool call - optional parameter missing",
			toolDef: config.Tool{
				Name:        "test_tool",
				Description: "Test tool",
				Parameters: map[string]config.Parameter{
					"param1": {Type: "string", Required: true},
					"param2": {Type: "string", Required: false},
				},
				Route: config.RouteSpec{Actors: []string{"actor1"}},
			},
			request: createCallToolRequest(map[string]interface{}{
				"param1": "value1",
			}),
			wantErr: false,
		},
		{
			name: "missing required parameter",
			toolDef: config.Tool{
				Name:        "test_tool",
				Description: "Test tool",
				Parameters: map[string]config.Parameter{
					"required_param": {Type: "string", Required: true},
				},
				Route: config.RouteSpec{Actors: []string{"actor1"}},
			},
			request:    createCallToolRequest(map[string]interface{}{}),
			wantErr:    true,
			wantErrMsg: "missing required parameter: required_param",
		},
		{
			name: "route template - valid",
			toolDef: config.Tool{
				Name:        "template_tool",
				Description: "Tool using template",
				Route:       config.RouteSpec{Template: "standard_pipeline"},
			},
			request: createCallToolRequest(map[string]interface{}{}),
			wantErr: false,
		},
		{
			name: "route template - not found",
			toolDef: config.Tool{
				Name:        "template_tool",
				Description: "Tool using invalid template",
				Route:       config.RouteSpec{Template: "non_existent_template"},
			},
			request:    createCallToolRequest(map[string]interface{}{}),
			wantErr:    true,
			wantErrMsg: "route error: route template \"non_existent_template\" not found",
		},
		{
			name: "tool with timeout configured",
			toolDef: config.Tool{
				Name:        "timeout_tool",
				Description: "Tool with timeout",
				Route:       config.RouteSpec{Actors: []string{"actor1"}},
				Timeout:     intPtr(30),
			},
			request: createCallToolRequest(map[string]interface{}{}),
			wantErr: false,
		},
		{
			name: "tool with progress enabled",
			toolDef: config.Tool{
				Name:        "progress_tool",
				Description: "Tool with progress",
				Route:       config.RouteSpec{Actors: []string{"actor1"}},
				Progress:    boolPtr(true),
			},
			request: createCallToolRequest(map[string]interface{}{}),
			wantErr: false,
		},
		{
			name: "tool with metadata",
			toolDef: config.Tool{
				Name:        "metadata_tool",
				Description: "Tool with metadata",
				Route:       config.RouteSpec{Actors: []string{"actor1"}},
				Metadata: map[string]string{
					"key1": "value1",
					"key2": "value2",
				},
			},
			request: createCallToolRequest(map[string]interface{}{}),
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &config.Config{
				Tools: []config.Tool{tt.toolDef},
				Routes: map[string][]string{
					"standard_pipeline": {"actor1", "actor2", "actor3"},
				},
			}

			jobStore := NewMockJobStore()
			if tt.jobStoreErr != nil {
				jobStore.createErr = tt.jobStoreErr
			}

			queueClient := &MockQueueClient{}
			registry := NewRegistry(cfg, jobStore, queueClient)

			handler := registry.createToolHandler(tt.toolDef)
			result, err := handler(context.Background(), tt.request)

			if err != nil {
				t.Errorf("Handler returned error: %v", err)
			}

			if tt.wantErr {
				if !result.IsError {
					t.Errorf("Expected error result but got success")
				}
				if tt.wantErrMsg != "" {
					content := result.Content[0]
					if textContent, ok := content.(mcp.TextContent); ok {
						if textContent.Text != tt.wantErrMsg {
							t.Errorf("Expected error message %q, got %q", tt.wantErrMsg, textContent.Text)
						}
					}
				}
				return
			}

			if result.IsError {
				t.Errorf("Expected success but got error: %v", result.Content)
			}

			time.Sleep(50 * time.Millisecond)

			if len(jobStore.envelopes) != 1 {
				t.Errorf("Expected 1 envelope in store, got %d", len(jobStore.envelopes))
			}

			for _, env := range jobStore.envelopes {
				expectedActors, _ := tt.toolDef.Route.GetActors(cfg.Routes)
				if len(env.Route.Actors) != len(expectedActors) {
					t.Errorf("Expected %d actors, got %d", len(expectedActors), len(env.Route.Actors))
				}

				if env.Route.Current != 0 {
					t.Errorf("Expected current=0, got %d", env.Route.Current)
				}

				if tt.toolDef.Timeout != nil {
					expectedTimeout := *tt.toolDef.Timeout
					if env.TimeoutSec != expectedTimeout {
						t.Errorf("Expected timeout=%d, got %d", expectedTimeout, env.TimeoutSec)
					}
				}
			}
		})
	}
}

// TestGetToolOptions tests tool options retrieval and merging
func TestGetToolOptions(t *testing.T) {
	tests := []struct {
		name        string
		config      *config.Config
		toolName    string
		wantErr     bool
		wantTimeout time.Duration
	}{
		{
			name: "tool with specific timeout",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:    "test_tool",
						Route:   config.RouteSpec{Actors: []string{"actor1"}},
						Timeout: intPtr(60),
					},
				},
			},
			toolName:    "test_tool",
			wantErr:     false,
			wantTimeout: 60 * time.Second,
		},
		{
			name: "tool inheriting default timeout",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:  "test_tool",
						Route: config.RouteSpec{Actors: []string{"actor1"}},
					},
				},
				Defaults: &config.ToolDefaults{
					Timeout: intPtr(120),
				},
			},
			toolName:    "test_tool",
			wantErr:     false,
			wantTimeout: 120 * time.Second,
		},
		{
			name: "tool overriding default timeout",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:    "test_tool",
						Route:   config.RouteSpec{Actors: []string{"actor1"}},
						Timeout: intPtr(30),
					},
				},
				Defaults: &config.ToolDefaults{
					Timeout: intPtr(120),
				},
			},
			toolName:    "test_tool",
			wantErr:     false,
			wantTimeout: 30 * time.Second,
		},
		{
			name: "non-existent tool",
			config: &config.Config{
				Tools: []config.Tool{
					{
						Name:  "test_tool",
						Route: config.RouteSpec{Actors: []string{"actor1"}},
					},
				},
			},
			toolName: "non_existent",
			wantErr:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			registry := NewRegistry(tt.config, jobs.NewStore(), &MockQueueClient{})

			opts, err := registry.GetToolOptions(tt.toolName)

			if tt.wantErr {
				if err == nil {
					t.Error("Expected error but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
			}

			if opts == nil {
				t.Fatal("Expected non-nil options")
			}

			if opts.Timeout != tt.wantTimeout {
				t.Errorf("Expected timeout=%v, got %v", tt.wantTimeout, opts.Timeout)
			}
		})
	}
}

// TestEnvelopeCreation tests envelope creation with various configurations
func TestEnvelopeCreation(t *testing.T) {
	tests := []struct {
		name             string
		toolDef          config.Tool
		defaults         *config.ToolDefaults
		expectDeadline   bool
		expectProgress   bool
		expectMetadata   bool
		metadataContains map[string]interface{}
	}{
		{
			name: "envelope with deadline",
			toolDef: config.Tool{
				Name:    "timeout_tool",
				Route:   config.RouteSpec{Actors: []string{"actor1"}},
				Timeout: intPtr(60),
			},
			expectDeadline: true,
		},
		{
			name: "envelope without timeout",
			toolDef: config.Tool{
				Name:  "no_timeout_tool",
				Route: config.RouteSpec{Actors: []string{"actor1"}},
			},
			expectDeadline: true,
		},
		{
			name: "envelope with job_id in metadata",
			toolDef: config.Tool{
				Name:  "metadata_tool",
				Route: config.RouteSpec{Actors: []string{"actor1"}},
			},
			expectMetadata: true,
			metadataContains: map[string]interface{}{
				"job_id": "should_be_set",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &config.Config{
				Tools:    []config.Tool{tt.toolDef},
				Defaults: tt.defaults,
			}

			jobStore := NewMockJobStore()
			queueClient := &MockQueueClient{}
			registry := NewRegistry(cfg, jobStore, queueClient)

			handler := registry.createToolHandler(tt.toolDef)
			request := createCallToolRequest(map[string]interface{}{})

			_, err := handler(context.Background(), request)
			if err != nil {
				t.Fatalf("Handler error: %v", err)
			}

			time.Sleep(50 * time.Millisecond)

			if len(jobStore.envelopes) != 1 {
				t.Fatalf("Expected 1 envelope, got %d", len(jobStore.envelopes))
			}

			for _, env := range jobStore.envelopes {
				if tt.expectDeadline {
					if env.Deadline.IsZero() {
						t.Error("Expected deadline to be set")
					}
				}

				if tt.expectMetadata {
					if env.Route.Metadata == nil {
						t.Fatal("Expected metadata to be set")
					}
					for key, expectedVal := range tt.metadataContains {
						if val, ok := env.Route.Metadata[key]; !ok {
							t.Errorf("Expected metadata key %q to exist", key)
						} else if expectedVal != "should_be_set" && val != expectedVal {
							t.Errorf("Expected metadata[%q]=%v, got %v", key, expectedVal, val)
						}
					}
				}
			}
		})
	}
}

// TestJobStoreFailure tests handling of job store failures
func TestJobStoreFailure(t *testing.T) {
	toolDef := config.Tool{
		Name:  "test_tool",
		Route: config.RouteSpec{Actors: []string{"actor1"}},
	}

	cfg := &config.Config{
		Tools: []config.Tool{toolDef},
	}

	jobStore := NewMockJobStore()
	jobStore.createErr = fmt.Errorf("database connection failed")

	queueClient := &MockQueueClient{}
	registry := NewRegistry(cfg, jobStore, queueClient)

	handler := registry.createToolHandler(toolDef)
	request := createCallToolRequest(map[string]interface{}{})

	result, err := handler(context.Background(), request)
	if err != nil {
		t.Errorf("Handler returned error: %v", err)
	}

	if !result.IsError {
		t.Error("Expected error result when job store fails")
	}
}

// TestQueueSendFailure tests handling of queue send failures
func TestQueueSendFailure(t *testing.T) {
	toolDef := config.Tool{
		Name:  "test_tool",
		Route: config.RouteSpec{Actors: []string{"actor1"}},
	}

	cfg := &config.Config{
		Tools: []config.Tool{toolDef},
	}

	jobStore := NewMockJobStore()

	queueClient := &MockQueueClientWithError{
		sendErr: fmt.Errorf("queue connection lost"),
	}
	registry := NewRegistry(cfg, jobStore, queueClient)

	handler := registry.createToolHandler(toolDef)
	request := createCallToolRequest(map[string]interface{}{})

	result, err := handler(context.Background(), request)
	if err != nil {
		t.Errorf("Handler returned error: %v", err)
	}

	if result.IsError {
		t.Error("Expected success result even when queue send happens async")
	}

	time.Sleep(100 * time.Millisecond)

	if len(jobStore.envelopes) != 1 {
		t.Fatalf("Expected 1 envelope in store, got %d", len(jobStore.envelopes))
	}

	for _, env := range jobStore.envelopes {
		if env.Status != types.EnvelopeStatusFailed {
			t.Errorf("Expected envelope status to be Failed, got %v", env.Status)
		}
		if env.Error == "" {
			t.Error("Expected error message to be set")
		}
	}
}

// Helper functions

func createCallToolRequest(args map[string]interface{}) mcp.CallToolRequest {
	req := mcp.CallToolRequest{}
	req.Params.Arguments = args
	return req
}

func intPtr(i int) *int {
	return &i
}

func boolPtr(b bool) *bool {
	return &b
}
