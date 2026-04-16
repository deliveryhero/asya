package stateproxypg

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// ErrNotFound is returned when a key is not present in the kv table.
var ErrNotFound = errors.New("key not found")

// KVRow represents a row in the kv table.
type KVRow struct {
	Key       string          `json:"key"`
	Value     json.RawMessage `json:"value"`
	CreatedAt time.Time       `json:"created_at"`
	UpdatedAt time.Time       `json:"updated_at"`
}

// Connector implements state-proxy operations over PostgreSQL.
type Connector struct {
	pool *pgxpool.Pool
}

// NewConnector creates a new PG connector.
func NewConnector(pool *pgxpool.Pool) *Connector {
	return &Connector{pool: pool}
}

// Read returns the value for a key. Returns ErrNotFound if missing.
func (c *Connector) Read(ctx context.Context, key string) (*KVRow, error) {
	row := c.pool.QueryRow(ctx,
		"SELECT key, value, created_at, updated_at FROM kv WHERE key = $1", key)

	var kv KVRow
	err := row.Scan(&kv.Key, &kv.Value, &kv.CreatedAt, &kv.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("read %q: %w", key, ErrNotFound)
	}
	if err != nil {
		return nil, fmt.Errorf("read %q: %w", key, err)
	}
	return &kv, nil
}

// Write upserts a key-value pair. Updates updated_at on conflict.
func (c *Connector) Write(ctx context.Context, key string, value json.RawMessage) error {
	_, err := c.pool.Exec(ctx,
		`INSERT INTO kv (key, value) VALUES ($1, $2)
		 ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()`,
		key, value)
	if err != nil {
		return fmt.Errorf("write %q: %w", key, err)
	}
	return nil
}

// Exists returns true if the key exists.
func (c *Connector) Exists(ctx context.Context, key string) (bool, error) {
	var dummy int
	err := c.pool.QueryRow(ctx, "SELECT 1 FROM kv WHERE key = $1", key).Scan(&dummy)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("exists %q: %w", key, err)
	}
	return true, nil
}

// Delete removes a key. Returns ErrNotFound if missing.
func (c *Connector) Delete(ctx context.Context, key string) error {
	ct, err := c.pool.Exec(ctx, "DELETE FROM kv WHERE key = $1", key)
	if err != nil {
		return fmt.Errorf("delete %q: %w", key, err)
	}
	if ct.RowsAffected() == 0 {
		return fmt.Errorf("delete %q: %w", key, ErrNotFound)
	}
	return nil
}

// List returns keys matching the prefix.
func (c *Connector) List(ctx context.Context, prefix string) ([]string, error) {
	rows, err := c.pool.Query(ctx,
		"SELECT key FROM kv WHERE key LIKE $1 ORDER BY key", prefix+"%")
	if err != nil {
		return nil, fmt.Errorf("list prefix %q: %w", prefix, err)
	}
	defer rows.Close()

	var keys []string
	for rows.Next() {
		var k string
		if err := rows.Scan(&k); err != nil {
			return nil, fmt.Errorf("list scan: %w", err)
		}
		keys = append(keys, k)
	}
	return keys, rows.Err()
}
