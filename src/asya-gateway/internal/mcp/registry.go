package mcp

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/google/uuid"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ToolHandler is a function that handles MCP tool calls
type ToolHandler func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error)

// Registry manages dynamic MCP tool registration from configuration
type Registry struct {
	config      *config.Config
	jobStore    jobs.JobStore
	queueClient queue.Client
	mcpServer   *server.MCPServer
	handlers    map[string]ToolHandler // Map of tool name -> handler
}

// NewRegistry creates a new tool registry
func NewRegistry(cfg *config.Config, jobStore jobs.JobStore, queueClient queue.Client) *Registry {
	return &Registry{
		config:      cfg,
		jobStore:    jobStore,
		queueClient: queueClient,
		handlers:    make(map[string]ToolHandler),
	}
}

// RegisterAll registers all tools from config to the MCP server
func (r *Registry) RegisterAll(mcpServer *server.MCPServer) error {
	r.mcpServer = mcpServer

	for _, toolDef := range r.config.Tools {
		if err := r.registerTool(toolDef); err != nil {
			return fmt.Errorf("failed to register tool %q: %w", toolDef.Name, err)
		}
		log.Printf("Registered tool: %s", toolDef.Name)
	}

	log.Printf("Successfully registered %d tools", len(r.config.Tools))
	return nil
}

// registerTool converts a config.Tool to an MCP tool and registers it
func (r *Registry) registerTool(toolDef config.Tool) error {
	// Build options for mcp.NewTool
	options := []mcp.ToolOption{mcp.WithDescription(toolDef.Description)}

	// Add all parameters as options
	for paramName, param := range toolDef.Parameters {
		paramOption, err := r.buildParameterOptions(paramName, param)
		if err != nil {
			return fmt.Errorf("parameter %q: %w", paramName, err)
		}
		options = append(options, paramOption)
	}

	// Create MCP tool with all options
	mcpTool := mcp.NewTool(toolDef.Name, options...)

	// Create handler closure that captures toolDef
	handler := r.createToolHandler(toolDef)

	// Store handler for REST API access
	r.handlers[toolDef.Name] = handler

	// Register with MCP server
	r.mcpServer.AddTool(mcpTool, handler)

	return nil
}

// GetToolHandler returns the handler for a given tool name
func (r *Registry) GetToolHandler(toolName string) ToolHandler {
	return r.handlers[toolName]
}

// buildParameterOptions creates the appropriate mcp.WithX option for a parameter
func (r *Registry) buildParameterOptions(name string, param config.Parameter) (mcp.ToolOption, error) {
	var paramOptions []mcp.PropertyOption

	// Add description if present
	if param.Description != "" {
		paramOptions = append(paramOptions, mcp.Description(param.Description))
	}

	// Add required flag if true
	if param.Required {
		paramOptions = append(paramOptions, mcp.Required())
	}

	// Build parameter option based on type
	switch param.Type {
	case "string":
		// Add enum if specified
		if len(param.Options) > 0 {
			paramOptions = append(paramOptions, mcp.Enum(param.Options...))
		}
		return mcp.WithString(name, paramOptions...), nil

	case "number", "integer":
		return mcp.WithNumber(name, paramOptions...), nil

	case "boolean":
		return mcp.WithBoolean(name, paramOptions...), nil

	case "array":
		if param.Items != nil {
			// Handle typed arrays
			switch param.Items.Type {
			case "string":
				paramOptions = append(paramOptions, mcp.WithStringItems())
			case "number", "integer":
				paramOptions = append(paramOptions, mcp.WithNumberItems())
			}
		}
		return mcp.WithArray(name, paramOptions...), nil

	case "object":
		// For objects, use a generic parameter
		// Object validation will be done in the handler
		log.Printf("Warning: object parameter %q uses generic validation", name)
		// We'll treat it as a flexible any parameter - mcp-go will handle it
		// No specific type method needed - it will accept any JSON object
		return mcp.WithString(name, paramOptions...), nil

	default:
		return nil, fmt.Errorf("unsupported parameter type: %s", param.Type)
	}
}

// createToolHandler creates a tool handler function for the given tool definition
func (r *Registry) createToolHandler(toolDef config.Tool) func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	return func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		// Resolve route actors
		actors, err := toolDef.Route.GetActors(r.config.Routes)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("route error: %v", err)), nil
		}

		// Get tool options (merged with defaults)
		opts := toolDef.GetOptions(r.config.Defaults)

		// Extract all arguments
		arguments := request.GetArguments()

		// Validate required parameters
		for paramName, param := range toolDef.Parameters {
			if param.Required {
				if _, ok := arguments[paramName]; !ok {
					return mcp.NewToolResultError(fmt.Sprintf("missing required parameter: %s", paramName)), nil
				}
			}
		}

		// Create envelope
		envelopeID := uuid.New().String()
		envelope := &types.Envelope{
			ID:     envelopeID,
			Status: types.EnvelopeStatusPending,
			Route: types.Route{
				Actors:  actors,
				Current: 0,
				Metadata: map[string]interface{}{
					"job_id": envelopeID, // For end queue tracking
				},
			},
			Payload:    arguments,
			TimeoutSec: int(opts.Timeout.Seconds()),
		}

		// Set deadline if timeout is configured
		if opts.Timeout > 0 {
			envelope.Deadline = time.Now().Add(opts.Timeout)
		}

		// Store envelope
		if err := r.jobStore.Create(envelope); err != nil {
			log.Printf("Failed to create envelope: %v", err)
			return mcp.NewToolResultError(fmt.Sprintf("failed to create envelope: %v", err)), nil
		}

		// Send to queue (async)
		go func() {
			// Update status to Running
			_ = r.jobStore.Update(types.EnvelopeUpdate{
				ID:        envelopeID,
				Status:    types.EnvelopeStatusRunning,
				Message:   "Sending envelope to first actor",
				Timestamp: time.Now(),
			})

			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()

			if err := r.queueClient.SendEnvelope(ctx, envelope); err != nil {
				log.Printf("Failed to send envelope to queue: %v", err)
				_ = r.jobStore.Update(types.EnvelopeUpdate{
					ID:        envelopeID,
					Status:    types.EnvelopeStatusFailed,
					Error:     fmt.Sprintf("failed to send envelope: %v", err),
					Timestamp: time.Now(),
				})
				return
			}
		}()

		// Build MCP-compliant structured response
		responseData := map[string]interface{}{
			"envelope_id": envelopeID,
			"message":     "Envelope created successfully",
			"status_url":  fmt.Sprintf("/envelopes/%s", envelopeID),
		}

		// Add stream endpoint if progress is enabled
		if opts.Progress {
			responseData["stream_url"] = fmt.Sprintf("/envelopes/%s/stream", envelopeID)
		}

		// Add metadata to response if present
		if len(opts.Metadata) > 0 {
			responseData["metadata"] = opts.Metadata
		}

		// Convert to JSON string for text content
		responseJSON, err := json.Marshal(responseData)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("failed to marshal response: %v", err)), nil
		}

		return mcp.NewToolResultText(string(responseJSON)), nil
	}
}

// GetToolOptions returns the options for a specific tool by name
func (r *Registry) GetToolOptions(toolName string) (*config.ToolOptions, error) {
	for _, tool := range r.config.Tools {
		if tool.Name == toolName {
			opts := tool.GetOptions(r.config.Defaults)
			return &opts, nil
		}
	}
	return nil, fmt.Errorf("tool %q not found", toolName)
}
