package pvckv

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/pg"
)

func TestInMem_Query_FilterEq(t *testing.T) {
	conn := newInMemConnector()
	seedConn(t, conn, map[string]string{
		"m-1": `{"status":"running","actor":"train"}`,
		"m-2": `{"status":"done","actor":"eval"}`,
		"m-3": `{"status":"running","actor":"deploy"}`,
	})
	resp, err := conn.Query(context.Background(), pg.QueryRequest{
		Filter: map[string]any{"status": "running"},
	})
	require.NoError(t, err)
	keys := rowKeys(resp)
	assert.Contains(t, keys, "m-1")
	assert.Contains(t, keys, "m-3")
	assert.NotContains(t, keys, "m-2")
}

func TestInMem_Query_Prefix(t *testing.T) {
	conn := newInMemConnector()
	seedConn(t, conn, map[string]string{
		"pfx-1": `{"status":"running"}`,
		"pfx-2": `{"status":"done"}`,
		"other": `{"status":"running"}`,
	})
	resp, err := conn.Query(context.Background(), pg.QueryRequest{Prefix: "pfx-"})
	require.NoError(t, err)
	keys := rowKeys(resp)
	assert.Contains(t, keys, "pfx-1")
	assert.Contains(t, keys, "pfx-2")
	assert.NotContains(t, keys, "other")
}

func TestInMem_Query_Gt(t *testing.T) {
	conn := newInMemConnector()
	seedConn(t, conn, map[string]string{
		"a": `{"progress":30}`,
		"b": `{"progress":70}`,
		"c": `{"progress":90}`,
	})
	resp, err := conn.Query(context.Background(), pg.QueryRequest{
		Filter: map[string]any{"progress": map[string]any{"$gt": float64(50)}},
	})
	require.NoError(t, err)
	keys := rowKeys(resp)
	assert.Contains(t, keys, "b")
	assert.Contains(t, keys, "c")
	assert.NotContains(t, keys, "a")
}

func TestInMem_Query_Limit(t *testing.T) {
	conn := newInMemConnector()
	seedConn(t, conn, map[string]string{
		"x-1": `{"status":"running"}`,
		"x-2": `{"status":"running"}`,
		"x-3": `{"status":"running"}`,
	})
	resp, err := conn.Query(context.Background(), pg.QueryRequest{Prefix: "x-", Limit: 2})
	require.NoError(t, err)
	assert.LessOrEqual(t, len(resp.Rows), 2)
	assert.Equal(t, 3, resp.Total)
}

func TestInMem_Query_Count(t *testing.T) {
	conn := newInMemConnector()
	seedConn(t, conn, map[string]string{
		"c-1": `{"status":"running"}`,
		"c-2": `{"status":"done"}`,
	})
	resp, err := conn.Query(context.Background(), pg.QueryRequest{Count: true})
	require.NoError(t, err)
	assert.Equal(t, 2, resp.Total)
	assert.Empty(t, resp.Rows)
}

func TestInMem_Query_Exists(t *testing.T) {
	conn := newInMemConnector()
	seedConn(t, conn, map[string]string{
		"e-1": `{"status":"running","error":"oops"}`,
		"e-2": `{"status":"running"}`,
	})
	resp, err := conn.Query(context.Background(), pg.QueryRequest{
		Filter: map[string]any{"error": map[string]any{"$exists": true}},
	})
	require.NoError(t, err)
	keys := rowKeys(resp)
	assert.Contains(t, keys, "e-1")
	assert.NotContains(t, keys, "e-2")
}

func TestBuildDuckDBWhere_Empty(t *testing.T) {
	where, args, err := buildDuckDBWhere(nil)
	assert.NoError(t, err)
	assert.Empty(t, where)
	assert.Nil(t, args)
}

func TestBuildDuckDBWhere_ImplicitEq(t *testing.T) {
	where, args, err := buildDuckDBWhere(map[string]any{"status": "running"})
	assert.NoError(t, err)
	assert.Contains(t, where, "json_extract_string")
	assert.Contains(t, where, "$1")
	assert.Equal(t, []any{"running"}, args)
}

func TestBuildDuckDBWhere_Gt(t *testing.T) {
	where, args, err := buildDuckDBWhere(map[string]any{
		"progress": map[string]any{"$gt": float64(50)},
	})
	assert.NoError(t, err)
	assert.Contains(t, where, ">")
	assert.Equal(t, []any{float64(50)}, args)
}

func TestBuildDuckDBWhere_UnsupportedOp(t *testing.T) {
	_, _, err := buildDuckDBWhere(map[string]any{
		"x": map[string]any{"$regex": "abc"},
	})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported operator")
}

func TestBuildDuckDBOrderBy(t *testing.T) {
	assert.Equal(t, "", buildDuckDBOrderBy(nil))
	assert.Contains(t, buildDuckDBOrderBy([]string{"-status"}), "DESC")
	assert.Contains(t, buildDuckDBOrderBy([]string{"status"}), "ASC")
}

func TestPVC_Query_DuckDB(t *testing.T) {
	dir := t.TempDir()
	conn, err := NewConnector(Config{Mode: "pvc", BaseDir: dir})
	require.NoError(t, err)

	seedConn(t, conn, map[string]string{
		"q-1": `{"status":"running","actor":"train"}`,
		"q-2": `{"status":"done","actor":"eval"}`,
		"q-3": `{"status":"running","actor":"deploy"}`,
	})

	resp, err := conn.Query(context.Background(), pg.QueryRequest{
		Prefix: "q-",
		Filter: map[string]any{"status": "running"},
	})
	require.NoError(t, err)
	keys := rowKeys(resp)
	assert.Contains(t, keys, "q-1")
	assert.Contains(t, keys, "q-3")
	assert.NotContains(t, keys, "q-2")
}

func TestPVC_Query_EmptyDir(t *testing.T) {
	dir := t.TempDir()
	conn, err := NewConnector(Config{Mode: "pvc", BaseDir: dir})
	require.NoError(t, err)
	resp, err := conn.Query(context.Background(), pg.QueryRequest{Prefix: "none-"})
	require.NoError(t, err)
	assert.Empty(t, resp.Rows)
}

// ─── helpers ─────────────────────────────────────────────────────────────────

func seedConn(t *testing.T, conn pg.ServerConnector, docs map[string]string) {
	t.Helper()
	for k, v := range docs {
		require.NoError(t, conn.Write(context.Background(), k, json.RawMessage(v)))
	}
}

func rowKeys(resp *pg.QueryResponse) []string {
	keys := make([]string, len(resp.Rows))
	for i, r := range resp.Rows {
		keys[i] = r.Key
	}
	return keys
}
