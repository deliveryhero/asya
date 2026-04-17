package pg

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestBuildQuery_SimpleFilter(t *testing.T) {
	sql, args, err := buildFilterSQL(QueryRequest{
		Prefix: "msg/",
		Filter: map[string]any{"status": "running"},
		Sort:   []string{"-created_at"},
		Limit:  10,
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "key LIKE $1")
	assert.Contains(t, sql, "value @> $2")
	assert.Contains(t, sql, "ORDER BY created_at DESC")
	assert.Contains(t, sql, "LIMIT 10")
	assert.Equal(t, "msg/%", args[0])
}

func TestBuildQuery_ComparisonOps(t *testing.T) {
	sql, args, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"progress": map[string]any{"$gt": float64(50)},
		},
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "(value->>'progress')::numeric > $")
	assert.Equal(t, float64(50), args[0])
}

func TestBuildQuery_GteAndLte(t *testing.T) {
	sql, args, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"score": map[string]any{"$gte": float64(10), "$lte": float64(100)},
		},
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "(value->>'score')::numeric >=")
	assert.Contains(t, sql, "(value->>'score')::numeric <=")
	assert.Len(t, args, 2)
}

func TestBuildQuery_InOperator(t *testing.T) {
	sql, args, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"status": map[string]any{"$in": []any{"running", "pending"}},
		},
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "value->>'status' = ANY($1)")
	assert.Equal(t, []string{"running", "pending"}, args[0])
}

func TestBuildQuery_NinOperator(t *testing.T) {
	sql, _, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"status": map[string]any{"$nin": []any{"canceled"}},
		},
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "NOT (value->>'status' = ANY($1))")
}

func TestBuildQuery_ExistsOperator(t *testing.T) {
	sql, _, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"error": map[string]any{"$exists": true},
		},
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "value ? 'error'")

	sql2, _, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"error": map[string]any{"$exists": false},
		},
	})
	require.NoError(t, err)
	assert.Contains(t, sql2, "NOT (value ? 'error')")
}

func TestBuildQuery_NeOperator(t *testing.T) {
	sql, args, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"status": map[string]any{"$ne": "canceled"},
		},
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "value->>'status' != $1")
	assert.Equal(t, "canceled", args[0])
}

func TestBuildQuery_CountMode(t *testing.T) {
	sql, args, err := buildFilterSQL(QueryRequest{
		Prefix: "msg/",
		Filter: map[string]any{"status": "running"},
		Count:  true,
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "SELECT count(*)")
	assert.NotContains(t, sql, "key, value")
	assert.Equal(t, "msg/%", args[0])
}

func TestBuildQuery_SortByValueField(t *testing.T) {
	sql, _, err := buildFilterSQL(QueryRequest{
		Sort: []string{"-status", "created_at"},
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "value->>'status' DESC")
	assert.Contains(t, sql, "created_at ASC")
}

func TestBuildQuery_OffsetOnly(t *testing.T) {
	sql, _, err := buildFilterSQL(QueryRequest{
		Offset: 20,
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "OFFSET 20")
}

func TestBuildQuery_NoFilters(t *testing.T) {
	sql, args, err := buildFilterSQL(QueryRequest{})
	require.NoError(t, err)
	assert.Equal(t, "SELECT key, value, created_at, updated_at FROM kv", sql)
	assert.Empty(t, args)
}

func TestBuildQuery_ContainsOperator(t *testing.T) {
	sql, args, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"headers": map[string]any{"$contains": map[string]any{"trace_id": "abc"}},
		},
	})
	require.NoError(t, err)
	assert.Contains(t, sql, "value @> $1::jsonb")
	assert.Len(t, args, 1)
}

func TestBuildQuery_InvalidFilterFieldName(t *testing.T) {
	_, _, err := buildFilterSQL(QueryRequest{
		Filter: map[string]any{"Robert'; DROP TABLE kv;--": "running"},
	})
	assert.ErrorIs(t, err, ErrInvalidFieldName)
}

func TestBuildQuery_InvalidSortFieldName(t *testing.T) {
	_, _, err := buildFilterSQL(QueryRequest{
		Sort: []string{"-valid_field", "bad field!"},
	})
	assert.ErrorIs(t, err, ErrInvalidFieldName)
}
