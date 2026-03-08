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

// NewHandler creates a new handler for the tool expose endpoint.
func NewHandler(registry *Registry) *Handler {
	return &Handler{
		registry: registry,
	}
}

// HandleExpose serves GET /mesh/expose (list tools).
// POST is no longer accepted — tools are configured via ConfigMap (flows.yaml).
func (h *Handler) HandleExpose(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		h.handleList(w, r)
	default:
		http.Error(w, "Method not allowed: tools are configured via ConfigMap", http.StatusMethodNotAllowed)
	}
}

// handleList returns all tools as a JSON array.
func (h *Handler) handleList(w http.ResponseWriter, _ *http.Request) {
	tools := h.registry.All()

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(tools); err != nil {
		http.Error(w, fmt.Sprintf("failed to encode response: %v", err), http.StatusInternalServerError)
		return
	}
}
