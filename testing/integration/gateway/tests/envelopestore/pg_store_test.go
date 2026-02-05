//go:build integration

package envelopestore

import (
	"context"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/envelopestore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func setupPgStore(t *testing.T) (*envelopestore.PgStore, func()) {
	t.Helper()

	ctx := context.Background()

	err := truncateTestTables(ctx)
	require.NoError(t, err, "Failed to truncate test tables")

	store, err := envelopestore.NewPgStore(ctx, getPostgresURL())
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

	envelope := &types.Envelope{
		ID: "test-create-get-1",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2", "actor3"},
			Current: 0,
		},
		Payload:    map[string]interface{}{"data": "test"},
		TimeoutSec: 300,
	}

	err := store.Create(envelope)
	require.NoError(t, err)

	retrieved, err := store.Get("test-create-get-1")
	require.NoError(t, err)
	assert.Equal(t, "test-create-get-1", retrieved.ID)
	assert.Equal(t, types.EnvelopeStatusPending, retrieved.Status)
	assert.Equal(t, []string{"actor1", "actor2", "actor3"}, retrieved.Route.Actors)
	assert.Equal(t, 0, retrieved.Route.Current)
	assert.Equal(t, 3, retrieved.TotalActors)
	assert.Equal(t, 0, retrieved.ActorsCompleted)
	assert.Equal(t, 0.0, retrieved.ProgressPercent)
}

