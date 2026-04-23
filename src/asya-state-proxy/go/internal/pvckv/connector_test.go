package pvckv

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/pg"
)

func TestConnector_ReadWriteExists(t *testing.T) {
	for _, tc := range allBackends(t) {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()

			exists, err := tc.conn.Exists(ctx, "k1")
			require.NoError(t, err)
			assert.False(t, exists)

			require.NoError(t, tc.conn.Write(ctx, "k1", json.RawMessage(`{"status":"running"}`)))

			exists, err = tc.conn.Exists(ctx, "k1")
			require.NoError(t, err)
			assert.True(t, exists)

			row, err := tc.conn.Read(ctx, "k1")
			require.NoError(t, err)
			assert.Equal(t, "k1", row.Key)
			assert.False(t, row.CreatedAt.IsZero())
			var doc map[string]any
			require.NoError(t, json.Unmarshal(row.Value, &doc))
			assert.Equal(t, "running", doc["status"])
		})
	}
}

func TestConnector_ReadNotFound(t *testing.T) {
	for _, tc := range allBackends(t) {
		t.Run(tc.name, func(t *testing.T) {
			_, err := tc.conn.Read(context.Background(), "missing")
			require.True(t, errors.Is(err, pg.ErrNotFound))
		})
	}
}

func TestConnector_Overwrite_PreservesCreatedAt(t *testing.T) {
	for _, tc := range allBackends(t) {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()
			require.NoError(t, tc.conn.Write(ctx, "k", json.RawMessage(`{"v":1}`)))
			row1, _ := tc.conn.Read(ctx, "k")

			require.NoError(t, tc.conn.Write(ctx, "k", json.RawMessage(`{"v":2}`)))
			row2, _ := tc.conn.Read(ctx, "k")

			var doc map[string]any
			require.NoError(t, json.Unmarshal(row2.Value, &doc))
			assert.Equal(t, float64(2), doc["v"])
			assert.True(t, row2.UpdatedAt.After(row2.CreatedAt) || row2.UpdatedAt.Equal(row2.CreatedAt))
			assert.Equal(t, row1.CreatedAt, row2.CreatedAt, "createdAt must be stable across overwrites")
		})
	}
}

func TestConnector_Delete(t *testing.T) {
	for _, tc := range allBackends(t) {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()
			require.NoError(t, tc.conn.Write(ctx, "del", json.RawMessage(`{"status":"done"}`)))
			require.NoError(t, tc.conn.Delete(ctx, "del"))
			exists, err := tc.conn.Exists(ctx, "del")
			require.NoError(t, err)
			assert.False(t, exists)
		})
	}
}

func TestConnector_DeleteNotFound(t *testing.T) {
	for _, tc := range allBackends(t) {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.conn.Delete(context.Background(), "ghost")
			require.True(t, errors.Is(err, pg.ErrNotFound))
		})
	}
}

func TestConnector_List(t *testing.T) {
	for _, tc := range allBackends(t) {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()
			for _, k := range []string{"pfx-a", "pfx-b", "other"} {
				require.NoError(t, tc.conn.Write(ctx, k, json.RawMessage(`{}`)))
			}
			keys, err := tc.conn.List(ctx, "pfx-")
			require.NoError(t, err)
			assert.ElementsMatch(t, []string{"pfx-a", "pfx-b"}, keys)
		})
	}
}

func TestConnector_WriteConditional_Success(t *testing.T) {
	for _, tc := range allBackends(t) {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()
			require.NoError(t, tc.conn.Write(ctx, "cas", json.RawMessage(`{"status":"pending"}`)))
			require.NoError(t, tc.conn.WriteConditional(ctx, "cas", json.RawMessage(`{"status":"running"}`), "pending"))
			row, _ := tc.conn.Read(ctx, "cas")
			var doc map[string]any
			json.Unmarshal(row.Value, &doc)
			assert.Equal(t, "running", doc["status"])
		})
	}
}

func TestConnector_WriteConditional_Fail(t *testing.T) {
	for _, tc := range allBackends(t) {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()
			require.NoError(t, tc.conn.Write(ctx, "cas2", json.RawMessage(`{"status":"running"}`)))
			err := tc.conn.WriteConditional(ctx, "cas2", json.RawMessage(`{"status":"done"}`), "pending")
			require.True(t, errors.Is(err, pg.ErrConditionFailed))
		})
	}
}

func TestConnector_PVC_Partition_Archive(t *testing.T) {
	dir := t.TempDir()
	conn, err := NewConnector(Config{
		Mode:            "pvc",
		BaseDir:         dir,
		Partition:       true,
		ArchiveStatuses: []string{"completed", "failed"},
	})
	require.NoError(t, err)
	ctx := context.Background()

	require.NoError(t, conn.Write(ctx, "task1", json.RawMessage(`{"status":"completed"}`)))

	keys, _ := conn.List(ctx, "")
	assert.Contains(t, keys, "task1")

	require.NoError(t, conn.Delete(ctx, "task1"))

	keys, _ = conn.List(ctx, "")
	assert.NotContains(t, keys, "task1")
}

func TestConnector_PVC_Partition_Remove_NonArchive(t *testing.T) {
	dir := t.TempDir()
	conn, err := NewConnector(Config{
		Mode:            "pvc",
		BaseDir:         dir,
		Partition:       true,
		ArchiveStatuses: []string{"completed"},
	})
	require.NoError(t, err)
	ctx := context.Background()

	require.NoError(t, conn.Write(ctx, "t1", json.RawMessage(`{"status":"running"}`)))
	require.NoError(t, conn.Delete(ctx, "t1"))

	keys, _ := conn.List(ctx, "")
	assert.NotContains(t, keys, "t1")
}

// ─── helpers ─────────────────────────────────────────────────────────────────

type backendCase struct {
	name string
	conn pg.ServerConnector
}

func allBackends(t *testing.T) []backendCase {
	t.Helper()
	pvc, err := NewConnector(Config{Mode: "pvc", BaseDir: t.TempDir()})
	require.NoError(t, err)
	return []backendCase{
		{name: "inmem", conn: newInMemConnector()},
		{name: "pvc", conn: pvc},
	}
}
