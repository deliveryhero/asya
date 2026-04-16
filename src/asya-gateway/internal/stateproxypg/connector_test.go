package stateproxypg

import (
	"context"
	"encoding/json"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dbURL := os.Getenv("STATEPROXY_PG_TEST_URL")
	if dbURL == "" {
		t.Skip("STATEPROXY_PG_TEST_URL not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dbURL)
	require.NoError(t, err)
	require.NoError(t, EnsureSchema(ctx, pool))
	// Clean up before test
	_, _ = pool.Exec(ctx, "DELETE FROM kv")
	t.Cleanup(func() { pool.Close() })
	return pool
}

func TestConnectorCRUD(t *testing.T) {
	pool := testPool(t)
	ctx := context.Background()
	conn := NewConnector(pool)

	// Write
	val := json.RawMessage(`{"status":"pending","actor":"echo"}`)
	require.NoError(t, conn.Write(ctx, "msg/test-1", val))

	// Read
	row, err := conn.Read(ctx, "msg/test-1")
	require.NoError(t, err)
	assert.Equal(t, "msg/test-1", row.Key)
	assert.JSONEq(t, `{"status":"pending","actor":"echo"}`, string(row.Value))

	// Exists
	exists, err := conn.Exists(ctx, "msg/test-1")
	require.NoError(t, err)
	assert.True(t, exists)

	exists, err = conn.Exists(ctx, "msg/nonexistent")
	require.NoError(t, err)
	assert.False(t, exists)

	// Update (upsert)
	val2 := json.RawMessage(`{"status":"running","actor":"echo"}`)
	require.NoError(t, conn.Write(ctx, "msg/test-1", val2))
	row, err = conn.Read(ctx, "msg/test-1")
	require.NoError(t, err)
	assert.JSONEq(t, `{"status":"running","actor":"echo"}`, string(row.Value))

	// List
	require.NoError(t, conn.Write(ctx, "msg/test-2", json.RawMessage(`{"status":"pending"}`)))
	keys, err := conn.List(ctx, "msg/")
	require.NoError(t, err)
	assert.Contains(t, keys, "msg/test-1")
	assert.Contains(t, keys, "msg/test-2")

	// Delete
	require.NoError(t, conn.Delete(ctx, "msg/test-1"))
	_, err = conn.Read(ctx, "msg/test-1")
	assert.ErrorIs(t, err, ErrNotFound)

	// Delete non-existent
	err = conn.Delete(ctx, "msg/nonexistent")
	assert.ErrorIs(t, err, ErrNotFound)
}

func TestConnectorReadNotFound(t *testing.T) {
	pool := testPool(t)
	ctx := context.Background()
	conn := NewConnector(pool)

	_, err := conn.Read(ctx, "msg/does-not-exist")
	assert.ErrorIs(t, err, ErrNotFound)
}
