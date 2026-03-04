package a2a

import (
	"encoding/json"
	"testing"
)

func TestDetectFLYEventType(t *testing.T) {
	tests := []struct {
		name     string
		payload  string
		expected string
	}{
		{"artifact_update", `{"artifact_update":{"artifact":{"artifact_id":"s0"}}}`, "artifact_update"},
		{"status_update", `{"status_update":{"status":{"state":"WORKING"}}}`, "status_update"},
		{"message", `{"message":{"role":"agent","parts":[{"text":"hi"}]}}`, "message"},
		{"legacy_partial", `{"type":"text_delta","token":"hello"}`, "partial"},
		{"empty", `{}`, "partial"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var payload map[string]any
			if err := json.Unmarshal([]byte(tt.payload), &payload); err != nil {
				t.Fatal(err)
			}
			got := DetectFLYEventType(payload)
			if got != tt.expected {
				t.Errorf("DetectFLYEventType = %q, want %q", got, tt.expected)
			}
		})
	}
}
