package a2a

import (
	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ToA2AState converts internal TaskStatus to a2a-go TaskState.
func ToA2AState(s types.TaskStatus) a2alib.TaskState {
	switch s {
	case types.TaskStatusPending:
		return a2alib.TaskStateSubmitted
	case types.TaskStatusRunning:
		return a2alib.TaskStateWorking
	case types.TaskStatusSucceeded:
		return a2alib.TaskStateCompleted
	case types.TaskStatusFailed:
		return a2alib.TaskStateFailed
	case types.TaskStatusCanceled:
		return a2alib.TaskStateCanceled
	case types.TaskStatusRejected:
		return a2alib.TaskStateRejected
	case types.TaskStatusPaused:
		return a2alib.TaskStateInputRequired
	case types.TaskStatusAuthRequired:
		return a2alib.TaskStateAuthRequired
	default:
		return a2alib.TaskStateUnknown
	}
}

// FromA2AState converts a2a-go TaskState to internal TaskStatus.
func FromA2AState(s a2alib.TaskState) types.TaskStatus {
	switch s {
	case a2alib.TaskStateSubmitted:
		return types.TaskStatusPending
	case a2alib.TaskStateWorking:
		return types.TaskStatusRunning
	case a2alib.TaskStateCompleted:
		return types.TaskStatusSucceeded
	case a2alib.TaskStateFailed:
		return types.TaskStatusFailed
	case a2alib.TaskStateCanceled:
		return types.TaskStatusCanceled
	case a2alib.TaskStateRejected:
		return types.TaskStatusRejected
	case a2alib.TaskStateInputRequired:
		return types.TaskStatusPaused
	case a2alib.TaskStateAuthRequired:
		return types.TaskStatusAuthRequired
	default:
		return types.TaskStatusUnknown
	}
}
