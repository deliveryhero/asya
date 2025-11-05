package mcp

import (
	"context"
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

// Server wraps the mark3labs MCP server
type Server struct {
	mcpServer   *server.MCPServer
	jobStore    jobs.JobStore
	queueClient queue.Client
	registry    *Registry
}

// NewServer creates a new MCP server using mark3labs/mcp-go
// If cfg is nil, uses default hardcoded tools for backward compatibility
func NewServer(jobStore jobs.JobStore, queueClient queue.Client, cfg *config.Config) *Server {
	s := &Server{
		jobStore:    jobStore,
		queueClient: queueClient,
	}

	// Create MCP server with minimal boilerplate
	s.mcpServer = server.NewMCPServer(
		"asya-gateway",
		"0.1.0",
		server.WithToolCapabilities(false), // Tools don't change at runtime
	)

	// Register tools based on config or use defaults
	if cfg != nil {
		// Use registry for dynamic tool registration
		s.registry = NewRegistry(cfg, jobStore, queueClient)
		if err := s.registry.RegisterAll(s.mcpServer); err != nil {
			log.Fatalf("Failed to register tools from config: %v", err)
		}
	} else {
		// Fallback to hardcoded tools for backward compatibility
		log.Println("No config provided, using default hardcoded tools")
		s.registerTools()
	}

	return s
}

func (s *Server) registerTools() {
	// Define the processImageWorkflow tool with clean fluent API
	tool := mcp.NewTool(
		"processImageWorkflow",
		mcp.WithDescription("Generate images, score them, and return the best results"),
		mcp.WithString("description",
			mcp.Required(),
			mcp.Description("Description of images to generate"),
		),
		mcp.WithNumber("count",
			mcp.Description("Number of images to generate (default: 5)"),
		),
		mcp.WithArray("route",
			mcp.Required(),
			mcp.Description("Actor route steps (e.g., [\"image-generator\", \"scorer\", \"happy-end\"])"),
			mcp.WithStringItems(),
		),
		mcp.WithNumber("timeout",
			mcp.Description("Total timeout for job in seconds"),
		),
	)

	// Register tool with handler
	s.mcpServer.AddTool(tool, s.handleProcessImageWorkflow)
}

func (s *Server) handleProcessImageWorkflow(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	// Extract required parameters with type safety
	description, err := request.RequireString("description")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}

	route, err := request.RequireStringSlice("route")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}

	if len(route) == 0 {
		return mcp.NewToolResultError("route cannot be empty"), nil
	}

	// Extract optional parameters with defaults
	count := request.GetFloat("count", 5.0)
	timeout := request.GetFloat("timeout", 0.0)

	// Create job
	jobID := uuid.New().String()
	job := &types.Job{
		ID: jobID,
		Route: types.Route{
			Steps:   route,
			Current: 0,
		},
		Payload: map[string]any{
			"description": description,
			"count":       int(count),
		},
		TimeoutSec: int(timeout),
	}

	// Store job
	if err := s.jobStore.Create(job); err != nil {
		log.Printf("Failed to create job: %v", err)
		return mcp.NewToolResultError(fmt.Sprintf("failed to create job: %v", err)), nil
	}

	// Send to queue (async)
	go func() {
		// Update status to Running
		s.jobStore.Update(types.JobUpdate{
			JobID:     jobID,
			Status:    types.JobStatusRunning,
			Message:   "Sending message to first actor",
			Timestamp: time.Now(),
		})

		if err := s.queueClient.SendMessage(context.Background(), job); err != nil {
			log.Printf("Failed to send message to queue: %v", err)
			s.jobStore.Update(types.JobUpdate{
				JobID:     jobID,
				Status:    types.JobStatusFailed,
				Error:     fmt.Sprintf("failed to send message: %v", err),
				Timestamp: time.Now(),
			})
			return
		}

		log.Printf("Job %s sent to queue %s", jobID, route[0])
	}()

	// Return success response with clean helper
	message := fmt.Sprintf(
		"Job created successfully with ID: %s\n\nUse the following endpoints:\n"+
			"- Status: GET /jobs/%s\n"+
			"- Real-time updates: GET /jobs/%s/stream (SSE)",
		jobID, jobID, jobID,
	)

	return mcp.NewToolResultText(message), nil
}

// GetMCPServer returns the underlying MCP server for HTTP integration
func (s *Server) GetMCPServer() *server.MCPServer {
	return s.mcpServer
}
