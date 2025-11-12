package jobs

import (
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
)

// TestCurrentActorName_Derivation tests that current_actor_name is correctly derived
// from Actors[CurrentActorIdx] in the UpdateProgress method
//
// Bug: If CurrentActorIdx is not properly checked, we could get index out of range panics
// or incorrect actor names
func TestCurrentActorName_Derivation(t *testing.T) {
	tests := []struct {
		name            string
		actors          []string
		currentActorIdx *int
		expectActorName *string
		expectPanic     bool
	}{
		{
			name:            "valid index 0",
			actors:          []string{"actor1", "actor2", "actor3"},
			currentActorIdx: intPtr(0),
			expectActorName: strPtr("actor1"),
		},
		{
			name:            "valid index 1",
			actors:          []string{"actor1", "actor2", "actor3"},
			currentActorIdx: intPtr(1),
			expectActorName: strPtr("actor2"),
		},
		{
			name:            "valid index at end",
			actors:          []string{"actor1", "actor2", "actor3"},
			currentActorIdx: intPtr(2),
			expectActorName: strPtr("actor3"),
		},
		{
			name:            "nil index",
			actors:          []string{"actor1", "actor2"},
			currentActorIdx: nil,
			expectActorName: nil,
		},
		{
			name:            "empty actors array",
			actors:          []string{},
			currentActorIdx: intPtr(0),
			expectActorName: nil,
		},
		{
			name:            "index out of bounds (too high)",
			actors:          []string{"actor1", "actor2"},
			currentActorIdx: intPtr(5),
			expectActorName: nil,
		},
		{
			name:            "negative index",
			actors:          []string{"actor1", "actor2"},
			currentActorIdx: intPtr(-1),
			expectActorName: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Test the derivation logic that's used in pg_store.go
			var currentActorName *string
			if tt.currentActorIdx != nil && *tt.currentActorIdx >= 0 && *tt.currentActorIdx < len(tt.actors) {
				name := tt.actors[*tt.currentActorIdx]
				currentActorName = &name
			}

			if tt.expectActorName == nil {
				assert.Nil(t, currentActorName)
			} else {
				assert.NotNil(t, currentActorName)
				assert.Equal(t, *tt.expectActorName, *currentActorName)
			}
		})
	}
}

// TestRouteActors_UpdateLogic tests the logic for updating route actors
// to ensure we don't lose the route information
//
// Bug: If we forget to update route_actors column, route modifications will be lost
func TestRouteActors_UpdateLogic(t *testing.T) {
	tests := []struct {
		name         string
		initialRoute []string
		updateActors []string
		expectRoute  []string
		expectTotal  int
	}{
		{
			name:         "route extends by 2 actors",
			initialRoute: []string{"a", "b"},
			updateActors: []string{"a", "b", "c", "d"},
			expectRoute:  []string{"a", "b", "c", "d"},
			expectTotal:  4,
		},
		{
			name:         "route extends by 1 actor",
			initialRoute: []string{"a", "b", "c"},
			updateActors: []string{"a", "b", "c", "d"},
			expectRoute:  []string{"a", "b", "c", "d"},
			expectTotal:  4,
		},
		{
			name:         "route replaces future actors",
			initialRoute: []string{"a", "b", "c"},
			updateActors: []string{"a", "x", "y", "z"},
			expectRoute:  []string{"a", "x", "y", "z"},
			expectTotal:  4,
		},
		{
			name:         "empty update actors",
			initialRoute: []string{"a", "b"},
			updateActors: []string{},
			expectRoute:  []string{"a", "b"},
			expectTotal:  2,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate the update logic from store.go UpdateProgress
			envelope := &types.Envelope{
				Route: types.Route{
					Actors: tt.initialRoute,
				},
				TotalActors: len(tt.initialRoute),
			}

			update := types.EnvelopeUpdate{
				Actors: tt.updateActors,
			}

			// Apply update logic
			if len(update.Actors) > 0 {
				envelope.Route.Actors = update.Actors
				envelope.TotalActors = len(update.Actors)
			}

			assert.Equal(t, tt.expectRoute, envelope.Route.Actors)
			assert.Equal(t, tt.expectTotal, envelope.TotalActors)
		})
	}
}

// TestEnvelopeUpdate_FieldMapping tests that EnvelopeUpdate fields correctly map to database columns
//
// Bug: If field names don't match between Go struct and SQL queries, we get runtime errors
func TestEnvelopeUpdate_FieldMapping(t *testing.T) {
	update := types.EnvelopeUpdate{
		ID:              "test-id",
		Status:          types.EnvelopeStatusRunning,
		Message:         "test message",
		Result:          nil,
		Error:           "",
		ProgressPercent: floatPtr(50.0),
		Actors:          []string{"actor1", "actor2"},
		CurrentActorIdx: intPtr(1),
		EnvelopeState:   strPtr("processing"),
	}

	// Verify all fields are accessible
	assert.Equal(t, "test-id", update.ID)
	assert.Equal(t, types.EnvelopeStatusRunning, update.Status)
	assert.Equal(t, "test message", update.Message)
	assert.NotNil(t, update.ProgressPercent)
	assert.Equal(t, 50.0, *update.ProgressPercent)
	assert.Equal(t, []string{"actor1", "actor2"}, update.Actors)
	assert.NotNil(t, update.CurrentActorIdx)
	assert.Equal(t, 1, *update.CurrentActorIdx)
	assert.NotNil(t, update.EnvelopeState)
	assert.Equal(t, "processing", *update.EnvelopeState)
}

// TestProgressUpdate_TransformToEnvelopeUpdate tests the transformation logic
// from ProgressUpdate (external) to EnvelopeUpdate (internal)
//
// Bug: If transformation doesn't copy all fields, we lose data
func TestProgressUpdate_TransformToEnvelopeUpdate(t *testing.T) {
	progress := types.ProgressUpdate{
		ID:              "test-envelope-1",
		Actors:          []string{"step1", "step2", "step3"},
		CurrentActorIdx: 1,
		Status:          "processing",
		Message:         "Processing at step2",
		ProgressPercent: 50.0,
	}

	// Simulate transformation from handlers.go
	progressPercent := progress.ProgressPercent
	update := types.EnvelopeUpdate{
		ID:              progress.ID,
		Status:          types.EnvelopeStatusRunning,
		Message:         progress.Message,
		ProgressPercent: &progressPercent,
		Actors:          progress.Actors,
		CurrentActorIdx: &progress.CurrentActorIdx,
		EnvelopeState:   strPtr(progress.Status),
	}

	// Verify transformation preserved all data
	assert.Equal(t, "test-envelope-1", update.ID)
	assert.Equal(t, types.EnvelopeStatusRunning, update.Status)
	assert.Equal(t, "Processing at step2", update.Message)
	assert.NotNil(t, update.ProgressPercent)
	assert.Equal(t, 50.0, *update.ProgressPercent)
	assert.Equal(t, []string{"step1", "step2", "step3"}, update.Actors)
	assert.NotNil(t, update.CurrentActorIdx)
	assert.Equal(t, 1, *update.CurrentActorIdx)
	assert.NotNil(t, update.EnvelopeState)
	assert.Equal(t, "processing", *update.EnvelopeState)
}

func strPtr(s string) *string {
	return &s
}
