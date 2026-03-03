package taskstore

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// PgStore manages task state in PostgreSQL
type PgStore struct {
	pool      *pgxpool.Pool
	mu        sync.RWMutex
	listeners map[string][]chan types.TaskUpdate
	timers    map[string]*time.Timer
	ctx       context.Context
	cancel    context.CancelFunc
}

// getEnvInt reads an integer from environment variable with default value
func getEnvInt(key string, defaultValue int) int {
	if val := os.Getenv(key); val != "" {
		if intVal, err := strconv.Atoi(val); err == nil {
			return intVal
		}
	}
	return defaultValue
}

// getEnvDuration reads a duration from environment variable with default value
func getEnvDuration(key string, defaultValue time.Duration) time.Duration {
	if val := os.Getenv(key); val != "" {
		if duration, err := time.ParseDuration(val); err == nil {
			return duration
		}
	}
	return defaultValue
}

// NewPgStore creates a new PostgreSQL-backed task store
func NewPgStore(ctx context.Context, connString string) (*PgStore, error) {
	config, err := pgxpool.ParseConfig(connString)
	if err != nil {
		return nil, fmt.Errorf("failed to parse connection string: %w", err)
	}

	// Configure connection pool from environment variables
	config.MaxConns = int32(getEnvInt("ASYA_DB_MAX_CONNS", 10))
	config.MinConns = int32(getEnvInt("ASYA_DB_MIN_CONNS", 2))
	config.MaxConnLifetime = getEnvDuration("ASYA_DB_MAX_CONN_LIFETIME", time.Hour)
	config.MaxConnIdleTime = getEnvDuration("ASYA_DB_MAX_CONN_IDLE_TIME", 30*time.Minute)

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
		listeners: make(map[string][]chan types.TaskUpdate),
		timers:    make(map[string]*time.Timer),
		ctx:       storeCtx,
		cancel:    cancel,
	}

	// Start background cleanup goroutine
	go s.cleanupOldUpdates()

	return s, nil
}

// Pool returns the underlying connection pool.
func (s *PgStore) Pool() *pgxpool.Pool {
	return s.pool
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
	for id, listeners := range s.listeners {
		for _, ch := range listeners {
			close(ch)
		}
		delete(s.listeners, id)
	}

	s.pool.Close()
}

// totalActors returns the total number of actors in the route (prev + curr + next).
func totalActors(route types.Route) int {
	total := len(route.Prev) + len(route.Next)
	if route.Curr != "" {
		total++
	}
	return total
}

