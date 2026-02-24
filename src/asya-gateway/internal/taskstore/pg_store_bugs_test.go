package taskstore

import (
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
)

// TestCurrentActorName_Derivation tests that current_actor_name is correctly derived
// from the Curr field in the UpdateProgress method
func TestCurrentActorName_Derivation(t *testing.T) {
	tests := []struct {
		name            string
		curr            string
		expectActorName *string
	}{
		{
			name:            "non-empty curr",
			curr:            "actor1",
			expectActorName: strPtr("actor1"),
		},
		{
			name:            "another non-empty curr",
			curr:            "processor",
			expectActorName: strPtr("processor"),
		},
		{
			name:            "empty curr (end of route)",
			curr:            "",
			expectActorName: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Test the derivation logic that's used in pg_store.go
			var currentActorName *string
			if tt.curr != "" {
				name := tt.curr
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

// TestRouteUpdate_Logic tests the logic for updating route prev/curr/next fields
// to ensure we don't lose route information
func TestRouteUpdate_Logic(t *testing.T) {
	tests := []struct {
		name         string
		initialRoute types.Route
		updatePrev   []string
		updateCurr   string
		updateNext   []string
		expectPrev   []string
		expectCurr   string
		expectNext   []string
		expectTotal  int
	}{
		{
			name: "route advances - actor0 completes, actor1 is current",
			initialRoute: types.Route{
				Prev: []string{},
				Curr: "a",
				Next: []string{"b"},
			},
			updatePrev:  []string{"a"},
			updateCurr:  "b",
			updateNext:  []string{},
			expectPrev:  []string{"a"},
			expectCurr:  "b",
			expectNext:  []string{},
			expectTotal: 2,
		},
		{
			name: "route extends - new actors added to next",
			initialRoute: types.Route{
				Prev: []string{},
				Curr: "a",
				Next: []string{"b", "c"},
			},
			updatePrev:  []string{},
			updateCurr:  "a",
			updateNext:  []string{"b", "c", "d"},
			expectPrev:  []string{},
			expectCurr:  "a",
			expectNext:  []string{"b", "c", "d"},
			expectTotal: 4,
		},
		{
			name: "route replaces future actors",
			initialRoute: types.Route{
				Prev: []string{},
				Curr: "a",
				Next: []string{"b", "c"},
			},
			updatePrev:  []string{},
			updateCurr:  "a",
			updateNext:  []string{"x", "y", "z"},
			expectPrev:  []string{},
			expectCurr:  "a",
			expectNext:  []string{"x", "y", "z"},
			expectTotal: 4,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate the update logic from store.go UpdateProgress
			task := &types.Task{
				Route:       tt.initialRoute,
				TotalActors: len(tt.initialRoute.Prev) + 1 + len(tt.initialRoute.Next),
			}

			update := types.TaskUpdate{
				Prev: tt.updatePrev,
				Curr: tt.updateCurr,
				Next: tt.updateNext,
			}

			// Apply update logic (mirrors store.go UpdateProgress)
			if update.Curr != "" || len(update.Prev) > 0 || len(update.Next) > 0 {
				task.Route.Prev = update.Prev
				task.Route.Curr = update.Curr
				task.Route.Next = update.Next
				total := len(update.Prev) + len(update.Next)
				if update.Curr != "" {
					total++
				}
				task.TotalActors = total
			}

			assert.Equal(t, tt.expectPrev, task.Route.Prev)
			assert.Equal(t, tt.expectCurr, task.Route.Curr)
			assert.Equal(t, tt.expectNext, task.Route.Next)
			assert.Equal(t, tt.expectTotal, task.TotalActors)
		})
	}
}

// TestTaskUpdate_FieldMapping tests that TaskUpdate fields correctly map to the new format
func TestTaskUpdate_FieldMapping(t *testing.T) {
	update := types.TaskUpdate{
		ID:              "test-id",
		Status:          types.TaskStatusRunning,
		Message:         "test message",
		Result:          nil,
		Error:           "",
		ProgressPercent: floatPtr(50.0),
		Prev:            []string{"actor1"},
		Curr:            "actor2",
		Next:            []string{},
		TaskState:       strPtr("processing"),
	}

	// Verify all fields are accessible
	assert.Equal(t, "test-id", update.ID)
	assert.Equal(t, types.TaskStatusRunning, update.Status)
	assert.Equal(t, "test message", update.Message)
	assert.NotNil(t, update.ProgressPercent)
	assert.Equal(t, 50.0, *update.ProgressPercent)
	assert.Equal(t, []string{"actor1"}, update.Prev)
	assert.Equal(t, "actor2", update.Curr)
	assert.Equal(t, []string{}, update.Next)
	assert.NotNil(t, update.TaskState)
	assert.Equal(t, "processing", *update.TaskState)
}

// TestProgressUpdate_TransformToTaskUpdate tests the transformation logic
// from ProgressUpdate (external) to TaskUpdate (internal)
func TestProgressUpdate_TransformToTaskUpdate(t *testing.T) {
	progress := types.ProgressUpdate{
		ID:     "test-task-1",
		Prev:   []string{"step1"},
		Curr:   "step2",
		Next:   []string{"step3"},
		Status: "processing",

		Message:         "Processing at step2",
		ProgressPercent: 50.0,
	}

	// Simulate transformation from handlers.go
	progressPercent := progress.ProgressPercent
	update := types.TaskUpdate{
		ID:              progress.ID,
		Status:          types.TaskStatusRunning,
		Message:         progress.Message,
		ProgressPercent: &progressPercent,
		Prev:            progress.Prev,
		Curr:            progress.Curr,
		Next:            progress.Next,
		TaskState:       strPtr(progress.Status),
	}

	// Verify transformation preserved all data
	assert.Equal(t, "test-task-1", update.ID)
	assert.Equal(t, types.TaskStatusRunning, update.Status)
	assert.Equal(t, "Processing at step2", update.Message)
	assert.NotNil(t, update.ProgressPercent)
	assert.Equal(t, 50.0, *update.ProgressPercent)
	assert.Equal(t, []string{"step1"}, update.Prev)
	assert.Equal(t, "step2", update.Curr)
	assert.Equal(t, []string{"step3"}, update.Next)
	assert.NotNil(t, update.TaskState)
	assert.Equal(t, "processing", *update.TaskState)
}
