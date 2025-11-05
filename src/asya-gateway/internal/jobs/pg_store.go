package jobs

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// PgStore manages job state in PostgreSQL
type PgStore struct {
	pool      *pgxpool.Pool
	mu        sync.RWMutex
	listeners map[string][]chan types.JobUpdate
	timers    map[string]*time.Timer
	ctx       context.Context
	cancel    context.CancelFunc
}

// NewPgStore creates a new PostgreSQL-backed job store
func NewPgStore(ctx context.Context, connString string) (*PgStore, error) {
	config, err := pgxpool.ParseConfig(connString)
	if err != nil {
		return nil, fmt.Errorf("failed to parse connection string: %w", err)
	}

	// Configure connection pool
	config.MaxConns = 10
	config.MinConns = 2
	config.MaxConnLifetime = time.Hour
	config.MaxConnIdleTime = 30 * time.Minute

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("failed to create connection pool: %w", err)
	}

	// Test connection
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	storeCtx, cancel := context.WithCancel(ctx)

	s := &PgStore{
		pool:      pool,
		listeners: make(map[string][]chan types.JobUpdate),
		timers:    make(map[string]*time.Timer),
		ctx:       storeCtx,
		cancel:    cancel,
	}

	// Start background cleanup goroutine
	go s.cleanupOldUpdates()

	return s, nil
}

// Close closes the database connection pool
func (s *PgStore) Close() {
	s.cancel()
	s.mu.Lock()
	defer s.mu.Unlock()

	// Cancel all timers
	for _, timer := range s.timers {
		timer.Stop()
	}

	// Close all listener channels
	for jobID, listeners := range s.listeners {
		for _, ch := range listeners {
			close(ch)
		}
		delete(s.listeners, jobID)
	}

	s.pool.Close()
}

