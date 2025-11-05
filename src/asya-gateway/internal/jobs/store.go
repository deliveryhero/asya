package jobs

import (
	"fmt"
	"sync"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Store manages job state in memory
type Store struct {
	mu        sync.RWMutex
	jobs      map[string]*types.Job
	listeners map[string][]chan types.JobUpdate
	timers    map[string]*time.Timer
}

// NewStore creates a new job store
func NewStore() *Store {
	return &Store{
		jobs:      make(map[string]*types.Job),
		listeners: make(map[string][]chan types.JobUpdate),
		timers:    make(map[string]*time.Timer),
	}
}

// Create creates a new job
func (s *Store) Create(job *types.Job) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.jobs[job.ID]; exists {
		return fmt.Errorf("job %s already exists", job.ID)
	}

	now := time.Now()
	job.CreatedAt = now
	job.UpdatedAt = now
	job.Status = types.JobStatusPending

	// Initialize progress tracking
	job.TotalSteps = len(job.Route.Steps)
	job.StepsCompleted = 0
	job.ProgressPercent = 0.0

	// Set deadline if timeout specified
	if job.TimeoutSec > 0 {
		job.Deadline = now.Add(time.Duration(job.TimeoutSec) * time.Second)

		// Start timeout timer
		s.timers[job.ID] = time.AfterFunc(time.Duration(job.TimeoutSec)*time.Second, func() {
			s.handleTimeout(job.ID)
		})
	}

	s.jobs[job.ID] = job
	return nil
}

// Get retrieves a job by ID
func (s *Store) Get(id string) (*types.Job, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	job, exists := s.jobs[id]
	if !exists {
		return nil, fmt.Errorf("job %s not found", id)
	}

	return job, nil
}

// Update updates a job's status
func (s *Store) Update(update types.JobUpdate) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	job, exists := s.jobs[update.JobID]
	if !exists {
		return fmt.Errorf("job %s not found", update.JobID)
	}

	job.Status = update.Status
	job.UpdatedAt = update.Timestamp

	if update.Result != nil {
		job.Result = update.Result
	}

	if update.Error != "" {
		job.Error = update.Error
	}

	if update.ProgressPercent != nil {
		job.ProgressPercent = *update.ProgressPercent
	}

	if update.Step != "" {
		job.CurrentStep = update.Step
	}

	// Cancel timeout timer if job reaches terminal state
	if s.isTerminal(update.Status) {
		s.cancelTimer(update.JobID)
	}

	// Notify listeners
	s.notifyListeners(update)

	return nil
}

// UpdateProgress updates job progress (lighter weight update for frequent progress reports)
func (s *Store) UpdateProgress(update types.JobUpdate) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	job, exists := s.jobs[update.JobID]
	if !exists {
		return fmt.Errorf("job %s not found", update.JobID)
	}

	job.Status = update.Status
	job.UpdatedAt = update.Timestamp

	if update.ProgressPercent != nil {
		job.ProgressPercent = *update.ProgressPercent
	}

	if update.Step != "" {
		job.CurrentStep = update.Step
	}

	// Notify listeners
	s.notifyListeners(update)

	return nil
}

// Subscribe creates a listener channel for job updates
func (s *Store) Subscribe(jobID string) chan types.JobUpdate {
	s.mu.Lock()
	defer s.mu.Unlock()

	ch := make(chan types.JobUpdate, 10)
	s.listeners[jobID] = append(s.listeners[jobID], ch)

	return ch
}

// Unsubscribe removes a listener channel
func (s *Store) Unsubscribe(jobID string, ch chan types.JobUpdate) {
	s.mu.Lock()
	defer s.mu.Unlock()

	listeners := s.listeners[jobID]
	for i, listener := range listeners {
		if listener == ch {
			s.listeners[jobID] = append(listeners[:i], listeners[i+1:]...)
			close(ch)
			break
		}
	}

	if len(s.listeners[jobID]) == 0 {
		delete(s.listeners, jobID)
	}
}

// notifyListeners sends updates to all listeners (must hold lock)
func (s *Store) notifyListeners(update types.JobUpdate) {
	listeners := s.listeners[update.JobID]
	for _, ch := range listeners {
		select {
		case ch <- update:
		default:
			// Channel full, skip
		}
	}
}

// IsActive checks if a job is still active (not timed out or in terminal state)
func (s *Store) IsActive(jobID string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()

	job, exists := s.jobs[jobID]
	if !exists {
		return false
	}

	// Check if job is in terminal state
	if s.isTerminal(job.Status) {
		return false
	}

	// Check if job has timed out
	if !job.Deadline.IsZero() && time.Now().After(job.Deadline) {
		return false
	}

	return true
}

// handleTimeout handles job timeout (called by timer)
func (s *Store) handleTimeout(jobID string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	job, exists := s.jobs[jobID]
	if !exists {
		return
	}

	// Only timeout if not already in terminal state
	if s.isTerminal(job.Status) {
		return
	}

	job.Status = types.JobStatusFailed
	job.Error = "job timed out"
	job.UpdatedAt = time.Now()

	// Notify listeners
	update := types.JobUpdate{
		JobID:     jobID,
		Status:    types.JobStatusFailed,
		Error:     "job timed out",
		Timestamp: time.Now(),
	}
	s.notifyListeners(update)

	// Clean up timer
	delete(s.timers, jobID)
}

// cancelTimer cancels and removes a timeout timer (must hold lock)
func (s *Store) cancelTimer(jobID string) {
	if timer, exists := s.timers[jobID]; exists {
		timer.Stop()
		delete(s.timers, jobID)
	}
}

// isTerminal checks if a status is terminal (must hold lock)
func (s *Store) isTerminal(status types.JobStatus) bool {
	return status == types.JobStatusSucceeded || status == types.JobStatusFailed
}
