//go:build integration

package taskstore

import (
	"context"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func setupPgStore(t *testing.T) (*taskstore.PgStore, func()) {
	t.Helper()

	ctx := context.Background()
	store, err := taskstore.NewPgStore(ctx, getPostgresURL())
	require.NoError(t, err, "Failed to create PgStore")

	cleanup := func() {
		store.Close()
	}

	return store, cleanup
}

func intPtr(i int) *int {
	return &i
}

func floatPtr(f float64) *float64 {
	return &f
}

func strPtr(s string) *string {
	return &s
}

// TestPgStore_CreateAndGet tests basic Create and Get operations
func TestPgStore_CreateAndGet(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	task := &types.Task{
		ID: "test-create-get-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2", "actor3"},
		},
		Payload:    map[string]interface{}{"data": "test"},
		TimeoutSec: 300,
	}

	err := store.Create(task)
	require.NoError(t, err)

	retrieved, err := store.Get("test-create-get-1")
	require.NoError(t, err)
	assert.Equal(t, "test-create-get-1", retrieved.ID)
	assert.Equal(t, types.TaskStatusPending, retrieved.Status)
	assert.Equal(t, []string{}, retrieved.Route.Prev)
	assert.Equal(t, "actor1", retrieved.Route.Curr)
	assert.Equal(t, []string{"actor2", "actor3"}, retrieved.Route.Next)
	assert.Equal(t, 3, retrieved.TotalActors)
	assert.Equal(t, 0, retrieved.ActorsCompleted)
	assert.Equal(t, 0.0, retrieved.ProgressPercent)
}

