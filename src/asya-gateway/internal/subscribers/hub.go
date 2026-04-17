package subscribers

import (
	"log/slog"
	"sync"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

const channelBuffer = 100

// Hub manages in-process Go channel subscriptions keyed by message ID.
type Hub struct {
	mu   sync.RWMutex
	subs map[string][]chan types.Event
}

// New creates a new subscriber hub.
func New() *Hub {
	return &Hub{subs: make(map[string][]chan types.Event)}
}

// Subscribe returns a buffered channel that will receive events for the given ID.
func (h *Hub) Subscribe(id string) <-chan types.Event {
	h.mu.Lock()
	defer h.mu.Unlock()
	ch := make(chan types.Event, channelBuffer)
	h.subs[id] = append(h.subs[id], ch)
	return ch
}

// Unsubscribe removes and closes the channel.
func (h *Hub) Unsubscribe(id string, ch <-chan types.Event) {
	h.mu.Lock()
	defer h.mu.Unlock()
	listeners := h.subs[id]
	for i, listener := range listeners {
		// Compare the underlying channel: ch is receive-only but listener is bidirectional.
		// They point to the same channel if Subscribe returned listener as <-chan.
		if (<-chan types.Event)(listener) == ch {
			close(listener)
			h.subs[id] = append(listeners[:i], listeners[i+1:]...)
			break
		}
	}
	if len(h.subs[id]) == 0 {
		delete(h.subs, id)
	}
}

// Publish sends an event to all subscribers for the given ID.
// Terminal status events use a blocking send to prevent silent drops
// that could leave SSE connections hanging. Non-terminal events are
// dropped if a channel is full.
func (h *Hub) Publish(id string, event types.Event) {
	h.mu.RLock()
	defer h.mu.RUnlock()

	isTerminal := event.Type == "status" && event.Status.IsTerminal()

	for _, ch := range h.subs[id] {
		if isTerminal {
			ch <- event
		} else {
			select {
			case ch <- event:
			default:
				slog.Warn("Event dropped: subscriber channel full", "id", id, "type", event.Type)
			}
		}
	}
}