// Create creates a new task
func (s *PgStore) Create(task *types.Task) error {
	now := time.Now()
	task.CreatedAt = now
	task.UpdatedAt = now
	task.Status = types.TaskStatusPending

	// Initialize progress tracking
	task.TotalActors = totalActors(task.Route)
	task.ActorsCompleted = 0
	task.ProgressPercent = 0.0

	// Derive current actor name from route
	currentActorName := task.Route.Curr

	var deadline *time.Time
	if task.TimeoutSec > 0 {
		d := now.Add(time.Duration(task.TimeoutSec) * time.Second)
		task.Deadline = d
		deadline = &d
	}

	payloadJSON, err := json.Marshal(task.Payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	// Ensure nil slices are stored as empty arrays
	routePrev := task.Route.Prev
	if routePrev == nil {
		routePrev = []string{}
	}
	routeNext := task.Route.Next
	if routeNext == nil {
		routeNext = []string{}
	}

	query := `
		INSERT INTO tasks (id, parent_id, context_id, status, route_prev, route_curr, route_next, current_actor_name, payload,
		                   timeout_sec, deadline, progress_percent, total_actors, actors_completed, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
	`

	_, err = s.pool.Exec(s.ctx, query,
		task.ID,
		task.ParentID,
		task.ContextID,
		task.Status,
		routePrev,
		task.Route.Curr,
		routeNext,
		currentActorName,
		payloadJSON,
		task.TimeoutSec,
		deadline,
		task.ProgressPercent,
		task.TotalActors,
		task.ActorsCompleted,
		task.CreatedAt,
		task.UpdatedAt,
	)

	if err != nil {
		return fmt.Errorf("failed to create task: %w", err)
	}

	// Set timeout timer if specified
	if task.TimeoutSec > 0 {
		s.mu.Lock()
		s.timers[task.ID] = time.AfterFunc(time.Duration(task.TimeoutSec)*time.Second, func() {
			s.handleTimeout(task.ID)
		})
		s.mu.Unlock()
	}

	return nil
}

// Get retrieves a task by ID
func (s *PgStore) Get(id string) (*types.Task, error) {
	query := `
		SELECT id, parent_id, context_id, status, route_prev, route_curr, route_next, payload, result, error, message, timeout_sec, deadline,
		       progress_percent, current_actor_name, actors_completed, total_actors, created_at, updated_at
		FROM tasks
		WHERE id = $1
	`

	var task types.Task
	var payloadJSON, resultJSON []byte
	var deadline *time.Time
	var errorStr, messageStr, currentActorName *string
	var contextID *string
	var timeoutSec *int

	err := s.pool.QueryRow(s.ctx, query, id).Scan(
		&task.ID,
		&task.ParentID,
		&contextID,
		&task.Status,
		&task.Route.Prev,
		&task.Route.Curr,
		&task.Route.Next,
		&payloadJSON,
		&resultJSON,
		&errorStr,
		&messageStr,
		&timeoutSec,
		&deadline,
		&task.ProgressPercent,
		&currentActorName,
		&task.ActorsCompleted,
		&task.TotalActors,
		&task.CreatedAt,
		&task.UpdatedAt,
	)

	if err == pgx.ErrNoRows {
		return nil, fmt.Errorf("task %s: %w", id, ErrNotFound)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to get task: %w", err)
	}

	// Handle nullable fields
	if contextID != nil {
		task.ContextID = *contextID
	}

	if deadline != nil {
		task.Deadline = *deadline
	}

	if errorStr != nil {
		task.Error = *errorStr
	}

	if messageStr != nil {
		task.Message = *messageStr
	}

	if timeoutSec != nil {
		task.TimeoutSec = *timeoutSec
	}

	if currentActorName != nil {
		task.CurrentActorName = *currentActorName
	}

	// Ensure route slices are never nil
	if task.Route.Prev == nil {
		task.Route.Prev = []string{}
	}
	if task.Route.Next == nil {
		task.Route.Next = []string{}
	}

	if payloadJSON != nil {
		if err := json.Unmarshal(payloadJSON, &task.Payload); err != nil {
			return nil, fmt.Errorf("failed to unmarshal payload: %w", err)
		}
	}

	if resultJSON != nil {
		if err := json.Unmarshal(resultJSON, &task.Result); err != nil {
			return nil, fmt.Errorf("failed to unmarshal result: %w", err)
		}
	} else {
		task.Result = map[string]interface{}{}
	}

	return &task, nil
}

// Update updates a task's status
func (s *PgStore) Update(update types.TaskUpdate) error {
	tx, err := s.pool.Begin(s.ctx)
	if err != nil {
		return fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(s.ctx) }()

	// Update main task record
	var resultJSON []byte
	if update.Result != nil {
		resultJSON, err = json.Marshal(update.Result)
		if err != nil {
			return fmt.Errorf("failed to marshal result: %w", err)
		}
	}

	// Prepare pause_metadata for SQL
	var pauseMetadata interface{}
	if update.PauseMetadata != nil {
		pauseMetadata = []byte(update.PauseMetadata)
	}

	updateQuery := `
		UPDATE tasks
		SET status = $1,
		    result = COALESCE($2, result),
		    error = COALESCE($3, error),
		    message = COALESCE(NULLIF($4, ''), message),
		    progress_percent = COALESCE($5, progress_percent),
		    updated_at = $6,
		    pause_metadata = COALESCE($8, pause_metadata)
		WHERE id = $7
	`

	result, err := tx.Exec(s.ctx, updateQuery,
		update.Status,
		resultJSON,
		update.Error,
		update.Message,
		update.ProgressPercent,
		update.Timestamp,
		update.ID,
		pauseMetadata,
	)

	if err != nil {
		return fmt.Errorf("failed to update task: %w", err)
	}

	if result.RowsAffected() == 0 {
		return fmt.Errorf("task %s not found", update.ID)
	}

	// Insert update record for SSE streaming
	// Derive current_actor_name from Curr field if available
	var currentActorName *string
	if update.Curr != "" {
		name := update.Curr
		currentActorName = &name
	} else if update.Actor != "" {
		currentActorName = &update.Actor
	}

	insertUpdateQuery := `
		INSERT INTO task_updates (task_id, status, message, result, error, progress_percent, actor, task_state, timestamp)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
	`

	// TaskState is already nullable (*string), pass directly
	var taskState interface{}
	if update.TaskState != nil && *update.TaskState != "" {
		taskState = *update.TaskState
	}

	_, err = tx.Exec(s.ctx, insertUpdateQuery,
		update.ID,
		update.Status,
		update.Message,
		resultJSON,
		update.Error,
		update.ProgressPercent,
		currentActorName,
		taskState,
		update.Timestamp,
	)

	if err != nil {
		return fmt.Errorf("failed to insert task update: %w", err)
	}

	if err := tx.Commit(s.ctx); err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}

	// Cancel timeout timer if task reaches final state
	if s.isFinal(update.Status) {
		s.mu.Lock()
		s.cancelTimer(update.ID)
		s.mu.Unlock()
	}

	// Freeze timeout timer when task is paused: save remaining budget via SQL and cancel timer
	if update.Status == types.TaskStatusPaused {
		if _, err := s.pool.Exec(s.ctx,
			`UPDATE tasks SET remaining_timeout_sec = EXTRACT(EPOCH FROM (deadline - NOW())) WHERE id = $1 AND deadline IS NOT NULL`,
			update.ID); err != nil {
			return fmt.Errorf("failed to save remaining timeout for paused task %s: %w", update.ID, err)
		}
		s.mu.Lock()
		s.cancelTimer(update.ID)
		s.mu.Unlock()
	}

	// Notify listeners
	s.mu.RLock()
	s.notifyListeners(update)
	s.mu.RUnlock()

	return nil
}