// TestPgStore_UpdateProgress_RouteActorsPersistence tests that route prev/curr/next is persisted
func TestPgStore_UpdateProgress_RouteActorsPersistence(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	task := &types.Task{
		ID: "test-route-persist-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(task)
	require.NoError(t, err)

	// Simulate actor modifying route by extending next
	update := types.TaskUpdate{
		ID:              "test-route-persist-1",
		Status:          types.TaskStatusRunning,
		ProgressPercent: floatPtr(25.0),
		Prev:            []string{},
		Curr:            "actor1",
		Next:            []string{"actor2", "actor3", "actor4"},
		TaskState:       strPtr("processing"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(update)
	require.NoError(t, err)

	// Verify route was persisted
	retrieved, err := store.Get("test-route-persist-1")
	require.NoError(t, err)
	assert.Equal(t, []string{}, retrieved.Route.Prev)
	assert.Equal(t, "actor1", retrieved.Route.Curr)
	assert.Equal(t, []string{"actor2", "actor3", "actor4"}, retrieved.Route.Next)
	assert.Equal(t, 4, retrieved.TotalActors, "TotalActors should be updated")
	assert.Equal(t, "actor1", retrieved.CurrentActorName, "CurrentActorName should be derived from Curr")
}

// TestPgStore_UpdateProgress_MultipleUpdates tests multiple progress updates with route changes
func TestPgStore_UpdateProgress_MultipleUpdates(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	task := &types.Task{
		ID: "test-multi-update-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "step1",
			Next: []string{"step2"},
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(task)
	require.NoError(t, err)

	// First update: at step1 with extended route
	update1 := types.TaskUpdate{
		ID:              "test-multi-update-1",
		Status:          types.TaskStatusRunning,
		ProgressPercent: floatPtr(10.0),
		Prev:            []string{},
		Curr:            "step1",
		Next:            []string{"step2", "step3"},
		TaskState:       strPtr("received"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(update1)
	require.NoError(t, err)

	// Second update: step1 completed, now at step2 with more steps
	update2 := types.TaskUpdate{
		ID:              "test-multi-update-1",
		Status:          types.TaskStatusRunning,
		ProgressPercent: floatPtr(50.0),
		Prev:            []string{"step1"},
		Curr:            "step2",
		Next:            []string{"step3", "step4", "step5"},
		TaskState:       strPtr("processing"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(update2)
	require.NoError(t, err)

	// Verify final state
	retrieved, err := store.Get("test-multi-update-1")
	require.NoError(t, err)
	assert.Equal(t, []string{"step1"}, retrieved.Route.Prev)
	assert.Equal(t, "step2", retrieved.Route.Curr)
	assert.Equal(t, []string{"step3", "step4", "step5"}, retrieved.Route.Next)
	assert.Equal(t, 5, retrieved.TotalActors)
	assert.Equal(t, "step2", retrieved.CurrentActorName)
	assert.InDelta(t, 50.0, retrieved.ProgressPercent, 0.1)
}

// TestPgStore_GetUpdates tests retrieving update history for SSE streaming
func TestPgStore_GetUpdates(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	task := &types.Task{
		ID: "test-get-updates-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(task)
	require.NoError(t, err)

	// Send multiple progress updates
	updates := []types.TaskUpdate{
		{
			ID:              "test-get-updates-1",
			Status:          types.TaskStatusRunning,
			ProgressPercent: floatPtr(10.0),
			Prev:            []string{},
			Curr:            "actor1",
			Next:            []string{"actor2"},
			TaskState:       strPtr("received"),
			Message:         "Received at actor1",
			Timestamp:       time.Now(),
		},
		{
			ID:              "test-get-updates-1",
			Status:          types.TaskStatusRunning,
			ProgressPercent: floatPtr(50.0),
			Prev:            []string{},
			Curr:            "actor1",
			Next:            []string{"actor2"},
			TaskState:       strPtr("processing"),
			Message:         "Processing at actor1",
			Timestamp:       time.Now().Add(100 * time.Millisecond),
		},
		{
			ID:              "test-get-updates-1",
			Status:          types.TaskStatusRunning,
			ProgressPercent: floatPtr(100.0),
			Prev:            []string{},
			Curr:            "actor1",
			Next:            []string{"actor2"},
			TaskState:       strPtr("completed"),
			Message:         "Completed at actor1",
			Timestamp:       time.Now().Add(200 * time.Millisecond),
		},
	}

	for _, update := range updates {
		err = store.UpdateProgress(update)
		require.NoError(t, err)
	}

	// Retrieve all updates
	retrieved, err := store.GetUpdates("test-get-updates-1", nil)
	require.NoError(t, err)
	assert.Len(t, retrieved, 3, "Should retrieve all 3 updates")

	// Verify updates are in chronological order
	assert.Equal(t, "Received at actor1", retrieved[0].Message)
	assert.Equal(t, "Processing at actor1", retrieved[1].Message)
	assert.Equal(t, "Completed at actor1", retrieved[2].Message)

	// Verify task state is preserved
	assert.Equal(t, "received", *retrieved[0].TaskState)
	assert.Equal(t, "processing", *retrieved[1].TaskState)
	assert.Equal(t, "completed", *retrieved[2].TaskState)
}

// TestPgStore_GetUpdates_Since tests retrieving updates since a specific time
func TestPgStore_GetUpdates_Since(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	task := &types.Task{
		ID: "test-get-updates-since-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{},
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(task)
	require.NoError(t, err)

	firstUpdate := types.TaskUpdate{
		ID:              "test-get-updates-since-1",
		Status:          types.TaskStatusRunning,
		ProgressPercent: floatPtr(10.0),
		Prev:            []string{},
		Curr:            "actor1",
		Next:            []string{},
		TaskState:       strPtr("received"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(firstUpdate)
	require.NoError(t, err)

	cutoffTime := time.Now()
	time.Sleep(10 * time.Millisecond)

	secondUpdate := types.TaskUpdate{
		ID:              "test-get-updates-since-1",
		Status:          types.TaskStatusRunning,
		ProgressPercent: floatPtr(50.0),
		Prev:            []string{},
		Curr:            "actor1",
		Next:            []string{},
		TaskState:       strPtr("processing"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(secondUpdate)
	require.NoError(t, err)

	// Get updates since cutoff time
	retrieved, err := store.GetUpdates("test-get-updates-since-1", &cutoffTime)
	require.NoError(t, err)
	assert.Len(t, retrieved, 1, "Should only get updates after cutoff time")
	assert.Equal(t, "processing", *retrieved[0].TaskState)
}

// TestPgStore_Update_FinalStatus tests final status updates
func TestPgStore_Update_FinalStatus(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	task := &types.Task{
		ID: "test-final-status-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(task)
	require.NoError(t, err)

	// Send final success update
	finalUpdate := types.TaskUpdate{
		ID:        "test-final-status-1",
		Status:    types.TaskStatusSucceeded,
		Message:   "Task completed successfully",
		Result:    map[string]interface{}{"output": "success"},
		Timestamp: time.Now(),
	}

	err = store.Update(finalUpdate)
	require.NoError(t, err)

	// Verify final state
	retrieved, err := store.Get("test-final-status-1")
	require.NoError(t, err)
	assert.Equal(t, types.TaskStatusSucceeded, retrieved.Status)
	assert.NotNil(t, retrieved.Result)
	assert.Equal(t, "Task completed successfully", retrieved.Message)
}

// TestPgStore_ConcurrentUpdates tests concurrent progress updates
func TestPgStore_ConcurrentUpdates(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	task := &types.Task{
		ID: "test-concurrent-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2", "actor3"},
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(task)
	require.NoError(t, err)

	// Send 10 concurrent updates
	done := make(chan error, 10)
	for i := 0; i < 10; i++ {
		go func(idx int) {
			update := types.TaskUpdate{
				ID:              "test-concurrent-1",
				Status:          types.TaskStatusRunning,
				ProgressPercent: floatPtr(float64(idx * 10)),
				Prev:            []string{},
				Curr:            "actor1",
				Next:            []string{"actor2", "actor3"},
				TaskState:       strPtr("processing"),
				Timestamp:       time.Now(),
			}
			done <- store.UpdateProgress(update)
		}(i)
	}

	// Wait for all updates
	for i := 0; i < 10; i++ {
		err := <-done
		assert.NoError(t, err)
	}

	// Verify task state is consistent
	retrieved, err := store.Get("test-concurrent-1")
	require.NoError(t, err)
	assert.Equal(t, types.TaskStatusRunning, retrieved.Status)
	assert.GreaterOrEqual(t, retrieved.ProgressPercent, 0.0)
}

// TestPgStore_IsActive tests task active status checking
func TestPgStore_IsActive(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	tests := []struct {
		name       string
		task       *types.Task
		update     *types.TaskUpdate
		wantActive bool
	}{
		{
			name: "pending task is active",
			task: &types.Task{
				ID: "test-active-pending",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			wantActive: true,
		},
		{
			name: "running task is active",
			task: &types.Task{
				ID: "test-active-running",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			update: &types.TaskUpdate{
				ID:        "test-active-running",
				Status:    types.TaskStatusRunning,
				Timestamp: time.Now(),
			},
			wantActive: true,
		},
		{
			name: "succeeded task is not active",
			task: &types.Task{
				ID: "test-active-succeeded",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			update: &types.TaskUpdate{
				ID:        "test-active-succeeded",
				Status:    types.TaskStatusSucceeded,
				Result:    map[string]interface{}{"output": "done"},
				Timestamp: time.Now(),
			},
			wantActive: false,
		},
		{
			name: "failed task is not active",
			task: &types.Task{
				ID: "test-active-failed",
				Route: types.Route{
					Prev: []string{},
					Curr: "actor1",
					Next: []string{},
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			update: &types.TaskUpdate{
				ID:        "test-active-failed",
				Status:    types.TaskStatusFailed,
				Error:     "Something went wrong",
				Timestamp: time.Now(),
			},
			wantActive: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := store.Create(tt.task)
			require.NoError(t, err)

			if tt.update != nil {
				err = store.Update(*tt.update)
				require.NoError(t, err)
			}

			active := store.IsActive(tt.task.ID)
			assert.Equal(t, tt.wantActive, active)
		})
	}
}
