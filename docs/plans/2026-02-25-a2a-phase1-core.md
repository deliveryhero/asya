# A2A Protocol Compliance - Phase 1: Core Endpoints

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make asya-gateway A2A-compliant by adding Agent Card discovery, POST /a2a/ (message/send + message/stream), GET /a2a/tasks/{id}, and GET /a2a/tasks/{id}:subscribe endpoints while maintaining backward compatibility with existing MCP/REST endpoints.

**Architecture:** New `internal/a2a/` package contains all A2A handlers, keeping MCP code untouched. A2A types live in `pkg/types/a2a.go`. The A2A handler accepts JSON-RPC requests at `POST /a2a/` and dispatches by method. Agent Card is served from tool config. Both protocols share the same TaskStore and queue infrastructure.

**Tech Stack:** Go 1.24, net/http (stdlib), JSON-RPC 2.0, SSE (text/event-stream), existing taskstore/queue packages

**Aint tasks covered:** 1fkrbh (partial - A2A status mapping), 1f5jo3, 1f2hre, 1f9519, 1fuhpq, 1fkoxi, 1f2tkx, 1fgpla

---

### Task 1: A2A Types and Error Format

**Files:**
- Create: `src/asya-gateway/pkg/types/a2a.go`
- Test: `src/asya-gateway/pkg/types/a2a_test.go`

**Step 1: Write A2A types and error format**

Create `pkg/types/a2a.go` with all A2A protocol types:

```go
package types

// --- A2A Task State Mapping ---

// A2ATaskState represents A2A protocol task states.
// These map from internal TaskStatus to A2A-compliant states.
type A2ATaskState string

const (
	A2AStateSubmitted     A2ATaskState = "submitted"
	A2AStateWorking       A2ATaskState = "working"
	A2AStateCompleted     A2ATaskState = "completed"
	A2AStateFailed        A2ATaskState = "failed"
	A2AStateInputRequired A2ATaskState = "input_required"
	A2AStateCanceled      A2ATaskState = "canceled"
	A2AStateRejected      A2ATaskState = "rejected"
	A2AStateUnknown       A2ATaskState = "unknown"
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
	default:
		return A2AStateUnknown
	}
}

// --- A2A Message Types ---

// A2APart represents a part of an A2A message (text, data, or file).
type A2APart struct {
	Type      string `json:"type"`                 // "text", "data", "file"
	Text      string `json:"text,omitempty"`        // for type=text
	Data      any    `json:"data,omitempty"`        // for type=data
	URL       string `json:"url,omitempty"`         // for type=file
	MediaType string `json:"media_type,omitempty"`  // MIME type for file parts
	Name      string `json:"name,omitempty"`        // filename for file parts
}

// A2AMessage represents an A2A protocol message.
type A2AMessage struct {
	Role      string    `json:"role"`                  // "user" or "agent"
	Parts     []A2APart `json:"parts"`
	Metadata  any       `json:"metadata,omitempty"`
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
	ID        string         `json:"id"`
	ContextID string         `json:"contextId,omitempty"`
	Status    A2ATaskStatus  `json:"status"`
	Artifacts []A2AArtifact  `json:"artifacts,omitempty"`
	History   []A2AMessage   `json:"history,omitempty"`
	Metadata  any            `json:"metadata,omitempty"`
}

// --- A2A JSON-RPC ---

// A2AJSONRPCRequest is the A2A JSON-RPC 2.0 request envelope.
type A2AJSONRPCRequest struct {
	JSONRPC string `json:"jsonrpc"`
	ID      any    `json:"id"`
	Method  string `json:"method"`
	Params  any    `json:"params"`
}

// A2AJSONRPCResponse is the A2A JSON-RPC 2.0 response envelope.
type A2AJSONRPCResponse struct {
	JSONRPC string        `json:"jsonrpc"`
	ID      any           `json:"id"`
	Result  any           `json:"result,omitempty"`
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
	Skill     string     `json:"skill,omitempty"`   // maps to tool name
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
```

**Step 2: Write tests for A2A type helpers**

Create `pkg/types/a2a_test.go`:

```go
package types

import (
	"encoding/json"
	"testing"
)

func TestToA2AState(t *testing.T) {
	tests := []struct {
		input TaskStatus
		want  A2ATaskState
	}{
		{TaskStatusPending, A2AStateSubmitted},
		{TaskStatusRunning, A2AStateWorking},
		{TaskStatusSucceeded, A2AStateCompleted},
		{TaskStatusFailed, A2AStateFailed},
		{TaskStatusUnknown, A2AStateUnknown},
	}
	for _, tt := range tests {
		got := ToA2AState(tt.input)
		if got != tt.want {
			t.Errorf("ToA2AState(%s) = %s, want %s", tt.input, got, tt.want)
		}
	}
}

func TestNewA2AError(t *testing.T) {
	resp := NewA2AError(1, A2AErrTaskNotFound, "task xyz not found")
	if resp.JSONRPC != "2.0" {
		t.Errorf("JSONRPC = %s, want 2.0", resp.JSONRPC)
	}
	if resp.Error == nil {
		t.Fatal("Error should not be nil")
	}
	if resp.Error.Code != A2AErrTaskNotFound {
		t.Errorf("Error.Code = %d, want %d", resp.Error.Code, A2AErrTaskNotFound)
	}
	if resp.Result != nil {
		t.Error("Result should be nil for error response")
	}
}

func TestNewA2AResult(t *testing.T) {
	task := A2ATask{ID: "t1", Status: A2ATaskStatus{State: A2AStateWorking}}
	resp := NewA2AResult(1, task)
	if resp.Error != nil {
		t.Error("Error should be nil for success response")
	}
	if resp.Result == nil {
		t.Fatal("Result should not be nil")
	}
}

func TestA2AMessageJSON(t *testing.T) {
	msg := A2AMessage{
		Role: "user",
		Parts: []A2APart{
			{Type: "text", Text: "Hello"},
			{Type: "data", Data: map[string]any{"key": "val"}},
		},
	}
	data, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}
	var decoded A2AMessage
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}
	if decoded.Role != "user" {
		t.Errorf("Role = %s, want user", decoded.Role)
	}
	if len(decoded.Parts) != 2 {
		t.Errorf("Parts count = %d, want 2", len(decoded.Parts))
	}
}
```

