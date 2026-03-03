package mcp

import (
	"context"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
)

// ToolHandler is a function that handles MCP tool calls
type ToolHandler func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error)

// Registry manages dynamic MCP tool registration.
// Tools are registered via the /mesh/expose API and stored in the DB-backed toolstore.
type Registry struct {
	taskStore   taskstore.TaskStore
	queueClient queue.Client
	mcpServer   *server.MCPServer
	handlers    map[string]ToolHandler // Map of tool name -> handler
}

// NewRegistry creates a new tool registry
func NewRegistry(taskStore taskstore.TaskStore, queueClient queue.Client) *Registry {
	return &Registry{
		taskStore:   taskStore,
		queueClient: queueClient,
		handlers:    make(map[string]ToolHandler),
	}
}

// GetToolHandler returns the handler for a given tool name
func (r *Registry) GetToolHandler(toolName string) ToolHandler {
	return r.handlers[toolName]
}
