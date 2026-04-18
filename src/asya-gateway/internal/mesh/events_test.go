package mesh

import (
	"encoding/json"
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestEnrichProgressEvent_MapsReceivedToRunning(t *testing.T) {
	data, _ := json.Marshal(map[string]any{
		"prev": []any{},
		"curr": "actor-1",
		"next": []any{"actor-2", "actor-3"},
	})
	event := types.Event{Type: "status", Status: "received", Data: data}

	out := enrichProgressEvent(event)

	assert.Equal(t, types.MessageStatusRunning, out.Status)
}

func TestEnrichProgressEvent_MapsProcessingToRunning(t *testing.T) {
	data, _ := json.Marshal(map[string]any{"prev": []any{}, "curr": "a", "next": []any{}})
	event := types.Event{Type: "status", Status: "processing", Data: data}
	out := enrichProgressEvent(event)
	assert.Equal(t, types.MessageStatusRunning, out.Status)
}

func TestEnrichProgressEvent_MapsCompletedToRunning(t *testing.T) {
	data, _ := json.Marshal(map[string]any{"prev": []any{}, "curr": "a", "next": []any{}})
	event := types.Event{Type: "status", Status: "completed", Data: data}
	out := enrichProgressEvent(event)
	assert.Equal(t, types.MessageStatusRunning, out.Status)
}

func TestEnrichProgressEvent_PassesThroughKnownStatuses(t *testing.T) {
	for _, s := range []types.MessageStatus{"running", "succeeded", "failed", "canceled"} {
		data, _ := json.Marshal(map[string]any{})
		out := enrichProgressEvent(types.Event{Type: "status", Status: s, Data: data})
		assert.Equal(t, s, out.Status, "status %q should pass through unchanged", s)
	}
}

func TestEnrichProgressEvent_InjectsProgressPercent(t *testing.T) {
	tests := []struct {
		name     string
		prev     []any
		next     []any
		expected float64
	}{
		{"first of 3", []any{}, []any{"b", "c"}, 100.0 / 3},
		{"middle of 3", []any{"a"}, []any{"c"}, 200.0 / 3},
		{"last of 3", []any{"a", "b"}, []any{}, 100.0},
		{"only actor", []any{}, []any{}, 0}, // total=1, no injection
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, _ := json.Marshal(map[string]any{
				"prev": tt.prev,
				"curr": "actor",
				"next": tt.next,
			})
			out := enrichProgressEvent(types.Event{Type: "status", Status: "received", Data: data})
			var d map[string]any
			require.NoError(t, json.Unmarshal(out.Data, &d))
			if tt.expected == 0 {
				_, exists := d["progress_percent"]
				assert.False(t, exists, "should not inject progress_percent for single-actor")
			} else {
				assert.InDelta(t, tt.expected, d["progress_percent"], 0.01)
			}
		})
	}
}

func TestEnrichProgressEvent_UpdatesStatusInsideDataBlob(t *testing.T) {
	data, _ := json.Marshal(map[string]any{
		"status": "received",
		"prev":   []any{},
		"curr":   "a",
		"next":   []any{"b"},
	})
	out := enrichProgressEvent(types.Event{Type: "status", Status: "received", Data: data})
	var d map[string]any
	require.NoError(t, json.Unmarshal(out.Data, &d))
	assert.Equal(t, "running", d["status"], "data.status should be mapped to 'running'")
}

func TestEnrichProgressEvent_DoesNotOverwriteExistingProgressPercent(t *testing.T) {
	data, _ := json.Marshal(map[string]any{
		"prev":             []any{},
		"curr":             "a",
		"next":             []any{"b"},
		"progress_percent": 42.0,
	})
	out := enrichProgressEvent(types.Event{Type: "status", Status: "received", Data: data})
	var d map[string]any
	require.NoError(t, json.Unmarshal(out.Data, &d))
	assert.Equal(t, 42.0, d["progress_percent"])
}
