package mcpadapter

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/internal/sseclient"
)

// Handler manages the MCP server and tool registration.
type Handler struct {
	mcpServer  *server.MCPServer
	registry   *Registry
	meshClient *meshclient.Client
}

// NewHandler creates a new MCP adapter handler.
func NewHandler(reg *Registry, meshClient *meshclient.Client) *Handler {
	h := &Handler{
		registry:   reg,
		meshClient: meshClient,
	}

	h.mcpServer = server.NewMCPServer(
		"asya-mcp-adapter",
		"1.0.0",
		server.WithToolCapabilities(true), // tools change via hot-reload
	)

	return h
}

// MCPServer returns the underlying mcp-go server for HTTP integration.
func (h *Handler) MCPServer() *server.MCPServer {
	return h.mcpServer
}

// SyncTools atomically replaces all tools in the MCP server with the current
// registry contents. Removes stale tools that were deleted from the ConfigMap.
func (h *Handler) SyncTools() {
	tools := h.registry.Tools()

	serverTools := make([]server.ServerTool, 0, len(tools))
	for _, toolCfg := range tools {
		serverTools = append(serverTools, server.ServerTool{
			Tool:    buildMCPTool(toolCfg),
			Handler: h.createToolHandler(toolCfg),
		})
	}
	h.mcpServer.SetTools(serverTools...)

	slog.Info("MCP tools synced", "count", len(tools))
}

// buildMCPTool converts a ToolConfig to an mcp.Tool.
func buildMCPTool(cfg ToolConfig) mcp.Tool {
	opts := []mcp.ToolOption{mcp.WithDescription(cfg.Description)}

	if len(cfg.InputSchema) > 0 {
		var schema map[string]any
		if json.Unmarshal(cfg.InputSchema, &schema) == nil {
			opts = append(opts, buildParamOptions(schema)...)
		}
	}

	return mcp.NewTool(cfg.Name, opts...)
}

// buildParamOptions converts a JSON Schema object to mcp.ToolOptions.
func buildParamOptions(schema map[string]any) []mcp.ToolOption {
	var opts []mcp.ToolOption

	properties, _ := schema["properties"].(map[string]any)
	requiredSet := make(map[string]bool)
	if requiredList, ok := schema["required"].([]any); ok {
		for _, r := range requiredList {
			if name, ok := r.(string); ok {
				requiredSet[name] = true
			}
		}
	}

	for name, propRaw := range properties {
		prop, ok := propRaw.(map[string]any)
		if !ok {
			continue
		}

		var paramOpts []mcp.PropertyOption
		if desc, ok := prop["description"].(string); ok && desc != "" {
			paramOpts = append(paramOpts, mcp.Description(desc))
		}
		if requiredSet[name] {
			paramOpts = append(paramOpts, mcp.Required())
		}

		paramType, _ := prop["type"].(string)
		switch paramType {
		case "string":
			if enumVals, ok := prop["enum"].([]any); ok {
				strs := make([]string, 0, len(enumVals))
				for _, v := range enumVals {
					if s, ok := v.(string); ok {
						strs = append(strs, s)
					}
				}
				paramOpts = append(paramOpts, mcp.Enum(strs...))
			}
			opts = append(opts, mcp.WithString(name, paramOpts...))
		case "number", "integer":
			opts = append(opts, mcp.WithNumber(name, paramOpts...))
		case "boolean":
			opts = append(opts, mcp.WithBoolean(name, paramOpts...))
		case "array":
			opts = append(opts, mcp.WithArray(name, paramOpts...))
		default:
			opts = append(opts, mcp.WithString(name, paramOpts...))
		}
	}

	return opts
}

