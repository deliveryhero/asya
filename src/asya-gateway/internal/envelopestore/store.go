package envelopestore

import (
	"fmt"
	"sync"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Store manages envelope state in memory
type Store struct {
	mu        sync.RWMutex
	envelopes map[string]*types.Envelope
	listeners map[string][]chan types.EnvelopeUpdate
	timers    map[string]*time.Timer
	updates   map[string][]types.EnvelopeUpdate // Historical updates for SSE replay
}

// NewStore creates a new envelope store
func NewStore() *Store {
	return &Store{
		envelopes: make(map[string]*types.Envelope),
		listeners: make(map[string][]chan types.EnvelopeUpdate),
		timers:    make(map[string]*time.Timer),
		updates:   make(map[string][]types.EnvelopeUpdate),
	}
}

// Create creates a new envelope
func (s *Store) Create(envelope *types.Envelope) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.envelopes[envelope.ID]; exists {
		return fmt.Errorf("envelope %s already exists", envelope.ID)
	}

	now := time.Now()
	envelope.CreatedAt = now
	envelope.UpdatedAt = now
	envelope.Status = types.EnvelopeStatusPending

	// Initialize progress tracking
	envelope.TotalActors = len(envelope.Route.Actors)
	envelope.ActorsCompleted = 0
	envelope.ProgressPercent = 0.0

	// Set deadline if timeout specified
	if envelope.TimeoutSec > 0 {
		envelope.Deadline = now.Add(time.Duration(envelope.TimeoutSec) * time.Second)

		// Start timeout timer
		s.timers[envelope.ID] = time.AfterFunc(time.Duration(envelope.TimeoutSec)*time.Second, func() {
			s.handleTimeout(envelope.ID)
		})
	}

	s.envelopes[envelope.ID] = envelope
	return nil
}

// Get retrieves a envelope by ID
func (s *Store) Get(id string) (*types.Envelope, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	envelope, exists := s.envelopes[id]
	if !exists {
		return nil, fmt.Errorf("envelope %s not found", id)
	}

	return envelope, nil
}

// Update updates a envelope's status
func (s *Store) Update(update types.EnvelopeUpdate) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	envelope, exists := s.envelopes[update.ID]
	if !exists {
		return fmt.Errorf("envelope %s not found", update.ID)
	}

	envelope.Status = update.Status
	envelope.UpdatedAt = update.Timestamp

	if update.Result != nil {
		envelope.Result = update.Result
	}

	if update.Error != "" {
		envelope.Error = update.Error
	}

	if update.ProgressPercent != nil {
		envelope.ProgressPercent = *update.ProgressPercent
	}

	if update.CurrentActorIdx != nil {
		envelope.CurrentActorIdx = *update.CurrentActorIdx
		if *update.CurrentActorIdx >= 0 && *update.CurrentActorIdx < len(update.Actors) {
			envelope.CurrentActorName = update.Actors[*update.CurrentActorIdx]
		}
	}

	if len(update.Actors) > 0 {
		envelope.Route.Actors = update.Actors
		envelope.TotalActors = len(update.Actors)
	}

	// Cancel timeout timer if envelope reaches final state
	if s.isFinal(update.Status) {
		s.cancelTimer(update.ID)
	}

	// Store update in history
	s.updates[update.ID] = append(s.updates[update.ID], update)

	// Notify listeners
	s.notifyListeners(update)

	return nil
}

