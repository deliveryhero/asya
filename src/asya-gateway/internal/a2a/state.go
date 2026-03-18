package a2a

import (
	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ToA2AState converts internal TaskStatus to a2a-go TaskState.
func ToA2AState(s types.EnvelopeStatus) a2alib.TaskState {
	switch s {
	case types.EnvelopeStatusPending:
		return a2alib.TaskStateSubmitted
	case types.EnvelopeStatusRunning:
		return a2alib.TaskStateWorking
	case types.EnvelopeStatusSucceeded:
		return a2alib.TaskStateCompleted
	case types.EnvelopeStatusFailed:
		return a2alib.TaskStateFailed
	case types.EnvelopeStatusCanceled:
		return a2alib.TaskStateCanceled
	case types.EnvelopeStatusRejected:
		return a2alib.TaskStateRejected
	case types.EnvelopeStatusPaused:
		return a2alib.TaskStateInputRequired
	case types.EnvelopeStatusAuthRequired:
		return a2alib.TaskStateAuthRequired
	default:
		return a2alib.TaskStateUnknown
	}
}

// FromA2AState converts a2a-go TaskState to internal TaskStatus.
func FromA2AState(s a2alib.TaskState) types.EnvelopeStatus {
	switch s {
	case a2alib.TaskStateSubmitted:
		return types.EnvelopeStatusPending
	case a2alib.TaskStateWorking:
		return types.EnvelopeStatusRunning
	case a2alib.TaskStateCompleted:
		return types.EnvelopeStatusSucceeded
	case a2alib.TaskStateFailed:
		return types.EnvelopeStatusFailed
	case a2alib.TaskStateCanceled:
		return types.EnvelopeStatusCanceled
	case a2alib.TaskStateRejected:
		return types.EnvelopeStatusRejected
	case a2alib.TaskStateInputRequired:
		return types.EnvelopeStatusPaused
	case a2alib.TaskStateAuthRequired:
		return types.EnvelopeStatusAuthRequired
	default:
		return types.EnvelopeStatusUnknown
	}
}