**Step 3: Run tests**

Run: `cd src/asya-gateway && go test ./pkg/types/ -v -run TestA2A -count=1`
Expected: PASS

**Step 4: Commit**

```bash
git add src/asya-gateway/pkg/types/a2a.go src/asya-gateway/pkg/types/a2a_test.go
git commit -m "feat(gateway): add A2A protocol types and error format"
```

---

### Task 2: Add ContextID to Task Model and Store

**Files:**
- Modify: `src/asya-gateway/pkg/types/task.go` (add ContextID field)
- Modify: `src/asya-gateway/internal/taskstore/store.go` (in-memory: pass through ContextID)
- Modify: `src/asya-gateway/internal/taskstore/pg_store.go` (add context_id column handling)
- Test: `src/asya-gateway/internal/taskstore/store_test.go`

**Step 1: Add ContextID field to Task struct**

In `pkg/types/task.go`, add `ContextID` field to the `Task` struct after `ParentID`:

```go
ContextID string  `json:"context_id,omitempty"` // Groups related tasks into conversations
```

**Step 2: Update in-memory store - no changes needed**

The in-memory store stores `*types.Task` directly, so `ContextID` is automatically preserved. No code changes needed.

**Step 3: Update pg_store - add context_id to SQL queries**

In `pg_store.go`:
- `Create()`: Add `context_id` to INSERT query and values
- `Get()`: Add `context_id` to SELECT query and Scan

**Step 4: Write test for ContextID persistence**

Add to `store_test.go`:

```go
func TestStore_ContextID(t *testing.T) {
	store := NewStore()
	task := &types.Task{
		ID:        "ctx-test-1",
		ContextID: "conv-123",
		Route:     types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
	}
	if err := store.Create(task); err != nil {
		t.Fatal(err)
	}
	got, err := store.Get("ctx-test-1")
	if err != nil {
		t.Fatal(err)
	}
	if got.ContextID != "conv-123" {
		t.Errorf("ContextID = %q, want %q", got.ContextID, "conv-123")
	}
}
```

**Step 5: Run tests**

Run: `cd src/asya-gateway && go test ./internal/taskstore/ -v -count=1`
Expected: PASS

**Step 6: Commit**

```bash
git add src/asya-gateway/pkg/types/task.go src/asya-gateway/internal/taskstore/
git commit -m "feat(gateway): add context_id field to task model for conversation grouping"
```

---

### Task 3: Agent Card Discovery Endpoint

**Files:**
- Create: `src/asya-gateway/internal/a2a/agent_card.go`
- Create: `src/asya-gateway/internal/a2a/agent_card_test.go`

**Step 1: Write agent card test**

```go
package a2a

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandleAgentCard(t *testing.T) {
	cfg := &config.Config{
		Tools: []config.Tool{
			{
				Name:        "echo",
				Description: "Echo tool",
				Route:       config.RouteSpec{Actors: []string{"echo-actor"}},
			},
			{
				Name:        "analyze",
				Description: "Analyze data",
				Route:       config.RouteSpec{Actors: []string{"analyzer"}},
			},
		},
	}

	handler := NewAgentCardHandler(cfg)

	req := httptest.NewRequest(http.MethodGet, "/.well-known/a2a/agent-card", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusOK)
	}

	ct := rr.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("Content-Type = %s, want application/json", ct)
	}

	var card types.AgentCard
	if err := json.NewDecoder(rr.Body).Decode(&card); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if card.Name != "asya-gateway" {
		t.Errorf("Name = %s, want asya-gateway", card.Name)
	}
	if len(card.Skills) != 2 {
		t.Errorf("Skills count = %d, want 2", len(card.Skills))
	}
	if !card.Capabilities.Streaming {
		t.Error("Streaming capability should be true")
	}
}

func TestHandleAgentCard_MethodNotAllowed(t *testing.T) {
	handler := NewAgentCardHandler(&config.Config{Tools: []config.Tool{}})
	req := httptest.NewRequest(http.MethodPost, "/.well-known/a2a/agent-card", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("status = %d, want %d", rr.Code, http.StatusMethodNotAllowed)
	}
}
```

**Step 2: Run test to verify it fails**

