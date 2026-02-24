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
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Server wraps the mark3labs MCP server
type Server struct {
	mcpServer   *server.MCPServer
	taskStore   taskstore.TaskStore
	queueClient queue.Client
	registry    *Registry
}

// NewServer creates a new MCP server using mark3labs/mcp-go
// If cfg is nil, uses default hardcoded tools for backward compatibility
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

	// Always create registry for /tools/call REST endpoint support
	if cfg != nil {
		// Use registry for dynamic tool registration
		s.registry = NewRegistry(cfg, taskStore, queueClient)
		if err := s.registry.RegisterAll(s.mcpServer); err != nil {
			log.Fatalf("Failed to register tools from config: %v", err)
		}
	} else {
		// Fallback to hardcoded tools for backward compatibility
		log.Println("No config provided, using default empty list of tools")
		// Create empty registry to support REST API
		s.registry = NewRegistry(&config.Config{Tools: []config.Tool{}}, taskStore, queueClient)
		s.registry.mcpServer = s.mcpServer
		s.registerToolsWithRegistry()
	}

	return s
}

func (s *Server) registerToolsWithRegistry() {
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
			mcp.Description("Actor route (e.g., [\"image-generator\", \"scorer\", \"ranker\"])"),
			mcp.WithStringItems(),
		),
		mcp.WithNumber("timeout",
			mcp.Description("Total timeout for job in seconds"),
		),
	)

	// Register tool with handler
	handler := s.handleProcessImageWorkflow
	s.mcpServer.AddTool(tool, handler)
	// Store in registry for /tools/call endpoint
	s.registry.handlers["processImageWorkflow"] = handler
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

	// Create task
	// route is the full actor list: first actor goes to Curr, rest go to Next
	taskID := uuid.New().String()
	var routeCurr string
	var routeNext []string
	if len(route) > 0 {
		routeCurr = route[0]
		routeNext = route[1:]
	}
	task := &types.Task{
		ID: taskID,
		Route: types.Route{
			Prev: []string{},
			Curr: routeCurr,
			Next: routeNext,
		},
		Payload: map[string]any{
			"description": description,
			"count":       int(count),
		},
		TimeoutSec: int(timeout),
	}

	// Store task
	if err := s.taskStore.Create(task); err != nil {
		log.Printf("Failed to create task: %v", err)
		return mcp.NewToolResultError(fmt.Sprintf("failed to create task: %v", err)), nil
	}

	// Send to queue (async)
	go func() {
		// Update status to Running
		_ = s.taskStore.Update(types.TaskUpdate{
			ID:        taskID,
			Status:    types.TaskStatusRunning,
			Message:   "Sending task to first actor",
			Timestamp: time.Now(),
		})

		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()

		if err := s.queueClient.SendMessage(ctx, task); err != nil {
			log.Printf("Failed to send task to queue: %v", err)
			_ = s.taskStore.Update(types.TaskUpdate{
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
		"status_url": fmt.Sprintf("/tasks/%s", taskID),
		"stream_url": fmt.Sprintf("/tasks/%s/stream", taskID),
	}

	// Convert to JSON string for text content
	responseJSON, err := json.Marshal(responseData)
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("failed to marshal response: %v", err)), nil
	}

	return mcp.NewToolResultText(string(responseJSON)), nil
}

// GetMCPServer returns the underlying MCP server for HTTP integration
func (s *Server) GetMCPServer() *server.MCPServer {
	return s.mcpServer
}
