package mesh

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"

	"github.com/deliveryhero/asya/asya-gateway/internal/store"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// HandleCancel processes DELETE /api/v1/mesh/{id}
//
// Steps:
//  1. Get current message
//  2. If already terminal, return 204 (idempotent)
//  3. Update status to canceled
//  4. Publish cancel event to subscribers
//  5. Return 204
func (h *Handler) HandleCancel(w http.ResponseWriter, r *http.Request, id string) {
	msg, err := h.store.Get(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
		return
	}
	if err != nil {
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	// Already terminal - idempotent
	if msg.Status.IsTerminal() {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	// Update to canceled
	cancelData, _ := json.Marshal(map[string]any{"status": "canceled"})
	err = h.store.UpdateStatus(r.Context(), id, types.MessageStatusCanceled, cancelData)
	if errors.Is(err, store.ErrStaleStatus) {
		// Race: became terminal between Get and UpdateStatus
		w.WriteHeader(http.StatusNoContent)
		return
	}
	if err != nil {
		slog.Error("Failed to cancel message", "error", err, "id", id)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	// Notify subscribers
	h.store.Publish(id, types.Event{
		Type:   "status",
		Status: types.MessageStatusCanceled,
		Data:   cancelData,
	})

	w.WriteHeader(http.StatusNoContent)
}
