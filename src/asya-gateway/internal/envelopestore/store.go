package envelopestore

import (
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"sync"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// ErrNotFound is returned when an envelope does not exist in the store.
var ErrNotFound = errors.New("envelope not found")

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

// routeTotalActors returns the total number of actors in the route (prev + curr + next).
func routeTotalActors(route types.Route) int {
	total := len(route.Prev) + len(route.Next)
	if route.Curr != "" {
		total++
	}
	return total
}

// applyRouteUpdate copies route fields from the update into the envelope and
// recalculates TotalActors / ActorsCompleted / CurrentActorName.
// Returns true if route fields were present in the update.
func applyRouteUpdate(envelope *types.Envelope, update types.EnvelopeUpdate) bool {
	if update.Curr == "" && len(update.Prev) == 0 && len(update.Next) == 0 {
		return false
	}
	envelope.Route.Prev = update.Prev
	envelope.Route.Curr = update.Curr
	envelope.Route.Next = update.Next
	envelope.TotalActors = routeTotalActors(envelope.Route)
	envelope.ActorsCompleted = len(update.Prev)
	envelope.CurrentActorName = update.Curr
	return true
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
	envelope.TotalActors = routeTotalActors(envelope.Route)
	envelope.ActorsCompleted = 0
	envelope.ProgressPercent = 0.0

	// Derive current actor name from route
	if envelope.Route.Curr != "" {
		envelope.CurrentActorName = envelope.Route.Curr
	}

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

// Get retrieves an envelope by ID
func (s *Store) Get(id string) (*types.Envelope, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	envelope, exists := s.envelopes[id]
	if !exists {
		return nil, fmt.Errorf("envelope %s: %w", id, ErrNotFound)
	}

	// Return a copy so callers do not share the map pointer with Update.
	copy := *envelope
	return &copy, nil
}

// Update updates an envelope's status
func (s *Store) Update(update types.EnvelopeUpdate) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	envelope, exists := s.envelopes[update.ID]
	if !exists {
		return fmt.Errorf("envelope %s not found", update.ID)
	}

	// First-write-wins: ignore updates for envelopes already in a terminal state.
	// This prevents late actor reports (e.g. x-sink) from overwriting a
	// backstop "failed" status after the deadline has elapsed.
	if s.isFinal(envelope.Status) {
		slog.Debug("Ignoring update for envelope in terminal state",
			"id", update.ID,
			"current_status", envelope.Status,
			"requested_status", update.Status)
		return nil
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

	if update.Message != "" {
		envelope.Message = update.Message
	}

	// Update route if any route fields are provided
	if !applyRouteUpdate(envelope, update) && update.Actor != "" {
		envelope.CurrentActorName = update.Actor
	}

	// Store pause metadata if present
	if update.PauseMetadata != nil {
		envelope.PauseMetadata = update.PauseMetadata
	}

	// Cancel timeout timer if envelope reaches final state
	if s.isFinal(update.Status) {
		s.cancelTimer(update.ID)
	}

	// Freeze timeout timer when envelope is paused: save remaining budget and cancel timer
	if update.Status == types.EnvelopeStatusPaused {
		s.freezeTimer(envelope)
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

	// Update route fields when provided
	applyRouteUpdate(envelope, update)

	if update.Message != "" {
		envelope.Message = update.Message
	}

	// Store pause metadata if present (HITL pause signal from sidecar)
	if update.PauseMetadata != nil {
		envelope.PauseMetadata = update.PauseMetadata
	}

	// Freeze timeout timer when envelope is paused: save remaining budget and cancel timer
	if update.Status == types.EnvelopeStatusPaused {
		s.freezeTimer(envelope)
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

	ch := make(chan types.EnvelopeUpdate, 100)
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
			slog.Warn("FLY event dropped: subscriber channel full", "task_id", update.ID)
		}
	}
}

// IsActive checks if an envelope is still active (not timed out or in final state)
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

	// Paused envelopes are not active (sidecar should not route further)
	if envelope.Status == types.EnvelopeStatusPaused {
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

// freezeTimer saves remaining timeout budget and cancels the timer (must hold lock)
func (s *Store) freezeTimer(envelope *types.Envelope) {
	if !envelope.Deadline.IsZero() {
		remaining := time.Until(envelope.Deadline).Seconds()
		if remaining < 0 {
			remaining = 0
		}
		envelope.RemainingTimeoutSec = &remaining
	}
	s.cancelTimer(envelope.ID)
}

// Resume transitions a paused envelope back to running, restarting the timeout timer
// with the remaining timeout budget. Returns the updated envelope.
func (s *Store) Resume(id string) (*types.Envelope, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	envelope, exists := s.envelopes[id]
	if !exists {
		return nil, fmt.Errorf("envelope %s not found", id)
	}

	if envelope.Status != types.EnvelopeStatusPaused {
		return nil, fmt.Errorf("envelope %s is not paused (status: %s)", id, envelope.Status)
	}

	envelope.Status = types.EnvelopeStatusRunning
	envelope.UpdatedAt = time.Now()
	envelope.PauseMetadata = nil

	// Thaw: restart timeout timer with remaining budget
	if envelope.RemainingTimeoutSec != nil && *envelope.RemainingTimeoutSec > 0 {
		remaining := *envelope.RemainingTimeoutSec
		envelope.Deadline = time.Now().Add(time.Duration(remaining * float64(time.Second)))
		envelope.RemainingTimeoutSec = nil
		s.timers[id] = time.AfterFunc(time.Duration(remaining*float64(time.Second)), func() {
			s.handleTimeout(id)
		})
	}

	// Notify listeners
	update := types.EnvelopeUpdate{
		ID:        id,
		Status:    types.EnvelopeStatusRunning,
		Message:   "Envelope resumed",
		Timestamp: envelope.UpdatedAt,
	}
	s.updates[id] = append(s.updates[id], update)
	s.notifyListeners(update)

	return envelope, nil
}

// List returns envelopes filtered by params with pagination. Returns (envelopes, totalCount, error).
func (s *Store) List(params EnvelopeListParams) ([]*types.Envelope, int, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// Collect matching envelopes
	var matched []*types.Envelope
	for _, envelope := range s.envelopes {
		if params.Status != nil && envelope.Status != *params.Status {
			continue
		}
		if params.ContextID != "" && envelope.ContextID != params.ContextID {
			continue
		}
		matched = append(matched, envelope)
	}

	// Sort by CreatedAt descending for deterministic pagination (matches PgStore behavior)
	sort.Slice(matched, func(i, j int) bool {
		return matched[i].CreatedAt.After(matched[j].CreatedAt)
	})

	totalCount := len(matched)

	// Apply offset
	if params.Offset > 0 {
		if params.Offset >= len(matched) {
			return []*types.Envelope{}, totalCount, nil
		}
		matched = matched[params.Offset:]
	}

	// Apply limit
	if params.Limit > 0 && params.Limit < len(matched) {
		matched = matched[:params.Limit]
	}

	return matched, totalCount, nil
}

// isFinal checks if a status is final (must hold lock)
func (s *Store) isFinal(status types.EnvelopeStatus) bool {
	return status == types.EnvelopeStatusSucceeded || status == types.EnvelopeStatusFailed || status == types.EnvelopeStatusCanceled
}

// NotifyFLY dispatches an ephemeral FLY event to in-process subscribers without persisting to storage.
// Used for streaming LLM tokens and real-time progress updates.
func (s *Store) NotifyFLY(id string, payload []byte) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	update := types.EnvelopeUpdate{
		ID:             id,
		Status:         types.EnvelopeStatusRunning,
		PartialPayload: json.RawMessage(payload),
		Timestamp:      time.Now(),
	}
	s.notifyListeners(update)
}