// UpdateProgress updates task progress (more frequent, lighter update)
func (s *PgStore) UpdateProgress(update types.TaskUpdate) error {
	tx, err := s.pool.Begin(s.ctx)
	if err != nil {
		return fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(s.ctx) }()

	// Derive current_actor_name from Curr field
	var currentActorName *string
	if update.Curr != "" {
		name := update.Curr
		currentActorName = &name
	}

	// Calculate total_actors from the route when it is updated
	var totalActors *int
	if update.Curr != "" || len(update.Prev) > 0 || len(update.Next) > 0 {
		total := len(update.Prev) + len(update.Next)
		if update.Curr != "" {
			total++
		}
		totalActors = &total
	}

	// actors_completed = len(prev): actors that have fully processed the message
	actorsCompleted := len(update.Prev)

	// Ensure nil slices are stored as empty arrays
	routePrev := update.Prev
	if routePrev == nil {
		routePrev = []string{}
	}
	routeNext := update.Next
	if routeNext == nil {
		routeNext = []string{}
	}

	// Prepare pause_metadata for SQL (nil → NULL, preserves existing value via COALESCE)
	var pauseMetadata interface{}
	if update.PauseMetadata != nil {
		pauseMetadata = []byte(update.PauseMetadata)
	}

	updateQuery := `
		UPDATE tasks
		SET progress_percent  = COALESCE($1, progress_percent),
		    current_actor_name = COALESCE($2, current_actor_name),
		    message            = COALESCE(NULLIF($3, ''), message),
		    route_prev         = $4,
		    route_curr         = $5,
		    route_next         = $6,
		    total_actors       = COALESCE($7, total_actors),
		    actors_completed   = $8,
		    status             = $9,
		    updated_at         = $10,
		    pause_metadata     = COALESCE($12, pause_metadata)
		WHERE id = $11
	`

	_, err = tx.Exec(s.ctx, updateQuery,
		update.ProgressPercent,
		currentActorName,
		update.Message,
		routePrev,
		update.Curr,
		routeNext,
		totalActors,
		actorsCompleted,
		update.Status,
		update.Timestamp,
		update.ID,
		pauseMetadata,
	)

	if err != nil {
		return fmt.Errorf("failed to update task progress: %w", err)
	}

	// Insert progress update record (uses derived current_actor_name for SSE streaming)
	insertUpdateQuery := `
		INSERT INTO task_updates (task_id, status, message, progress_percent, actor, task_state, partial_payload, timestamp)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
	`

	// TaskState is already nullable (*string), pass directly
	var taskState interface{}
	if update.TaskState != nil && *update.TaskState != "" {
		taskState = *update.TaskState
	}

	// PartialPayload is persisted so SSE clients connecting after task completion can replay it
	var partialPayload interface{}
	if update.PartialPayload != nil {
		partialPayload = []byte(update.PartialPayload)
	}

	_, err = tx.Exec(s.ctx, insertUpdateQuery,
		update.ID,
		update.Status,
		update.Message,
		update.ProgressPercent,
		currentActorName,
		taskState,
		partialPayload,
		update.Timestamp,
	)

	if err != nil {
		return fmt.Errorf("failed to insert progress update: %w", err)
	}

	if err := tx.Commit(s.ctx); err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}

	// Freeze timeout timer when task is paused: save remaining budget and cancel timer
	if update.Status == types.TaskStatusPaused {
		if _, err := s.pool.Exec(s.ctx,
			`UPDATE tasks SET remaining_timeout_sec = EXTRACT(EPOCH FROM (deadline - NOW())) WHERE id = $1 AND deadline IS NOT NULL`,
			update.ID); err != nil {
			return fmt.Errorf("failed to save remaining timeout for paused task %s: %w", update.ID, err)
		}
		s.mu.Lock()
		s.cancelTimer(update.ID)
		s.notifyListeners(update)
		s.mu.Unlock()
	} else {
		// Notify SSE listeners
		s.mu.RLock()
		s.notifyListeners(update)
		s.mu.RUnlock()
	}

	return nil
}

