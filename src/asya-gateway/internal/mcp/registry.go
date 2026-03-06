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

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ToolHandler is a function that handles MCP tool calls
type ToolHandler func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error)

// Registry manages dynamic MCP tool registration from the DB-backed tool registry
type Registry struct {
	toolRegistry *toolstore.Registry
	taskStore    taskstore.TaskStore
	queueClient  queue.Client
	mcpServer    *server.MCPServer
	handlers     map[string]ToolHandler // Map of tool name -> handler
}

// NewRegistry creates a new tool registry
func NewRegistry(toolRegistry *toolstore.Registry, taskStore taskstore.TaskStore, queueClient queue.Client) *Registry {
	return &Registry{
		toolRegistry: toolRegistry,
		taskStore:    taskStore,
		queueClient:  queueClient,
		handlers:     make(map[string]ToolHandler),
	}
}

// RegisterAll registers all MCP-enabled tools from the tool registry to the MCP server
func (r *Registry) RegisterAll(mcpServer *server.MCPServer) error {
	r.mcpServer = mcpServer

	if r.toolRegistry == nil {
		return nil
	}

	tools := r.toolRegistry.MCPTools()
	for _, toolDef := range tools {
		if err := r.registerTool(toolDef); err != nil {
			return fmt.Errorf("failed to register tool %q: %w", toolDef.Name, err)
		}
		log.Printf("Registered MCP tool: %s", toolDef.Name)
	}

	log.Printf("Successfully registered %d MCP tools", len(tools))
	return nil
}

