package mesh

import (
	"errors"
	"net/http"

	"github.com/deliveryhero/asya/asya-gateway/internal/store"
)

// HandleGet processes GET /api/v1/mesh/{id}
//
// Returns 200 with Message JSON.
// Returns 404 if not found.
func (h *Handler) HandleGet(w http.ResponseWriter, r *http.Request, id string) {
	msg, err := h.store.Get(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
		return
	}
	if err != nil {
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	writeJSON(w, http.StatusOK, messageToResponse(msg))
}
