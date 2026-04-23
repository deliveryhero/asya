package s3kv

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
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
	// Types must be preserved ([]any, not []string).
	assert.IsType(t, "succeeded", args[0])
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

// --- encodeKeyAsFilename / logicalKeyFromFile ---

func TestEncodeKeyAsFilename_Plain(t *testing.T) {
	assert.Equal(t, "abc", encodeKeyAsFilename("abc"))
}

func TestEncodeKeyAsFilename_Slash(t *testing.T) {
	assert.Equal(t, "msg%2Ftest-1", encodeKeyAsFilename("msg/test-1"))
}

func TestEncodeKeyAsFilename_Percent(t *testing.T) {
	// A key that already contains "%" must not collide with a slash-encoded key.
	assert.Equal(t, "a%252Fb", encodeKeyAsFilename("a%2Fb"))
}

func TestEncodeDecodeRoundTrip(t *testing.T) {
	keys := []string{"abc", "msg/test-1", "a%2Fb", "x/y/z", "no-special"}
	for _, key := range keys {
		encoded := encodeKeyAsFilename(key)
		decoded := logicalKeyFromFile("/tmp/q/"+encoded+".json", "/tmp/q")
		assert.Equal(t, key, decoded, "round-trip for key %q", key)
	}
}

func TestLogicalKeyFromFile(t *testing.T) {
	assert.Equal(t, "abc", logicalKeyFromFile("/tmp/s3kv-123/abc.json", "/tmp/s3kv-123"))
}

func TestLogicalKeyFromFile_WithSlashInKey(t *testing.T) {
	assert.Equal(t, "msg/test-1", logicalKeyFromFile("/tmp/s3kv-123/msg%2Ftest-1.json", "/tmp/s3kv-123"))
}

// --- toAnySlice ---

func TestToAnySlice_Strings(t *testing.T) {
	got := toAnySlice([]any{"a", "b", "c"})
	assert.Equal(t, []any{"a", "b", "c"}, got)
}

func TestToAnySlice_PreservesTypes(t *testing.T) {
	// Types must be preserved — not converted to strings.
	got := toAnySlice([]any{1, 2.5, true})
	assert.Equal(t, []any{1, 2.5, true}, got)
}

func TestToAnySlice_NotASlice(t *testing.T) {
	assert.Nil(t, toAnySlice("not a slice"))
}

// --- QueryEngine integration (real DuckDB, mock S3) ---

// makeS3Doc serialises a flat+nested document into a mock S3 GetObjectOutput.
func makeS3Doc(t *testing.T, fields map[string]any) *s3.GetObjectOutput {
	t.Helper()
	fields["_ca"] = "2026-04-22T10:00:00.000000000Z"
	fields["_ua"] = "2026-04-22T10:05:00.000000000Z"
	b, err := json.Marshal(fields)
	require.NoError(t, err)
	return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(b))}
}

// TestQueryEngine_RoundtripWithNestedPayload verifies that the DuckDB query
// pipeline correctly round-trips documents that contain nested JSON objects.
// This is a regression test for the struct_pack(* EXCLUDE (filename)) bug
// (DuckDB does not allow STAR inside a function argument) and for the
// json.Marshal column-scan approach that replaced it.
func TestQueryEngine_RoundtripWithNestedPayload(t *testing.T) {
	docs := map[string]map[string]any{
		"task-1": {
			"status": "pending",
			"actor":  "test-echo",
			"payload": map[string]any{
				"question": "hello",
				"meta":     map[string]any{"trace": "abc123"},
			},
		},
		"task-2": {
			"status": "running",
			"actor":  "test-doubler",
			"payload": map[string]any{
				"value": 42.0,
			},
		},
	}

	mock := &mockS3Client{
		listObjectsV2Fn: func(_ context.Context, _ *s3.ListObjectsV2Input, _ ...func(*s3.Options)) (*s3.ListObjectsV2Output, error) {
			return &s3.ListObjectsV2Output{
				Contents: []s3types.Object{
					{Key: aws.String("mesh/msg/task-1.json")},
					{Key: aws.String("mesh/msg/task-2.json")},
				},
			}, nil
		},
		getObjectFn: func(_ context.Context, params *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
			key := aws.ToString(params.Key)
			switch key {
			case "mesh/msg/task-1.json":
				return makeS3Doc(t, copyMap(docs["task-1"])), nil
			case "mesh/msg/task-2.json":
				return makeS3Doc(t, copyMap(docs["task-2"])), nil
			}
			return nil, &s3types.NoSuchKey{}
		},
	}

	conn := NewConnector(mock, "bucket", "mesh/msg", nil)
	qe, err := NewQueryEngine(conn, nil)
	require.NoError(t, err)
	defer qe.Close()

	// Query for all rows (no filter).
	resp, err := qe.Query(context.Background(), QueryRequest{Prefix: ""})
	require.NoError(t, err)
	assert.Equal(t, 2, resp.Total)
	assert.Len(t, resp.Rows, 2)

	// Index by key for order-independent assertions.
	byKey := make(map[string]KVRow, 2)
	for _, r := range resp.Rows {
		byKey[r.Key] = r
	}

	// Verify task-1: nested payload round-trips correctly.
	r1, ok := byKey["task-1"]
	require.True(t, ok, "task-1 missing from results")
	assert.False(t, r1.CreatedAt.IsZero(), "created_at must be set")
	var v1 map[string]any
	require.NoError(t, json.Unmarshal(r1.Value, &v1))
	assert.Equal(t, "pending", v1["status"])
	payload1, ok := v1["payload"].(map[string]any)
	require.True(t, ok, "payload must be a map")
	assert.Equal(t, "hello", payload1["question"])

	// Verify task-2: numeric payload field.
	r2, ok := byKey["task-2"]
	require.True(t, ok, "task-2 missing from results")
	var v2 map[string]any
	require.NoError(t, json.Unmarshal(r2.Value, &v2))
	assert.Equal(t, "running", v2["status"])

	// Query with a status filter.
	resp2, err := qe.Query(context.Background(), QueryRequest{
		Prefix: "",
		Filter: map[string]any{"status": "pending"},
	})
	require.NoError(t, err)
	assert.Equal(t, 1, resp2.Total)
	assert.Len(t, resp2.Rows, 1)
	assert.Equal(t, "task-1", resp2.Rows[0].Key)
}

func copyMap(m map[string]any) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}