// GetUpdates retrieves all updates for a task (for SSE streaming)
func (s *PgStore) GetUpdates(id string, since *time.Time) ([]types.TaskUpdate, error) {
	var query string
	var args []interface{}

	if since != nil {
		query = `
			SELECT task_id, status, message, result, error, progress_percent, actor, task_state, partial_payload, timestamp
			FROM task_updates
			WHERE task_id = $1 AND timestamp > $2
			ORDER BY timestamp ASC
		`
		args = []interface{}{id, since}
	} else {
		query = `
			SELECT task_id, status, message, result, error, progress_percent, actor, task_state, partial_payload, timestamp
			FROM task_updates
			WHERE task_id = $1
			ORDER BY timestamp ASC
		`
		args = []interface{}{id}
	}

	rows, err := s.pool.Query(s.ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to query updates: %w", err)
	}
	defer rows.Close()

	var updates []types.TaskUpdate
	for rows.Next() {
		var update types.TaskUpdate
		var resultJSON []byte
		var errorStr *string
		var actorName *string
		var partialPayloadJSON []byte

		err := rows.Scan(
			&update.ID,
			&update.Status,
			&update.Message,
			&resultJSON,
			&errorStr,
			&update.ProgressPercent,
			&actorName,
			&update.TaskState,
			&partialPayloadJSON,
			&update.Timestamp,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan update: %w", err)
		}

		if errorStr != nil {
			update.Error = *errorStr
		}

		if actorName != nil {
			update.Actor = *actorName
			update.Curr = *actorName
		}

		if resultJSON != nil {
			if err := json.Unmarshal(resultJSON, &update.Result); err != nil {
				return nil, fmt.Errorf("failed to unmarshal result: %w", err)
			}
		}

		if partialPayloadJSON != nil {
			update.PartialPayload = json.RawMessage(partialPayloadJSON)
		}

		updates = append(updates, update)
	}

	return updates, rows.Err()
}

