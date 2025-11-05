package messages

import "encoding/json"

// Route represents the routing information for a message
type Route struct {
	Steps    []string               `json:"steps"`
	Current  int                    `json:"current"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// Message represents the full message structure
type Message struct {
	JobID   string          `json:"job_id"` // Required top-level job_id
	Payload json.RawMessage `json:"payload"`
	Route   Route           `json:"route"`
}

// GetCurrentStep returns the current step name from the route
func (r *Route) GetCurrentStep() string {
	if r.Current >= 0 && r.Current < len(r.Steps) {
		return r.Steps[r.Current]
	}
	return ""
}

// GetNextStep returns the next step name, or empty if at the end
func (r *Route) GetNextStep() string {
	nextIndex := r.Current + 1
	if nextIndex >= 0 && nextIndex < len(r.Steps) {
		return r.Steps[nextIndex]
	}
	return ""
}

// HasNextStep returns true if there are more steps after current
func (r *Route) HasNextStep() bool {
	return r.Current+1 < len(r.Steps)
}

// IncrementCurrent creates a new route with incremented current index
func (r *Route) IncrementCurrent() Route {
	return Route{
		Steps:    r.Steps,
		Current:  r.Current + 1,
		Metadata: r.Metadata,
	}
}
