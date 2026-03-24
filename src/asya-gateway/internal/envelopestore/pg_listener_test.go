package envelopestore

import (
	"testing"
)

func TestParseNotification(t *testing.T) {
	tests := []struct {
		name          string
		raw           string
		wantTaskID    string
		wantEventType string
		wantPayload   string
		wantOK        bool
	}{
		{
			name:          "fly event",
			raw:           `task-123:fly:{"text":"hello"}`,
			wantTaskID:    "task-123",
			wantEventType: "fly",
			wantPayload:   `{"text":"hello"}`,
			wantOK:        true,
		},
		{
			name:          "progress event",
			raw:           `task-456:progress:{"status":"running","message":"processing"}`,
			wantTaskID:    "task-456",
			wantEventType: "progress",
			wantPayload:   `{"status":"running","message":"processing"}`,
			wantOK:        true,
		},
		{
			name:          "final event",
			raw:           `task-789:final:{"status":"succeeded","result":{"output":"done"}}`,
			wantTaskID:    "task-789",
			wantEventType: "final",
			wantPayload:   `{"status":"succeeded","result":{"output":"done"}}`,
			wantOK:        true,
		},
		{
			name:          "payload with colons",
			raw:           `task-456:fly:{"url":"http://example.com:8080"}`,
			wantTaskID:    "task-456",
			wantEventType: "fly",
			wantPayload:   `{"url":"http://example.com:8080"}`,
			wantOK:        true,
		},
		{
			name:   "no colon",
			raw:    "invalid",
			wantOK: false,
		},
		{
			name:   "single colon only",
			raw:    "task-123:fly",
			wantOK: false,
		},
		{
			name:   "empty string",
			raw:    "",
			wantOK: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			taskID, eventType, payload, ok := parseNotification(tt.raw)
			if ok != tt.wantOK {
				t.Fatalf("ok = %v, want %v", ok, tt.wantOK)
			}
			if !ok {
				return
			}
			if taskID != tt.wantTaskID {
				t.Errorf("taskID = %q, want %q", taskID, tt.wantTaskID)
			}
			if eventType != tt.wantEventType {
				t.Errorf("eventType = %q, want %q", eventType, tt.wantEventType)
			}
			if payload != tt.wantPayload {
				t.Errorf("payload = %q, want %q", payload, tt.wantPayload)
			}
		})
	}
}
