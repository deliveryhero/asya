package jobs

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

// PgStore manages envelope state in PostgreSQL
type PgStore struct {
	pool      *pgxpool.Pool
	mu        sync.RWMutex
	listeners map[string][]chan types.EnvelopeUpdate
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

// NewPgStore creates a new PostgreSQL-backed envelope store
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
		listeners: make(map[string][]chan types.EnvelopeUpdate),
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
	for id, listeners := range s.listeners {
		for _, ch := range listeners {
			close(ch)
		}
		delete(s.listeners, id)
	}

	s.pool.Close()
}

// Create creates a new envelope
func (s *PgStore) Create(envelope *types.Envelope) error {
	now := time.Now()
	envelope.CreatedAt = now
	envelope.UpdatedAt = now
	envelope.Status = types.EnvelopeStatusPending

	// Initialize progress tracking
	envelope.TotalActors = len(envelope.Route.Actors)
	envelope.ActorsCompleted = 0
	envelope.ProgressPercent = 0.0

	var deadline *time.Time
	if envelope.TimeoutSec > 0 {
		d := now.Add(time.Duration(envelope.TimeoutSec) * time.Second)
		envelope.Deadline = d
		deadline = &d
	}

	payloadJSON, err := json.Marshal(envelope.Payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	query := `
		INSERT INTO envelopes (id, parent_id, status, route_actors, route_current, payload, timeout_sec, deadline,
		                 progress_percent, total_actors, actors_completed, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
	`

	_, err = s.pool.Exec(s.ctx, query,
		envelope.ID,
		envelope.ParentID,
		envelope.Status,
		envelope.Route.Actors,
		envelope.Route.Current,
		payloadJSON,
		envelope.TimeoutSec,
		deadline,
		envelope.ProgressPercent,
		envelope.TotalActors,
		envelope.ActorsCompleted,
		envelope.CreatedAt,
		envelope.UpdatedAt,
	)

	if err != nil {
		return fmt.Errorf("failed to create envelope: %w", err)
	}

	// Set timeout timer if specified
	if envelope.TimeoutSec > 0 {
		s.mu.Lock()
		s.timers[envelope.ID] = time.AfterFunc(time.Duration(envelope.TimeoutSec)*time.Second, func() {
			s.handleTimeout(envelope.ID)
		})
		s.mu.Unlock()
	}

	return nil
}

// Get retrieves a envelope by ID
func (s *PgStore) Get(id string) (*types.Envelope, error) {
	query := `
		SELECT id, parent_id, status, route_actors, route_current, payload, result, error, message, timeout_sec, deadline,
		       progress_percent, current_actor_idx, current_actor_name, actors_completed, total_actors, created_at, updated_at
		FROM envelopes
		WHERE id = $1
	`

	var envelope types.Envelope
	var payloadJSON, resultJSON []byte
	var deadline *time.Time
	var errorStr, messageStr, currentActorName *string
	var timeoutSec *int

	err := s.pool.QueryRow(s.ctx, query, id).Scan(
		&envelope.ID,
		&envelope.ParentID,
		&envelope.Status,
		&envelope.Route.Actors,
		&envelope.Route.Current,
		&payloadJSON,
		&resultJSON,
		&errorStr,
		&messageStr,
		&timeoutSec,
		&deadline,
		&envelope.ProgressPercent,
		&envelope.CurrentActorIdx,
		&currentActorName,
		&envelope.ActorsCompleted,
		&envelope.TotalActors,
		&envelope.CreatedAt,
		&envelope.UpdatedAt,
	)

	if err == pgx.ErrNoRows {
		return nil, fmt.Errorf("envelope %s not found", id)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to get envelope: %w", err)
	}

	// Handle nullable fields
	if deadline != nil {
		envelope.Deadline = *deadline
	}

	if errorStr != nil {
		envelope.Error = *errorStr
	}

	if messageStr != nil {
		envelope.Message = *messageStr
	}

	if timeoutSec != nil {
		envelope.TimeoutSec = *timeoutSec
	}

	if currentActorName != nil {
		envelope.CurrentActorName = *currentActorName
	}

	if payloadJSON != nil {
		if err := json.Unmarshal(payloadJSON, &envelope.Payload); err != nil {
			return nil, fmt.Errorf("failed to unmarshal payload: %w", err)
		}
	}

	if resultJSON != nil {
		if err := json.Unmarshal(resultJSON, &envelope.Result); err != nil {
			return nil, fmt.Errorf("failed to unmarshal result: %w", err)
		}
	} else {
		envelope.Result = map[string]interface{}{}
	}

	return &envelope, nil
}

// Update updates a envelope's status
func (s *PgStore) Update(update types.EnvelopeUpdate) error {
	tx, err := s.pool.Begin(s.ctx)
	if err != nil {
		return fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(s.ctx) }()

	// Update main envelope record
	var resultJSON []byte
	if update.Result != nil {
		resultJSON, err = json.Marshal(update.Result)
		if err != nil {
			return fmt.Errorf("failed to marshal result: %w", err)
		}
	}

	updateQuery := `
		UPDATE envelopes
		SET status = $1,
		    result = COALESCE($2, result),
		    error = COALESCE($3, error),
		    message = COALESCE(NULLIF($4, ''), message),
		    progress_percent = COALESCE($5, progress_percent),
		    updated_at = $6
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
	)

	if err != nil {
		return fmt.Errorf("failed to update envelope: %w", err)
	}

	if result.RowsAffected() == 0 {
		return fmt.Errorf("envelope %s not found", update.ID)
	}

	// Insert update record for SSE streaming
	// Derive current_actor_name from Actors and CurrentActorIdx if available
	var currentActorName *string
	if update.CurrentActorIdx != nil && *update.CurrentActorIdx >= 0 && *update.CurrentActorIdx < len(update.Actors) {
		name := update.Actors[*update.CurrentActorIdx]
		currentActorName = &name
	}

	insertUpdateQuery := `
		INSERT INTO envelope_updates (envelope_id, status, message, result, error, progress_percent, actor, envelope_state, timestamp)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
	`

	// EnvelopeState is already nullable (*string), pass directly
	var envelopeState interface{}
	if update.EnvelopeState != nil && *update.EnvelopeState != "" {
		envelopeState = *update.EnvelopeState
	}

	_, err = tx.Exec(s.ctx, insertUpdateQuery,
		update.ID,
		update.Status,
		update.Message,
		resultJSON,
		update.Error,
		update.ProgressPercent,
		currentActorName,
		envelopeState,
		update.Timestamp,
	)

	if err != nil {
		return fmt.Errorf("failed to insert envelope update: %w", err)
	}

	if err := tx.Commit(s.ctx); err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}

	// Cancel timeout timer if envelope reaches final state
	if s.isFinal(update.Status) {
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

// UpdateProgress updates envelope progress (more frequent, lighter update)
func (s *PgStore) UpdateProgress(update types.EnvelopeUpdate) error {
	tx, err := s.pool.Begin(s.ctx)
	if err != nil {
		return fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(s.ctx) }()

	// Update main envelope record with progress fields
	// Derive current_actor_name from Actors and CurrentActorIdx
	var currentActorName *string
	if update.CurrentActorIdx != nil && *update.CurrentActorIdx >= 0 && *update.CurrentActorIdx < len(update.Actors) {
		name := update.Actors[*update.CurrentActorIdx]
		currentActorName = &name
	}

	// Calculate total_actors from the Actors slice when route is updated
	var totalActors *int
	if len(update.Actors) > 0 {
		total := len(update.Actors)
		totalActors = &total
	}

	updateQuery := `
		UPDATE envelopes
		SET progress_percent = COALESCE($1, progress_percent),
		    current_actor_idx = COALESCE($2, current_actor_idx),
		    current_actor_name = COALESCE($3, current_actor_name),
		    message = COALESCE(NULLIF($4, ''), message),
		    route_actors = COALESCE($5, route_actors),
		    total_actors = COALESCE($6, total_actors),
		    status = $7,
		    updated_at = $8
		WHERE id = $9
	`

	_, err = tx.Exec(s.ctx, updateQuery,
		update.ProgressPercent,
		update.CurrentActorIdx,
		currentActorName,
		update.Message,
		update.Actors,
		totalActors,
		update.Status,
		update.Timestamp,
		update.ID,
	)

	if err != nil {
		return fmt.Errorf("failed to update envelope progress: %w", err)
	}

	// Insert progress update record (uses derived current_actor_name for SSE streaming)
	insertUpdateQuery := `
		INSERT INTO envelope_updates (envelope_id, status, message, progress_percent, actor, envelope_state, timestamp)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`

	// EnvelopeState is already nullable (*string), pass directly
	var envelopeState interface{}
	if update.EnvelopeState != nil && *update.EnvelopeState != "" {
		envelopeState = *update.EnvelopeState
	}

	_, err = tx.Exec(s.ctx, insertUpdateQuery,
		update.ID,
		update.Status,
		update.Message,
		update.ProgressPercent,
		currentActorName,
		envelopeState,
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

// GetUpdates retrieves all updates for a envelope (for SSE streaming)
func (s *PgStore) GetUpdates(id string, since *time.Time) ([]types.EnvelopeUpdate, error) {
	var query string
	var args []interface{}

	if since != nil {
		query = `
			SELECT envelope_id, status, message, result, error, progress_percent, actor, envelope_state, timestamp
			FROM envelope_updates
			WHERE envelope_id = $1 AND timestamp > $2
			ORDER BY timestamp ASC
		`
		args = []interface{}{id, since}
	} else {
		query = `
			SELECT envelope_id, status, message, result, error, progress_percent, actor, envelope_state, timestamp
			FROM envelope_updates
			WHERE envelope_id = $1
			ORDER BY timestamp ASC
		`
		args = []interface{}{id}
	}

	rows, err := s.pool.Query(s.ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to query updates: %w", err)
	}
	defer rows.Close()

	var updates []types.EnvelopeUpdate
	for rows.Next() {
		var update types.EnvelopeUpdate
		var resultJSON []byte
		var errorStr *string
		var actorName *string

		err := rows.Scan(
			&update.ID,
			&update.Status,
			&update.Message,
			&resultJSON,
			&errorStr,
			&update.ProgressPercent,
			&actorName,
			&update.EnvelopeState,
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

// Subscribe creates a listener channel for envelope updates
func (s *PgStore) Subscribe(id string) chan types.EnvelopeUpdate {
	s.mu.Lock()
	defer s.mu.Unlock()

	ch := make(chan types.EnvelopeUpdate, 10)
	s.listeners[id] = append(s.listeners[id], ch)

	return ch
}

// Unsubscribe removes a listener channel
func (s *PgStore) Unsubscribe(id string, ch chan types.EnvelopeUpdate) {
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
func (s *PgStore) notifyListeners(update types.EnvelopeUpdate) {
	listeners := s.listeners[update.ID]
	for _, ch := range listeners {
		select {
		case ch <- update:
		default:
			// Channel full, skip
		}
	}
}

// IsActive checks if a envelope is still active
func (s *PgStore) IsActive(id string) bool {
	query := `
		SELECT status, deadline
		FROM envelopes
		WHERE id = $1
	`

	var status types.EnvelopeStatus
	var deadline *time.Time

	err := s.pool.QueryRow(s.ctx, query, id).Scan(&status, &deadline)
	if err != nil {
		return false
	}

	// Check if envelope is in final state
	if s.isFinal(status) {
		return false
	}

	// Check if envelope has timed out
	if deadline != nil && time.Now().After(*deadline) {
		return false
	}

	return true
}

// handleTimeout handles envelope timeout (called by timer)
func (s *PgStore) handleTimeout(id string) {
	// Check if envelope is already in final state before marking as timed out
	envelope, err := s.Get(id)
	if err != nil {
		fmt.Printf("Failed to get envelope %s for timeout check: %v\n", id, err)
		s.mu.Lock()
		delete(s.timers, id)
		s.mu.Unlock()
		return
	}

	// Don't overwrite final states
	if s.isFinal(envelope.Status) {
		s.mu.Lock()
		delete(s.timers, id)
		s.mu.Unlock()
		return
	}

	update := types.EnvelopeUpdate{
		ID:        id,
		Status:    types.EnvelopeStatusFailed,
		Error:     "envelope timed out",
		Timestamp: time.Now(),
	}

	if err := s.Update(update); err != nil {
		fmt.Printf("Failed to update timed out envelope %s: %v\n", id, err)
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

// isFinal checks if a status is final
func (s *PgStore) isFinal(status types.EnvelopeStatus) bool {
	return status == types.EnvelopeStatusSucceeded || status == types.EnvelopeStatusFailed
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
				DELETE FROM envelope_updates
				WHERE timestamp < $1
				AND envelope_id IN (
					SELECT id FROM envelopes
					WHERE status IN ('succeeded', 'failed')
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