// Create creates a new job
func (s *PgStore) Create(job *types.Job) error {
	now := time.Now()
	job.CreatedAt = now
	job.UpdatedAt = now
	job.Status = types.JobStatusPending

	// Initialize progress tracking
	job.TotalSteps = len(job.Route.Steps)
	job.StepsCompleted = 0
	job.ProgressPercent = 0.0

	var deadline *time.Time
	if job.TimeoutSec > 0 {
		d := now.Add(time.Duration(job.TimeoutSec) * time.Second)
		job.Deadline = d
		deadline = &d
	}

	payloadJSON, err := json.Marshal(job.Payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	query := `
		INSERT INTO jobs (id, status, route_steps, route_current, payload, timeout_sec, deadline,
		                 progress_percent, total_steps, steps_completed, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
	`

	_, err = s.pool.Exec(s.ctx, query,
		job.ID,
		job.Status,
		job.Route.Steps,
		job.Route.Current,
		payloadJSON,
		job.TimeoutSec,
		deadline,
		job.ProgressPercent,
		job.TotalSteps,
		job.StepsCompleted,
		job.CreatedAt,
		job.UpdatedAt,
	)

	if err != nil {
		return fmt.Errorf("failed to create job: %w", err)
	}

	// Set timeout timer if specified
	if job.TimeoutSec > 0 {
		s.mu.Lock()
		s.timers[job.ID] = time.AfterFunc(time.Duration(job.TimeoutSec)*time.Second, func() {
			s.handleTimeout(job.ID)
		})
		s.mu.Unlock()
	}

	return nil
}

// Get retrieves a job by ID
func (s *PgStore) Get(id string) (*types.Job, error) {
	query := `
		SELECT id, status, route_steps, route_current, payload, result, error, timeout_sec, deadline,
		       progress_percent, current_step, steps_completed, total_steps, created_at, updated_at
		FROM jobs
		WHERE id = $1
	`

	var job types.Job
	var payloadJSON, resultJSON []byte
	var deadline *time.Time
	var errorStr, currentStep *string
	var timeoutSec *int

	err := s.pool.QueryRow(s.ctx, query, id).Scan(
		&job.ID,
		&job.Status,
		&job.Route.Steps,
		&job.Route.Current,
		&payloadJSON,
		&resultJSON,
		&errorStr,
		&timeoutSec,
		&deadline,
		&job.ProgressPercent,
		&currentStep,
		&job.StepsCompleted,
		&job.TotalSteps,
		&job.CreatedAt,
		&job.UpdatedAt,
	)

	if err == pgx.ErrNoRows {
		return nil, fmt.Errorf("job %s not found", id)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to get job: %w", err)
	}

	// Handle nullable fields
	if deadline != nil {
		job.Deadline = *deadline
	}

	if errorStr != nil {
		job.Error = *errorStr
	}

	if timeoutSec != nil {
		job.TimeoutSec = *timeoutSec
	}

	if currentStep != nil {
		job.CurrentStep = *currentStep
	}

	if payloadJSON != nil {
		if err := json.Unmarshal(payloadJSON, &job.Payload); err != nil {
			return nil, fmt.Errorf("failed to unmarshal payload: %w", err)
		}
	}

	if resultJSON != nil {
		if err := json.Unmarshal(resultJSON, &job.Result); err != nil {
			return nil, fmt.Errorf("failed to unmarshal result: %w", err)
		}
	}

	return &job, nil
}

// Update updates a job's status
func (s *PgStore) Update(update types.JobUpdate) error {
	tx, err := s.pool.Begin(s.ctx)
	if err != nil {
		return fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer tx.Rollback(s.ctx)

	// Update main job record
	var resultJSON []byte
	if update.Result != nil {
		resultJSON, err = json.Marshal(update.Result)
		if err != nil {
			return fmt.Errorf("failed to marshal result: %w", err)
		}
	}

	updateQuery := `
		UPDATE jobs
		SET status = $1,
		    result = COALESCE($2, result),
		    error = COALESCE($3, error),
		    updated_at = $4
		WHERE id = $5
	`

	result, err := tx.Exec(s.ctx, updateQuery,
		update.Status,
		resultJSON,
		update.Error,
		update.Timestamp,
		update.JobID,
	)

	if err != nil {
		return fmt.Errorf("failed to update job: %w", err)
	}

	if result.RowsAffected() == 0 {
		return fmt.Errorf("job %s not found", update.JobID)
	}

	// Insert update record for SSE streaming
	insertUpdateQuery := `
		INSERT INTO job_updates (job_id, status, message, result, error, progress_percent, step, step_status, timestamp)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
	`

	// Convert empty strings to NULL for step_status
	var stepStatus interface{}
	if update.StepStatus != "" {
		stepStatus = update.StepStatus
	}

	_, err = tx.Exec(s.ctx, insertUpdateQuery,
		update.JobID,
		update.Status,
		update.Message,
		resultJSON,
		update.Error,
		update.ProgressPercent,
		update.Step,
		stepStatus,
		update.Timestamp,
	)

	if err != nil {
		return fmt.Errorf("failed to insert job update: %w", err)
	}

	if err := tx.Commit(s.ctx); err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}

	// Cancel timeout timer if job reaches terminal state
	if s.isTerminal(update.Status) {
		s.mu.Lock()
		s.cancelTimer(update.JobID)
		s.mu.Unlock()
	}

	// Notify listeners
	s.mu.RLock()
	s.notifyListeners(update)
	s.mu.RUnlock()

	return nil
}

// UpdateProgress updates job progress (more frequent, lighter update)
func (s *PgStore) UpdateProgress(update types.JobUpdate) error {
	tx, err := s.pool.Begin(s.ctx)
	if err != nil {
		return fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer tx.Rollback(s.ctx)

	// Update main job record with progress fields
	updateQuery := `
		UPDATE jobs
		SET progress_percent = COALESCE($1, progress_percent),
		    current_step = COALESCE(NULLIF($2, ''), current_step),
		    status = $3,
		    updated_at = $4
		WHERE id = $5
	`

	_, err = tx.Exec(s.ctx, updateQuery,
		update.ProgressPercent,
		update.Step,
		update.Status,
		update.Timestamp,
		update.JobID,
	)

	if err != nil {
		return fmt.Errorf("failed to update job progress: %w", err)
	}

	// Insert progress update record
	insertUpdateQuery := `
		INSERT INTO job_updates (job_id, status, message, progress_percent, step, step_status, timestamp)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`

	// Convert empty strings to NULL for step_status
	var stepStatus interface{}
	if update.StepStatus != "" {
		stepStatus = update.StepStatus
	}

	_, err = tx.Exec(s.ctx, insertUpdateQuery,
		update.JobID,
		update.Status,
		update.Message,
		update.ProgressPercent,
		update.Step,
		stepStatus,
		update.Timestamp,
	)

	if err != nil {
		return fmt.Errorf("failed to insert progress update: %w", err)
	}

	if err := tx.Commit(s.ctx); err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}

	// Notify SSE listeners
	s.mu.RLock()
	s.notifyListeners(update)
	s.mu.RUnlock()

	return nil
}

// GetUpdates retrieves all updates for a job (for SSE streaming)
func (s *PgStore) GetUpdates(jobID string, since *time.Time) ([]types.JobUpdate, error) {
	var query string
	var args []interface{}

	if since != nil {
		query = `
			SELECT job_id, status, message, result, error, progress_percent, step, step_status, timestamp
			FROM job_updates
			WHERE job_id = $1 AND timestamp > $2
			ORDER BY timestamp ASC
		`
		args = []interface{}{jobID, since}
	} else {
		query = `
			SELECT job_id, status, message, result, error, progress_percent, step, step_status, timestamp
			FROM job_updates
			WHERE job_id = $1
			ORDER BY timestamp ASC
		`
		args = []interface{}{jobID}
	}

	rows, err := s.pool.Query(s.ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to query updates: %w", err)
	}
	defer rows.Close()

	var updates []types.JobUpdate
	for rows.Next() {
		var update types.JobUpdate
		var resultJSON []byte

		err := rows.Scan(
			&update.JobID,
			&update.Status,
			&update.Message,
			&resultJSON,
			&update.Error,
			&update.ProgressPercent,
			&update.Step,
			&update.StepStatus,
			&update.Timestamp,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan update: %w", err)
		}

		if resultJSON != nil {
			if err := json.Unmarshal(resultJSON, &update.Result); err != nil {
				return nil, fmt.Errorf("failed to unmarshal result: %w", err)
			}
		}

		updates = append(updates, update)
	}

	return updates, rows.Err()
}

// Subscribe creates a listener channel for job updates
func (s *PgStore) Subscribe(jobID string) chan types.JobUpdate {
	s.mu.Lock()
	defer s.mu.Unlock()

	ch := make(chan types.JobUpdate, 10)
	s.listeners[jobID] = append(s.listeners[jobID], ch)

	return ch
}

// Unsubscribe removes a listener channel
func (s *PgStore) Unsubscribe(jobID string, ch chan types.JobUpdate) {
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

// notifyListeners sends updates to all listeners (must hold read lock)
func (s *PgStore) notifyListeners(update types.JobUpdate) {
	listeners := s.listeners[update.JobID]
	for _, ch := range listeners {
		select {
		case ch <- update:
		default:
			// Channel full, skip
		}
	}
}

// IsActive checks if a job is still active
func (s *PgStore) IsActive(jobID string) bool {
	query := `
		SELECT status, deadline
		FROM jobs
		WHERE id = $1
	`

	var status types.JobStatus
	var deadline *time.Time

	err := s.pool.QueryRow(s.ctx, query, jobID).Scan(&status, &deadline)
	if err != nil {
		return false
	}

	// Check if job is in terminal state
	if s.isTerminal(status) {
		return false
	}

	// Check if job has timed out
	if deadline != nil && time.Now().After(*deadline) {
		return false
	}

	return true
}

// handleTimeout handles job timeout (called by timer)
func (s *PgStore) handleTimeout(jobID string) {
	update := types.JobUpdate{
		JobID:     jobID,
		Status:    types.JobStatusFailed,
		Error:     "job timed out",
		Timestamp: time.Now(),
	}

	if err := s.Update(update); err != nil {
		// Log error but don't fail - timeout already occurred
		fmt.Printf("Failed to update timed out job %s: %v\n", jobID, err)
	}

	s.mu.Lock()
	delete(s.timers, jobID)
	s.mu.Unlock()
}

// cancelTimer cancels and removes a timeout timer (must hold lock)
func (s *PgStore) cancelTimer(jobID string) {
	if timer, exists := s.timers[jobID]; exists {
		timer.Stop()
		delete(s.timers, jobID)
	}
}

// isTerminal checks if a status is terminal
func (s *PgStore) isTerminal(status types.JobStatus) bool {
	return status == types.JobStatusSucceeded || status == types.JobStatusFailed
}

// cleanupOldUpdates periodically removes old job updates (keep last 24 hours)
func (s *PgStore) cleanupOldUpdates() {
	ticker := time.NewTicker(1 * time.Hour)
	defer ticker.Stop()

	for {
		select {
		case <-s.ctx.Done():
			return
		case <-ticker.C:
			cutoff := time.Now().Add(-24 * time.Hour)
			query := `
				DELETE FROM job_updates
				WHERE timestamp < $1
				AND job_id IN (
					SELECT id FROM jobs
					WHERE status IN ('Succeeded', 'Failed')
					AND updated_at < $1
				)
			`
			_, err := s.pool.Exec(s.ctx, query, cutoff)
			if err != nil {
				fmt.Printf("Failed to cleanup old job updates: %v\n", err)
			}
		}
	}
}
