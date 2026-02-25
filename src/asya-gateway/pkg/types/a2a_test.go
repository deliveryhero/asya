package types

import (
	"encoding/json"
	"testing"
)

func TestA2AToA2AState(t *testing.T) {
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

func TestA2ANewA2AError(t *testing.T) {
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

func TestA2ANewA2AResult(t *testing.T) {
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
