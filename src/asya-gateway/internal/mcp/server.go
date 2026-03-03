package mcp

import (
	"log"

	"github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
)

// Server wraps the mark3labs MCP server
type Server struct {
	mcpServer   *server.MCPServer
	taskStore   taskstore.TaskStore
	queueClient queue.Client
	registry    *Registry
}

// NewServer creates a new MCP server using mark3labs/mcp-go.
// Tools are registered dynamically via the toolstore registry and /mesh/expose API.
func NewServer(taskStore taskstore.TaskStore, queueClient queue.Client) *Server {
	s := &Server{
		taskStore:   taskStore,
		queueClient: queueClient,
	}

	// Create MCP server with minimal boilerplate
	s.mcpServer = server.NewMCPServer(
		"asya-gateway",
		"0.1.0",
		server.WithToolCapabilities(false), // Tools don't change at runtime
	)

	// Create empty registry to support REST API
	s.registry = NewRegistry(taskStore, queueClient)
	s.registry.mcpServer = s.mcpServer

	log.Println("MCP server initialized (tools registered via /mesh/expose API)")

	return s
}

// GetMCPServer returns the underlying MCP server for HTTP integration
func (s *Server) GetMCPServer() *server.MCPServer {
	return s.mcpServer
}
