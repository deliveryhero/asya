package a2a

import (
	"context"
	"testing"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestStoreAdapterGet(t *testing.T) {
	store := taskstore.NewStore()
	adapter := NewStoreAdapter(store)

	task := &types.Task{
		ID:        "test-task-1",
		ContextID: "test-context",
		Status:    types.TaskStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Payload: map[string]interface{}{"test": "data"},
		Message: "Task initialized",
	}

	err := store.Create(task)
	require.NoError(t, err)

	a2aTask, version, err := adapter.Get(context.Background(), a2alib.TaskID("test-task-1"))
	require.NoError(t, err)
	assert.NotEqual(t, a2alib.TaskVersionMissing, version)
	assert.Equal(t, a2alib.TaskID("test-task-1"), a2aTask.ID)
	assert.Equal(t, "test-context", a2aTask.ContextID)
	assert.Equal(t, a2alib.TaskStateSubmitted, a2aTask.Status.State)
	assert.NotNil(t, a2aTask.Status.Message)
	require.Len(t, a2aTask.Status.Message.Parts, 1)
	textPart, ok := a2aTask.Status.Message.Parts[0].(*a2alib.TextPart)
	require.True(t, ok)
	assert.Equal(t, "Task initialized", textPart.Text)
}

func TestStoreAdapterGetNotFound(t *testing.T) {
	store := taskstore.NewStore()
	adapter := NewStoreAdapter(store)

	_, _, err := adapter.Get(context.Background(), a2alib.TaskID("nonexistent"))
	assert.ErrorIs(t, err, a2alib.ErrTaskNotFound)
}

func TestStoreAdapterSave(t *testing.T) {
	store := taskstore.NewStore()
	adapter := NewStoreAdapter(store)

	task := &types.Task{
		ID:        "test-task-2",
		ContextID: "test-context",
		Status:    types.TaskStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Payload: map[string]interface{}{"test": "data"},
	}

	err := store.Create(task)
	require.NoError(t, err)

	a2aTask := &a2alib.Task{
		ID:        a2alib.TaskID("test-task-2"),
		ContextID: "test-context",
		Status: a2alib.TaskStatus{
			State: a2alib.TaskStateWorking,
			Message: a2alib.NewMessage(a2alib.MessageRoleAgent,
				&a2alib.TextPart{Text: "Processing task"},
			),
		},
	}

	version, err := adapter.Save(context.Background(), a2aTask, a2aTask, a2alib.TaskVersionMissing)
	require.NoError(t, err)
	assert.NotEqual(t, a2alib.TaskVersionMissing, version)

	updatedTask, err := store.Get("test-task-2")
	require.NoError(t, err)
	assert.Equal(t, types.TaskStatusRunning, updatedTask.Status)
	assert.Equal(t, "Processing task", updatedTask.Message)
}

func TestStoreAdapterList(t *testing.T) {
	store := taskstore.NewStore()
	adapter := NewStoreAdapter(store)

	task1 := &types.Task{
		ID:        "test-task-3",
		ContextID: "test-context",
		Status:    types.TaskStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Payload: map[string]interface{}{"test": "data1"},
	}
	task2 := &types.Task{
		ID:        "test-task-4",
		ContextID: "test-context",
		Status:    types.TaskStatusRunning,
		Route: types.Route{
			Prev: []string{"actor1"},
			Curr: "actor2",
			Next: []string{},
		},
		Payload: map[string]interface{}{"test": "data2"},
	}

	err := store.Create(task1)
	require.NoError(t, err)
	err = store.Create(task2)
	require.NoError(t, err)

	err = store.Update(types.TaskUpdate{
		ID:        "test-task-4",
		Status:    types.TaskStatusRunning,
		Timestamp: time.Now(),
	})
	require.NoError(t, err)

	resp, err := adapter.List(context.Background(), &a2alib.ListTasksRequest{})
	require.NoError(t, err)
	assert.Len(t, resp.Tasks, 2)
	assert.Equal(t, 2, resp.TotalSize)
	assert.Equal(t, 2, resp.PageSize)

	resp, err = adapter.List(context.Background(), &a2alib.ListTasksRequest{
		Status: a2alib.TaskStateSubmitted,
	})
	require.NoError(t, err)
	assert.Len(t, resp.Tasks, 1)
	assert.Equal(t, a2alib.TaskID("test-task-3"), resp.Tasks[0].ID)
}
