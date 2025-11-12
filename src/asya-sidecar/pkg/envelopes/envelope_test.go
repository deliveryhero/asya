package envelopes

import (
	"encoding/json"
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
