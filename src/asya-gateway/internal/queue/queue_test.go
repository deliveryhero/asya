package queue

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewActorMessage(t *testing.T) {
	tests := []struct {
		name         string
		task         *types.Task
		expectErr    bool
		validateMsg  func(*testing.T, ActorMessage)
		validateJSON func(*testing.T, []byte)
	}{
		{
			name: "message with deadline includes status.deadline_at",
			task: &types.Task{
				ID: "task-123",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor-1",
					Next: []string{"actor-2"},
				},
				Payload:  map[string]interface{}{"key": "value"},
				Deadline: time.Date(2026, 3, 1, 12, 0, 0, 0, time.UTC),
			},
			expectErr: false,
			validateMsg: func(t *testing.T, msg ActorMessage) {
				assert.Equal(t, "task-123", msg.ID)
				assert.NotNil(t, msg.Status)
				assert.Equal(t, "2026-03-01T12:00:00Z", msg.Status.DeadlineAt)
				assert.Equal(t, "actor-1", msg.Status.Actor)
				assert.Equal(t, "pending", msg.Status.Phase)
			},
			validateJSON: func(t *testing.T, jsonData []byte) {
				var parsed map[string]interface{}
				require.NoError(t, json.Unmarshal(jsonData, &parsed))

				status, ok := parsed["status"].(map[string]interface{})
				require.True(t, ok, "status should be an object")
				assert.Equal(t, "2026-03-01T12:00:00Z", status["deadline_at"])

				_, hasTopLevelDeadline := parsed["deadline"]
				assert.False(t, hasTopLevelDeadline, "top-level deadline field should not exist")
			},
		},
		{
			name: "message without deadline omits status.deadline_at",
			task: &types.Task{
				ID: "task-456",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor-2",
					Next: []string{},
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			expectErr: false,
			validateMsg: func(t *testing.T, msg ActorMessage) {
				assert.Equal(t, "task-456", msg.ID)
				assert.NotNil(t, msg.Status)
				assert.Empty(t, msg.Status.DeadlineAt)
			},
			validateJSON: func(t *testing.T, jsonData []byte) {
				var parsed map[string]interface{}
				require.NoError(t, json.Unmarshal(jsonData, &parsed))

				status, ok := parsed["status"].(map[string]interface{})
				require.True(t, ok, "status should be an object")

				_, hasDeadlineAt := status["deadline_at"]
				assert.False(t, hasDeadlineAt, "deadline_at should be omitted when empty")
			},
		},
		{
			name: "deadline_at uses RFC3339 UTC format",
			task: &types.Task{
				ID: "task-789",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor-3",
					Next: []string{},
				},
				Payload:  map[string]interface{}{},
				Deadline: time.Date(2026, 12, 31, 23, 59, 59, 0, time.FixedZone("PST", -8*3600)),
			},
			expectErr: false,
			validateMsg: func(t *testing.T, msg ActorMessage) {
				assert.NotNil(t, msg.Status)
				assert.NotEmpty(t, msg.Status.DeadlineAt)

				parsedTime, err := time.Parse(time.RFC3339, msg.Status.DeadlineAt)
				require.NoError(t, err, "deadline_at should be valid RFC3339")
				assert.Equal(t, time.UTC, parsedTime.Location(), "deadline_at should be in UTC")
			},
		},
		{
			name: "error when route.curr is empty",
			task: &types.Task{
				ID: "task-error",
				Route: types.Route{
					Prev: []string{},
					Curr: "",
					Next: []string{},
				},
				Payload: map[string]interface{}{},
			},
			expectErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			msg, err := NewActorMessage(tt.task)

			if tt.expectErr {
				assert.Error(t, err)
				return
			}

			require.NoError(t, err)

			if tt.validateMsg != nil {
				tt.validateMsg(t, msg)
			}

			if tt.validateJSON != nil {
				jsonData, err := json.Marshal(msg)
				require.NoError(t, err)
				tt.validateJSON(t, jsonData)
			}
		})
	}
}
