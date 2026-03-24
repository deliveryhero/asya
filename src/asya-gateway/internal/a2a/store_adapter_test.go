package a2a

import (
	"context"
	"fmt"
	"testing"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/deliveryhero/asya/asya-gateway/internal/envelopestore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestStoreAdapterGet(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	task := &types.Envelope{
		ID:        "test-task-1",
		ContextID: "test-context",
		Status:    types.EnvelopeStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Payload: map[string]any{"test": "data"},
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
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	_, _, err := adapter.Get(context.Background(), a2alib.TaskID("nonexistent"))
	assert.ErrorIs(t, err, a2alib.ErrTaskNotFound)
}

func TestStoreAdapterSave(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	task := &types.Envelope{
		ID:        "test-task-2",
		ContextID: "test-context",
		Status:    types.EnvelopeStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Payload: map[string]any{"test": "data"},
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
	assert.Equal(t, types.EnvelopeStatusRunning, updatedTask.Status)
	assert.Equal(t, "Processing task", updatedTask.Message)
}

func TestStoreAdapterList(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	task1 := &types.Envelope{
		ID:        "test-task-3",
		ContextID: "test-context",
		Status:    types.EnvelopeStatusPending,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Payload: map[string]any{"test": "data1"},
	}
	task2 := &types.Envelope{
		ID:        "test-task-4",
		ContextID: "test-context",
		Status:    types.EnvelopeStatusRunning,
		Route: types.Route{
			Prev: []string{"actor1"},
			Curr: "actor2",
			Next: []string{},
		},
		Payload: map[string]any{"test": "data2"},
	}

	err := store.Create(task1)
	require.NoError(t, err)
	err = store.Create(task2)
	require.NoError(t, err)

	err = store.Update(types.EnvelopeUpdate{
		ID:        "test-task-4",
		Status:    types.EnvelopeStatusRunning,
		Timestamp: time.Now(),
	})
	require.NoError(t, err)

	resp, err := adapter.List(context.Background(), &a2alib.ListTasksRequest{})
	require.NoError(t, err)
	assert.Len(t, resp.Tasks, 2)
	assert.Equal(t, 2, resp.TotalSize)
	assert.Equal(t, 50, resp.PageSize) // default page size

	resp, err = adapter.List(context.Background(), &a2alib.ListTasksRequest{
		Status: a2alib.TaskStateSubmitted,
	})
	require.NoError(t, err)
	assert.Len(t, resp.Tasks, 1)
	assert.Equal(t, a2alib.TaskID("test-task-3"), resp.Tasks[0].ID)
}

func TestStoreAdapterListPagination(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	// Create 5 tasks in ctx-1
	for i := range 5 {
		err := store.Create(&types.Envelope{
			ID:        fmt.Sprintf("ctx1-task-%d", i),
			ContextID: "ctx-1",
			Route: types.Route{
				Prev: []string{},
				Curr: "actor1",
				Next: []string{},
			},
			Payload: map[string]any{"i": i},
		})
		require.NoError(t, err)
	}

	// Create 1 task in ctx-2
	err := store.Create(&types.Envelope{
		ID:        "ctx2-task-0",
		ContextID: "ctx-2",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Payload: map[string]any{"i": 0},
	})
	require.NoError(t, err)

	// Filter by context_id = ctx-1
	resp, err := adapter.List(context.Background(), &a2alib.ListTasksRequest{
		ContextID: "ctx-1",
	})
	require.NoError(t, err)
	assert.Equal(t, 5, resp.TotalSize)
	assert.Len(t, resp.Tasks, 5)
	assert.Empty(t, resp.NextPageToken)

	// Paginate with page_size=2
	resp, err = adapter.List(context.Background(), &a2alib.ListTasksRequest{
		ContextID: "ctx-1",
		PageSize:  2,
	})
	require.NoError(t, err)
	assert.Equal(t, 5, resp.TotalSize)
	assert.Len(t, resp.Tasks, 2)
	assert.Equal(t, 2, resp.PageSize)
	assert.Equal(t, "2", resp.NextPageToken)

	// Fetch page 2
	resp2, err := adapter.List(context.Background(), &a2alib.ListTasksRequest{
		ContextID: "ctx-1",
		PageSize:  2,
		PageToken: resp.NextPageToken,
	})
	require.NoError(t, err)
	assert.Equal(t, 5, resp2.TotalSize)
	assert.Len(t, resp2.Tasks, 2)
	assert.Equal(t, "4", resp2.NextPageToken)

	// Verify no overlap between pages
	page1IDs := map[a2alib.TaskID]bool{}
	for _, task := range resp.Tasks {
		page1IDs[task.ID] = true
	}
	for _, task := range resp2.Tasks {
		assert.False(t, page1IDs[task.ID], "task %s appears in both page 1 and page 2", task.ID)
	}

	// Fetch page 3 (last page, only 1 task)
	resp3, err := adapter.List(context.Background(), &a2alib.ListTasksRequest{
		ContextID: "ctx-1",
		PageSize:  2,
		PageToken: resp2.NextPageToken,
	})
	require.NoError(t, err)
	assert.Equal(t, 5, resp3.TotalSize)
	assert.Len(t, resp3.Tasks, 1)
	assert.Empty(t, resp3.NextPageToken)

	// Verify ctx-2 filter
	resp, err = adapter.List(context.Background(), &a2alib.ListTasksRequest{
		ContextID: "ctx-2",
	})
	require.NoError(t, err)
	assert.Equal(t, 1, resp.TotalSize)
	assert.Len(t, resp.Tasks, 1)
	assert.Equal(t, a2alib.TaskID("ctx2-task-0"), resp.Tasks[0].ID)
}

func TestStoreAdapterListStatusFilter(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	// Create a pending task
	err := store.Create(&types.Envelope{
		ID:        "pending-task",
		ContextID: "ctx-filter",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Payload: map[string]any{},
	})
	require.NoError(t, err)

	// Create a task and move it to running
	err = store.Create(&types.Envelope{
		ID:        "running-task",
		ContextID: "ctx-filter",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Payload: map[string]any{},
	})
	require.NoError(t, err)

	err = store.Update(types.EnvelopeUpdate{
		ID:        "running-task",
		Status:    types.EnvelopeStatusRunning,
		Timestamp: time.Now(),
	})
	require.NoError(t, err)

	// Filter by TaskStateWorking (maps to running)
	resp, err := adapter.List(context.Background(), &a2alib.ListTasksRequest{
		Status: a2alib.TaskStateWorking,
	})
	require.NoError(t, err)
	assert.Equal(t, 1, resp.TotalSize)
	require.Len(t, resp.Tasks, 1)
	assert.Equal(t, a2alib.TaskID("running-task"), resp.Tasks[0].ID)
	assert.Equal(t, a2alib.TaskStateWorking, resp.Tasks[0].Status.State)
}

// ---------------------------------------------------------------------------
// State proxy hydration (history + artifacts)
// ---------------------------------------------------------------------------

// fakeStateProxy is a test double for stateproxy.Reader.
type fakeStateProxy struct {
	payloads map[string]map[string]any // prefix+"/"+id -> payload
	err      error
}

func (f *fakeStateProxy) ReadPayload(_ context.Context, prefix, taskID string) (map[string]any, error) {
	if f.err != nil {
		return nil, f.err
	}
	return f.payloads[prefix+"/"+taskID], nil
}

func buildPayloadWithHistory(msgs []map[string]any) map[string]any {
	history := make([]any, len(msgs))
	for i, m := range msgs {
		history[i] = m
	}
	return map[string]any{
		"a2a": map[string]any{
			"task": map[string]any{
				"history": history,
			},
		},
	}
}

func TestStoreAdapterGet_HistoryHydratedForSucceededTask(t *testing.T) {
	store := envelopestore.NewStore()
	sp := &fakeStateProxy{
		payloads: map[string]map[string]any{
			"succeeded/hist-task": buildPayloadWithHistory([]map[string]any{
				{
					"messageId": "msg-1",
					"role":      "user",
					"parts":     []any{map[string]any{"kind": "text", "text": "Hello"}},
				},
			}),
		},
	}
	adapter := NewStoreAdapter(store, sp)

	task := &types.Envelope{
		ID:        "hist-task",
		ContextID: "ctx",
		Status:    types.EnvelopeStatusSucceeded,
		Route:     types.Route{Prev: []string{"actor1"}, Curr: "", Next: []string{}},
		Payload:   map[string]any{},
	}
	require.NoError(t, store.Create(task))
	require.NoError(t, store.Update(types.EnvelopeUpdate{
		ID:        "hist-task",
		Status:    types.EnvelopeStatusSucceeded,
		Timestamp: time.Now(),
	}))

	got, _, err := adapter.Get(context.Background(), "hist-task")
	require.NoError(t, err)
	require.Len(t, got.History, 1)
	assert.Equal(t, a2alib.MessageRoleUser, got.History[0].Role)
}

func TestStoreAdapterGet_HistoryOmittedForInFlightTask(t *testing.T) {
	store := envelopestore.NewStore()
	sp := &fakeStateProxy{
		payloads: map[string]map[string]any{
			// provide data for "running" prefix (should never be read)
			"running/inflight-task": buildPayloadWithHistory([]map[string]any{
				{"messageId": "msg-x", "role": "user", "parts": []any{}},
			}),
		},
	}
	adapter := NewStoreAdapter(store, sp)

	task := &types.Envelope{
		ID:        "inflight-task",
		ContextID: "ctx",
		Status:    types.EnvelopeStatusRunning,
		Route:     types.Route{Prev: []string{}, Curr: "actor1", Next: []string{}},
		Payload:   map[string]any{},
	}
	require.NoError(t, store.Create(task))
	require.NoError(t, store.Update(types.EnvelopeUpdate{
		ID:        "inflight-task",
		Status:    types.EnvelopeStatusRunning,
		Timestamp: time.Now(),
	}))

	got, _, err := adapter.Get(context.Background(), "inflight-task")
	require.NoError(t, err)
	assert.Nil(t, got.History, "history must be omitted for in-flight tasks")
}

func TestStoreAdapterGet_HistoryOmittedOnStateProxyError(t *testing.T) {
	store := envelopestore.NewStore()
	sp := &fakeStateProxy{err: fmt.Errorf("s3 unavailable")}
	adapter := NewStoreAdapter(store, sp)

	task := &types.Envelope{
		ID:        "err-task",
		ContextID: "ctx",
		Status:    types.EnvelopeStatusSucceeded,
		Route:     types.Route{Prev: []string{"a"}, Curr: "", Next: []string{}},
		Payload:   map[string]any{},
	}
	require.NoError(t, store.Create(task))
	require.NoError(t, store.Update(types.EnvelopeUpdate{
		ID:        "err-task",
		Status:    types.EnvelopeStatusSucceeded,
		Timestamp: time.Now(),
	}))

	// Must succeed despite state proxy error; history simply omitted
	got, _, err := adapter.Get(context.Background(), "err-task")
	require.NoError(t, err)
	assert.Nil(t, got.History, "history must be omitted when state proxy read fails")
}

func TestStoreAdapterGet_HistoryOmittedWhenNoFileExists(t *testing.T) {
	store := envelopestore.NewStore()
	sp := &fakeStateProxy{payloads: map[string]map[string]any{}} // empty — no files
	adapter := NewStoreAdapter(store, sp)

	task := &types.Envelope{
		ID:        "no-file-task",
		ContextID: "ctx",
		Status:    types.EnvelopeStatusSucceeded,
		Route:     types.Route{Prev: []string{}, Curr: "", Next: []string{}},
		Payload:   map[string]any{},
	}
	require.NoError(t, store.Create(task))
	require.NoError(t, store.Update(types.EnvelopeUpdate{
		ID:        "no-file-task",
		Status:    types.EnvelopeStatusSucceeded,
		Timestamp: time.Now(),
	}))

	got, _, err := adapter.Get(context.Background(), "no-file-task")
	require.NoError(t, err)
	assert.Nil(t, got.History)
}

func TestStoreAdapterGet_ArtifactsHydratedWhenPresent(t *testing.T) {
	store := envelopestore.NewStore()
	sp := &fakeStateProxy{
		payloads: map[string]map[string]any{
			"succeeded/art-task": {
				"a2a": map[string]any{
					"task": map[string]any{
						"history": []any{},
						"artifacts": []any{
							map[string]any{
								"artifactId": "artifact-1",
								"name":       "result.json",
								"parts": []any{
									map[string]any{"kind": "text", "text": "{}"},
								},
							},
						},
					},
				},
			},
		},
	}
	adapter := NewStoreAdapter(store, sp)

	task := &types.Envelope{
		ID:        "art-task",
		ContextID: "ctx",
		Status:    types.EnvelopeStatusSucceeded,
		Route:     types.Route{Prev: []string{"a"}, Curr: "", Next: []string{}},
		Payload:   map[string]any{},
	}
	require.NoError(t, store.Create(task))
	require.NoError(t, store.Update(types.EnvelopeUpdate{
		ID:        "art-task",
		Status:    types.EnvelopeStatusSucceeded,
		Timestamp: time.Now(),
	}))

	got, _, err := adapter.Get(context.Background(), "art-task")
	require.NoError(t, err)
	require.Len(t, got.Artifacts, 1)
	assert.Equal(t, a2alib.ArtifactID("artifact-1"), got.Artifacts[0].ID)
}

func TestStoreAdapterGet_HistoryHydratedForPausedTask(t *testing.T) {
	store := envelopestore.NewStore()
	sp := &fakeStateProxy{
		payloads: map[string]map[string]any{
			"paused/pause-task": buildPayloadWithHistory([]map[string]any{
				{"messageId": "m1", "role": "user", "parts": []any{map[string]any{"kind": "text", "text": "hi"}}},
				{"messageId": "m2", "role": "agent", "parts": []any{map[string]any{"kind": "text", "text": "need info"}}},
			}),
		},
	}
	adapter := NewStoreAdapter(store, sp)

	task := &types.Envelope{
		ID:        "pause-task",
		ContextID: "ctx",
		Status:    types.EnvelopeStatusPaused,
		Route:     types.Route{Prev: []string{"a"}, Curr: "x-pause", Next: []string{"x-resume"}},
		Payload:   map[string]any{},
	}
	require.NoError(t, store.Create(task))
	require.NoError(t, store.Update(types.EnvelopeUpdate{
		ID:        "pause-task",
		Status:    types.EnvelopeStatusPaused,
		Timestamp: time.Now(),
	}))

	got, _, err := adapter.Get(context.Background(), "pause-task")
	require.NoError(t, err)
	require.Len(t, got.History, 2, "paused task must return full conversation history")
}

// ---------------------------------------------------------------------------
// Result payload NOT stored in PG for succeeded tasks
// ---------------------------------------------------------------------------

func TestStoreAdapterGet_NoArtifactForSucceededTaskWithoutStateProxy(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil) // no state proxy

	task := &types.Envelope{
		ID:        "no-sp-task",
		ContextID: "ctx",
		Status:    types.EnvelopeStatusSucceeded,
		Route:     types.Route{Prev: []string{"actor1"}, Curr: "", Next: []string{}},
		Payload:   map[string]any{},
	}
	require.NoError(t, store.Create(task))
	require.NoError(t, store.Update(types.EnvelopeUpdate{
		ID:        "no-sp-task",
		Status:    types.EnvelopeStatusSucceeded,
		Timestamp: time.Now(),
	}))

	got, _, err := adapter.Get(context.Background(), "no-sp-task")
	require.NoError(t, err)
	assert.Empty(t, got.Artifacts, "succeeded task without state proxy must have no artifacts")
}

// ---------------------------------------------------------------------------
// Artifact event filtering in Save()
// ---------------------------------------------------------------------------

func TestStoreAdapterSave_SkipsDBForArtifactAppend(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	taskID := "artifact-skip-task"
	err := store.Create(&types.Envelope{
		ID:        taskID,
		ContextID: "ctx",
		Route:     types.Route{Prev: []string{}, Curr: "actor1", Next: []string{}},
		Payload:   map[string]any{},
	})
	require.NoError(t, err)

	// Transition to running
	err = store.Update(types.EnvelopeUpdate{
		ID:        taskID,
		Status:    types.EnvelopeStatusRunning,
		Timestamp: time.Now(),
	})
	require.NoError(t, err)

	a2aTask := &a2alib.Task{
		ID:        a2alib.TaskID(taskID),
		ContextID: "ctx",
		Status:    a2alib.TaskStatus{State: a2alib.TaskStateWorking},
	}

	artifactEvent := &a2alib.TaskArtifactUpdateEvent{
		TaskID:    a2alib.TaskID(taskID),
		ContextID: "ctx",
		Append:    true,
		Artifact: &a2alib.Artifact{
			ID:    "fly-stream",
			Parts: a2alib.ContentParts{a2alib.TextPart{Text: "hello"}},
		},
	}

	prevVersion := a2alib.TaskVersion(42)
	version, err := adapter.Save(context.Background(), a2aTask, artifactEvent, prevVersion)
	require.NoError(t, err)
	assert.Equal(t, prevVersion, version)

	envelope, err := store.Get(taskID)
	require.NoError(t, err)
	assert.Equal(t, types.EnvelopeStatusRunning, envelope.Status)
	assert.Empty(t, envelope.Message, "Save() should not write to store for artifact events")
}

func TestStoreAdapterSave_SkipsDBForNewArtifact(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	taskID := "artifact-new-task"
	err := store.Create(&types.Envelope{
		ID:        taskID,
		ContextID: "ctx",
		Route:     types.Route{Prev: []string{}, Curr: "actor1", Next: []string{}},
	})
	require.NoError(t, err)

	// Transition to running
	err = store.Update(types.EnvelopeUpdate{
		ID:        taskID,
		Status:    types.EnvelopeStatusRunning,
		Timestamp: time.Now(),
	})
	require.NoError(t, err)

	a2aTask := &a2alib.Task{
		ID:        a2alib.TaskID(taskID),
		ContextID: "ctx",
		Status:    a2alib.TaskStatus{State: a2alib.TaskStateWorking},
	}

	artifactEvent := &a2alib.TaskArtifactUpdateEvent{
		TaskID:    a2alib.TaskID(taskID),
		ContextID: "ctx",
		Append:    false,
		Artifact: &a2alib.Artifact{
			ID:    "fly-stream",
			Parts: a2alib.ContentParts{a2alib.TextPart{Text: "first chunk"}},
		},
	}

	prevVersion := a2alib.TaskVersion(10)
	version, err := adapter.Save(context.Background(), a2aTask, artifactEvent, prevVersion)
	require.NoError(t, err)
	assert.Equal(t, prevVersion, version)
}

func TestStoreAdapterSave_StatusEventsStillWriteToDB(t *testing.T) {
	store := envelopestore.NewStore()
	adapter := NewStoreAdapter(store, nil)

	taskID := "status-write-task"
	err := store.Create(&types.Envelope{
		ID:        taskID,
		ContextID: "ctx",
		Status:    types.EnvelopeStatusPending,
		Route:     types.Route{Prev: []string{}, Curr: "actor1", Next: []string{}},
	})
	require.NoError(t, err)

	a2aTask := &a2alib.Task{
		ID:        a2alib.TaskID(taskID),
		ContextID: "ctx",
		Status: a2alib.TaskStatus{
			State:   a2alib.TaskStateWorking,
			Message: a2alib.NewMessage(a2alib.MessageRoleAgent, &a2alib.TextPart{Text: "working"}),
		},
	}

	statusEvent := a2alib.NewStatusUpdateEvent(a2aTask, a2alib.TaskStateWorking, nil)

	version, err := adapter.Save(context.Background(), a2aTask, statusEvent, a2alib.TaskVersionMissing)
	require.NoError(t, err)
	assert.NotEqual(t, a2alib.TaskVersionMissing, version)

	envelope, err := store.Get(taskID)
	require.NoError(t, err)
	assert.Equal(t, types.EnvelopeStatusRunning, envelope.Status)
}
