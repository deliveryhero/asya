package messages

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestRoute_GetCurrentActor(t *testing.T) {
	tests := []struct {
		name     string
		route    Route
		expected string
	}{
		{
			name:     "first actor",
			route:    Route{Prev: []string{}, Curr: "actor1", Next: []string{"actor2", "actor3"}},
			expected: "actor1",
		},
		{
			name:     "middle actor",
			route:    Route{Prev: []string{"actor1"}, Curr: "actor2", Next: []string{"actor3"}},
			expected: "actor2",
		},
		{
			name:     "last actor",
			route:    Route{Prev: []string{"actor1", "actor2"}, Curr: "actor3", Next: []string{}},
			expected: "actor3",
		},
		{
			name:     "end of route (curr empty)",
			route:    Route{Prev: []string{"actor1", "actor2"}, Curr: "", Next: []string{}},
			expected: "",
		},
		{
			name:     "empty route",
			route:    Route{Prev: []string{}, Curr: "", Next: []string{}},
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.route.GetCurrentActor()
			if result != tt.expected {
				t.Errorf("GetCurrentActor() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestRoute_GetNextActor(t *testing.T) {
	tests := []struct {
		name     string
		route    Route
		expected string
	}{
		{
			name:     "has next actor",
			route:    Route{Prev: []string{}, Curr: "actor1", Next: []string{"actor2", "actor3"}},
			expected: "actor2",
		},
		{
			name:     "last actor",
			route:    Route{Prev: []string{"actor1", "actor2"}, Curr: "actor3", Next: []string{}},
			expected: "",
		},
		{
			name:     "empty route",
			route:    Route{Prev: []string{}, Curr: "", Next: []string{}},
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.route.GetNextActor()
			if result != tt.expected {
				t.Errorf("GetNextActor() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestRoute_HasNextActor(t *testing.T) {
	tests := []struct {
		name     string
		route    Route
		expected bool
	}{
		{
			name:     "has next",
			route:    Route{Prev: []string{}, Curr: "actor1", Next: []string{"actor2", "actor3"}},
			expected: true,
		},
		{
			name:     "at last actor",
			route:    Route{Prev: []string{"actor1", "actor2"}, Curr: "actor3", Next: []string{}},
			expected: false,
		},
		{
			name:     "end of route",
			route:    Route{Prev: []string{"actor1", "actor2"}, Curr: "", Next: []string{}},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.route.HasNextActor()
			if result != tt.expected {
				t.Errorf("HasNextActor() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestRoute_IncrementCurrent(t *testing.T) {
	route := Route{Prev: []string{}, Curr: "actor1", Next: []string{"actor2", "actor3"}}
	newRoute := route.IncrementCurrent()

	if newRoute.Curr != "actor2" {
		t.Errorf("IncrementCurrent() curr = %v, want actor2", newRoute.Curr)
	}

	if len(newRoute.Prev) != 1 || newRoute.Prev[0] != "actor1" {
		t.Errorf("IncrementCurrent() prev = %v, want [actor1]", newRoute.Prev)
	}

	if len(newRoute.Next) != 1 || newRoute.Next[0] != "actor3" {
		t.Errorf("IncrementCurrent() next = %v, want [actor3]", newRoute.Next)
	}

	// Verify original unchanged
	if route.Curr != "actor1" {
		t.Errorf("Original route modified, curr = %v, want actor1", route.Curr)
	}
}

func TestRoute_IncrementCurrent_LastActor(t *testing.T) {
	route := Route{Prev: []string{"actor1", "actor2"}, Curr: "actor3", Next: []string{}}
	newRoute := route.IncrementCurrent()

	if newRoute.Curr != "" {
		t.Errorf("IncrementCurrent() at last actor curr = %v, want empty string", newRoute.Curr)
	}

	if len(newRoute.Prev) != 3 {
		t.Errorf("IncrementCurrent() prev len = %d, want 3", len(newRoute.Prev))
	}

	if newRoute.Prev[2] != "actor3" {
		t.Errorf("IncrementCurrent() prev[2] = %v, want actor3", newRoute.Prev[2])
	}
}

func TestMessage_JSONSerialization(t *testing.T) {
	original := Message{
		Route: Route{
			Prev: []string{"actor1"},
			Curr: "actor2",
			Next: []string{"actor3"},
		},
		Payload: json.RawMessage(`{"data": "test"}`),
	}

	// Marshal
	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	// Unmarshal
	var decoded Message
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// Verify
	if decoded.Route.Curr != original.Route.Curr {
		t.Errorf("Route.Curr = %v, want %v", decoded.Route.Curr, original.Route.Curr)
	}

	if len(decoded.Route.Prev) != len(original.Route.Prev) {
		t.Errorf("Route.Prev length = %v, want %v", len(decoded.Route.Prev), len(original.Route.Prev))
	}

	if len(decoded.Route.Next) != len(original.Route.Next) {
		t.Errorf("Route.Next length = %v, want %v", len(decoded.Route.Next), len(original.Route.Next))
	}

	// Compare JSON payload (ignoring whitespace)
	var origPayload, decodedPayload map[string]interface{}
	_ = json.Unmarshal(original.Payload, &origPayload)
	_ = json.Unmarshal(decoded.Payload, &decodedPayload)

	origData, _ := origPayload["data"].(string)
	decodedData, _ := decodedPayload["data"].(string)

	if decodedData != origData {
		t.Errorf("Payload data = %v, want %v", decodedData, origData)
	}
}

func TestMessage_ParentID_Serialization(t *testing.T) {
	tests := []struct {
		name     string
		msg      Message
		wantJSON string
	}{
		{
			name: "message without parent_id",
			msg: Message{
				ID: "abc-123",
				Route: Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
				Payload: json.RawMessage(`{"data":"test"}`),
			},
			wantJSON: `{"id":"abc-123","route":{"prev":[],"curr":"actor1","next":[]},"payload":{"data":"test"}}`,
		},
		{
			name: "fanout child with parent_id",
			msg: Message{
				ID:       "abc-123-1",
				ParentID: stringPtr("abc-123"),
				Route: Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
				Payload: json.RawMessage(`{"data":"test"}`),
			},
			wantJSON: `{"id":"abc-123-1","parent_id":"abc-123","route":{"prev":[],"curr":"actor1","next":[]},"payload":{"data":"test"}}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, err := json.Marshal(tt.msg)
			if err != nil {
				t.Fatalf("Failed to marshal: %v", err)
			}

			// Verify JSON contains expected fields
			var decoded map[string]interface{}
			if err := json.Unmarshal(data, &decoded); err != nil {
				t.Fatalf("Failed to unmarshal to map: %v", err)
			}

			if tt.msg.ParentID == nil {
				if _, exists := decoded["parent_id"]; exists {
					t.Errorf("parent_id should be omitted when nil, but found in JSON")
				}
			} else {
				parentID, exists := decoded["parent_id"].(string)
				if !exists {
					t.Errorf("parent_id should exist in JSON")
				} else if parentID != *tt.msg.ParentID {
					t.Errorf("parent_id = %q, want %q", parentID, *tt.msg.ParentID)
				}
			}

			// Verify round-trip
			var roundtrip Message
			if err := json.Unmarshal(data, &roundtrip); err != nil {
				t.Fatalf("Failed to unmarshal: %v", err)
			}

			if roundtrip.ID != tt.msg.ID {
				t.Errorf("ID = %q, want %q", roundtrip.ID, tt.msg.ID)
			}

			if (roundtrip.ParentID == nil) != (tt.msg.ParentID == nil) {
				t.Errorf("ParentID nil mismatch: got %v, want %v", roundtrip.ParentID == nil, tt.msg.ParentID == nil)
			} else if roundtrip.ParentID != nil && *roundtrip.ParentID != *tt.msg.ParentID {
				t.Errorf("ParentID = %q, want %q", *roundtrip.ParentID, *tt.msg.ParentID)
			}
		})
	}
}

func stringPtr(s string) *string {
	return &s
}

func TestNewDefaultStatus(t *testing.T) {
	status := NewDefaultStatus("my-actor")

	if status.Phase != PhasePending {
		t.Errorf("Phase = %q, want %q", status.Phase, PhasePending)
	}
	if status.Actor != "my-actor" {
		t.Errorf("Actor = %q, want %q", status.Actor, "my-actor")
	}
	if status.Attempt != 1 {
		t.Errorf("Attempt = %d, want 1", status.Attempt)
	}
	if status.MaxAttempts != 1 {
		t.Errorf("MaxAttempts = %d, want 1", status.MaxAttempts)
	}
	if status.CreatedAt == "" {
		t.Error("CreatedAt should not be empty")
	}
	if status.UpdatedAt == "" {
		t.Error("UpdatedAt should not be empty")
	}
	if status.Reason != "" {
		t.Errorf("Reason should be empty, got %q", status.Reason)
	}
	if status.Error != nil {
		t.Error("Error should be nil")
	}
}

func TestStatus_JSONSerialization(t *testing.T) {
	status := &Status{
		Phase:       PhaseProcessing,
		Reason:      "test-reason",
		Actor:       "test-actor",
		Attempt:     2,
		MaxAttempts: 3,
		CreatedAt:   "2025-01-01T00:00:00Z",
		UpdatedAt:   "2025-01-01T00:01:00Z",
		Error: &StatusError{
			Message:   "something went wrong",
			Type:      "ValueError",
			Traceback: "line 42",
		},
	}

	data, err := json.Marshal(status)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	var decoded Status
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if decoded.Phase != status.Phase {
		t.Errorf("Phase = %q, want %q", decoded.Phase, status.Phase)
	}
	if decoded.Reason != status.Reason {
		t.Errorf("Reason = %q, want %q", decoded.Reason, status.Reason)
	}
	if decoded.Actor != status.Actor {
		t.Errorf("Actor = %q, want %q", decoded.Actor, status.Actor)
	}
	if decoded.Attempt != status.Attempt {
		t.Errorf("Attempt = %d, want %d", decoded.Attempt, status.Attempt)
	}
	if decoded.MaxAttempts != status.MaxAttempts {
		t.Errorf("MaxAttempts = %d, want %d", decoded.MaxAttempts, status.MaxAttempts)
	}
	if decoded.CreatedAt != status.CreatedAt {
		t.Errorf("CreatedAt = %q, want %q", decoded.CreatedAt, status.CreatedAt)
	}
	if decoded.UpdatedAt != status.UpdatedAt {
		t.Errorf("UpdatedAt = %q, want %q", decoded.UpdatedAt, status.UpdatedAt)
	}
	if decoded.Error == nil {
		t.Fatal("Error should not be nil")
	}
	if decoded.Error.Message != "something went wrong" {
		t.Errorf("Error.Message = %q, want %q", decoded.Error.Message, "something went wrong")
	}
	if decoded.Error.Type != "ValueError" {
		t.Errorf("Error.Type = %q, want %q", decoded.Error.Type, "ValueError")
	}
}

func TestStatus_JSONSerialization_OmitsEmptyFields(t *testing.T) {
	status := &Status{
		Phase:     PhasePending,
		Actor:     "actor1",
		Attempt:   1,
		CreatedAt: "2025-01-01T00:00:00Z",
		UpdatedAt: "2025-01-01T00:00:00Z",
	}

	data, err := json.Marshal(status)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	var decoded map[string]interface{}
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal to map: %v", err)
	}

	if _, exists := decoded["reason"]; exists {
		t.Error("reason should be omitted when empty")
	}
	if _, exists := decoded["error"]; exists {
		t.Error("error should be omitted when nil")
	}
}

func TestMessage_WithStatus_Serialization(t *testing.T) {
	msg := Message{
		ID: "test-123",
		Route: Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Payload: json.RawMessage(`{"data":"test"}`),
		Status: &Status{
			Phase:       PhasePending,
			Actor:       "actor1",
			Attempt:     1,
			MaxAttempts: 1,
			CreatedAt:   "2025-01-01T00:00:00Z",
			UpdatedAt:   "2025-01-01T00:00:00Z",
		},
	}

	data, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	var decoded Message
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if decoded.Status == nil {
		t.Fatal("Status should not be nil after round-trip")
	}
	if decoded.Status.Phase != PhasePending {
		t.Errorf("Status.Phase = %q, want %q", decoded.Status.Phase, PhasePending)
	}
	if decoded.Status.Actor != "actor1" {
		t.Errorf("Status.Actor = %q, want %q", decoded.Status.Actor, "actor1")
	}
}

func TestMessage_WithoutStatus_BackwardCompat(t *testing.T) {
	rawJSON := `{"id":"test-123","route":{"prev":[],"curr":"a","next":["b"]},"payload":{"data":"test"}}`

	var msg Message
	if err := json.Unmarshal([]byte(rawJSON), &msg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if msg.Status != nil {
		t.Error("Status should be nil for messages without status field")
	}
	if msg.ID != "test-123" {
		t.Errorf("ID = %q, want %q", msg.ID, "test-123")
	}
	if msg.Route.Curr != "a" {
		t.Errorf("Route.Curr = %q, want %q", msg.Route.Curr, "a")
	}
	if len(msg.Route.Next) != 1 {
		t.Errorf("Route.Next length = %d, want 1", len(msg.Route.Next))
	}

	// Re-marshal should omit status
	data, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Failed to re-marshal: %v", err)
	}

	var decoded map[string]interface{}
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal to map: %v", err)
	}

	if _, exists := decoded["status"]; exists {
		t.Error("status should be omitted when nil")
	}
}

// TestMessage_RawMessagePreservesPayloadBytes verifies that json.RawMessage
// keeps payload as raw bytes without parsing into Go objects.
// This is a regression test for the optimization in asya-866.
func TestMessage_RawMessagePreservesPayloadBytes(t *testing.T) {
	// Large nested payload that would be expensive to parse
	rawJSON := `{
		"id": "test-123",
		"route": {"prev": [], "curr": "a", "next": ["b"]},
		"payload": {"deeply": {"nested": {"structure": {"with": {"many": {"levels": "value"}}}}}, "array": [1,2,3,4,5]}
	}`

	var msg Message
	if err := json.Unmarshal([]byte(rawJSON), &msg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// Verify payload is stored as raw bytes, not parsed
	expectedPayload := `{"deeply": {"nested": {"structure": {"with": {"many": {"levels": "value"}}}}}, "array": [1,2,3,4,5]}`

	// Compare after normalizing whitespace using reflect.DeepEqual
	var expected, actual interface{}
	if err := json.Unmarshal([]byte(expectedPayload), &expected); err != nil {
		t.Fatalf("Failed to parse expected: %v", err)
	}
	if err := json.Unmarshal(msg.Payload, &actual); err != nil {
		t.Fatalf("Failed to parse actual: %v", err)
	}

	if !reflect.DeepEqual(expected, actual) {
		expectedBytes, _ := json.Marshal(expected)
		actualBytes, _ := json.Marshal(actual)
		t.Errorf("Payload mismatch:\ngot:  %s\nwant: %s", string(actualBytes), string(expectedBytes))
	}

	// Verify that re-marshaling preserves the structure (semantically, not byte-for-byte)
	remarshaled, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Failed to re-marshal: %v", err)
	}

	var roundtrip Message
	if err := json.Unmarshal(remarshaled, &roundtrip); err != nil {
		t.Fatalf("Failed to unmarshal roundtrip: %v", err)
	}

	// Payload should be semantically equivalent after roundtrip
	// (whitespace may differ due to JSON normalization, but content must match)
	var originalPayload, roundtripPayload interface{}
	if err := json.Unmarshal(msg.Payload, &originalPayload); err != nil {
		t.Fatalf("Failed to parse original payload: %v", err)
	}
	if err := json.Unmarshal(roundtrip.Payload, &roundtripPayload); err != nil {
		t.Fatalf("Failed to parse roundtrip payload: %v", err)
	}

	if !reflect.DeepEqual(originalPayload, roundtripPayload) {
		origBytes, _ := json.Marshal(originalPayload)
		rtBytes, _ := json.Marshal(roundtripPayload)
		t.Errorf("Payload not preserved after roundtrip:\ngot:  %s\nwant: %s", string(rtBytes), string(origBytes))
	}
}

// TestMessage_RawMessageForwardsUnchanged verifies that payload bytes
// can be extracted and forwarded without modification.
func TestMessage_RawMessageForwardsUnchanged(t *testing.T) {
	// Simulate receiving a message from queue
	queueMessage := []byte(`{"id":"msg-1","route":{"prev":[],"curr":"actor1","next":[]},"payload":{"key":"value","number":42}}`)

	var msg Message
	if err := json.Unmarshal(queueMessage, &msg); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// The payload should be extractable as raw bytes
	payloadBytes := []byte(msg.Payload)

	// Verify it's valid JSON that can be parsed independently
	var payload map[string]interface{}
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		t.Fatalf("Payload is not valid JSON: %v", err)
	}

	expected := map[string]interface{}{
		"key":    "value",
		"number": float64(42),
	}
	if !reflect.DeepEqual(payload, expected) {
		t.Errorf("payload mismatch:\ngot:  %v\nwant: %v", payload, expected)
	}
}
