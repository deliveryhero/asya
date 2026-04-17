package mesh

import (
	"net/http"
	"strconv"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// HandleList processes GET /api/v1/mesh/?status=running&limit=10&offset=0
//
// Returns 200 {"messages": [...], "total": 42}
func (h *Handler) HandleList(w http.ResponseWriter, r *http.Request) {
	params := types.ListParams{
		Prefix: "msg/",
		Sort:   []string{"-created_at"},
	}

	// Parse query parameters
	if status := r.URL.Query().Get("status"); status != "" {
		params.Filters = map[string]any{"status": status}
	}
	if limitStr := r.URL.Query().Get("limit"); limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil && v > 0 {
			params.Limit = v
		}
	}
	if offsetStr := r.URL.Query().Get("offset"); offsetStr != "" {
		if v, err := strconv.Atoi(offsetStr); err == nil && v >= 0 {
			params.Offset = v
		}
	}

	messages, total, err := h.store.List(r.Context(), params)
	if err != nil {
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	// Build response
	msgResponses := make([]map[string]any, 0, len(messages))
	for _, msg := range messages {
		msgResponses = append(msgResponses, messageToResponse(msg))
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"messages": msgResponses,
		"total":    total,
	})
}