// registerTool converts a toolstore.Tool to an MCP tool and registers it
func (r *Registry) registerTool(toolDef toolstore.Tool) error {
	// Build options for mcp.NewTool
	options := []mcp.ToolOption{mcp.WithDescription(toolDef.Description)}

	// Parse parameters JSON Schema and add as a single schema option if present
	if len(toolDef.Parameters) > 0 {
		var schema map[string]interface{}
		if err := json.Unmarshal(toolDef.Parameters, &schema); err == nil {
			paramOptions := buildParamOptionsFromSchema(schema)
			options = append(options, paramOptions...)
		}
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

// buildParamOptionsFromSchema converts a parameter schema object into MCP tool options.
// Supports two formats:
//   - JSON Schema: {"properties": {"name": {...}}, "required": ["name"]}
//   - Flat format: {"name": {"type": "string", "required": true, ...}}
func buildParamOptionsFromSchema(schema map[string]interface{}) []mcp.ToolOption {
	var opts []mcp.ToolOption

	// Detect format: JSON Schema has a "properties" key; flat format does not.
	properties, hasProperties := schema["properties"].(map[string]interface{})

	requiredSet := make(map[string]bool)
	if hasProperties {
		// JSON Schema: required list is a top-level array
		requiredList, _ := schema["required"].([]interface{})
		for _, r := range requiredList {
			if name, ok := r.(string); ok {
				requiredSet[name] = true
			}
		}
	} else {
		// Flat format: treat the schema itself as the properties map
		properties = make(map[string]interface{})
		for name, v := range schema {
			if prop, ok := v.(map[string]interface{}); ok {
				properties[name] = prop
				if req, _ := prop["required"].(bool); req {
					requiredSet[name] = true
				}
			}
		}
	}

	for name, propRaw := range properties {
		prop, ok := propRaw.(map[string]interface{})
		if !ok {
			continue
		}

		var paramOptions []mcp.PropertyOption

		if desc, ok := prop["description"].(string); ok && desc != "" {
			paramOptions = append(paramOptions, mcp.Description(desc))
		}

		if requiredSet[name] {
			paramOptions = append(paramOptions, mcp.Required())
		}

		paramType, _ := prop["type"].(string)

		switch paramType {
		case "string":
			if enumVals, ok := prop["enum"].([]interface{}); ok {
				strs := make([]string, 0, len(enumVals))
				for _, v := range enumVals {
					if s, ok := v.(string); ok {
						strs = append(strs, s)
					}
				}
				paramOptions = append(paramOptions, mcp.Enum(strs...))
			}
			opts = append(opts, mcp.WithString(name, paramOptions...))
		case "number", "integer":
			opts = append(opts, mcp.WithNumber(name, paramOptions...))
		case "boolean":
			opts = append(opts, mcp.WithBoolean(name, paramOptions...))
		case "array":
			opts = append(opts, mcp.WithArray(name, paramOptions...))
		default:
			opts = append(opts, mcp.WithString(name, paramOptions...))
		}
	}

	return opts
}

// GetToolHandler returns the handler for a given tool name
func (r *Registry) GetToolHandler(toolName string) ToolHandler {
	return r.handlers[toolName]
}

// createToolHandler creates a tool handler function for the given tool definition.
// The tool sends the payload to a single entrypoint actor; routing is handled by
// router actors via ABI yields (Continuation-Passing Style).
func (r *Registry) createToolHandler(toolDef toolstore.Tool) func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	return func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		// Extract all arguments
		arguments := request.GetArguments()

		// Validate required parameters. Supports two formats:
		//   - JSON Schema: top-level "required" array
		//   - Flat format: per-property "required": true field
		if len(toolDef.Parameters) > 0 {
			var schema map[string]interface{}
			if err := json.Unmarshal(toolDef.Parameters, &schema); err == nil {
				if requiredList, ok := schema["required"].([]interface{}); ok {
					// JSON Schema format
					for _, r := range requiredList {
						if paramName, ok := r.(string); ok {
							if _, exists := arguments[paramName]; !exists {
								return mcp.NewToolResultError(fmt.Sprintf("missing required parameter: %s", paramName)), nil
							}
						}
					}
				} else {
					// Flat format: {"paramName": {"required": true, ...}}
					for name, propRaw := range schema {
						if prop, ok := propRaw.(map[string]interface{}); ok {
							if req, _ := prop["required"].(bool); req {
								if _, exists := arguments[name]; !exists {
									return mcp.NewToolResultError(fmt.Sprintf("missing required parameter: %s", name)), nil
								}
							}
						}
					}
				}
			}
		}

		// Resolve timeout
		timeoutSec := 300 // 5 minutes default
		if toolDef.TimeoutSec != nil {
			timeoutSec = *toolDef.TimeoutSec
		}
		timeout := time.Duration(timeoutSec) * time.Second

		// Create task with route from tool definition
		taskID := uuid.New().String()
		routeNext := toolDef.RouteNext
		if routeNext == nil {
			routeNext = []string{}
		}
		task := &types.Task{
			ID:     taskID,
			Status: types.TaskStatusPending,
			Route: types.Route{
				Prev: []string{},
				Curr: toolDef.Actor,
				Next: routeNext,
			},
			Payload:    arguments,
			TimeoutSec: timeoutSec,
		}

		// Set deadline if timeout is configured
		if timeout > 0 {
			task.Deadline = time.Now().Add(timeout)
		}

		// Store task
		if err := r.taskStore.Create(task); err != nil {
			log.Printf("Failed to create task: %v", err)
			return mcp.NewToolResultError(fmt.Sprintf("failed to create task: %v", err)), nil
		}

		// Send to queue (async)
		go func() {
			// Update status to Running
			_ = r.taskStore.Update(types.TaskUpdate{
				ID:        taskID,
				Status:    types.TaskStatusRunning,
				Message:   "Sending task to first actor",
				Timestamp: time.Now(),
			})

			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()

			if err := r.queueClient.SendMessage(ctx, task); err != nil {
				log.Printf("Failed to send task to queue: %v", err)
				_ = r.taskStore.Update(types.TaskUpdate{
					ID:        taskID,
					Status:    types.TaskStatusFailed,
					Error:     fmt.Sprintf("failed to send task: %v", err),
					Timestamp: time.Now(),
				})
				return
			}
		}()

		// Build MCP-compliant structured response
		responseData := map[string]interface{}{
			"task_id":    taskID,
			"message":    "Task created successfully",
			"status_url": fmt.Sprintf("/mesh/%s", taskID),
		}

		// Add stream endpoint if progress is enabled
		if toolDef.Progress {
			responseData["stream_url"] = fmt.Sprintf("/mesh/%s/stream", taskID)
		}

		// Convert to JSON string for text content
		responseJSON, err := json.Marshal(responseData)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("failed to marshal response: %v", err)), nil
		}

		return mcp.NewToolResultText(string(responseJSON)), nil
	}
}
