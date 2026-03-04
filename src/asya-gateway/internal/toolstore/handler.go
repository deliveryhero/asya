package toolstore

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// Handler handles HTTP requests for /mesh/expose.
type Handler struct {
	registry *Registry
}

// NewHandler creates a new handler for tool registration.
func NewHandler(registry *Registry) *Handler {
	return &Handler{
		registry: registry,
	}
}

// HandleExpose dispatches GET (list) and POST (upsert) for /mesh/expose.
func (h *Handler) HandleExpose(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		h.handleList(w, r)
	case http.MethodPost:
		h.handleRegister(w, r)
	default:
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

// handleList returns all tools as JSON array.
func (h *Handler) handleList(w http.ResponseWriter, r *http.Request) {
	tools := h.registry.All()

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(tools); err != nil {
		http.Error(w, fmt.Sprintf("failed to encode response: %v", err), http.StatusInternalServerError)
		return
	}
}

// handleRegister parses RegisterRequest, creates/updates tool, returns 201 (new) or 200 (update).
func (h *Handler) handleRegister(w http.ResponseWriter, r *http.Request) {
	var req RegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf("invalid request body: %v", err), http.StatusBadRequest)
		return
	}

	// Resolve actor and route_next from either "actor" or "route" field
	actor := req.Actor
	var routeNext []string
	if len(req.Route) > 0 {
		actor = req.Route[0]
		if len(req.Route) > 1 {
			routeNext = req.Route[1:]
		}
	}

	// Map RegisterRequest to Tool
	tool := Tool{
		Name:        req.Name,
		Actor:       actor,
		RouteNext:   routeNext,
		Description: req.Description,
		Parameters:  req.Parameters,
		TimeoutSec:  req.TimeoutSec,
		Progress:    req.Progress,
		MCPEnabled:  true,
	}

	// MCPEnabled defaults to true
	if req.MCPEnabled != nil {
		tool.MCPEnabled = *req.MCPEnabled
	}

	// Map A2A config
	if req.A2A != nil {
		tool.A2AEnabled = req.A2A.Enabled
		tool.A2ATags = req.A2A.Tags
		tool.A2AInputModes = req.A2A.InputModes
		tool.A2AOutputModes = req.A2A.OutputModes
		tool.A2AExamples = req.A2A.Examples
	}

	// Check if tool exists
	existing := h.registry.GetByName(req.Name)

	// Upsert to registry
	if err := h.registry.Upsert(r.Context(), tool); err != nil {
		http.Error(w, fmt.Sprintf("failed to register tool: %v", err), http.StatusInternalServerError)
		return
	}

	// Return 201 for new, 200 for update
	statusCode := http.StatusOK
	if existing == nil {
		statusCode = http.StatusCreated
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	if err := json.NewEncoder(w).Encode(tool); err != nil {
		http.Error(w, fmt.Sprintf("failed to encode response: %v", err), http.StatusInternalServerError)
		return
	}
}
