package s3kv

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// --- buildWhereClause ---

func TestBuildWhere_Empty(t *testing.T) {
	where, args, err := buildWhereClause(nil)
	require.NoError(t, err)
	assert.Empty(t, where)
	assert.Nil(t, args)
}

func TestBuildWhere_ImplicitEq(t *testing.T) {
	where, args, err := buildWhereClause(map[string]any{"status": "running"})
	require.NoError(t, err)
	assert.Contains(t, where, "status = $1")
	assert.Equal(t, []any{"running"}, args)
}

func TestBuildWhere_ExplicitEq(t *testing.T) {
	where, args, err := buildWhereClause(map[string]any{"status": map[string]any{"$eq": "running"}})
	require.NoError(t, err)
	assert.Contains(t, where, "status = $1")
	assert.Equal(t, []any{"running"}, args)
}

func TestBuildWhere_Ne(t *testing.T) {
	where, args, err := buildWhereClause(map[string]any{"status": map[string]any{"$ne": "failed"}})
	require.NoError(t, err)
	assert.Contains(t, where, "status != $1")
	assert.Equal(t, []any{"failed"}, args)
}

func TestBuildWhere_Gt(t *testing.T) {
	where, args, err := buildWhereClause(map[string]any{"progress": map[string]any{"$gt": 50}})
	require.NoError(t, err)
	assert.Contains(t, where, "progress > $1")
	assert.Equal(t, []any{50}, args)
}

func TestBuildWhere_Lte(t *testing.T) {
	where, _, err := buildWhereClause(map[string]any{"progress": map[string]any{"$lte": 100}})
	require.NoError(t, err)
	assert.Contains(t, where, "progress <= $1")
}

func TestBuildWhere_In(t *testing.T) {
	where, args, err := buildWhereClause(map[string]any{
		"status": map[string]any{"$in": []any{"running", "pending"}},
	})
	require.NoError(t, err)
	assert.Contains(t, where, "status IN ($1, $2)")
	assert.Equal(t, []any{"running", "pending"}, args)
}

func TestBuildWhere_Nin(t *testing.T) {
	where, args, err := buildWhereClause(map[string]any{
		"status": map[string]any{"$nin": []any{"succeeded", "failed", "canceled"}},
	})
	require.NoError(t, err)
	assert.Contains(t, where, "status NOT IN ($1, $2, $3)")
	assert.Equal(t, 3, len(args))
}

func TestBuildWhere_ExistsTrue(t *testing.T) {
	where, _, err := buildWhereClause(map[string]any{"deadline_at": map[string]any{"$exists": true}})
	require.NoError(t, err)
	assert.Contains(t, where, "deadline_at IS NOT NULL")
}

func TestBuildWhere_ExistsFalse(t *testing.T) {
	where, _, err := buildWhereClause(map[string]any{"error": map[string]any{"$exists": false}})
	require.NoError(t, err)
	assert.Contains(t, where, "error IS NULL")
}

func TestBuildWhere_InEmptySlice(t *testing.T) {
	where, args, err := buildWhereClause(map[string]any{"status": map[string]any{"$in": []any{}}})
	require.NoError(t, err)
	assert.Equal(t, " WHERE FALSE", where)
	assert.Empty(t, args)
}

func TestBuildWhere_InvalidField(t *testing.T) {
	_, _, err := buildWhereClause(map[string]any{"status; DROP TABLE": "x"})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "invalid field name")
}

func TestBuildWhere_UnsupportedOp(t *testing.T) {
	_, _, err := buildWhereClause(map[string]any{"x": map[string]any{"$regex": ".*"}})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported filter operator")
}

// --- buildOrderBy ---

func TestBuildOrderBy_Empty(t *testing.T) {
	s, err := buildOrderBy(nil)
	require.NoError(t, err)
	assert.Empty(t, s)
}

func TestBuildOrderBy_Asc(t *testing.T) {
	s, err := buildOrderBy([]string{"created_at"})
	require.NoError(t, err)
	assert.Equal(t, " ORDER BY created_at ASC", s)
}

func TestBuildOrderBy_Desc(t *testing.T) {
	s, err := buildOrderBy([]string{"-progress"})
	require.NoError(t, err)
	assert.Equal(t, " ORDER BY progress DESC", s)
}

func TestBuildOrderBy_Multi(t *testing.T) {
	s, err := buildOrderBy([]string{"status", "-progress"})
	require.NoError(t, err)
	assert.Equal(t, " ORDER BY status ASC, progress DESC", s)
}

func TestBuildOrderBy_InvalidField(t *testing.T) {
	_, err := buildOrderBy([]string{"-status; DROP TABLE"})
	assert.Error(t, err)
}

// --- buildLimitOffset ---

func TestBuildLimitOffset_None(t *testing.T) {
	assert.Equal(t, "", buildLimitOffset(0, 0))
}

func TestBuildLimitOffset_LimitOnly(t *testing.T) {
	assert.Equal(t, " LIMIT 10", buildLimitOffset(10, 0))
}

func TestBuildLimitOffset_Both(t *testing.T) {
	assert.Equal(t, " LIMIT 10 OFFSET 5", buildLimitOffset(10, 5))
}

// --- logicalKeyFromFile ---

func TestLogicalKeyFromFile(t *testing.T) {
	assert.Equal(t, "abc", logicalKeyFromFile("/tmp/s3kv-123/abc.json", "/tmp/s3kv-123"))
}

func TestLogicalKeyFromFile_WithSlashInKey(t *testing.T) {
	// Keys containing "/" are stored as "__" in filenames.
	assert.Equal(t, "msg/test-1", logicalKeyFromFile("/tmp/s3kv-123/msg__test-1.json", "/tmp/s3kv-123"))
}

// --- toStringSlice ---

func TestToStringSlice(t *testing.T) {
	got := toStringSlice([]any{"a", "b", "c"})
	assert.Equal(t, []string{"a", "b", "c"}, got)
}

func TestToStringSlice_Numbers(t *testing.T) {
	got := toStringSlice([]any{1, 2, 3})
	assert.Equal(t, []string{"1", "2", "3"}, got)
}

func TestToStringSlice_NotASlice(t *testing.T) {
	got := toStringSlice("not a slice")
	assert.Nil(t, got)
}
