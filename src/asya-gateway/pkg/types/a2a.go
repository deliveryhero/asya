package types

// --- A2A Task State Mapping ---

// A2ATaskState represents A2A protocol task states.
// These map from internal TaskStatus to A2A-compliant states.
type A2ATaskState string

const (
	A2AStateSubmitted A2ATaskState = "submitted"
	A2AStateWorking   A2ATaskState = "working"
	A2AStateCompleted A2ATaskState = "completed"
	A2AStateFailed    A2ATaskState = "failed"
	A2AStateUnknown   A2ATaskState = "unknown"

	// A2A spec states for Phase 2: human-in-the-loop, cancellation, rejection
	A2AStateInputRequired A2ATaskState = "input_required"
	A2AStateCanceled      A2ATaskState = "canceled"
	A2AStateRejected      A2ATaskState = "rejected"
)

// ToA2AState converts internal TaskStatus to A2A task state.
func ToA2AState(s TaskStatus) A2ATaskState {
	switch s {
	case TaskStatusPending:
		return A2AStateSubmitted
	case TaskStatusRunning:
		return A2AStateWorking
	case TaskStatusSucceeded:
		return A2AStateCompleted
	case TaskStatusFailed:
		return A2AStateFailed
	case TaskStatusPaused:
		return A2AStateInputRequired
	case TaskStatusCanceled:
		return A2AStateCanceled
	default:
		return A2AStateUnknown
	}
}

// --- A2A Message Types ---

// A2APart represents a part of an A2A message (text, data, or file).
type A2APart struct {
	Type      string `json:"type"`                 // "text", "data", "file"
	Text      string `json:"text,omitempty"`       // for type=text
	Data      any    `json:"data,omitempty"`       // for type=data
	URL       string `json:"url,omitempty"`        // for type=file
	MediaType string `json:"media_type,omitempty"` // MIME type for file parts
	Name      string `json:"name,omitempty"`       // filename for file parts
}

// A2AMessage represents an A2A protocol message.
type A2AMessage struct {
	Role     string    `json:"role"` // "user" or "agent"
	Parts    []A2APart `json:"parts"`
	Metadata any       `json:"metadata,omitempty"`
}

// A2AArtifact represents an output artifact from task processing.
type A2AArtifact struct {
	ArtifactID  string    `json:"artifactId"`
	Name        string    `json:"name,omitempty"`
	Description string    `json:"description,omitempty"`
	Parts       []A2APart `json:"parts"`
	Metadata    any       `json:"metadata,omitempty"`
}

// A2ATaskStatus represents the status block in an A2A task response.
type A2ATaskStatus struct {
	State     A2ATaskState `json:"state"`
	Message   *A2AMessage  `json:"message,omitempty"`
	Timestamp string       `json:"timestamp"`
}

// A2ATask represents the full A2A task response.
type A2ATask struct {
	ID        string        `json:"id"`
	ContextID string        `json:"contextId,omitempty"`
	Status    A2ATaskStatus `json:"status"`
	Artifacts []A2AArtifact `json:"artifacts,omitempty"`
	History   []A2AMessage  `json:"history,omitempty"`
	Metadata  any           `json:"metadata,omitempty"`
}

// --- A2A JSON-RPC ---

// A2AJSONRPCRequest is the A2A JSON-RPC 2.0 request message.
type A2AJSONRPCRequest struct {
	JSONRPC string `json:"jsonrpc"`
	ID      any    `json:"id"`
	Method  string `json:"method"`
	Params  any    `json:"params"`
}

// A2AJSONRPCResponse is the A2A JSON-RPC 2.0 response message.
type A2AJSONRPCResponse struct {
	JSONRPC string           `json:"jsonrpc"`
	ID      any              `json:"id"`
	Result  any              `json:"result,omitempty"`
	Error   *A2AJSONRPCError `json:"error,omitempty"`
}

// A2AJSONRPCError is the A2A JSON-RPC error object.
type A2AJSONRPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

// A2A JSON-RPC error codes (standard + A2A-specific)
const (
	A2AErrParseError       = -32700
	A2AErrInvalidRequest   = -32600
	A2AErrMethodNotFound   = -32601
	A2AErrInvalidParams    = -32602
	A2AErrInternalError    = -32603
	A2AErrTaskNotFound     = -32001
	A2AErrUnsupported      = -32002
	A2AErrContentTypeError = -32003
)

// NewA2AError creates an A2A JSON-RPC error response.
func NewA2AError(id any, code int, message string) *A2AJSONRPCResponse {
	return &A2AJSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error: &A2AJSONRPCError{
			Code:    code,
			Message: message,
		},
	}
}

// NewA2AResult creates an A2A JSON-RPC success response.
func NewA2AResult(id any, result any) *A2AJSONRPCResponse {
	return &A2AJSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Result:  result,
	}
}

// --- A2A Send Message Request Params ---

// A2ASendMessageParams are the params for message/send and message/stream.
type A2ASendMessageParams struct {
	Message   A2AMessage `json:"message"`
	ContextID string     `json:"contextId,omitempty"`
	TaskID    string     `json:"taskId,omitempty"`
	Skill     string     `json:"skill,omitempty"` // maps to tool name
}

// --- A2A SSE Event Types ---

// A2ATaskStatusUpdateEvent is sent over SSE when task status changes.
type A2ATaskStatusUpdateEvent struct {
	ID     string        `json:"id"`
	Status A2ATaskStatus `json:"status"`
	Final  bool          `json:"final"`
}

// A2ATaskArtifactUpdateEvent is sent over SSE when an artifact is produced.
type A2ATaskArtifactUpdateEvent struct {
	ID       string      `json:"id"`
	Artifact A2AArtifact `json:"artifact"`
}

// --- Agent Card ---

// AgentCard represents the A2A Agent Card for discovery.
type AgentCard struct {
	Name             string         `json:"name"`
	Description      string         `json:"description,omitempty"`
	Version          string         `json:"version"`
	URL              string         `json:"url"`
	ProtocolVersions []string       `json:"protocolVersions"`
	Capabilities     AgentCaps      `json:"capabilities"`
	Skills           []AgentSkill   `json:"skills"`
	SecuritySchemes  map[string]any `json:"securitySchemes,omitempty"`
}

// AgentCaps describes what the agent supports.
type AgentCaps struct {
	Streaming         bool `json:"streaming"`
	PushNotifications bool `json:"pushNotifications"`
}

// AgentSkill represents a skill (maps to a gateway tool).
type AgentSkill struct {
	ID          string         `json:"id"`
	Name        string         `json:"name"`
	Description string         `json:"description,omitempty"`
	InputSchema map[string]any `json:"inputSchema,omitempty"`
}
