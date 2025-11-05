package messages

import (
	"encoding/json"
	"testing"
)

func TestRoute_GetCurrentStep(t *testing.T) {
	tests := []struct {
		name     string
		route    Route
		expected string
	}{
		{
			name:     "first step",
			route:    Route{Steps: []string{"step1", "step2", "step3"}, Current: 0},
			expected: "step1",
		},
		{
			name:     "middle step",
			route:    Route{Steps: []string{"step1", "step2", "step3"}, Current: 1},
			expected: "step2",
		},
		{
			name:     "last step",
			route:    Route{Steps: []string{"step1", "step2", "step3"}, Current: 2},
			expected: "step3",
		},
		{
			name:     "out of bounds",
			route:    Route{Steps: []string{"step1", "step2"}, Current: 5},
			expected: "",
		},
		{
			name:     "negative index",
			route:    Route{Steps: []string{"step1", "step2"}, Current: -1},
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.route.GetCurrentStep()
			if result != tt.expected {
				t.Errorf("GetCurrentStep() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestRoute_GetNextStep(t *testing.T) {
	tests := []struct {
		name     string
		route    Route
		expected string
	}{
		{
			name:     "has next step",
			route:    Route{Steps: []string{"step1", "step2", "step3"}, Current: 0},
			expected: "step2",
		},
		{
			name:     "last step",
			route:    Route{Steps: []string{"step1", "step2", "step3"}, Current: 2},
			expected: "",
		},
		{
			name:     "empty steps",
			route:    Route{Steps: []string{}, Current: 0},
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.route.GetNextStep()
			if result != tt.expected {
				t.Errorf("GetNextStep() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestRoute_HasNextStep(t *testing.T) {
	tests := []struct {
		name     string
		route    Route
		expected bool
	}{
		{
			name:     "has next",
			route:    Route{Steps: []string{"step1", "step2", "step3"}, Current: 0},
			expected: true,
		},
		{
			name:     "at last step",
			route:    Route{Steps: []string{"step1", "step2", "step3"}, Current: 2},
			expected: false,
		},
		{
			name:     "beyond last step",
			route:    Route{Steps: []string{"step1", "step2"}, Current: 5},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.route.HasNextStep()
			if result != tt.expected {
				t.Errorf("HasNextStep() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestRoute_IncrementCurrent(t *testing.T) {
	route := Route{Steps: []string{"step1", "step2", "step3"}, Current: 0}
	newRoute := route.IncrementCurrent()

	if newRoute.Current != 1 {
		t.Errorf("IncrementCurrent() current = %v, want 1", newRoute.Current)
	}

	// Verify original unchanged
	if route.Current != 0 {
		t.Errorf("Original route modified, current = %v, want 0", route.Current)
	}
}

func TestMessage_JSONSerialization(t *testing.T) {
	original := Message{
		Route: Route{
			Steps:   []string{"step1", "step2", "step3"},
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
	var decoded Message
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// Verify
	if decoded.Route.Current != original.Route.Current {
		t.Errorf("Route.Current = %v, want %v", decoded.Route.Current, original.Route.Current)
	}

	if len(decoded.Route.Steps) != len(original.Route.Steps) {
		t.Errorf("Route.Steps length = %v, want %v", len(decoded.Route.Steps), len(original.Route.Steps))
	}

	// Compare JSON payload (ignoring whitespace)
	var origPayload, decodedPayload map[string]interface{}
	json.Unmarshal(original.Payload, &origPayload)
	json.Unmarshal(decoded.Payload, &decodedPayload)

	origData, _ := origPayload["data"].(string)
	decodedData, _ := decodedPayload["data"].(string)

	if decodedData != origData {
		t.Errorf("Payload data = %v, want %v", decodedData, origData)
	}
}
