package a2a

import (
	"testing"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestToA2AState(t *testing.T) {
	tests := []struct {
		name     string
		input    types.EnvelopeStatus
		expected a2alib.TaskState
	}{
		{"pending to submitted", types.EnvelopeStatusPending, a2alib.TaskStateSubmitted},
		{"running to working", types.EnvelopeStatusRunning, a2alib.TaskStateWorking},
		{"succeeded to completed", types.EnvelopeStatusSucceeded, a2alib.TaskStateCompleted},
		{"failed to failed", types.EnvelopeStatusFailed, a2alib.TaskStateFailed},
		{"canceled to canceled", types.EnvelopeStatusCanceled, a2alib.TaskStateCanceled},
		{"rejected to rejected", types.EnvelopeStatusRejected, a2alib.TaskStateRejected},
		{"paused to input_required", types.EnvelopeStatusPaused, a2alib.TaskStateInputRequired},
		{"auth_required to auth_required", types.EnvelopeStatusAuthRequired, a2alib.TaskStateAuthRequired},
		{"unknown to unknown", types.EnvelopeStatusUnknown, a2alib.TaskStateUnknown},
		{"invalid input to unknown", types.EnvelopeStatus("invalid"), a2alib.TaskStateUnknown},
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
		expected types.EnvelopeStatus
	}{
		{"submitted to pending", a2alib.TaskStateSubmitted, types.EnvelopeStatusPending},
		{"working to running", a2alib.TaskStateWorking, types.EnvelopeStatusRunning},
		{"completed to succeeded", a2alib.TaskStateCompleted, types.EnvelopeStatusSucceeded},
		{"failed to failed", a2alib.TaskStateFailed, types.EnvelopeStatusFailed},
		{"canceled to canceled", a2alib.TaskStateCanceled, types.EnvelopeStatusCanceled},
		{"rejected to rejected", a2alib.TaskStateRejected, types.EnvelopeStatusRejected},
		{"input_required to paused", a2alib.TaskStateInputRequired, types.EnvelopeStatusPaused},
		{"auth_required to auth_required", a2alib.TaskStateAuthRequired, types.EnvelopeStatusAuthRequired},
		{"unknown to unknown", a2alib.TaskStateUnknown, types.EnvelopeStatusUnknown},
		{"invalid input to unknown", a2alib.TaskState("invalid"), types.EnvelopeStatusUnknown},
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
	statuses := []types.EnvelopeStatus{
		types.EnvelopeStatusPending,
		types.EnvelopeStatusRunning,
		types.EnvelopeStatusSucceeded,
		types.EnvelopeStatusFailed,
		types.EnvelopeStatusCanceled,
		types.EnvelopeStatusRejected,
		types.EnvelopeStatusPaused,
		types.EnvelopeStatusAuthRequired,
		types.EnvelopeStatusUnknown,
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
