package a2aadapter

import (
	a2alib "github.com/a2aproject/a2a-go/a2a"
)

// MeshStatusToA2A converts a mesh status string to A2A TaskState.
// Mapping per RFC Section 4.3.
func MeshStatusToA2A(status string) a2alib.TaskState {
	switch status {
	case "pending":
		return a2alib.TaskStateSubmitted
	case "running":
		return a2alib.TaskStateWorking
	case "succeeded":
		return a2alib.TaskStateCompleted
	case "failed":
		return a2alib.TaskStateFailed
	case "canceled":
		return a2alib.TaskStateCanceled
	case "paused":
		return a2alib.TaskStateInputRequired
	case "auth_required":
		return a2alib.TaskStateAuthRequired
	default:
		return a2alib.TaskStateUnknown
	}
}

// A2AToMeshStatus converts an A2A TaskState to a mesh status string.
func A2AToMeshStatus(state a2alib.TaskState) string {
	switch state {
	case a2alib.TaskStateSubmitted:
		return "pending"
	case a2alib.TaskStateWorking:
		return "running"
	case a2alib.TaskStateCompleted:
		return "succeeded"
	case a2alib.TaskStateFailed:
		return "failed"
	case a2alib.TaskStateCanceled:
		return "canceled"
	case a2alib.TaskStateInputRequired:
		return "paused"
	case a2alib.TaskStateAuthRequired:
		return "auth_required"
	default:
		return "unknown"
	}
}
