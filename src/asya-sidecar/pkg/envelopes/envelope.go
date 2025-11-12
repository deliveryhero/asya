package envelopes

import "encoding/json"

// Route represents the routing information for a message
type Route struct {
	Actors   []string               `json:"actors"`
	Current  int                    `json:"current"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// Envelope represents the full envelope structure with routing metadata.
//
// Fanout ID Semantics:
// When an actor returns an array response, the sidecar creates multiple envelopes (fanout).
// The first fanout envelope retains the original ID to preserve SSE streaming compatibility.
// Subsequent fanout envelopes receive suffixed IDs following the pattern: {original_id}-{index}
//
// Example fanout from envelope "abc-123" returning 3 items:
//   - Index 0: ID = "abc-123"      ParentID = nil     (original ID, SSE clients can track this)
//   - Index 1: ID = "abc-123-1"    ParentID = "abc-123" (fanout child)
//   - Index 2: ID = "abc-123-2"    ParentID = "abc-123" (fanout child)
//
// All fanout children have ParentID set to the original envelope ID for traceability.
type Envelope struct {
	ID       string                 `json:"id"`
	ParentID *string                `json:"parent_id,omitempty"` // Set for fanout children (index > 0)
	Route    Route                  `json:"route"`
	Headers  map[string]interface{} `json:"headers,omitempty"`
	Payload  json.RawMessage        `json:"payload"`
}

// GetCurrentActor returns the current actor name from the route
func (r *Route) GetCurrentActor() string {
	if r.Current >= 0 && r.Current < len(r.Actors) {
		return r.Actors[r.Current]
	}
	return ""
}

// GetNextActor returns the next actor name, or empty if at the end
func (r *Route) GetNextActor() string {
	nextIndex := r.Current + 1
	if nextIndex >= 0 && nextIndex < len(r.Actors) {
		return r.Actors[nextIndex]
	}
	return ""
}

// HasNextActor returns true if there are more actors after current
func (r *Route) HasNextActor() bool {
	return r.Current+1 < len(r.Actors)
}

// IncrementCurrent creates a new route with incremented current index
func (r *Route) IncrementCurrent() Route {
	return Route{
		Actors:   r.Actors,
		Current:  r.Current + 1,
		Metadata: r.Metadata,
	}
}
