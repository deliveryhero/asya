package gcskv

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"testing"
	"time"

	"cloud.google.com/go/storage"
	"google.golang.org/api/iterator"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/s3kv"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// --- mock GCSObject ---

type mockObject struct {
	body   []byte
	gen    int64
	notExist bool // simulate ErrObjectNotExist
	delErr   error
}

func (m *mockObject) NewReader(_ context.Context) (io.ReadCloser, error) {
	if m.notExist {
		return nil, storage.ErrObjectNotExist
	}
	return io.NopCloser(bytes.NewReader(m.body)), nil
}
func (m *mockObject) NewWriter(_ context.Context) io.WriteCloser {
	return &mockWriter{obj: m}
}
func (m *mockObject) NewWriterWithCondition(_ context.Context, _ storage.Conditions) io.WriteCloser {
	return &mockWriter{obj: m}
}
func (m *mockObject) Attrs(_ context.Context) (*storage.ObjectAttrs, error) {
	if m.notExist {
		return nil, storage.ErrObjectNotExist
	}
	return &storage.ObjectAttrs{Generation: m.gen}, nil
}
func (m *mockObject) Delete(_ context.Context) error {
	if m.delErr != nil {
		return m.delErr
	}
	if m.notExist {
		return storage.ErrObjectNotExist
	}
	m.notExist = true
	return nil
}

type mockWriter struct {
	obj *mockObject
	buf bytes.Buffer
}

func (w *mockWriter) Write(p []byte) (int, error) { return w.buf.Write(p) }
func (w *mockWriter) Close() error {
	w.obj.body = w.buf.Bytes()
	w.obj.notExist = false
	return nil
}

// --- mock ListIterator ---

type mockIter struct {
	names []string
	pos   int
}

func (i *mockIter) Next() (*storage.ObjectAttrs, error) {
	if i.pos >= len(i.names) {
		return nil, iterator.Done
	}
	a := &storage.ObjectAttrs{Name: i.names[i.pos]}
	i.pos++
	return a, nil
}

// --- mock BucketClient ---

type mockBucket struct {
	objects map[string]*mockObject
}

func newMockBucket() *mockBucket {
	return &mockBucket{objects: map[string]*mockObject{}}
}

func (b *mockBucket) put(name string, body []byte) {
	b.objects[name] = &mockObject{body: body, gen: 1}
}

func (b *mockBucket) ObjectHandle(name string) GCSObject {
	if o, ok := b.objects[name]; ok {
		return o
	}
	// Always return a tracked object so NewWriter().Close() persists the write.
	o := &mockObject{notExist: true}
	b.objects[name] = o
	return o
}

func (b *mockBucket) Objects(_ context.Context, q *storage.Query) ListIterator {
	prefix := ""
	if q != nil {
		prefix = q.Prefix
	}
	var names []string
	for name := range b.objects {
		if !b.objects[name].notExist && (prefix == "" || len(name) >= len(prefix) && name[:len(prefix)] == prefix) {
			names = append(names, name)
		}
	}
	return &mockIter{names: names}
}

// --- helpers ---

func storedDoc(t *testing.T, fields map[string]any) []byte {
	t.Helper()
	fields["_ca"] = "2026-04-23T10:00:00.000000000Z"
	fields["_ua"] = "2026-04-23T10:05:00.000000000Z"
	b, err := json.Marshal(fields)
	require.NoError(t, err)
	return b
}

func testConn(mb *mockBucket) *Connector {
	return newConnectorWithClient(mb, "pre", nil)
}

// --- CRUD tests ---

func TestGCS_Read_Success(t *testing.T) {
	mb := newMockBucket()
	mb.put("pre/abc.json", storedDoc(t, map[string]any{"status": "running"}))
	row, err := testConn(mb).Read(context.Background(), "abc")
	require.NoError(t, err)
	assert.Equal(t, "abc", row.Key)
	assert.False(t, row.CreatedAt.IsZero())
	var v map[string]any
	require.NoError(t, json.Unmarshal(row.Value, &v))
	assert.Equal(t, "running", v["status"])
	assert.NotContains(t, v, "_ca")
}

