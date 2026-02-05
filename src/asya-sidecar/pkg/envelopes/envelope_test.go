package envelopes

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
			route:    Route{Actors: []string{"actor1", "actor2", "actor3"}, Current: 0},
			expected: "actor1",
		},
		{
			name:     "middle actor",
			route:    Route{Actors: []string{"actor1", "actor2", "actor3"}, Current: 1},
			expected: "actor2",
		},
		{
			name:     "last actor",
			route:    Route{Actors: []string{"actor1", "actor2", "actor3"}, Current: 2},
			expected: "actor3",
		},
		{
			name:     "out of bounds",
			route:    Route{Actors: []string{"actor1", "actor2"}, Current: 5},
			expected: "",
		},
		{
			name:     "negative index",
			route:    Route{Actors: []string{"actor1", "actor2"}, Current: -1},
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
			route:    Route{Actors: []string{"actor1", "actor2", "actor3"}, Current: 0},
			expected: "actor2",
		},
		{
			name:     "last actor",
			route:    Route{Actors: []string{"actor1", "actor2", "actor3"}, Current: 2},
			expected: "",
		},
		{
			name:     "empty actors",
			route:    Route{Actors: []string{}, Current: 0},
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
			route:    Route{Actors: []string{"actor1", "actor2", "actor3"}, Current: 0},
			expected: true,
		},
		{
			name:     "at last actor",
			route:    Route{Actors: []string{"actor1", "actor2", "actor3"}, Current: 2},
			expected: false,
		},
		{
			name:     "beyond last actor",
			route:    Route{Actors: []string{"actor1", "actor2"}, Current: 5},
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
	route := Route{Actors: []string{"actor1", "actor2", "actor3"}, Current: 0}
	newRoute := route.IncrementCurrent()

	if newRoute.Current != 1 {
		t.Errorf("IncrementCurrent() current = %v, want 1", newRoute.Current)
	}

	// Verify original unchanged
	if route.Current != 0 {
		t.Errorf("Original route modified, current = %v, want 0", route.Current)
	}
}

