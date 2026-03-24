package envelopestore

import (
	"testing"
)

func TestParseFLYNotification(t *testing.T) {
	tests := []struct {
		name        string
		raw         string
		wantTaskID  string
		wantPayload string
		wantOK      bool
	}{
		{
			name:        "valid notification",
			raw:         `task-123:{"text":"hello"}`,
			wantTaskID:  "task-123",
			wantPayload: `{"text":"hello"}`,
			wantOK:      true,
		},
		{
			name:        "payload with colons",
			raw:         `task-456:{"url":"http://example.com:8080"}`,
			wantTaskID:  "task-456",
			wantPayload: `{"url":"http://example.com:8080"}`,
			wantOK:      true,
		},
		{
			name:   "no colon",
			raw:    "invalid",
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
			taskID, payload, ok := parseFLYNotification(tt.raw)
			if ok != tt.wantOK {
				t.Fatalf("ok = %v, want %v", ok, tt.wantOK)
			}
			if !ok {
				return
			}
			if taskID != tt.wantTaskID {
				t.Errorf("taskID = %q, want %q", taskID, tt.wantTaskID)
			}
			if payload != tt.wantPayload {
				t.Errorf("payload = %q, want %q", payload, tt.wantPayload)
			}
		})
	}
}
