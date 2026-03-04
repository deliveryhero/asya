package mcp

import (
	"log"

	"github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
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
// If cfg is nil, no tools are registered from config (tools can still be
// registered dynamically via the /mesh/expose API).
func NewServer(taskStore taskstore.TaskStore, queueClient queue.Client, cfg *config.Config) *Server {
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

	// Create registry and register tools from config
	s.registry = NewRegistry(cfg, taskStore, queueClient)
	s.registry.mcpServer = s.mcpServer

	if cfg != nil && len(cfg.Tools) > 0 {
		if err := s.registry.RegisterAll(s.mcpServer); err != nil {
			log.Fatalf("Failed to register tools from config: %v", err)
		}
	} else {
		log.Println("MCP server initialized (no config tools; use /mesh/expose API for dynamic registration)")
	}

	return s
}

// GetMCPServer returns the underlying MCP server for HTTP integration
func (s *Server) GetMCPServer() *server.MCPServer {
	return s.mcpServer
}
