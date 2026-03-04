package mcp

import (
	"log"

	"github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
)

// Server wraps the mark3labs MCP server
type Server struct {
	mcpServer   *server.MCPServer
	taskStore   taskstore.TaskStore
	queueClient queue.Client
	registry    *Registry
}

// NewServer creates a new MCP server using mark3labs/mcp-go.
// Tools are loaded from the DB-backed tool registry (toolstore.Registry).
func NewServer(taskStore taskstore.TaskStore, queueClient queue.Client, toolRegistry *toolstore.Registry) *Server {
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

	// Create registry that reads from toolstore.Registry
	s.registry = NewRegistry(toolRegistry, taskStore, queueClient)
	s.registry.mcpServer = s.mcpServer

	if toolRegistry != nil {
		tools := toolRegistry.MCPTools()
		if len(tools) > 0 {
			if err := s.registry.RegisterAll(s.mcpServer); err != nil {
				log.Fatalf("Failed to register tools from registry: %v", err)
			}
		} else {
			log.Println("MCP server initialized (no MCP-enabled tools registered; use /mesh/expose API for dynamic registration)")
		}
	} else {
		log.Println("MCP server initialized (no tool registry; use /mesh/expose API for dynamic registration)")
	}

	return s
}

// GetMCPServer returns the underlying MCP server for HTTP integration
func (s *Server) GetMCPServer() *server.MCPServer {
	return s.mcpServer
}
