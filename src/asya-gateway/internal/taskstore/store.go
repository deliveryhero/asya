package taskstore

import (
	"fmt"
	"sync"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Store manages task state in memory
type Store struct {
	mu        sync.RWMutex
	tasks     map[string]*types.Task
	listeners map[string][]chan types.TaskUpdate
	timers    map[string]*time.Timer
	updates   map[string][]types.TaskUpdate // Historical updates for SSE replay
}

// NewStore creates a new task store
func NewStore() *Store {
	return &Store{
		tasks:     make(map[string]*types.Task),
		listeners: make(map[string][]chan types.TaskUpdate),
		timers:    make(map[string]*time.Timer),
		updates:   make(map[string][]types.TaskUpdate),
	}
}

// Create creates a new task
func (s *Store) Create(task *types.Task) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.tasks[task.ID]; exists {
		return fmt.Errorf("task %s already exists", task.ID)
	}

	now := time.Now()
	task.CreatedAt = now
	task.UpdatedAt = now
	task.Status = types.TaskStatusPending

	// Initialize progress tracking
	task.TotalActors = len(task.Route.Actors)
	task.ActorsCompleted = 0
	task.ProgressPercent = 0.0

	// Set deadline if timeout specified
	if task.TimeoutSec > 0 {
		task.Deadline = now.Add(time.Duration(task.TimeoutSec) * time.Second)

		// Start timeout timer
		s.timers[task.ID] = time.AfterFunc(time.Duration(task.TimeoutSec)*time.Second, func() {
			s.handleTimeout(task.ID)
		})
	}

	s.tasks[task.ID] = task
	return nil
}

// Get retrieves a task by ID
func (s *Store) Get(id string) (*types.Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	task, exists := s.tasks[id]
	if !exists {
		return nil, fmt.Errorf("task %s not found", id)
	}

	return task, nil
}

// Update updates a task's status
func (s *Store) Update(update types.TaskUpdate) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	task, exists := s.tasks[update.ID]
	if !exists {
		return fmt.Errorf("task %s not found", update.ID)
	}

	task.Status = update.Status
	task.UpdatedAt = update.Timestamp

	if update.Result != nil {
		task.Result = update.Result
	}

	if update.Error != "" {
		task.Error = update.Error
	}

	if update.ProgressPercent != nil {
		task.ProgressPercent = *update.ProgressPercent
	}

	if update.CurrentActorIdx != nil {
		task.CurrentActorIdx = *update.CurrentActorIdx
		if *update.CurrentActorIdx >= 0 && *update.CurrentActorIdx < len(update.Actors) {
			task.CurrentActorName = update.Actors[*update.CurrentActorIdx]
		}
	}

	if len(update.Actors) > 0 {
		task.Route.Actors = update.Actors
		task.TotalActors = len(update.Actors)
	}

	// Cancel timeout timer if task reaches final state
	if s.isFinal(update.Status) {
		s.cancelTimer(update.ID)
	}

	// Store update in history
	s.updates[update.ID] = append(s.updates[update.ID], update)

	// Notify listeners
	s.notifyListeners(update)

	return nil
}

// UpdateProgress updates task progress (lighter weight update for frequent progress reports)
func (s *Store) UpdateProgress(update types.TaskUpdate) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	task, exists := s.tasks[update.ID]
	if !exists {
		return fmt.Errorf("task %s not found", update.ID)
	}

	task.Status = update.Status
	task.UpdatedAt = update.Timestamp

	if update.ProgressPercent != nil {
		task.ProgressPercent = *update.ProgressPercent
	}

	if update.CurrentActorIdx != nil {
		task.CurrentActorIdx = *update.CurrentActorIdx
		if *update.CurrentActorIdx >= 0 && *update.CurrentActorIdx < len(update.Actors) {
			task.CurrentActorName = update.Actors[*update.CurrentActorIdx]
		}
	}

	if update.Message != "" {
		task.Message = update.Message
	}

	if len(update.Actors) > 0 {
		task.Route.Actors = update.Actors
		task.TotalActors = len(update.Actors)
	}

	// Store update in history
	s.updates[update.ID] = append(s.updates[update.ID], update)

	// Notify listeners
	s.notifyListeners(update)

	return nil
}

// GetUpdates retrieves all updates for a task (optionally filtered by time)
func (s *Store) GetUpdates(id string, since *time.Time) ([]types.TaskUpdate, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	updates, exists := s.updates[id]
	if !exists {
		return []types.TaskUpdate{}, nil
	}

	if since == nil {
		return updates, nil
	}

	var filtered []types.TaskUpdate
	for _, update := range updates {
		if update.Timestamp.After(*since) {
			filtered = append(filtered, update)
		}
	}

	return filtered, nil
}

// Subscribe creates a listener channel for task updates
func (s *Store) Subscribe(id string) chan types.TaskUpdate {
	s.mu.Lock()
	defer s.mu.Unlock()

	ch := make(chan types.TaskUpdate, 10)
	s.listeners[id] = append(s.listeners[id], ch)

	return ch
}

// Unsubscribe removes a listener channel
func (s *Store) Unsubscribe(id string, ch chan types.TaskUpdate) {
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
func (s *Store) notifyListeners(update types.TaskUpdate) {
	listeners := s.listeners[update.ID]
	for _, ch := range listeners {
		select {
		case ch <- update:
		default:
			// Channel full, skip
		}
	}
}

// IsActive checks if a task is still active (not timed out or in final state)
func (s *Store) IsActive(id string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()

	task, exists := s.tasks[id]
	if !exists {
		return false
	}

	// Check if task is in final state
	if s.isFinal(task.Status) {
		return false
	}

	// Check if task has timed out
	if !task.Deadline.IsZero() && time.Now().After(task.Deadline) {
		return false
	}

	return true
}

// handleTimeout handles task timeout (called by timer)
func (s *Store) handleTimeout(id string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	task, exists := s.tasks[id]
	if !exists {
		return
	}

	// Only timeout if not already in final state
	if s.isFinal(task.Status) {
		return
	}

	task.Status = types.TaskStatusFailed
	task.Error = "task timed out"
	task.UpdatedAt = time.Now()

	// Notify listeners
	update := types.TaskUpdate{
		ID:        id,
		Status:    types.TaskStatusFailed,
		Error:     "task timed out",
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
func (s *Store) isFinal(status types.TaskStatus) bool {
	return status == types.TaskStatusSucceeded || status == types.TaskStatusFailed
}