func TestEnvelope_JSONSerialization(t *testing.T) {
	original := Envelope{
		Route: Route{
			Actors:  []string{"actor1", "actor2", "actor3"},
			Current: 1,
		},
		Payload: json.RawMessage(`{"data": "test"}`),
	}

	// Marshal
	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	// Unmarshal
	var decoded Envelope
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// Verify
	if decoded.Route.Current != original.Route.Current {
		t.Errorf("Route.Current = %v, want %v", decoded.Route.Current, original.Route.Current)
	}

	if len(decoded.Route.Actors) != len(original.Route.Actors) {
		t.Errorf("Route.Actors length = %v, want %v", len(decoded.Route.Actors), len(original.Route.Actors))
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

func TestEnvelope_ParentID_Serialization(t *testing.T) {
	tests := []struct {
		name     string
		envelope Envelope
		wantJSON string
	}{
		{
			name: "envelope without parent_id",
			envelope: Envelope{
				ID: "abc-123",
				Route: Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
				Payload: json.RawMessage(`{"data":"test"}`),
			},
			wantJSON: `{"id":"abc-123","route":{"actors":["actor1"],"current":0},"payload":{"data":"test"}}`,
		},
		{
			name: "fanout child with parent_id",
			envelope: Envelope{
				ID:       "abc-123-1",
				ParentID: stringPtr("abc-123"),
				Route: Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
				Payload: json.RawMessage(`{"data":"test"}`),
			},
			wantJSON: `{"id":"abc-123-1","parent_id":"abc-123","route":{"actors":["actor1"],"current":0},"payload":{"data":"test"}}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, err := json.Marshal(tt.envelope)
			if err != nil {
				t.Fatalf("Failed to marshal: %v", err)
			}

			// Verify JSON contains expected fields
			var decoded map[string]interface{}
			if err := json.Unmarshal(data, &decoded); err != nil {
				t.Fatalf("Failed to unmarshal to map: %v", err)
			}

			if tt.envelope.ParentID == nil {
				if _, exists := decoded["parent_id"]; exists {
					t.Errorf("parent_id should be omitted when nil, but found in JSON")
				}
			} else {
				parentID, exists := decoded["parent_id"].(string)
				if !exists {
					t.Errorf("parent_id should exist in JSON")
				} else if parentID != *tt.envelope.ParentID {
					t.Errorf("parent_id = %q, want %q", parentID, *tt.envelope.ParentID)
				}
			}

			// Verify round-trip
			var roundtrip Envelope
			if err := json.Unmarshal(data, &roundtrip); err != nil {
				t.Fatalf("Failed to unmarshal: %v", err)
			}

			if roundtrip.ID != tt.envelope.ID {
				t.Errorf("ID = %q, want %q", roundtrip.ID, tt.envelope.ID)
			}

			if (roundtrip.ParentID == nil) != (tt.envelope.ParentID == nil) {
				t.Errorf("ParentID nil mismatch: got %v, want %v", roundtrip.ParentID == nil, tt.envelope.ParentID == nil)
			} else if roundtrip.ParentID != nil && *roundtrip.ParentID != *tt.envelope.ParentID {
				t.Errorf("ParentID = %q, want %q", *roundtrip.ParentID, *tt.envelope.ParentID)
			}
		})
	}
}

func stringPtr(s string) *string {
	return &s
}

// TestEnvelope_RawMessagePreservesPayloadBytes verifies that json.RawMessage
// keeps payload as raw bytes without parsing into Go objects.
// This is a regression test for the optimization in asya-866.
func TestEnvelope_RawMessagePreservesPayloadBytes(t *testing.T) {
	// Large nested payload that would be expensive to parse
	rawJSON := `{
		"id": "test-123",
		"route": {"actors": ["a", "b"], "current": 0},
		"payload": {"deeply": {"nested": {"structure": {"with": {"many": {"levels": "value"}}}}}, "array": [1,2,3,4,5]}
	}`

	var envelope Envelope
	if err := json.Unmarshal([]byte(rawJSON), &envelope); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// Verify payload is stored as raw bytes, not parsed
	expectedPayload := `{"deeply": {"nested": {"structure": {"with": {"many": {"levels": "value"}}}}}, "array": [1,2,3,4,5]}`

	// Compare after normalizing whitespace using reflect.DeepEqual
	var expected, actual interface{}
	if err := json.Unmarshal([]byte(expectedPayload), &expected); err != nil {
		t.Fatalf("Failed to parse expected: %v", err)
	}
	if err := json.Unmarshal(envelope.Payload, &actual); err != nil {
		t.Fatalf("Failed to parse actual: %v", err)
	}

	if !reflect.DeepEqual(expected, actual) {
		expectedBytes, _ := json.Marshal(expected)
		actualBytes, _ := json.Marshal(actual)
		t.Errorf("Payload mismatch:\ngot:  %s\nwant: %s", string(actualBytes), string(expectedBytes))
	}

	// Verify that re-marshaling preserves the structure (semantically, not byte-for-byte)
	remarshaled, err := json.Marshal(envelope)
	if err != nil {
		t.Fatalf("Failed to re-marshal: %v", err)
	}

	var roundtrip Envelope
	if err := json.Unmarshal(remarshaled, &roundtrip); err != nil {
		t.Fatalf("Failed to unmarshal roundtrip: %v", err)
	}

	// Payload should be semantically equivalent after roundtrip
	// (whitespace may differ due to JSON normalization, but content must match)
	var originalPayload, roundtripPayload interface{}
	if err := json.Unmarshal(envelope.Payload, &originalPayload); err != nil {
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

// TestEnvelope_RawMessageForwardsUnchanged verifies that payload bytes
// can be extracted and forwarded without modification.
func TestEnvelope_RawMessageForwardsUnchanged(t *testing.T) {
	// Simulate receiving a message from queue
	queueMessage := []byte(`{"id":"msg-1","route":{"actors":["actor1"],"current":0},"payload":{"key":"value","number":42}}`)

	var envelope Envelope
	if err := json.Unmarshal(queueMessage, &envelope); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// The payload should be extractable as raw bytes
	payloadBytes := []byte(envelope.Payload)

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
