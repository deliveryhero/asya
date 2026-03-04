package a2a

import (
	"testing"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestToA2AState(t *testing.T) {
	tests := []struct {
		name     string
		input    types.TaskStatus
		expected a2alib.TaskState
	}{
		{"pending to submitted", types.TaskStatusPending, a2alib.TaskStateSubmitted},
		{"running to working", types.TaskStatusRunning, a2alib.TaskStateWorking},
		{"succeeded to completed", types.TaskStatusSucceeded, a2alib.TaskStateCompleted},
		{"failed to failed", types.TaskStatusFailed, a2alib.TaskStateFailed},
		{"canceled to canceled", types.TaskStatusCanceled, a2alib.TaskStateCanceled},
		{"rejected to rejected", types.TaskStatusRejected, a2alib.TaskStateRejected},
		{"paused to input_required", types.TaskStatusPaused, a2alib.TaskStateInputRequired},
		{"auth_required to auth_required", types.TaskStatusAuthRequired, a2alib.TaskStateAuthRequired},
		{"unknown to unknown", types.TaskStatusUnknown, a2alib.TaskStateUnknown},
		{"invalid input to unknown", types.TaskStatus("invalid"), a2alib.TaskStateUnknown},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := ToA2AState(tt.input)
			if result != tt.expected {
				t.Errorf("ToA2AState(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestFromA2AState(t *testing.T) {
	tests := []struct {
		name     string
		input    a2alib.TaskState
		expected types.TaskStatus
	}{
		{"submitted to pending", a2alib.TaskStateSubmitted, types.TaskStatusPending},
		{"working to running", a2alib.TaskStateWorking, types.TaskStatusRunning},
		{"completed to succeeded", a2alib.TaskStateCompleted, types.TaskStatusSucceeded},
		{"failed to failed", a2alib.TaskStateFailed, types.TaskStatusFailed},
		{"canceled to canceled", a2alib.TaskStateCanceled, types.TaskStatusCanceled},
		{"rejected to rejected", a2alib.TaskStateRejected, types.TaskStatusRejected},
		{"input_required to paused", a2alib.TaskStateInputRequired, types.TaskStatusPaused},
		{"auth_required to auth_required", a2alib.TaskStateAuthRequired, types.TaskStatusAuthRequired},
		{"unknown to unknown", a2alib.TaskStateUnknown, types.TaskStatusUnknown},
		{"invalid input to unknown", a2alib.TaskState("invalid"), types.TaskStatusUnknown},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := FromA2AState(tt.input)
			if result != tt.expected {
				t.Errorf("FromA2AState(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestRoundTrip(t *testing.T) {
	statuses := []types.TaskStatus{
		types.TaskStatusPending,
		types.TaskStatusRunning,
		types.TaskStatusSucceeded,
		types.TaskStatusFailed,
		types.TaskStatusCanceled,
		types.TaskStatusRejected,
		types.TaskStatusPaused,
		types.TaskStatusAuthRequired,
		types.TaskStatusUnknown,
	}

	for _, status := range statuses {
		t.Run(string(status), func(t *testing.T) {
			a2aState := ToA2AState(status)
			roundTrip := FromA2AState(a2aState)
			if roundTrip != status {
				t.Errorf("Round trip failed for %q: got %q after internal→a2a→internal", status, roundTrip)
			}
		})
	}
}
