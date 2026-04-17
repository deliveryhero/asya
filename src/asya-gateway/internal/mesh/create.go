package mesh

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// createRequest is the JSON body for POST /api/v1/mesh/?actor={name}.
type createRequest struct {
	Payload any            `json:"payload,omitempty"`
	Headers map[string]any `json:"headers,omitempty"`
	Timeout int            `json:"timeout,omitempty"` // seconds
}

// HandleCreate processes POST /api/v1/mesh/?actor={name}
//
// Steps:
//  1. Parse actor from query param (required)
//  2. Generate UUID for message ID
//  3. Build MessageData with actor, payload, headers, deadline
//  4. Stamp x-asya-gateway-url into headers
//  5. Store message in state-proxy (status: pending)
//  6. Build envelope and send to actor queue
//  7. Return 201 {"id": "..."}
func (h *Handler) HandleCreate(w http.ResponseWriter, r *http.Request) {
	actor := r.URL.Query().Get("actor")
	if actor == "" {
		http.Error(w, `{"error":"actor query parameter required"}`, http.StatusBadRequest)
		return
	}

	var req createRequest
	if err := readJSON(r, &req); err != nil {
		http.Error(w, `{"error":"invalid JSON body"}`, http.StatusBadRequest)
		return
	}

	// Generate message ID
	id := uuid.New().String()
	now := time.Now().UTC()

	// Stamp gateway URL into headers
	if req.Headers == nil {
		req.Headers = make(map[string]any)
	}
	req.Headers["x-asya-gateway-url"] = h.gatewayURL

	// Calculate deadline
	deadlineAt := ""
	if req.Timeout > 0 {
		deadlineAt = now.Add(time.Duration(req.Timeout) * time.Second).Format(time.RFC3339)
	}

	// Build message data
	msgData := types.MessageData{
		Actor:      actor,
		Payload:    req.Payload,
		Headers:    req.Headers,
		DeadlineAt: deadlineAt,
	}
	dataBytes, err := json.Marshal(msgData)
	if err != nil {
		slog.Error("Failed to marshal message data", "error", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	// Store message
	msg := &types.Message{
		ID:        id,
		Status:    types.MessageStatusPending,
		Data:      dataBytes,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := h.store.Create(r.Context(), msg); err != nil {
		slog.Error("Failed to create message", "error", err)
		http.Error(w, `{"error":"failed to create message"}`, http.StatusInternalServerError)
		return
	}

	// Build envelope for actor queue
	envelope := map[string]any{
		"id": id,
		"route": map[string]any{
			"prev": []string{},
			"curr": actor,
			"next": []string{},
		},
		"headers": req.Headers,
		"payload": req.Payload,
	}
	if req.Timeout > 0 {
		envelope["status"] = map[string]any{
			"deadline_at": deadlineAt,
		}
	}

	envelopeBytes, err := json.Marshal(envelope)
	if err != nil {
		slog.Error("Failed to marshal envelope", "error", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	// Dispatch to actor queue
	if err := h.sender.Send(r.Context(), actor, envelopeBytes); err != nil {
		slog.Error("Failed to send envelope to queue", "error", err, "actor", actor)
		http.Error(w, `{"error":"failed to dispatch message"}`, http.StatusInternalServerError)
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{"id": id})
}
