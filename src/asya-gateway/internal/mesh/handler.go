package mesh

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/deliveryhero/asya/asya-gateway/internal/store"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Handler holds dependencies for mesh API handlers.
type Handler struct {
	store      store.MessageStore
	sender     EnvelopeSender
	gatewayURL string // stamped into envelope headers as x-asya-gateway-url
}

// EnvelopeSender dispatches envelopes to actor queues.
type EnvelopeSender interface {
	Send(ctx context.Context, actor, namespace string, envelope []byte) error
}

// NewHandler creates a new mesh API handler.
func NewHandler(s store.MessageStore, sender EnvelopeSender, gatewayURL string) *Handler {
	return &Handler{store: s, sender: sender, gatewayURL: gatewayURL}
}

// RegisterExternal registers external API routes (port 8080).
//
//	POST   /api/v1/mesh/           -> Create
//	GET    /api/v1/mesh/           -> List
//	GET    /api/v1/mesh/{id}       -> Get
//	GET    /api/v1/mesh/{id}/events -> SSE Subscribe
//	DELETE /api/v1/mesh/{id}       -> Cancel
func (h *Handler) RegisterExternal(mux *http.ServeMux) {
	mux.HandleFunc("/api/v1/mesh/", func(w http.ResponseWriter, r *http.Request) {
		// Parse path: /api/v1/mesh/, /api/v1/mesh/{id}, /api/v1/mesh/{id}/events
		path := strings.TrimPrefix(r.URL.Path, "/api/v1/mesh/")

		// Root: /api/v1/mesh/
		if path == "" {
			switch r.Method {
			case http.MethodPost:
				h.HandleCreate(w, r)
			case http.MethodGet:
				h.HandleList(w, r)
			default:
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			}
			return
		}

		// Parse {id} and optional /events suffix
		parts := strings.SplitN(path, "/", 2)
		id := parts[0]
		suffix := ""
		if len(parts) > 1 {
			suffix = parts[1]
		}

		if suffix == "events" {
			switch r.Method {
			case http.MethodGet:
				h.HandleEventsGet(w, r, id)
			default:
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			}
			return
		}

		if suffix == "" {
			switch r.Method {
			case http.MethodGet:
				h.HandleGet(w, r, id)
			case http.MethodDelete:
				h.HandleCancel(w, r, id)
			default:
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			}
			return
		}

		http.NotFound(w, r)
	})
}

// RegisterInternal registers internal API routes (port 8081).
//
//	POST   /api/v1/mesh/{id}/events -> Publish event (sidecar)
//	GET    /api/v1/mesh/{id}        -> Get (sidecar heartbeat)
func (h *Handler) RegisterInternal(mux *http.ServeMux) {
	mux.HandleFunc("/api/v1/mesh/", func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/api/v1/mesh/")
		if path == "" {
			http.NotFound(w, r)
			return
		}

		parts := strings.SplitN(path, "/", 2)
		id := parts[0]
		suffix := ""
		if len(parts) > 1 {
			suffix = parts[1]
		}

		if suffix == "events" && r.Method == http.MethodPost {
			h.HandleEventsPost(w, r, id)
			return
		}

		if suffix == "" && r.Method == http.MethodGet {
			h.HandleGet(w, r, id)
			return
		}

		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	})
}

// writeJSON writes a JSON response.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// readJSON decodes a JSON request body.
func readJSON(r *http.Request, v any) error {
	return json.NewDecoder(r.Body).Decode(v)
}

// messageToResponse converts a types.Message into a JSON-friendly response.
func messageToResponse(msg *types.Message) map[string]any {
	resp := map[string]any{
		"id":         msg.ID,
		"status":     msg.Status,
		"created_at": msg.CreatedAt,
		"updated_at": msg.UpdatedAt,
	}
	if msg.Data != nil {
		var data map[string]any
		if err := json.Unmarshal(msg.Data, &data); err == nil {
			resp["data"] = data
		}
	}
	return resp
}
