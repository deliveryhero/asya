package s3kv

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"strings"
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

// newQueryEngineWithDocs creates a QueryEngine backed by a fixed set of in-memory docs
// keyed by logical key → field map.
//
// The Connector stores documents in S3 using LITERAL slashes in object keys:
//   mesh/msg/ns/region/task-abc.json  (not mesh/msg/ns%2Fregion%2Ftask-abc.json)
//
// URL-encoding of slashes only happens for temp file names on disk (so DuckDB
// does not interpret "/" as a directory separator inside tmpDir).
func newQueryEngineWithDocs(t *testing.T, docs map[string]map[string]any) (*QueryEngine, *Connector) {
	t.Helper()

	// S3 object keys use literal slashes — same convention as Connector.objectKey().
	var objects []s3types.Object
	for k := range docs {
		objKey := "mesh/msg/" + k + ".json"
		objects = append(objects, s3types.Object{Key: aws.String(objKey)})
	}

	mock := &mockS3Client{
		listObjectsV2Fn: func(_ context.Context, _ *s3.ListObjectsV2Input, _ ...func(*s3.Options)) (*s3.ListObjectsV2Output, error) {
			return &s3.ListObjectsV2Output{Contents: objects}, nil
		},
		getObjectFn: func(_ context.Context, params *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
			key := aws.ToString(params.Key)
			// Strip S3 prefix + .json suffix to recover the logical key.
			logKey := strings.TrimPrefix(key, "mesh/msg/")
			logKey = strings.TrimSuffix(logKey, ".json")
			fields, ok := docs[logKey]
			if !ok {
				return nil, &s3types.NoSuchKey{}
			}
			return makeS3Doc(t, copyMap(fields)), nil
		},
	}

	conn := NewConnector(mock, "bucket", "mesh/msg", nil)
	qe, err := NewQueryEngine(conn, nil)
	require.NoError(t, err)
	t.Cleanup(func() { qe.Close() })
	return qe, conn
}

// TestQueryEngine_EmptyBucket verifies Query returns {Total:0} for empty prefix.
func TestQueryEngine_EmptyBucket(t *testing.T) {
	qe, _ := newQueryEngineWithDocs(t, map[string]map[string]any{})
	resp, err := qe.Query(context.Background(), QueryRequest{Prefix: "nomatch/"})
	require.NoError(t, err)
	assert.Equal(t, 0, resp.Total)
	assert.Empty(t, resp.Rows)
}

// TestQueryEngine_Count verifies the count-only path (req.Count=true).
func TestQueryEngine_Count(t *testing.T) {
	qe, _ := newQueryEngineWithDocs(t, map[string]map[string]any{
		"msg/a": {"status": "pending"},
		"msg/b": {"status": "pending"},
		"msg/c": {"status": "running"},
	})

	// Count all.
	resp, err := qe.Query(context.Background(), QueryRequest{Count: true})
	require.NoError(t, err)
	assert.Equal(t, 3, resp.Total)
	assert.Empty(t, resp.Rows, "count-only must not return rows")

	// Count with filter.
	resp2, err := qe.Query(context.Background(), QueryRequest{
		Count:  true,
		Filter: map[string]any{"status": "pending"},
	})
	require.NoError(t, err)
	assert.Equal(t, 2, resp2.Total)
	assert.Empty(t, resp2.Rows)
}

// TestQueryEngine_LimitOffset verifies pagination.
func TestQueryEngine_LimitOffset(t *testing.T) {
	docs := map[string]map[string]any{
		"msg/1": {"status": "pending", "seq": 1.0},
		"msg/2": {"status": "pending", "seq": 2.0},
		"msg/3": {"status": "pending", "seq": 3.0},
		"msg/4": {"status": "pending", "seq": 4.0},
	}
	qe, _ := newQueryEngineWithDocs(t, docs)

	resp, err := qe.Query(context.Background(), QueryRequest{
		Sort:  []string{"seq"},
		Limit: 2,
	})
	require.NoError(t, err)
	assert.Equal(t, 4, resp.Total, "Total is count before LIMIT")
	assert.Len(t, resp.Rows, 2)

	resp2, err := qe.Query(context.Background(), QueryRequest{
		Sort:   []string{"seq"},
		Limit:  2,
		Offset: 2,
	})
	require.NoError(t, err)
	assert.Equal(t, 4, resp2.Total)
	assert.Len(t, resp2.Rows, 2)

	// Rows from first and second page must not overlap.
	keys1 := map[string]bool{resp.Rows[0].Key: true, resp.Rows[1].Key: true}
	for _, r := range resp2.Rows {
		assert.False(t, keys1[r.Key], "page 2 must not repeat page 1 keys")
	}
}

// TestQueryEngine_Sort verifies descending sort puts higher-status lexicographically last.
func TestQueryEngine_Sort(t *testing.T) {
	qe, _ := newQueryEngineWithDocs(t, map[string]map[string]any{
		"msg/a": {"status": "running"},
		"msg/b": {"status": "pending"},
		"msg/c": {"status": "completed"},
	})

	resp, err := qe.Query(context.Background(), QueryRequest{Sort: []string{"status"}})
	require.NoError(t, err)
	require.Len(t, resp.Rows, 3)
	statuses := []string{}
	for _, r := range resp.Rows {
		var v map[string]any
		require.NoError(t, json.Unmarshal(r.Value, &v))
		statuses = append(statuses, v["status"].(string))
	}
	// Ascending: completed < pending < running.
	assert.Equal(t, "completed", statuses[0])
	assert.Equal(t, "pending", statuses[1])
	assert.Equal(t, "running", statuses[2])

	resp2, err := qe.Query(context.Background(), QueryRequest{Sort: []string{"-status"}})
	require.NoError(t, err)
	require.Len(t, resp2.Rows, 3)
	var v0 map[string]any
	require.NoError(t, json.Unmarshal(resp2.Rows[0].Value, &v0))
	assert.Equal(t, "running", v0["status"], "descending: running first")
}