// createToolHandler creates an MCP tool handler that does two-step dispatch:
// 1. POST /api/v1/mesh/?actor=X (local, same pod)
// 2. GET /api/v1/mesh/{id}/events (via Ingress, hash-routed)
// 3. Translate mesh SSE events -> MCP progress/log/result
func (h *Handler) createToolHandler(cfg ToolConfig) server.ToolHandlerFunc {
	return func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		arguments := request.GetArguments()

		// Validate required parameters
		if len(cfg.InputSchema) > 0 {
			if err := validateRequired(cfg.InputSchema, arguments); err != nil {
				return mcp.NewToolResultError(err.Error()), nil
			}
		}

		timeout := cfg.Timeout
		if timeout == 0 {
			timeout = 300 // default 5 minutes
		}

		// Step 1: Create message in mesh-api
		createResp, err := h.meshClient.Create(ctx, cfg.Actor, meshclient.CreateRequest{
			Payload: arguments,
			Timeout: timeout,
		})
		if err != nil {
			slog.Error("Mesh create failed", "tool", cfg.Name, "error", err)
			return mcp.NewToolResultError(fmt.Sprintf("dispatch failed: %v", err)), nil
		}

		slog.Info("Mesh message created", "tool", cfg.Name, "id", createResp.ID, "actor", cfg.Actor)

		// Step 2: Subscribe to SSE events via Ingress
		sseCtx, sseCancel := context.WithTimeout(ctx, time.Duration(timeout)*time.Second)
		defer sseCancel()

		events, errCh := h.meshClient.SubscribeEvents(sseCtx, createResp.ID)

		// Extract progress token from request metadata (if client sent one)
		var progressToken mcp.ProgressToken
		if request.Params.Meta != nil {
			progressToken = request.Params.Meta.ProgressToken
		}

		// Step 3: Relay mesh events as MCP notifications
		var finalResult *mcp.CallToolResult
		for evt := range events {
			switch evt.Type {
			case "status":
				var status sseclient.StatusData
				if json.Unmarshal(evt.Data, &status) != nil {
					continue
				}

				if sseclient.IsTerminal(status.Status) || sseclient.IsInterrupted(status.Status) {
					finalResult = statusToCallToolResult(status)
					sseCancel()
					continue
				}

				// Non-terminal status → progress notification
				if progressToken != nil && cfg.Progress {
					_ = h.mcpServer.SendNotificationToClient(ctx,
						"notifications/progress",
						map[string]any{
							"progressToken": progressToken,
							"progress":      status.Progress,
							"total":         100.0,
							"message":       status.Message,
						})
				}

			case "fly":
				// FLY → log notification to the calling client
				_ = h.mcpServer.SendLogMessageToClient(ctx, mcp.LoggingMessageNotification{
					Params: mcp.LoggingMessageNotificationParams{
						Level:  mcp.LoggingLevelInfo,
						Logger: cfg.Name,
						Data:   json.RawMessage(evt.Data),
					},
				})
			}
		}

		// Check for SSE errors
		if sseErr := <-errCh; sseErr != nil && finalResult == nil {
			slog.Warn("SSE stream error", "id", createResp.ID, "error", sseErr)
			// Fall back to polling mesh-api for final status
			finalResult = h.pollForResult(ctx, createResp.ID, time.Duration(timeout)*time.Second)
		}

		if finalResult == nil {
			// Timeout or unexpected close -- check current status
			finalResult = h.pollForResult(ctx, createResp.ID, 5*time.Second)
		}

		if finalResult == nil {
			return mcp.NewToolResultError("timeout: no result received"), nil
		}

		return finalResult, nil
	}
}

// statusToCallToolResult converts a terminal mesh status to an MCP CallToolResult.
func statusToCallToolResult(status sseclient.StatusData) *mcp.CallToolResult {
	switch status.Status {
	case "succeeded":
		if status.Result != nil {
			data, err := json.Marshal(status.Result)
			if err == nil {
				return mcp.NewToolResultText(string(data))
			}
		}
		if status.Message != "" {
			return mcp.NewToolResultText(status.Message)
		}
		return mcp.NewToolResultText("completed")

	case "failed":
		msg := "task failed"
		if status.Error != "" {
			msg = status.Error
		} else if status.Message != "" {
			msg = status.Message
		}
		return mcp.NewToolResultError(msg)

	case "canceled":
		return mcp.NewToolResultError("task was canceled")

	case "paused":
		pausedJSON, _ := json.Marshal(map[string]string{"status": "paused", "message": status.Message})
		return mcp.NewToolResultText(string(pausedJSON))

	default:
		return mcp.NewToolResultError(fmt.Sprintf("unexpected status: %s", status.Status))
	}
}

// pollForResult checks mesh-api for current message status as a fallback.
func (h *Handler) pollForResult(ctx context.Context, id string, timeout time.Duration) *mcp.CallToolResult {
	pollCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-pollCtx.Done():
			return nil
		case <-ticker.C:
			status, err := h.meshClient.Get(pollCtx, id)
			if err != nil {
				continue
			}
			if sseclient.IsTerminal(status.Status) || sseclient.IsInterrupted(status.Status) {
				var s sseclient.StatusData
				s.Status = status.Status
				if status.Data != nil {
					_ = json.Unmarshal(status.Data, &s)
				}
				return statusToCallToolResult(s)
			}
		}
	}
}

// validateRequired checks that all required parameters are present.
func validateRequired(schemaRaw json.RawMessage, args map[string]any) error {
	var schema map[string]any
	if json.Unmarshal(schemaRaw, &schema) != nil {
		return nil // cannot parse, skip validation
	}

	requiredList, ok := schema["required"].([]any)
	if !ok {
		return nil
	}

	for _, r := range requiredList {
		name, ok := r.(string)
		if !ok {
			continue
		}
		if _, exists := args[name]; !exists {
			return fmt.Errorf("missing required parameter: %s", name)
		}
	}
	return nil
}