func TestGCS_Read_NotFound(t *testing.T) {
	_, err := testConn(newMockBucket()).Read(context.Background(), "x")
	assert.ErrorIs(t, err, s3kv.ErrNotFound)
}

func TestGCS_Write_Creates(t *testing.T) {
	mb := newMockBucket()
	err := testConn(mb).Write(context.Background(), "k1", json.RawMessage(`{"status":"pending"}`))
	require.NoError(t, err)
	obj := mb.objects["pre/k1.json"]
	require.NotNil(t, obj)
	var doc map[string]any
	require.NoError(t, json.Unmarshal(obj.body, &doc))
	assert.Equal(t, "pending", doc["status"])
	assert.NotEmpty(t, doc["_ca"])
}

func TestGCS_Write_PreservesCreatedAt(t *testing.T) {
	mb := newMockBucket()
	mb.put("pre/k.json", storedDoc(t, map[string]any{"status": "pending"}))
	err := testConn(mb).Write(context.Background(), "k", json.RawMessage(`{"status":"running"}`))
	require.NoError(t, err)
	var doc map[string]any
	require.NoError(t, json.Unmarshal(mb.objects["pre/k.json"].body, &doc))
	// _ca is re-formatted as RFC3339Nano (trailing zeros stripped).
	// Compare as parsed time rather than raw string.
	caStr, _ := doc["_ca"].(string)
	ca, err := time.Parse(time.RFC3339Nano, caStr)
	require.NoError(t, err, "_ca must be a valid RFC3339Nano timestamp")
	assert.Equal(t, 2026, ca.Year())
	assert.Equal(t, 10, ca.Hour(), "_ca must be preserved to the same hour")
}

func TestGCS_WriteConditional_Match(t *testing.T) {
	mb := newMockBucket()
	mb.put("pre/k.json", storedDoc(t, map[string]any{"status": "pending"}))
	err := testConn(mb).WriteConditional(context.Background(), "k",
		json.RawMessage(`{"status":"running"}`), "pending")
	require.NoError(t, err)
	var doc map[string]any
	require.NoError(t, json.Unmarshal(mb.objects["pre/k.json"].body, &doc))
	assert.Equal(t, "running", doc["status"])
}

func TestGCS_WriteConditional_Mismatch(t *testing.T) {
	mb := newMockBucket()
	mb.put("pre/k.json", storedDoc(t, map[string]any{"status": "running"}))
	err := testConn(mb).WriteConditional(context.Background(), "k",
		json.RawMessage(`{"status":"done"}`), "pending")
	assert.ErrorIs(t, err, s3kv.ErrConditionFailed)
}

func TestGCS_WriteConditional_NotFound(t *testing.T) {
	err := testConn(newMockBucket()).WriteConditional(context.Background(), "x",
		json.RawMessage(`{}`), "pending")
	assert.ErrorIs(t, err, s3kv.ErrNotFound)
}

func TestGCS_Exists_True(t *testing.T) {
	mb := newMockBucket()
	mb.put("pre/k.json", storedDoc(t, map[string]any{}))
	ok, err := testConn(mb).Exists(context.Background(), "k")
	require.NoError(t, err)
	assert.True(t, ok)
}

func TestGCS_Exists_False(t *testing.T) {
	ok, err := testConn(newMockBucket()).Exists(context.Background(), "nope")
	require.NoError(t, err)
	assert.False(t, ok)
}

func TestGCS_Delete_Success(t *testing.T) {
	mb := newMockBucket()
	mb.put("pre/k.json", storedDoc(t, map[string]any{}))
	err := testConn(mb).Delete(context.Background(), "k")
	require.NoError(t, err)
	assert.True(t, mb.objects["pre/k.json"].notExist)
}

func TestGCS_Delete_NotFound(t *testing.T) {
	err := testConn(newMockBucket()).Delete(context.Background(), "gone")
	assert.ErrorIs(t, err, s3kv.ErrNotFound)
}