// TestQueryEngine_FilterOperators verifies $ne, $gt, $in, $nin, $exists.
func TestQueryEngine_FilterOperators(t *testing.T) {
	qe, _ := newQueryEngineWithDocs(t, map[string]map[string]any{
		"msg/1": {"status": "pending", "priority": 1.0},
		"msg/2": {"status": "running", "priority": 5.0},
		"msg/3": {"status": "completed", "priority": 3.0},
		"msg/4": {"status": "pending"},
	})

	// $ne: exclude completed.
	resp, err := qe.Query(context.Background(), QueryRequest{
		Filter: map[string]any{"status": map[string]any{"$ne": "completed"}},
	})
	require.NoError(t, err)
	assert.Equal(t, 3, resp.Total)

	// $gt: priority > 2.
	resp2, err := qe.Query(context.Background(), QueryRequest{
		Filter: map[string]any{"priority": map[string]any{"$gt": 2.0}},
	})
	require.NoError(t, err)
	assert.Equal(t, 2, resp2.Total)

	// $in.
	resp3, err := qe.Query(context.Background(), QueryRequest{
		Filter: map[string]any{"status": map[string]any{"$in": []any{"pending", "running"}}},
	})
	require.NoError(t, err)
	assert.Equal(t, 3, resp3.Total)

	// $nin: exclude pending and running → only completed.
	resp4, err := qe.Query(context.Background(), QueryRequest{
		Filter: map[string]any{"status": map[string]any{"$nin": []any{"pending", "running"}}},
	})
	require.NoError(t, err)
	assert.Equal(t, 1, resp4.Total)

	// $exists: only docs with priority field.
	resp5, err := qe.Query(context.Background(), QueryRequest{
		Filter: map[string]any{"priority": map[string]any{"$exists": true}},
	})
	require.NoError(t, err)
	assert.Equal(t, 3, resp5.Total)
}

// TestQueryEngine_KeysWithSlashes verifies keys containing "/" survive encode→DuckDB→decode.
func TestQueryEngine_KeysWithSlashes(t *testing.T) {
	qe, _ := newQueryEngineWithDocs(t, map[string]map[string]any{
		"ns/region/task-abc": {"status": "running"},
		"ns/region/task-xyz": {"status": "pending"},
	})

	resp, err := qe.Query(context.Background(), QueryRequest{
		Filter: map[string]any{"status": "running"},
	})
	require.NoError(t, err)
	require.Len(t, resp.Rows, 1)
	// Key must be decoded back to the original slash form.
	assert.Equal(t, "ns/region/task-abc", resp.Rows[0].Key)
}

// TestQueryEngine_TimestampsPreserved verifies _ca/_ua survive the DuckDB roundtrip.
func TestQueryEngine_TimestampsPreserved(t *testing.T) {
	qe, _ := newQueryEngineWithDocs(t, map[string]map[string]any{
		"msg/ts": {"status": "pending"},
	})

	resp, err := qe.Query(context.Background(), QueryRequest{})
	require.NoError(t, err)
	require.Len(t, resp.Rows, 1)
	row := resp.Rows[0]
	// _ca/_ua are set to "2026-04-22T10:00:00.000000000Z" in makeS3Doc.
	assert.False(t, row.CreatedAt.IsZero(), "CreatedAt must be set")
	assert.False(t, row.UpdatedAt.IsZero(), "UpdatedAt must be set")
	// Both timestamps are the same in makeS3Doc fixture (_ua = _ca).
	assert.Equal(t, 2026, row.CreatedAt.Year())
	// Value must NOT contain _ca/_ua (they are stripped by parseStored).
	var v map[string]any
	require.NoError(t, json.Unmarshal(row.Value, &v))
	assert.NotContains(t, v, "_ca")
	assert.NotContains(t, v, "_ua")
}

// TestQueryEngine_NullFieldsInMixedSchema verifies that union_by_name=true
// causes NULL columns for documents missing a field, and that those NULLs
// don't corrupt other documents' values.
func TestQueryEngine_NullFieldsInMixedSchema(t *testing.T) {
	// doc-a has "extra", doc-b does not.
	qe, _ := newQueryEngineWithDocs(t, map[string]map[string]any{
		"msg/doc-a": {"status": "pending", "extra": "present"},
		"msg/doc-b": {"status": "running"},
	})

	resp, err := qe.Query(context.Background(), QueryRequest{})
	require.NoError(t, err)
	assert.Equal(t, 2, resp.Total)

	byKey := map[string]KVRow{}
	for _, r := range resp.Rows {
		byKey[r.Key] = r
	}

	var va map[string]any
	require.NoError(t, json.Unmarshal(byKey["msg/doc-a"].Value, &va))
	assert.Equal(t, "pending", va["status"])
	assert.Equal(t, "present", va["extra"])

	var vb map[string]any
	require.NoError(t, json.Unmarshal(byKey["msg/doc-b"].Value, &vb))
	assert.Equal(t, "running", vb["status"])
	// "extra" must be absent or null — must not bleed from doc-a.
	if extra, exists := vb["extra"]; exists {
		assert.Nil(t, extra, "extra must be null for doc-b, not 'present'")
	}
}