// UpdateProgress updates envelope progress (lighter weight update for frequent progress reports)
func (s *Store) UpdateProgress(update types.EnvelopeUpdate) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	envelope, exists := s.envelopes[update.ID]
	if !exists {
		return fmt.Errorf("envelope %s not found", update.ID)
	}

	envelope.Status = update.Status
	envelope.UpdatedAt = update.Timestamp

	if update.ProgressPercent != nil {
		envelope.ProgressPercent = *update.ProgressPercent
	}

	if update.CurrentActorIdx != nil {
		envelope.CurrentActorIdx = *update.CurrentActorIdx
		if *update.CurrentActorIdx >= 0 && *update.CurrentActorIdx < len(update.Actors) {
			envelope.CurrentActorName = update.Actors[*update.CurrentActorIdx]
		}
	}

	if update.Message != "" {
		envelope.Message = update.Message
	}

	if len(update.Actors) > 0 {
		envelope.Route.Actors = update.Actors
		envelope.TotalActors = len(update.Actors)
	}

	// Store update in history
	s.updates[update.ID] = append(s.updates[update.ID], update)

	// Notify listeners
	s.notifyListeners(update)

	return nil
}

// GetUpdates retrieves all updates for an envelope (optionally filtered by time)
func (s *Store) GetUpdates(id string, since *time.Time) ([]types.EnvelopeUpdate, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	updates, exists := s.updates[id]
	if !exists {
		return []types.EnvelopeUpdate{}, nil
	}

	if since == nil {
		return updates, nil
	}

	var filtered []types.EnvelopeUpdate
	for _, update := range updates {
		if update.Timestamp.After(*since) {
			filtered = append(filtered, update)
		}
	}

	return filtered, nil
}

// Subscribe creates a listener channel for envelope updates
func (s *Store) Subscribe(id string) chan types.EnvelopeUpdate {
	s.mu.Lock()
	defer s.mu.Unlock()

	ch := make(chan types.EnvelopeUpdate, 10)
	s.listeners[id] = append(s.listeners[id], ch)

	return ch
}

// Unsubscribe removes a listener channel
func (s *Store) Unsubscribe(id string, ch chan types.EnvelopeUpdate) {
	s.mu.Lock()
	defer s.mu.Unlock()

	listeners := s.listeners[id]
	for i, listener := range listeners {
		if listener == ch {
			s.listeners[id] = append(listeners[:i], listeners[i+1:]...)
			close(ch)
			break
		}
	}

	if len(s.listeners[id]) == 0 {
		delete(s.listeners, id)
	}
}

// notifyListeners sends updates to all listeners (must hold lock)
func (s *Store) notifyListeners(update types.EnvelopeUpdate) {
	listeners := s.listeners[update.ID]
	for _, ch := range listeners {
		select {
		case ch <- update:
		default:
			// Channel full, skip
		}
	}
}

// IsActive checks if a envelope is still active (not timed out or in final state)
func (s *Store) IsActive(id string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()

	envelope, exists := s.envelopes[id]
	if !exists {
		return false
	}

	// Check if envelope is in final state
	if s.isFinal(envelope.Status) {
		return false
	}

	// Check if envelope has timed out
	if !envelope.Deadline.IsZero() && time.Now().After(envelope.Deadline) {
		return false
	}

	return true
}

// handleTimeout handles envelope timeout (called by timer)
func (s *Store) handleTimeout(id string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	envelope, exists := s.envelopes[id]
	if !exists {
		return
	}

	// Only timeout if not already in final state
	if s.isFinal(envelope.Status) {
		return
	}

	envelope.Status = types.EnvelopeStatusFailed
	envelope.Error = "envelope timed out"
	envelope.UpdatedAt = time.Now()

	// Notify listeners
	update := types.EnvelopeUpdate{
		ID:        id,
		Status:    types.EnvelopeStatusFailed,
		Error:     "envelope timed out",
		Timestamp: time.Now(),
	}
	s.notifyListeners(update)

	// Clean up timer
	delete(s.timers, id)
}

// cancelTimer cancels and removes a timeout timer (must hold lock)
func (s *Store) cancelTimer(id string) {
	if timer, exists := s.timers[id]; exists {
		timer.Stop()
		delete(s.timers, id)
	}
}

// isFinal checks if a status is final (must hold lock)
func (s *Store) isFinal(status types.EnvelopeStatus) bool {
	return status == types.EnvelopeStatusSucceeded || status == types.EnvelopeStatusFailed
}
