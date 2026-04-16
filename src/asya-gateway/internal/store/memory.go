package store

import (
	"context"
	"encoding/json"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/subscribers"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// MemoryStore implements MessageStore using in-memory maps.
// Used for unit tests and local development.
type MemoryStore struct {
	mu       sync.RWMutex
	messages map[string]*types.Message
	hub      *subscribers.Hub
}

// NewMemoryStore creates a new in-memory message store.
func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		messages: make(map[string]*types.Message),
		hub:      subscribers.New(),
	}
}

// Create stores a new message. If the message ID already exists, it overwrites.
func (m *MemoryStore) Create(_ context.Context, msg *types.Message) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	cp := *msg
	m.messages[msg.ID] = &cp
	return nil
}

// Get retrieves a message by ID. Returns ErrNotFound if not present.
func (m *MemoryStore) Get(_ context.Context, id string) (*types.Message, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	msg, ok := m.messages[id]
	if !ok {
		return nil, ErrNotFound
	}
	cp := *msg
	return &cp, nil
}

// UpdateStatus updates the status and data of a message.
// Enforces monotonic status ordering: returns ErrStaleStatus if the new status
// does not advance the current status.
func (m *MemoryStore) UpdateStatus(_ context.Context, id string, status types.MessageStatus, data json.RawMessage) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	msg, ok := m.messages[id]
	if !ok {
		return ErrNotFound
	}
	if !types.StatusAdvances(msg.Status, status) {
		return ErrStaleStatus
	}
	msg.Status = status
	if data != nil {
		msg.Data = data
	}
	msg.UpdatedAt = time.Now().UTC()
	return nil
}

// Delete removes a message by ID. Returns ErrNotFound if not present.
func (m *MemoryStore) Delete(_ context.Context, id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.messages[id]; !ok {
		return ErrNotFound
	}
	delete(m.messages, id)
	return nil
}

// List returns messages matching the given filter parameters.
// Supports prefix, status filter, limit, and offset.
func (m *MemoryStore) List(_ context.Context, params types.ListParams) ([]*types.Message, int, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var filtered []*types.Message
	for _, msg := range m.messages {
		// Apply status filter if present
		if statusVal, ok := params.Filters["status"]; ok {
			if s, ok := statusVal.(string); ok && string(msg.Status) != s {
				continue
			}
		}
		filtered = append(filtered, msg)
	}

	// Sort by created_at descending by default
	sort.Slice(filtered, func(i, j int) bool {
		return filtered[i].CreatedAt.After(filtered[j].CreatedAt)
	})

	total := len(filtered)

	// Apply sort from params (simplified: support -created_at)
	if len(params.Sort) > 0 {
		for _, s := range params.Sort {
			if s == "created_at" {
				sort.Slice(filtered, func(i, j int) bool {
					return filtered[i].CreatedAt.Before(filtered[j].CreatedAt)
				})
			}
			if s == "-created_at" {
				sort.Slice(filtered, func(i, j int) bool {
					return filtered[i].CreatedAt.After(filtered[j].CreatedAt)
				})
			}
			if strings.HasPrefix(s, "-updated_at") {
				sort.Slice(filtered, func(i, j int) bool {
					return filtered[i].UpdatedAt.After(filtered[j].UpdatedAt)
				})
			}
		}
	}

	// Apply offset
	if params.Offset > 0 && params.Offset < len(filtered) {
		filtered = filtered[params.Offset:]
	} else if params.Offset >= len(filtered) {
		filtered = nil
	}

	// Apply limit
	if params.Limit > 0 && params.Limit < len(filtered) {
		filtered = filtered[:params.Limit]
	}

	// Return copies
	result := make([]*types.Message, len(filtered))
	for i, msg := range filtered {
		cp := *msg
		result[i] = &cp
	}

	return result, total, nil
}

// Subscribe returns a channel that receives events for the given message ID.
func (m *MemoryStore) Subscribe(id string) <-chan types.Event {
	return m.hub.Subscribe(id)
}

// Unsubscribe removes and closes the channel for the given message ID.
func (m *MemoryStore) Unsubscribe(id string, ch <-chan types.Event) {
	m.hub.Unsubscribe(id, ch)
}

// Publish sends an event to all subscribers for the given message ID.
func (m *MemoryStore) Publish(id string, event types.Event) {
	m.hub.Publish(id, event)
}
