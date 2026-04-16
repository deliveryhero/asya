package stateproxypg

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestBuildQuery_SimpleFilter(t *testing.T) {
	sql, args := buildFilterSQL(QueryRequest{
		Prefix: "msg/",
		Filter: map[string]any{"status": "running"},
		Sort:   []string{"-created_at"},
		Limit:  10,
	})
	assert.Contains(t, sql, "key LIKE $1")
	assert.Contains(t, sql, "value @> $2")
	assert.Contains(t, sql, "ORDER BY created_at DESC")
	assert.Contains(t, sql, "LIMIT 10")
	assert.Equal(t, "msg/%", args[0])
}

func TestBuildQuery_ComparisonOps(t *testing.T) {
	sql, args := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"progress": map[string]any{"$gt": float64(50)},
		},
	})
	assert.Contains(t, sql, "(value->>'progress')::numeric > $")
	assert.Equal(t, float64(50), args[0])
}

func TestBuildQuery_GteAndLte(t *testing.T) {
	sql, args := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"score": map[string]any{"$gte": float64(10), "$lte": float64(100)},
		},
	})
	assert.Contains(t, sql, "(value->>'score')::numeric >=")
	assert.Contains(t, sql, "(value->>'score')::numeric <=")
	assert.Len(t, args, 2)
}

func TestBuildQuery_InOperator(t *testing.T) {
	sql, args := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"status": map[string]any{"$in": []any{"running", "pending"}},
		},
	})
	assert.Contains(t, sql, "value->>'status' = ANY($1)")
	assert.Equal(t, []string{"running", "pending"}, args[0])
}

func TestBuildQuery_NinOperator(t *testing.T) {
	sql, _ := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"status": map[string]any{"$nin": []any{"canceled"}},
		},
	})
	assert.Contains(t, sql, "NOT (value->>'status' = ANY($1))")
}

func TestBuildQuery_ExistsOperator(t *testing.T) {
	sql, _ := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"error": map[string]any{"$exists": true},
		},
	})
	assert.Contains(t, sql, "value ? 'error'")

	sql2, _ := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"error": map[string]any{"$exists": false},
		},
	})
	assert.Contains(t, sql2, "NOT (value ? 'error')")
}

func TestBuildQuery_NeOperator(t *testing.T) {
	sql, args := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"status": map[string]any{"$ne": "canceled"},
		},
	})
	assert.Contains(t, sql, "value->>'status' != $1")
	assert.Equal(t, "canceled", args[0])
}

func TestBuildQuery_CountMode(t *testing.T) {
	sql, args := buildFilterSQL(QueryRequest{
		Prefix: "msg/",
		Filter: map[string]any{"status": "running"},
		Count:  true,
	})
	assert.Contains(t, sql, "SELECT count(*)")
	assert.NotContains(t, sql, "key, value")
	assert.Equal(t, "msg/%", args[0])
}

func TestBuildQuery_SortByValueField(t *testing.T) {
	sql, _ := buildFilterSQL(QueryRequest{
		Sort: []string{"-status", "created_at"},
	})
	assert.Contains(t, sql, "value->>'status' DESC")
	assert.Contains(t, sql, "created_at ASC")
}

func TestBuildQuery_OffsetOnly(t *testing.T) {
	sql, _ := buildFilterSQL(QueryRequest{
		Offset: 20,
	})
	assert.Contains(t, sql, "OFFSET 20")
}

func TestBuildQuery_NoFilters(t *testing.T) {
	sql, args := buildFilterSQL(QueryRequest{})
	assert.Equal(t, "SELECT key, value, created_at, updated_at FROM kv", sql)
	assert.Empty(t, args)
}

func TestBuildQuery_ContainsOperator(t *testing.T) {
	sql, args := buildFilterSQL(QueryRequest{
		Filter: map[string]any{
			"headers": map[string]any{"$contains": map[string]any{"trace_id": "abc"}},
		},
	})
	assert.Contains(t, sql, "value @> $1::jsonb")
	assert.Len(t, args, 1)
}
