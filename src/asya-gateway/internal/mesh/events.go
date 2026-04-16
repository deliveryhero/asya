package mesh

import (
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/store"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// HandleEventsGet processes GET /api/v1/mesh/{id}/events
//
// SSE stream. Steps:
//  1. Get current message from store
//  2. If terminal, write single SSE event and return
//  3. Write current status as first SSE event (catch-up)
//  4. Subscribe to in-process channel
//  5. Stream events until terminal or client disconnect
//  6. Unsubscribe on exit
func (h *Handler) HandleEventsGet(w http.ResponseWriter, r *http.Request, id string) {
	// Check if client supports SSE
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	// Get current state from store
	msg, err := h.store.Get(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
		return
	}
	if err != nil {
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	// Set SSE headers
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)

	// If already terminal, write single event and return
	if msg.Status.IsTerminal() {
		_ = writeSSE(w, flusher, "status", msg.Data)
		return
	}

	// Write current status as catch-up event
	if err = writeSSE(w, flusher, "status", msg.Data); err != nil {
		return
	}

	// Subscribe to live events
	ch := h.store.Subscribe(id)
	defer h.store.Unsubscribe(id, ch)

	keepalive := time.NewTicker(15 * time.Second)
	defer keepalive.Stop()

	ctx := r.Context()
	for {
		select {
		case event, ok := <-ch:
			if !ok {
				return
			}
			if err = writeSSE(w, flusher, event.Type, event.Data); err != nil {
				return
			}
			if event.Type == "status" && event.Status.IsTerminal() {
				return
			}
		case <-keepalive.C:
			if _, err = fmt.Fprintf(w, ":keepalive\n\n"); err != nil { // nosemgrep
				return
			}
			flusher.Flush()
		case <-ctx.Done():
			return
		}
	}
}

// HandleEventsPost processes POST /api/v1/mesh/{id}/events (internal port)
//
// Request body:
//
//	{"type": "status", "status": "running", "data": {"actor": "x", "progress": 50}}
//	{"type": "fly", "data": {"text": "token..."}}
//
// Steps:
//  1. Parse event from request body
//  2. If type=status: update store (monotonic ordering enforced)
//  3. Publish event to in-process subscribers
//  4. Return 204
func (h *Handler) HandleEventsPost(w http.ResponseWriter, r *http.Request, id string) {
	var event types.Event
	if err := readJSON(r, &event); err != nil {
		http.Error(w, `{"error":"invalid JSON body"}`, http.StatusBadRequest)
		return
	}

	if event.Type == "status" {
		// Update store with monotonic ordering
		err := h.store.UpdateStatus(r.Context(), id, event.Status, event.Data)
		if errors.Is(err, store.ErrStaleStatus) {
			// Stale status update - return 204 without publishing to subscribers
			slog.Debug("Stale status update ignored", "id", id, "status", event.Status)
			w.WriteHeader(http.StatusNoContent)
			return
		} else if errors.Is(err, store.ErrNotFound) {
			http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
			return
		} else if err != nil {
			slog.Error("Failed to update status", "error", err, "id", id)
			http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
			return
		}
	}
	// FLY events are ephemeral - never written to store

	// Publish to in-process subscribers
	h.store.Publish(id, event)

	w.WriteHeader(http.StatusNoContent)
}

// writeSSE writes a single SSE event to the response writer.
// Returns an error if the write fails (e.g. client disconnected).
func writeSSE(w http.ResponseWriter, flusher http.Flusher, eventType string, data json.RawMessage) error {
	if _, err := fmt.Fprintf(w, "event: %s\n", eventType); err != nil { // nosemgrep
		return err
	}
	if data != nil {
		if _, err := fmt.Fprintf(w, "data: %s\n", string(data)); err != nil { // nosemgrep
			return err
		}
	} else {
		if _, err := fmt.Fprintf(w, "data: {}\n"); err != nil { // nosemgrep
			return err
		}
	}
	if _, err := fmt.Fprintf(w, "\n"); err != nil { // nosemgrep
		return err
	}
	flusher.Flush()
	return nil
}
