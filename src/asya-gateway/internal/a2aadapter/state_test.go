package a2aadapter_test

import (
	"testing"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/stretchr/testify/assert"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
)

func TestMeshStatusToA2A(t *testing.T) {
	tests := []struct {
		mesh string
		a2a  a2alib.TaskState
	}{
		{"pending", a2alib.TaskStateSubmitted},
		{"running", a2alib.TaskStateWorking},
		{"succeeded", a2alib.TaskStateCompleted},
		{"failed", a2alib.TaskStateFailed},
		{"canceled", a2alib.TaskStateCanceled},
		{"paused", a2alib.TaskStateInputRequired},
		{"auth_required", a2alib.TaskStateAuthRequired},
		{"garbage", a2alib.TaskStateUnknown},
	}

	for _, tt := range tests {
		t.Run(tt.mesh, func(t *testing.T) {
			assert.Equal(t, tt.a2a, a2aadapter.MeshStatusToA2A(tt.mesh))
		})
	}
}

func TestA2AToMeshStatus(t *testing.T) {
	tests := []struct {
		a2a  a2alib.TaskState
		mesh string
	}{
		{a2alib.TaskStateSubmitted, "pending"},
		{a2alib.TaskStateWorking, "running"},
		{a2alib.TaskStateCompleted, "succeeded"},
		{a2alib.TaskStateFailed, "failed"},
		{a2alib.TaskStateCanceled, "canceled"},
		{a2alib.TaskStateInputRequired, "paused"},
		{a2alib.TaskStateAuthRequired, "auth_required"},
		{a2alib.TaskStateUnknown, "unknown"},
	}

	for _, tt := range tests {
		t.Run(tt.mesh, func(t *testing.T) {
			assert.Equal(t, tt.mesh, a2aadapter.A2AToMeshStatus(tt.a2a))
		})
	}
}

func TestRoundTrip(t *testing.T) {
	statuses := []string{"pending", "running", "succeeded", "failed", "canceled", "paused", "auth_required"}
	for _, s := range statuses {
		assert.Equal(t, s, a2aadapter.A2AToMeshStatus(a2aadapter.MeshStatusToA2A(s)),
			"round-trip failed for %q", s)
	}
}