func TestGCS_List(t *testing.T) {
	mb := newMockBucket()
	mb.put("pre/msg/a.json", storedDoc(t, map[string]any{}))
	mb.put("pre/msg/b.json", storedDoc(t, map[string]any{}))
	mb.put("pre/other.json", storedDoc(t, map[string]any{}))
	keys, err := testConn(mb).List(context.Background(), "msg/")
	require.NoError(t, err)
	assert.Len(t, keys, 2)
	for _, k := range keys {
		assert.True(t, k == "msg/a" || k == "msg/b", "unexpected key: %q", k)
	}
}

func TestGCS_ObjectName_WithPrefix(t *testing.T) {
	conn := newConnectorWithClient(nil, "mesh/msg", nil)
	assert.Equal(t, "mesh/msg/abc.json", conn.objectName("abc"))
}

func TestGCS_ObjectName_NoPrefix(t *testing.T) {
	conn := newConnectorWithClient(nil, "", nil)
	assert.Equal(t, "abc.json", conn.objectName("abc"))
}

func TestGCS_LogicalKey(t *testing.T) {
	conn := newConnectorWithClient(nil, "mesh/msg", nil)
	assert.Equal(t, "abc", conn.logicalKey("mesh/msg/abc.json"))
}

func TestGCS_TimestampRoundtrip(t *testing.T) {
	mb := newMockBucket()
	conn := testConn(mb)
	require.NoError(t, conn.Write(context.Background(), "ts", json.RawMessage(`{"x":1}`)))
	row, err := conn.Read(context.Background(), "ts")
	require.NoError(t, err)
	assert.WithinDuration(t, time.Now(), row.CreatedAt, 5*time.Second)
	var v map[string]any
	require.NoError(t, json.Unmarshal(row.Value, &v))
	assert.NotContains(t, v, "_ca")
	assert.NotContains(t, v, "_ua")
}

// TestGCS_QueryEngine_Integration verifies the full DuckDB roundtrip using the
// GCS connector: write docs → QueryEngine.Query() with filter → correct rows.
func TestGCS_QueryEngine_Integration(t *testing.T) {
	mb := newMockBucket()
	conn := testConn(mb)

	// Write two documents directly via the connector.
	require.NoError(t, conn.Write(context.Background(), "task/a",
		json.RawMessage(`{"status":"pending","actor":"echo","payload":{"q":"hello"}}`)))
	require.NoError(t, conn.Write(context.Background(), "task/b",
		json.RawMessage(`{"status":"running","actor":"doubler"}`)))

	qe, err := s3kv.NewQueryEngine(conn, nil)
	require.NoError(t, err)
	defer qe.Close()

	// Query all.
	resp, err := qe.Query(context.Background(), s3kv.QueryRequest{Prefix: ""})
	require.NoError(t, err)
	assert.Equal(t, 2, resp.Total)

	// Query with filter.
	resp2, err := qe.Query(context.Background(), s3kv.QueryRequest{
		Filter: map[string]any{"status": "pending"},
	})
	require.NoError(t, err)
	assert.Equal(t, 1, resp2.Total)
	require.Len(t, resp2.Rows, 1)
	assert.Equal(t, "task/a", resp2.Rows[0].Key)

	// Verify nested payload survives DuckDB roundtrip.
	var v map[string]any
	require.NoError(t, json.Unmarshal(resp2.Rows[0].Value, &v))
	payload, ok := v["payload"].(map[string]any)
	require.True(t, ok)
	assert.Equal(t, "hello", payload["q"])
}

// Compile-time check: *Connector satisfies s3kv.StorageBackend.
var _ s3kv.StorageBackend = (*Connector)(nil)

// Ensure errors.Is works for GCS-specific errors wrapping ErrObjectNotExist.
func TestGCS_ErrObjectNotExist_IsNotFound(t *testing.T) {
	err := errors.New("gcs: " + storage.ErrObjectNotExist.Error())
	// Direct check
	assert.False(t, errors.Is(err, storage.ErrObjectNotExist), "wrapped string != sentinel")
	assert.True(t, errors.Is(storage.ErrObjectNotExist, storage.ErrObjectNotExist))
}