// Subscribe creates a listener channel for task updates
func (s *PgStore) Subscribe(id string) chan types.TaskUpdate {
	s.mu.Lock()
	defer s.mu.Unlock()

	ch := make(chan types.TaskUpdate, 10)
	s.listeners[id] = append(s.listeners[id], ch)

	return ch
}

// Unsubscribe removes a listener channel
func (s *PgStore) Unsubscribe(id string, ch chan types.TaskUpdate) {
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

// notifyListeners sends updates to all listeners (must hold read lock)
func (s *PgStore) notifyListeners(update types.TaskUpdate) {
	listeners := s.listeners[update.ID]
	for _, ch := range listeners {
		select {
		case ch <- update:
		default:
			// Channel full, skip
		}
	}
}

// IsActive checks if a task is still active
func (s *PgStore) IsActive(id string) bool {
	query := `
		SELECT status, deadline
		FROM tasks
		WHERE id = $1
	`

	var status types.TaskStatus
	var deadline *time.Time

	err := s.pool.QueryRow(s.ctx, query, id).Scan(&status, &deadline)
	if err != nil {
		return false
	}

	// Check if task is in final state
	if s.isFinal(status) {
		return false
	}

	// Paused tasks are not active (sidecar should not route further)
	if status == types.TaskStatusPaused {
		return false
	}

	// Check if task has timed out
	if deadline != nil && time.Now().After(*deadline) {
		return false
	}

	return true
}

// handleTimeout handles task timeout (called by timer)
func (s *PgStore) handleTimeout(id string) {
	// Check if task is already in final state before marking as timed out
	task, err := s.Get(id)
	if err != nil {
		fmt.Printf("Failed to get task %s for timeout check: %v\n", id, err)
		s.mu.Lock()
		delete(s.timers, id)
		s.mu.Unlock()
		return
	}

	// Don't overwrite final states
	if s.isFinal(task.Status) {
		s.mu.Lock()
		delete(s.timers, id)
		s.mu.Unlock()
		return
	}

	update := types.TaskUpdate{
		ID:        id,
		Status:    types.TaskStatusFailed,
		Error:     "task timed out",
		Timestamp: time.Now(),
	}

	if err := s.Update(update); err != nil {
		fmt.Printf("Failed to update timed out task %s: %v\n", id, err)
	}

	s.mu.Lock()
	delete(s.timers, id)
	s.mu.Unlock()
}

// cancelTimer cancels and removes a timeout timer (must hold lock)
func (s *PgStore) cancelTimer(id string) {
	if timer, exists := s.timers[id]; exists {
		timer.Stop()
		delete(s.timers, id)
	}
}

// Resume transitions a paused task back to running, restarting the timeout timer
func (s *PgStore) Resume(id string) (*types.Task, error) {
	// Thaw: restore remaining timeout and transition to running
	result, err := s.pool.Exec(s.ctx, `
		UPDATE tasks
		SET status = $1,
		    deadline = CASE WHEN remaining_timeout_sec IS NOT NULL
		                    THEN NOW() + remaining_timeout_sec * INTERVAL '1 second'
		                    ELSE deadline END,
		    remaining_timeout_sec = NULL,
		    pause_metadata = NULL,
		    updated_at = NOW()
		WHERE id = $2 AND status = 'paused'
	`, types.TaskStatusRunning, id)
	if err != nil {
		return nil, fmt.Errorf("failed to resume task: %w", err)
	}

	if result.RowsAffected() == 0 {
		// Task either doesn't exist or is not paused
		task, err := s.Get(id)
		if err != nil {
			return nil, fmt.Errorf("task %s not found", id)
		}
		return nil, fmt.Errorf("task %s is not paused (status: %s)", id, task.Status)
	}

	// Fetch updated task
	task, err := s.Get(id)
	if err != nil {
		return nil, err
	}

	// Restart in-memory timeout timer with restored deadline
	if !task.Deadline.IsZero() {
		remaining := time.Until(task.Deadline)
		if remaining > 0 {
			s.mu.Lock()
			s.timers[id] = time.AfterFunc(remaining, func() {
				s.handleTimeout(id)
			})
			s.mu.Unlock()
		}
	}

	// Notify listeners
	update := types.TaskUpdate{
		ID:        id,
		Status:    types.TaskStatusRunning,
		Message:   "Task resumed",
		Timestamp: task.UpdatedAt,
	}
	s.mu.RLock()
	s.notifyListeners(update)
	s.mu.RUnlock()

	return task, nil
}

// List returns tasks, optionally filtered by status
func (s *PgStore) List(status *types.TaskStatus) ([]*types.Task, error) {
	query := `
		SELECT id, context_id, status, payload, result, error, timeout_seconds, deadline,
		       remaining_timeout_sec, progress_percent, current_actor_name, message,
		       pause_metadata, actors_completed, total_actors,
		       route_prev, route_curr, route_next,
		       created_at, updated_at
		FROM tasks`
	var args []any

	if status != nil {
		query += " WHERE status = $1"
		args = []any{*status}
	}

	query += " ORDER BY created_at DESC"

	rows, err := s.pool.Query(s.ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to list tasks: %w", err)
	}
	defer rows.Close()

	var tasks []*types.Task
	for rows.Next() {
		var task types.Task
		var payloadJSON, resultJSON, pauseMetadataJSON []byte
		var remainingTimeout *float64

		err := rows.Scan(
			&task.ID, &task.ContextID, &task.Status,
			&payloadJSON, &resultJSON, &task.Error,
			&task.TimeoutSec, &task.Deadline,
			&remainingTimeout,
			&task.ProgressPercent, &task.CurrentActorName, &task.Message,
			&pauseMetadataJSON,
			&task.ActorsCompleted, &task.TotalActors,
			&task.Route.Prev, &task.Route.Curr, &task.Route.Next,
			&task.CreatedAt, &task.UpdatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan task: %w", err)
		}

		if payloadJSON != nil {
			if err := json.Unmarshal(payloadJSON, &task.Payload); err != nil {
				return nil, fmt.Errorf("failed to unmarshal payload for task %s: %w", task.ID, err)
			}
		}
		if resultJSON != nil {
			if err := json.Unmarshal(resultJSON, &task.Result); err != nil {
				return nil, fmt.Errorf("failed to unmarshal result for task %s: %w", task.ID, err)
			}
		}
		if pauseMetadataJSON != nil {
			task.PauseMetadata = pauseMetadataJSON
		}
		if remainingTimeout != nil {
			task.RemainingTimeoutSec = remainingTimeout
		}

		tasks = append(tasks, &task)
	}

	return tasks, nil
}

// isFinal checks if a status is final
func (s *PgStore) isFinal(status types.TaskStatus) bool {
	return status == types.TaskStatusSucceeded || status == types.TaskStatusFailed || status == types.TaskStatusCanceled
}

// cleanupOldUpdates periodically removes old task updates (keep last 24 hours)
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
				DELETE FROM task_updates
				WHERE timestamp < $1
				AND task_id IN (
					SELECT id FROM tasks
					WHERE status IN ('succeeded', 'failed')
					AND updated_at < $1
				)
			`
			_, err := s.pool.Exec(s.ctx, query, cutoff)
			if err != nil {
				fmt.Printf("Failed to cleanup old task updates: %v\n", err)
			}
		}
	}
}
