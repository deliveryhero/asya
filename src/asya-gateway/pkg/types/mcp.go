package types

// MCP JSON-RPC 2.0 envelope types

// JSONRPCRequest represents a JSON-RPC 2.0 request
type JSONRPCRequest struct {
	JSONRPC string `json:"jsonrpc"` // Must be "2.0"
	ID      any    `json:"id,omitempty"`
	Method  string `json:"method"`
	Params  any    `json:"params,omitempty"`
}

// JSONRPCResponse represents a JSON-RPC 2.0 response
type JSONRPCResponse struct {
	JSONRPC string        `json:"jsonrpc"` // Must be "2.0"
	ID      any           `json:"id,omitempty"`
	Result  any           `json:"result,omitempty"`
	Error   *JSONRPCError `json:"error,omitempty"`
}

// JSONRPCError represents a JSON-RPC 2.0 error
type JSONRPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

// JSON-RPC error codes
const (
	ErrorCodeParseError     = -32700
	ErrorCodeInvalidRequest = -32600
	ErrorCodeMethodNotFound = -32601
	ErrorCodeInvalidParams  = -32602
	ErrorCodeInternalError  = -32603
)

// MCP-specific types

// Tool represents an MCP tool definition
type Tool struct {
	Name        string      `json:"name"`
	Description string      `json:"description,omitempty"`
	InputSchema InputSchema `json:"inputSchema"`
}

// InputSchema represents JSON Schema for tool input
type InputSchema struct {
	Type       string              `json:"type"`
	Properties map[string]Property `json:"properties,omitempty"`
	Required   []string            `json:"required,omitempty"`
}

// Property represents a JSON Schema property
type Property struct {
	Type        string    `json:"type"`
	Description string    `json:"description,omitempty"`
	Items       *Property `json:"items,omitempty"` // For arrays
	Enum        []string  `json:"enum,omitempty"`
}

// ServerInfo represents MCP server information
type ServerInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

// ServerCapabilities represents MCP server capabilities
type ServerCapabilities struct {
	Tools *ToolsCapability `json:"tools,omitempty"`
}

// ToolsCapability indicates server supports tools
type ToolsCapability struct {
	ListChanged bool `json:"listChanged,omitempty"`
}

// InitializeResult is returned from initialize request
type InitializeResult struct {
	ProtocolVersion string             `json:"protocolVersion"`
	ServerInfo      ServerInfo         `json:"serverInfo"`
	Capabilities    ServerCapabilities `json:"capabilities"`
}

// CallToolParams represents parameters for tools/call
type CallToolParams struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments,omitempty"`
}

// CallToolResult represents the result of a tool call
type CallToolResult struct {
	Content []Content `json:"content"`
	IsError bool      `json:"isError,omitempty"`
}

// Content represents MCP content (text, image, resource, etc.)
type Content struct {
	Type string `json:"type"` // "text", "image", "resource"
	Text string `json:"text,omitempty"`
}

// ProgressNotification represents a progress notification
type ProgressNotification struct {
	JSONRPC string         `json:"jsonrpc"`
	Method  string         `json:"method"` // "notifications/progress"
	Params  ProgressParams `json:"params"`
}

// ProgressParams contains progress notification parameters
type ProgressParams struct {
	ProgressToken string  `json:"progressToken"`
	Progress      float64 `json:"progress"` // 0.0 to 1.0
	Total         float64 `json:"total,omitempty"`
}