Run: `cd src/asya-gateway && go test ./internal/a2a/ -v -run TestHandleAgentCard -count=1`
Expected: FAIL (package doesn't exist yet)

**Step 3: Implement agent card handler**

Create `internal/a2a/agent_card.go`:

```go
package a2a

import (
	"encoding/json"
	"net/http"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// AgentCardHandler serves the A2A Agent Card at /.well-known/a2a/agent-card
type AgentCardHandler struct {
	config *config.Config
}

// NewAgentCardHandler creates a handler that generates an Agent Card from tool config.
func NewAgentCardHandler(cfg *config.Config) *AgentCardHandler {
	return &AgentCardHandler{config: cfg}
}

func (h *AgentCardHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	skills := make([]types.AgentSkill, 0, len(h.config.Tools))
	for _, tool := range h.config.Tools {
		skills = append(skills, types.AgentSkill{
			ID:          tool.Name,
			Name:        tool.Name,
			Description: tool.Description,
		})
	}

	card := types.AgentCard{
		Name:             "asya-gateway",
		Description:      "Asya Actor Mesh Gateway - A2A compliant",
		Version:          "0.1.0",
		URL:              "/a2a/",
		ProtocolVersions: []string{"0.2.1"},
		Capabilities: types.AgentCaps{
			Streaming:         true,
			PushNotifications: false,
		},
		Skills: skills,
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(card)
}
```

**Step 4: Run tests**

Run: `cd src/asya-gateway && go test ./internal/a2a/ -v -run TestHandleAgentCard -count=1`
Expected: PASS

**Step 5: Commit**

```bash
git add src/asya-gateway/internal/a2a/
git commit -m "feat(gateway): add Agent Card discovery endpoint (GET /.well-known/a2a/agent-card)"
```

---

### Task 4: A2A Message Translation Layer

**Files:**
- Create: `src/asya-gateway/internal/a2a/translator.go`
- Create: `src/asya-gateway/internal/a2a/translator_test.go`

This task builds the bidirectional translation between A2A messages and internal task types.

**Step 1: Write translator tests**

Test inbound (A2A message -> task payload) and outbound (task -> A2A task) translation:

```go
package a2a

import (
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestMessageToPayload_SingleDataPart(t *testing.T) {
	msg := types.A2AMessage{
		Role: "user",
		Parts: []types.A2APart{
			{Type: "data", Data: map[string]any{"key": "val"}},
		},
	}
	payload := MessageToPayload(msg)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}
	if m["key"] != "val" {
		t.Errorf("key = %v, want val", m["key"])
	}
}

func TestMessageToPayload_TextPart(t *testing.T) {
	msg := types.A2AMessage{
		Role:  "user",
		Parts: []types.A2APart{{Type: "text", Text: "hello"}},
	}
	payload := MessageToPayload(msg)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}
	if m["_a2a_text"] != "hello" {
		t.Errorf("_a2a_text = %v, want hello", m["_a2a_text"])
	}
}

func TestMessageToPayload_MixedParts(t *testing.T) {
	msg := types.A2AMessage{
		Role: "user",
		Parts: []types.A2APart{
			{Type: "text", Text: "analyze this"},
			{Type: "data", Data: map[string]any{"x": 1}},
			{Type: "file", URL: "s3://b/f.pdf", MediaType: "application/pdf"},
		},
	}
	payload := MessageToPayload(msg)
	m, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected map, got %T", payload)
	}
	if m["_a2a_text"] != "analyze this" {
		t.Error("missing _a2a_text")
	}
	files, ok := m["_a2a_files"].([]map[string]string)
	if !ok || len(files) != 1 {
		t.Error("missing or wrong _a2a_files")
	}
}

func TestTaskToA2ATask(t *testing.T) {
	task := &types.Task{
		ID:        "t1",
		ContextID: "ctx-1",
		Status:    types.TaskStatusSucceeded,
		Result:    map[string]any{"score": 0.9},
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	a2aTask := TaskToA2ATask(task)
	if a2aTask.ID != "t1" {
		t.Errorf("ID = %s, want t1", a2aTask.ID)
	}
	if a2aTask.ContextID != "ctx-1" {
		t.Errorf("ContextID = %s, want ctx-1", a2aTask.ContextID)
	}
	if a2aTask.Status.State != types.A2AStateCompleted {
		t.Errorf("State = %s, want completed", a2aTask.Status.State)
	}
	if len(a2aTask.Artifacts) != 1 {
		t.Errorf("Artifacts count = %d, want 1", len(a2aTask.Artifacts))
	}
}
```

**Step 2: Implement translator**

Create `internal/a2a/translator.go`:

```go
package a2a

import (
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// MessageToPayload converts an A2A message to an internal task payload.
//
// Rules:
// 1. Single data part -> unwrap as payload directly
// 2. Text parts -> merge into _a2a_text
// 3. File parts -> collect into _a2a_files array
// 4. Mixed -> combine into unified payload with _a2a_* keys
func MessageToPayload(msg types.A2AMessage) any {
	var textParts []string
	var dataParts []map[string]any
	var fileParts []map[string]string

	for _, part := range msg.Parts {
		switch part.Type {
		case "text":
			textParts = append(textParts, part.Text)
		case "data":
			if m, ok := part.Data.(map[string]any); ok {
				dataParts = append(dataParts, m)
			}
		case "file":
			fileParts = append(fileParts, map[string]string{
				"url":        part.URL,
				"media_type": part.MediaType,
			})
		}
	}

	// Single data part, no text or files: unwrap directly
	if len(dataParts) == 1 && len(textParts) == 0 && len(fileParts) == 0 {
		return dataParts[0]
	}

	// Build composite payload
	payload := make(map[string]any)

	// Merge data parts
	for _, dp := range dataParts {
		for k, v := range dp {
			payload[k] = v
		}
	}

	// Add text
	if len(textParts) == 1 {
		payload["_a2a_text"] = textParts[0]
	} else if len(textParts) > 1 {
		combined := ""
		for i, t := range textParts {
			if i > 0 {
				combined += "\n"
			}
			combined += t
		}
		payload["_a2a_text"] = combined
	}

	// Add files
	if len(fileParts) > 0 {
		payload["_a2a_files"] = fileParts
	}

	return payload
}

// TaskToA2ATask converts an internal Task to an A2A Task response.
func TaskToA2ATask(task *types.Task) types.A2ATask {
	a2aTask := types.A2ATask{
		ID:        task.ID,
		ContextID: task.ContextID,
		Status: types.A2ATaskStatus{
			State:     types.ToA2AState(task.Status),
			Timestamp: task.UpdatedAt.UTC().Format("2006-01-02T15:04:05Z"),
		},
	}

	// Add status message if present
	if task.Message != "" {
		a2aTask.Status.Message = &types.A2AMessage{
			Role:  "agent",
			Parts: []types.A2APart{{Type: "text", Text: task.Message}},
		}
	}

	// Convert result to artifact
	if task.Result != nil && task.Status == types.TaskStatusSucceeded {
		a2aTask.Artifacts = []types.A2AArtifact{
			{
				ArtifactID: "result-1",
				Parts:      []types.A2APart{{Type: "data", Data: task.Result}},
			},
		}
	}

	// Convert error to status message
	if task.Error != "" && task.Status == types.TaskStatusFailed {
		a2aTask.Status.Message = &types.A2AMessage{
			Role:  "agent",
			Parts: []types.A2APart{{Type: "text", Text: task.Error}},
		}
	}

	// Add progress metadata for in-progress tasks
	if task.Status == types.TaskStatusRunning {
		a2aTask.Metadata = map[string]any{
			"progress_percent":   task.ProgressPercent,
			"current_actor_name": task.CurrentActorName,
			"actors_completed":   task.ActorsCompleted,
			"total_actors":       task.TotalActors,
		}
	}

	return a2aTask
}

// TaskUpdateToSSEEvents converts an internal TaskUpdate to A2A SSE events.
func TaskUpdateToSSEEvents(update types.TaskUpdate) types.A2ATaskStatusUpdateEvent {
	state := types.ToA2AState(update.Status)
	final := state == types.A2AStateCompleted || state == types.A2AStateFailed ||
		state == types.A2AStateCanceled || state == types.A2AStateRejected

	event := types.A2ATaskStatusUpdateEvent{
		ID: update.ID,
		Status: types.A2ATaskStatus{
			State:     state,
			Timestamp: update.Timestamp.UTC().Format("2006-01-02T15:04:05Z"),
		},
		Final: final,
	}

	// Add message from update
	msg := update.Message
	if update.Error != "" {
		msg = update.Error
	}
	if msg != "" {
		role := "agent"
		event.Status.Message = &types.A2AMessage{
			Role:  role,
			Parts: []types.A2APart{{Type: "text", Text: msg}},
		}
	}

	return event
}
```

**Step 3: Run tests**

Run: `cd src/asya-gateway && go test ./internal/a2a/ -v -run TestMessage -count=1 && go test ./internal/a2a/ -v -run TestTaskTo -count=1`
Expected: PASS

**Step 4: Commit**

```bash
git add src/asya-gateway/internal/a2a/translator.go src/asya-gateway/internal/a2a/translator_test.go
git commit -m "feat(gateway): add A2A message translation layer"
```

---

### Task 5: A2A Handler - POST /a2a/ (message/send)

**Files:**
- Create: `src/asya-gateway/internal/a2a/handler.go`
- Create: `src/asya-gateway/internal/a2a/handler_test.go`

**Step 1: Write handler test for message/send**

```go
package a2a

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandler_MessageSend(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{
		Tools: []config.Tool{
			{
				Name:        "echo",
				Description: "Echo tool",
				Route:       config.RouteSpec{Actors: []string{"echo-actor"}},
			},
		},
	}
	h := NewHandler(store, nil, cfg)

	reqBody := types.A2AJSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "message/send",
		Params: map[string]any{
			"message": map[string]any{
				"role": "user",
				"parts": []any{
					map[string]any{"type": "data", "data": map[string]any{"input": "hello"}},
				},
			},
			"skill": "echo",
		},
	}

	body, _ := json.Marshal(reqBody)
	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200, body: %s", rr.Code, rr.Body.String())
	}

	var resp types.A2AJSONRPCResponse
	if err := json.NewDecoder(rr.Body).Decode(&resp); err != nil {
		t.Fatalf("decode error: %v", err)
	}

	if resp.Error != nil {
		t.Fatalf("unexpected error: %+v", resp.Error)
	}

	// Result should be an A2A Task
	resultBytes, _ := json.Marshal(resp.Result)
	var a2aTask types.A2ATask
	if err := json.Unmarshal(resultBytes, &a2aTask); err != nil {
		t.Fatalf("failed to decode A2ATask from result: %v", err)
	}

	if a2aTask.ID == "" {
		t.Error("Task ID should not be empty")
	}
	if a2aTask.Status.State != types.A2AStateSubmitted {
		t.Errorf("State = %s, want submitted", a2aTask.Status.State)
	}
}

func TestHandler_MessageSend_SkillNotFound(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{Tools: []config.Tool{}}
	h := NewHandler(store, nil, cfg)

	reqBody := types.A2AJSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "message/send",
		Params: map[string]any{
			"message": map[string]any{
				"role":  "user",
				"parts": []any{map[string]any{"type": "text", "text": "hi"}},
			},
			"skill": "nonexistent",
		},
	}

	body, _ := json.Marshal(reqBody)
	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	var resp types.A2AJSONRPCResponse
	json.NewDecoder(rr.Body).Decode(&resp)

	if resp.Error == nil {
		t.Fatal("expected error for nonexistent skill")
	}
	if resp.Error.Code != types.A2AErrInvalidParams {
		t.Errorf("error code = %d, want %d", resp.Error.Code, types.A2AErrInvalidParams)
	}
}

func TestHandler_MethodNotFound(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{Tools: []config.Tool{}}
	h := NewHandler(store, nil, cfg)

	reqBody := types.A2AJSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "unknown/method",
	}

	body, _ := json.Marshal(reqBody)
	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	var resp types.A2AJSONRPCResponse
	json.NewDecoder(rr.Body).Decode(&resp)

	if resp.Error == nil || resp.Error.Code != types.A2AErrMethodNotFound {
		t.Errorf("expected method not found error")
	}
}

func TestHandler_InvalidJSON(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{Tools: []config.Tool{}}
	h := NewHandler(store, nil, cfg)

	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader([]byte("not json")))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	var resp types.A2AJSONRPCResponse
	json.NewDecoder(rr.Body).Decode(&resp)

	if resp.Error == nil || resp.Error.Code != types.A2AErrParseError {
		t.Error("expected parse error")
	}
}

func TestHandler_GetNotAllowed(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{Tools: []config.Tool{}}
	h := NewHandler(store, nil, cfg)

	req := httptest.NewRequest(http.MethodGet, "/a2a/", nil)
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("status = %d, want 405", rr.Code)
	}
}
```

**Step 2: Implement A2A handler**

Create `internal/a2a/handler.go`:

```go
package a2a

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Handler handles A2A JSON-RPC requests at POST /a2a/
type Handler struct {
	taskStore   taskstore.TaskStore
	queueClient queue.Client
	config      *config.Config
	toolIndex   map[string]*config.Tool // tool name -> tool def
}

// NewHandler creates a new A2A handler.
func NewHandler(store taskstore.TaskStore, queueClient queue.Client, cfg *config.Config) *Handler {
	idx := make(map[string]*config.Tool)
	if cfg != nil {
		for i := range cfg.Tools {
			idx[cfg.Tools[i].Name] = &cfg.Tools[i]
		}
	}
	return &Handler{
		taskStore:   store,
		queueClient: queueClient,
		config:      cfg,
		toolIndex:   idx,
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var rpcReq types.A2AJSONRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&rpcReq); err != nil {
		h.writeJSON(w, types.NewA2AError(nil, types.A2AErrParseError, "invalid JSON"))
		return
	}

	switch rpcReq.Method {
	case "message/send":
		h.handleMessageSend(w, r, rpcReq)
	case "message/stream":
		h.handleMessageStream(w, r, rpcReq)
	case "tasks/get":
		h.handleTasksGet(w, rpcReq)
	default:
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrMethodNotFound,
			fmt.Sprintf("method %q not found", rpcReq.Method)))
	}
}

func (h *Handler) handleMessageSend(w http.ResponseWriter, r *http.Request, rpcReq types.A2AJSONRPCRequest) {
	params, err := h.parseMessageParams(rpcReq)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams, err.Error()))
		return
	}

	// Resolve skill (tool)
	tool, ok := h.toolIndex[params.Skill]
	if !ok {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams,
			fmt.Sprintf("skill %q not found", params.Skill)))
		return
	}

	// Resolve route actors
	actors, err := tool.Route.GetActors(h.config.Routes)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInternalError,
			fmt.Sprintf("route error: %v", err)))
		return
	}

	// Translate A2A message to payload
	payload := MessageToPayload(params.Message)

	// Determine context_id
	contextID := params.ContextID
	if contextID == "" {
		contextID = uuid.New().String()
	}

	// Create task
	taskID := params.TaskID
	if taskID == "" {
		taskID = uuid.New().String()
	}

	var routeCurr string
	var routeNext []string
	if len(actors) > 0 {
		routeCurr = actors[0]
		routeNext = actors[1:]
	}

	opts := tool.GetOptions(h.config.Defaults)

	task := &types.Task{
		ID:        taskID,
		ContextID: contextID,
		Status:    types.TaskStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: routeCurr,
			Next: routeNext,
		},
		Payload:    payload,
		TimeoutSec: int(opts.Timeout.Seconds()),
	}

	if opts.Timeout > 0 {
		task.Deadline = time.Now().Add(opts.Timeout)
	}

	if err := h.taskStore.Create(task); err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInternalError,
			fmt.Sprintf("failed to create task: %v", err)))
		return
	}

	// Send to queue async
	go h.sendToQueue(task)

	// Return A2A Task response
	a2aTask := TaskToA2ATask(task)
	h.writeJSON(w, types.NewA2AResult(rpcReq.ID, a2aTask))
}

func (h *Handler) sendToQueue(task *types.Task) {
	_ = h.taskStore.Update(types.TaskUpdate{
		ID:        task.ID,
		Status:    types.TaskStatusRunning,
		Message:   "Sending task to first actor",
		Timestamp: time.Now(),
	})

	if h.queueClient == nil {
		slog.Warn("Queue client not configured, skipping task send", "id", task.ID)
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := h.queueClient.SendMessage(ctx, task); err != nil {
		slog.Error("Failed to send task to queue", "id", task.ID, "error", err)
		_ = h.taskStore.Update(types.TaskUpdate{
			ID:        task.ID,
			Status:    types.TaskStatusFailed,
			Error:     fmt.Sprintf("failed to send task: %v", err),
			Timestamp: time.Now(),
		})
	}
}

func (h *Handler) handleTasksGet(w http.ResponseWriter, rpcReq types.A2AJSONRPCRequest) {
	// Parse params to get task ID
	paramsBytes, err := json.Marshal(rpcReq.Params)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams, "invalid params"))
		return
	}
	var params struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(paramsBytes, &params); err != nil || params.ID == "" {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams, "missing task id"))
		return
	}

	task, err := h.taskStore.Get(params.ID)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrTaskNotFound,
			fmt.Sprintf("task %q not found", params.ID)))
		return
	}

	a2aTask := TaskToA2ATask(task)
	h.writeJSON(w, types.NewA2AResult(rpcReq.ID, a2aTask))
}

func (h *Handler) parseMessageParams(rpcReq types.A2AJSONRPCRequest) (*types.A2ASendMessageParams, error) {
	paramsBytes, err := json.Marshal(rpcReq.Params)
	if err != nil {
		return nil, fmt.Errorf("invalid params: %w", err)
	}

	var params types.A2ASendMessageParams
	if err := json.Unmarshal(paramsBytes, &params); err != nil {
		return nil, fmt.Errorf("invalid message params: %w", err)
	}

	if len(params.Message.Parts) == 0 {
		return nil, fmt.Errorf("message must have at least one part")
	}

	if params.Skill == "" {
		return nil, fmt.Errorf("skill is required")
	}

	return &params, nil
}

func (h *Handler) writeJSON(w http.ResponseWriter, resp *types.A2AJSONRPCResponse) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		slog.Error("Failed to encode A2A response", "error", err)
	}
}
```

**Important**: Add `"context"` import to the handler.go imports (used in `sendToQueue`).

**Step 3: Run tests**

Run: `cd src/asya-gateway && go test ./internal/a2a/ -v -run TestHandler -count=1`
Expected: PASS

**Step 4: Commit**

```bash
git add src/asya-gateway/internal/a2a/handler.go src/asya-gateway/internal/a2a/handler_test.go
git commit -m "feat(gateway): add A2A handler with message/send and tasks/get methods"
```

---

### Task 6: A2A Streaming - message/stream and tasks/subscribe

**Files:**
- Modify: `src/asya-gateway/internal/a2a/handler.go` (add streaming methods)
- Create: `src/asya-gateway/internal/a2a/streaming.go`
- Create: `src/asya-gateway/internal/a2a/streaming_test.go`

**Step 1: Write streaming tests**

Test `message/stream` and the REST `GET /a2a/tasks/{id}:subscribe` endpoint:

```go
package a2a

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandler_MessageStream(t *testing.T) {
	store := taskstore.NewStore()
	cfg := &config.Config{
		Tools: []config.Tool{
			{Name: "echo", Description: "Echo", Route: config.RouteSpec{Actors: []string{"echo-actor"}}},
		},
	}
	h := NewHandler(store, nil, cfg)

	reqBody := types.A2AJSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "message/stream",
		Params: map[string]any{
			"message": map[string]any{
				"role":  "user",
				"parts": []any{map[string]any{"type": "text", "text": "hi"}},
			},
			"skill": "echo",
		},
	}

	body, _ := json.Marshal(reqBody)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	req := httptest.NewRequest(http.MethodPost, "/a2a/", bytes.NewReader(body)).WithContext(ctx)
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	// Run handler in goroutine since streaming blocks
	done := make(chan struct{})
	go func() {
		h.ServeHTTP(rr, req)
		close(done)
	}()

	// Complete the task after a short delay
	time.Sleep(100 * time.Millisecond)

	// Find the task ID from store (there should be exactly 1 task)
	// The handler creates a task and starts streaming
	// We need to complete it to end the stream

	// Cancel context to stop streaming
	cancel()
	<-done

	// Check SSE headers
	ct := rr.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "text/event-stream") {
		t.Errorf("Content-Type = %s, want text/event-stream", ct)
	}

	// Parse SSE events
	scanner := bufio.NewScanner(rr.Body)
	eventCount := 0
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "data: ") {
			eventCount++
		}
	}

	if eventCount < 1 {
		t.Errorf("expected at least 1 SSE event, got %d", eventCount)
	}
}

func TestSubscribeHandler(t *testing.T) {
	store := taskstore.NewStore()
	task := &types.Task{
		ID:     "sub-test-1",
		Status: types.TaskStatusPending,
		Route:  types.Route{Prev: []string{}, Curr: "a1", Next: []string{}},
	}
	store.Create(task)

	sh := NewSubscribeHandler(store)

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/sub-test-1:subscribe", nil).WithContext(ctx)
	rr := httptest.NewRecorder()

	// Complete task after a delay
	go func() {
		time.Sleep(100 * time.Millisecond)
		store.Update(types.TaskUpdate{
			ID:        "sub-test-1",
			Status:    types.TaskStatusSucceeded,
			Result:    map[string]any{"ok": true},
			Timestamp: time.Now(),
		})
	}()

	sh.ServeHTTP(rr, req)

	ct := rr.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "text/event-stream") {
		t.Errorf("Content-Type = %s, want text/event-stream", ct)
	}

	// Should have received events
	body := rr.Body.String()
	if !strings.Contains(body, "event:") {
		t.Error("expected SSE events in response")
	}
}

func TestSubscribeHandler_TaskNotFound(t *testing.T) {
	store := taskstore.NewStore()
	sh := NewSubscribeHandler(store)

	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/nonexistent:subscribe", nil)
	rr := httptest.NewRecorder()

	sh.ServeHTTP(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rr.Code)
	}
}
```

**Step 2: Implement streaming handler**

Create `internal/a2a/streaming.go`:

```go
package a2a

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"regexp"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

var subscribePathRegex = regexp.MustCompile(`^/a2a/tasks/([^/]+):subscribe$`)

// SubscribeHandler handles GET /a2a/tasks/{id}:subscribe (SSE)
type SubscribeHandler struct {
	taskStore taskstore.TaskStore
}

// NewSubscribeHandler creates a new subscribe handler.
func NewSubscribeHandler(store taskstore.TaskStore) *SubscribeHandler {
	return &SubscribeHandler{taskStore: store}
}

func (sh *SubscribeHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := subscribePathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

	// Verify task exists
	_, err := sh.taskStore.Get(taskID)
	if err != nil {
		http.Error(w, "Task not found", http.StatusNotFound)
		return
	}

	streamTaskUpdates(w, r, sh.taskStore, taskID)
}

// handleMessageStream implements the message/stream JSON-RPC method.
// It creates a task and immediately starts streaming updates via SSE.
func (h *Handler) handleMessageStream(w http.ResponseWriter, r *http.Request, rpcReq types.A2AJSONRPCRequest) {
	params, err := h.parseMessageParams(rpcReq)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams, err.Error()))
		return
	}

	tool, ok := h.toolIndex[params.Skill]
	if !ok {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInvalidParams,
			fmt.Sprintf("skill %q not found", params.Skill)))
		return
	}

	actors, err := tool.Route.GetActors(h.config.Routes)
	if err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInternalError, err.Error()))
		return
	}

	payload := MessageToPayload(params.Message)
	contextID := params.ContextID
	if contextID == "" {
		contextID = "ctx-" + fmt.Sprintf("%d", time.Now().UnixNano())
	}

	taskID := params.TaskID
	if taskID == "" {
		taskID = fmt.Sprintf("a2a-%d", time.Now().UnixNano())
	}

	var routeCurr string
	var routeNext []string
	if len(actors) > 0 {
		routeCurr = actors[0]
		routeNext = actors[1:]
	}

	opts := tool.GetOptions(h.config.Defaults)
	task := &types.Task{
		ID:        taskID,
		ContextID: contextID,
		Route:     types.Route{Prev: []string{}, Curr: routeCurr, Next: routeNext},
		Payload:   payload,
		TimeoutSec: int(opts.Timeout.Seconds()),
	}

	if opts.Timeout > 0 {
		task.Deadline = time.Now().Add(opts.Timeout)
	}

	if err := h.taskStore.Create(task); err != nil {
		h.writeJSON(w, types.NewA2AError(rpcReq.ID, types.A2AErrInternalError, err.Error()))
		return
	}

	go h.sendToQueue(task)

	// Stream updates as SSE
	streamTaskUpdates(w, r, h.taskStore, taskID)
}

// streamTaskUpdates streams A2A-formatted SSE events for a task.
// Shared between message/stream and tasks/subscribe.
func streamTaskUpdates(w http.ResponseWriter, r *http.Request, store taskstore.TaskStore, taskID string) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming not supported", http.StatusInternalServerError)
		return
	}

	// Send historical updates
	historicalUpdates, err := store.GetUpdates(taskID, nil)
	if err != nil {
		slog.Warn("Failed to get historical updates", "error", err, "task_id", taskID)
	} else {
		for _, update := range historicalUpdates {
			writeSSEEvent(w, flusher, update)
		}
	}

	// Subscribe to live updates
	updateChan := store.Subscribe(taskID)
	defer store.Unsubscribe(taskID, updateChan)

	keepaliveTicker := time.NewTicker(15 * time.Second)
	defer keepaliveTicker.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-keepaliveTicker.C:
			_, _ = fmt.Fprintf(w, ": keepalive\n\n")
			flusher.Flush()
		case update := <-updateChan:
			writeSSEEvent(w, flusher, update)
			if isFinalA2AStatus(update.Status) {
				flusher.Flush()
				return
			}
		}
	}
}

func writeSSEEvent(w http.ResponseWriter, flusher http.Flusher, update types.TaskUpdate) {
	a2aEvent := TaskUpdateToSSEEvents(update)

	eventType := "status_update"
	data, err := json.Marshal(a2aEvent)
	if err != nil {
		slog.Error("Failed to marshal A2A event", "error", err)
		return
	}

	// Security: Safe to use Fprintf here - data is pre-encoded JSON for SSE streaming.
	_, _ = fmt.Fprintf(w, "event: %s\n", eventType)
	_, _ = fmt.Fprintf(w, "data: %s\n\n", data)
	flusher.Flush()
}

func isFinalA2AStatus(status types.TaskStatus) bool {
	return status == types.TaskStatusSucceeded || status == types.TaskStatusFailed
}
```

**Step 3: Run tests**

Run: `cd src/asya-gateway && go test ./internal/a2a/ -v -run TestHandler_MessageStream -count=1 && go test ./internal/a2a/ -v -run TestSubscribe -count=1`
Expected: PASS

**Step 4: Commit**

```bash
git add src/asya-gateway/internal/a2a/streaming.go src/asya-gateway/internal/a2a/streaming_test.go src/asya-gateway/internal/a2a/handler.go
git commit -m "feat(gateway): add A2A streaming (message/stream + tasks/subscribe SSE)"
```

---

### Task 7: A2A REST Task Status Endpoint

**Files:**
- Create: `src/asya-gateway/internal/a2a/task_handler.go`
- Create: `src/asya-gateway/internal/a2a/task_handler_test.go`

This adds `GET /a2a/tasks/{id}` as a REST endpoint (in addition to the JSON-RPC `tasks/get` method).

**Step 1: Write tests**

```go
package a2a

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestTaskStatusHandler(t *testing.T) {
	store := taskstore.NewStore()
	task := &types.Task{
		ID:        "rest-task-1",
		ContextID: "ctx-1",
		Status:    types.TaskStatusPending,
		Route:     types.Route{Prev: []string{}, Curr: "a1", Next: []string{"a2"}},
	}
	store.Create(task)

	// Update to succeeded
	store.Update(types.TaskUpdate{
		ID:        "rest-task-1",
		Status:    types.TaskStatusSucceeded,
		Result:    map[string]any{"output": "done"},
		Timestamp: time.Now(),
	})

	h := NewTaskStatusHandler(store)
	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/rest-task-1", nil)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}

	var a2aTask types.A2ATask
	json.NewDecoder(rr.Body).Decode(&a2aTask)

	if a2aTask.ID != "rest-task-1" {
		t.Errorf("ID = %s, want rest-task-1", a2aTask.ID)
	}
	if a2aTask.Status.State != types.A2AStateCompleted {
		t.Errorf("State = %s, want completed", a2aTask.Status.State)
	}
	if a2aTask.ContextID != "ctx-1" {
		t.Errorf("ContextID = %s, want ctx-1", a2aTask.ContextID)
	}
}

func TestTaskStatusHandler_NotFound(t *testing.T) {
	store := taskstore.NewStore()
	h := NewTaskStatusHandler(store)
	req := httptest.NewRequest(http.MethodGet, "/a2a/tasks/nonexistent", nil)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rr.Code)
	}
}
```

**Step 2: Implement task status handler**

Create `internal/a2a/task_handler.go`:

```go
package a2a

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"regexp"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
)

var taskPathRegex = regexp.MustCompile(`^/a2a/tasks/([^/:]+)$`)

// TaskStatusHandler handles GET /a2a/tasks/{id}
type TaskStatusHandler struct {
	taskStore taskstore.TaskStore
}

// NewTaskStatusHandler creates a new REST task status handler.
func NewTaskStatusHandler(store taskstore.TaskStore) *TaskStatusHandler {
	return &TaskStatusHandler{taskStore: store}
}

func (h *TaskStatusHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	matches := taskPathRegex.FindStringSubmatch(r.URL.Path)
	if matches == nil {
		http.Error(w, "Invalid path", http.StatusBadRequest)
		return
	}
	taskID := matches[1]

	task, err := h.taskStore.Get(taskID)
	if err != nil {
		http.Error(w, "Task not found", http.StatusNotFound)
		return
	}

	a2aTask := TaskToA2ATask(task)

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(a2aTask); err != nil {
		slog.Error("Failed to encode A2A task", "error", err)
	}
}
```

**Step 3: Run tests**

Run: `cd src/asya-gateway && go test ./internal/a2a/ -v -run TestTaskStatus -count=1`
Expected: PASS

**Step 4: Commit**

```bash
git add src/asya-gateway/internal/a2a/task_handler.go src/asya-gateway/internal/a2a/task_handler_test.go
git commit -m "feat(gateway): add REST GET /a2a/tasks/{id} endpoint"
```

---

### Task 8: Wire A2A Routes in main.go

**Files:**
- Modify: `src/asya-gateway/cmd/gateway/main.go`

**Step 1: Add A2A route registration**

After the existing route registration block (around line 168), add:

```go
// A2A protocol endpoints
a2aHandler := a2a.NewHandler(taskStore, queueClient, toolConfig)
a2aTaskStatusHandler := a2a.NewTaskStatusHandler(taskStore)
a2aSubscribeHandler := a2a.NewSubscribeHandler(taskStore)

// Agent Card discovery
if toolConfig != nil {
    agentCardHandler := a2a.NewAgentCardHandler(toolConfig)
    mux.Handle("/.well-known/a2a/agent-card", agentCardHandler)
}

// A2A JSON-RPC endpoint (message/send, message/stream, tasks/get)
mux.Handle("/a2a/", a2aHandler)

// A2A REST endpoints
mux.HandleFunc("/a2a/tasks/", func(w http.ResponseWriter, r *http.Request) {
    if strings.HasSuffix(r.URL.Path, ":subscribe") {
        a2aSubscribeHandler.ServeHTTP(w, r)
    } else {
        a2aTaskStatusHandler.ServeHTTP(w, r)
    }
})
```

Add `"github.com/deliveryhero/asya/asya-gateway/internal/a2a"` to imports.

Add startup log lines:

```go
slog.Info("A2A endpoint: POST /a2a/ (JSON-RPC: message/send, message/stream, tasks/get)")
slog.Info("A2A Agent Card: GET /.well-known/a2a/agent-card")
slog.Info("A2A task status: GET /a2a/tasks/{id}")
slog.Info("A2A subscribe: GET /a2a/tasks/{id}:subscribe (SSE)")
```

**Step 2: Run unit tests for all gateway packages**

Run: `cd src/asya-gateway && go test ./... -count=1`
Expected: PASS

**Step 3: Run lint**

Run: `make -C src/asya-gateway lint` or `make lint`
Expected: PASS (fix any issues)

**Step 4: Commit**

```bash
git add src/asya-gateway/cmd/gateway/main.go
git commit -m "feat(gateway): wire A2A endpoints in main.go (agent card, JSON-RPC, task status, subscribe)"
```

---

### Task 9: Final Verification and Cleanup

**Step 1: Run full unit test suite**

Run: `make -C src/asya-gateway test-unit`
Expected: PASS

**Step 2: Run full linting**

Run: `make lint`
Expected: PASS

**Step 3: Verify build**

Run: `make -C src/asya-gateway build` or `cd src/asya-gateway && go build ./...`
Expected: PASS

**Step 4: Final commit with any fixes**

If any fixes were needed, commit them:
```bash
git commit -m "fix(gateway): address lint and test issues in A2A implementation"
```

**Step 5: Push and create PR**

```bash
git push -u origin 1c0d/phase1-a2a-core
```

Create PR targeting `main` with:
- Title: "feat(gateway): A2A protocol compliance - core endpoints"
- Body summarizing all 8 tasks implemented