// TestPgStore_UpdateProgress_RouteActorsPersistence tests that route_actors is persisted
func TestPgStore_UpdateProgress_RouteActorsPersistence(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	envelope := &types.Envelope{
		ID: "test-route-persist-1",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2"},
			Current: 0,
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(envelope)
	require.NoError(t, err)

	// Simulate actor modifying route by adding more actors
	modifiedRoute := []string{"actor1", "actor2", "actor3", "actor4"}

	update := types.EnvelopeUpdate{
		ID:              "test-route-persist-1",
		Status:          types.EnvelopeStatusRunning,
		ProgressPercent: floatPtr(25.0),
		Actors:          modifiedRoute,
		CurrentActorIdx: intPtr(0),
		EnvelopeState:   strPtr("processing"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(update)
	require.NoError(t, err)

	// Verify route was persisted
	retrieved, err := store.Get("test-route-persist-1")
	require.NoError(t, err)
	assert.Equal(t, modifiedRoute, retrieved.Route.Actors, "Route actors should be updated")
	assert.Equal(t, 4, retrieved.TotalActors, "TotalActors should be updated")
	assert.Equal(t, 0, retrieved.CurrentActorIdx, "CurrentActorIdx should be updated")
	assert.Equal(t, "actor1", retrieved.CurrentActorName, "CurrentActorName should be derived")
}

// TestPgStore_UpdateProgress_MultipleUpdates tests multiple progress updates with route changes
func TestPgStore_UpdateProgress_MultipleUpdates(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	envelope := &types.Envelope{
		ID: "test-multi-update-1",
		Route: types.Route{
			Actors:  []string{"step1", "step2"},
			Current: 0,
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(envelope)
	require.NoError(t, err)

	// First update: extend route
	update1 := types.EnvelopeUpdate{
		ID:              "test-multi-update-1",
		Status:          types.EnvelopeStatusRunning,
		ProgressPercent: floatPtr(10.0),
		Actors:          []string{"step1", "step2", "step3"},
		CurrentActorIdx: intPtr(0),
		EnvelopeState:   strPtr("received"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(update1)
	require.NoError(t, err)

	// Second update: further extend route
	update2 := types.EnvelopeUpdate{
		ID:              "test-multi-update-1",
		Status:          types.EnvelopeStatusRunning,
		ProgressPercent: floatPtr(50.0),
		Actors:          []string{"step1", "step2", "step3", "step4", "step5"},
		CurrentActorIdx: intPtr(1),
		EnvelopeState:   strPtr("processing"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(update2)
	require.NoError(t, err)

	// Verify final state
	retrieved, err := store.Get("test-multi-update-1")
	require.NoError(t, err)
	assert.Equal(t, []string{"step1", "step2", "step3", "step4", "step5"}, retrieved.Route.Actors)
	assert.Equal(t, 5, retrieved.TotalActors)
	assert.Equal(t, 1, retrieved.CurrentActorIdx)
	assert.Equal(t, "step2", retrieved.CurrentActorName)
	assert.InDelta(t, 50.0, retrieved.ProgressPercent, 0.1)
}

// TestPgStore_GetUpdates tests retrieving update history for SSE streaming
func TestPgStore_GetUpdates(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	envelope := &types.Envelope{
		ID: "test-get-updates-1",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2"},
			Current: 0,
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(envelope)
	require.NoError(t, err)

	// Send multiple progress updates
	updates := []types.EnvelopeUpdate{
		{
			ID:              "test-get-updates-1",
			Status:          types.EnvelopeStatusRunning,
			ProgressPercent: floatPtr(10.0),
			Actors:          []string{"actor1", "actor2"},
			CurrentActorIdx: intPtr(0),
			EnvelopeState:   strPtr("received"),
			Message:         "Received at actor1",
			Timestamp:       time.Now(),
		},
		{
			ID:              "test-get-updates-1",
			Status:          types.EnvelopeStatusRunning,
			ProgressPercent: floatPtr(50.0),
			Actors:          []string{"actor1", "actor2"},
			CurrentActorIdx: intPtr(0),
			EnvelopeState:   strPtr("processing"),
			Message:         "Processing at actor1",
			Timestamp:       time.Now().Add(100 * time.Millisecond),
		},
		{
			ID:              "test-get-updates-1",
			Status:          types.EnvelopeStatusRunning,
			ProgressPercent: floatPtr(100.0),
			Actors:          []string{"actor1", "actor2"},
			CurrentActorIdx: intPtr(0),
			EnvelopeState:   strPtr("completed"),
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

	// Verify envelope state is preserved
	assert.Equal(t, "received", *retrieved[0].EnvelopeState)
	assert.Equal(t, "processing", *retrieved[1].EnvelopeState)
	assert.Equal(t, "completed", *retrieved[2].EnvelopeState)
}

// TestPgStore_GetUpdates_Since tests retrieving updates since a specific time
func TestPgStore_GetUpdates_Since(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	envelope := &types.Envelope{
		ID: "test-get-updates-since-1",
		Route: types.Route{
			Actors:  []string{"actor1"},
			Current: 0,
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(envelope)
	require.NoError(t, err)

	firstUpdate := types.EnvelopeUpdate{
		ID:              "test-get-updates-since-1",
		Status:          types.EnvelopeStatusRunning,
		ProgressPercent: floatPtr(10.0),
		Actors:          []string{"actor1"},
		CurrentActorIdx: intPtr(0),
		EnvelopeState:   strPtr("received"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(firstUpdate)
	require.NoError(t, err)

	cutoffTime := time.Now()
	time.Sleep(10 * time.Millisecond)

	secondUpdate := types.EnvelopeUpdate{
		ID:              "test-get-updates-since-1",
		Status:          types.EnvelopeStatusRunning,
		ProgressPercent: floatPtr(50.0),
		Actors:          []string{"actor1"},
		CurrentActorIdx: intPtr(0),
		EnvelopeState:   strPtr("processing"),
		Timestamp:       time.Now(),
	}

	err = store.UpdateProgress(secondUpdate)
	require.NoError(t, err)

	// Get updates since cutoff time
	retrieved, err := store.GetUpdates("test-get-updates-since-1", &cutoffTime)
	require.NoError(t, err)
	assert.Len(t, retrieved, 1, "Should only get updates after cutoff time")
	assert.Equal(t, "processing", *retrieved[0].EnvelopeState)
}

// TestPgStore_Update_FinalStatus tests final status updates
func TestPgStore_Update_FinalStatus(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	envelope := &types.Envelope{
		ID: "test-final-status-1",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2"},
			Current: 0,
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(envelope)
	require.NoError(t, err)

	// Send final success update
	finalUpdate := types.EnvelopeUpdate{
		ID:        "test-final-status-1",
		Status:    types.EnvelopeStatusSucceeded,
		Message:   "Envelope completed successfully",
		Result:    map[string]interface{}{"output": "success"},
		Timestamp: time.Now(),
	}

	err = store.Update(finalUpdate)
	require.NoError(t, err)

	// Verify final state
	retrieved, err := store.Get("test-final-status-1")
	require.NoError(t, err)
	assert.Equal(t, types.EnvelopeStatusSucceeded, retrieved.Status)
	assert.NotNil(t, retrieved.Result)
	assert.Equal(t, "Envelope completed successfully", retrieved.Message)
}

// TestPgStore_ConcurrentUpdates tests concurrent progress updates
func TestPgStore_ConcurrentUpdates(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	envelope := &types.Envelope{
		ID: "test-concurrent-1",
		Route: types.Route{
			Actors:  []string{"actor1", "actor2", "actor3"},
			Current: 0,
		},
		Payload: map[string]interface{}{"data": "test"},
	}

	err := store.Create(envelope)
	require.NoError(t, err)

	// Send 10 concurrent updates
	done := make(chan error, 10)
	for i := 0; i < 10; i++ {
		go func(idx int) {
			update := types.EnvelopeUpdate{
				ID:              "test-concurrent-1",
				Status:          types.EnvelopeStatusRunning,
				ProgressPercent: floatPtr(float64(idx * 10)),
				Actors:          []string{"actor1", "actor2", "actor3"},
				CurrentActorIdx: intPtr(0),
				EnvelopeState:   strPtr("processing"),
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

	// Verify envelope state is consistent
	retrieved, err := store.Get("test-concurrent-1")
	require.NoError(t, err)
	assert.Equal(t, types.EnvelopeStatusRunning, retrieved.Status)
	assert.GreaterOrEqual(t, retrieved.ProgressPercent, 0.0)
}

// TestPgStore_IsActive tests envelope active status checking
func TestPgStore_IsActive(t *testing.T) {
	store, cleanup := setupPgStore(t)
	defer cleanup()

	tests := []struct {
		name       string
		envelope   *types.Envelope
		update     *types.EnvelopeUpdate
		wantActive bool
	}{
		{
			name: "pending envelope is active",
			envelope: &types.Envelope{
				ID: "test-active-pending",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			wantActive: true,
		},
		{
			name: "running envelope is active",
			envelope: &types.Envelope{
				ID: "test-active-running",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			update: &types.EnvelopeUpdate{
				ID:        "test-active-running",
				Status:    types.EnvelopeStatusRunning,
				Timestamp: time.Now(),
			},
			wantActive: true,
		},
		{
			name: "succeeded envelope is not active",
			envelope: &types.Envelope{
				ID: "test-active-succeeded",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			update: &types.EnvelopeUpdate{
				ID:        "test-active-succeeded",
				Status:    types.EnvelopeStatusSucceeded,
				Result:    map[string]interface{}{"output": "done"},
				Timestamp: time.Now(),
			},
			wantActive: false,
		},
		{
			name: "failed envelope is not active",
			envelope: &types.Envelope{
				ID: "test-active-failed",
				Route: types.Route{
					Actors:  []string{"actor1"},
					Current: 0,
				},
				Payload: map[string]interface{}{"data": "test"},
			},
			update: &types.EnvelopeUpdate{
				ID:        "test-active-failed",
				Status:    types.EnvelopeStatusFailed,
				Error:     "Something went wrong",
				Timestamp: time.Now(),
			},
			wantActive: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := store.Create(tt.envelope)
			require.NoError(t, err)

			if tt.update != nil {
				err = store.Update(*tt.update)
				require.NoError(t, err)
			}

			active := store.IsActive(tt.envelope.ID)
			assert.Equal(t, tt.wantActive, active)
		})
	}
}
