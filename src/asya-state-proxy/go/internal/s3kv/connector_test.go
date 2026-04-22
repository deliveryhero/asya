package s3kv

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// mockS3Client implements S3Client for tests.
type mockS3Client struct {
	getObjectFn    func(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	putObjectFn    func(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
	deleteObjectFn func(ctx context.Context, params *s3.DeleteObjectInput, optFns ...func(*s3.Options)) (*s3.DeleteObjectOutput, error)
	headObjectFn   func(ctx context.Context, params *s3.HeadObjectInput, optFns ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
	listObjectsV2Fn func(ctx context.Context, params *s3.ListObjectsV2Input, optFns ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
}

func (m *mockS3Client) GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	if m.getObjectFn != nil {
		return m.getObjectFn(ctx, params, optFns...)
	}
	return nil, &s3types.NoSuchKey{}
}
func (m *mockS3Client) PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	if m.putObjectFn != nil {
		return m.putObjectFn(ctx, params, optFns...)
	}
	return &s3.PutObjectOutput{}, nil
}
func (m *mockS3Client) DeleteObject(ctx context.Context, params *s3.DeleteObjectInput, optFns ...func(*s3.Options)) (*s3.DeleteObjectOutput, error) {
	if m.deleteObjectFn != nil {
		return m.deleteObjectFn(ctx, params, optFns...)
	}
	return &s3.DeleteObjectOutput{}, nil
}
func (m *mockS3Client) HeadObject(ctx context.Context, params *s3.HeadObjectInput, optFns ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	if m.headObjectFn != nil {
		return m.headObjectFn(ctx, params, optFns...)
	}
	return nil, &s3types.NotFound{}
}
func (m *mockS3Client) ListObjectsV2(ctx context.Context, params *s3.ListObjectsV2Input, optFns ...func(*s3.Options)) (*s3.ListObjectsV2Output, error) {
	if m.listObjectsV2Fn != nil {
		return m.listObjectsV2Fn(ctx, params, optFns...)
	}
	return &s3.ListObjectsV2Output{}, nil
}

func newConn(mock S3Client) *Connector {
	return NewConnector(mock, "bucket", "mesh/msg", slog.Default())
}

// makeStoredBody serialises fields + _ca/_ua into an io.ReadCloser for use as a
// mock S3 GetObject body.
func makeStoredBody(t *testing.T, fields map[string]any) io.ReadCloser {
	t.Helper()
	fields["_ca"] = "2026-04-22T10:00:00Z"
	fields["_ua"] = "2026-04-22T10:05:00Z"
	b, err := json.Marshal(fields)
	require.NoError(t, err)
	return io.NopCloser(bytes.NewReader(b))
}

// --- objectKey / logicalKey ---

func TestObjectKey(t *testing.T) {
	c := NewConnector(nil, "b", "mesh/msg", nil)
	assert.Equal(t, "mesh/msg/abc.json", c.objectKey("abc"))
}

func TestObjectKeyNoPrefix(t *testing.T) {
	c := NewConnector(nil, "b", "", nil)
	assert.Equal(t, "abc.json", c.objectKey("abc"))
}

func TestLogicalKey(t *testing.T) {
	c := NewConnector(nil, "b", "mesh/msg", nil)
	assert.Equal(t, "abc", c.logicalKey("mesh/msg/abc.json"))
}

// --- Read ---

func TestRead_Success(t *testing.T) {
	mock := &mockS3Client{
		getObjectFn: func(_ context.Context, params *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
			assert.Equal(t, "bucket", aws.ToString(params.Bucket))
			assert.Equal(t, "mesh/msg/abc.json", aws.ToString(params.Key))
			return &s3.GetObjectOutput{
				Body: makeStoredBody(t, map[string]any{"status": "running"}),
			}, nil
		},
	}
	row, err := newConn(mock).Read(context.Background(), "abc")
	require.NoError(t, err)
	assert.Equal(t, "abc", row.Key)
	assert.False(t, row.CreatedAt.IsZero(), "created_at must be populated")
	assert.False(t, row.UpdatedAt.IsZero(), "updated_at must be populated")

	var val map[string]any
	require.NoError(t, json.Unmarshal(row.Value, &val))
	assert.Equal(t, "running", val["status"])
	assert.Nil(t, val["_ca"], "_ca must be stripped from returned value")
	assert.Nil(t, val["_ua"], "_ua must be stripped from returned value")
}

func TestRead_NotFound(t *testing.T) {
	_, err := newConn(&mockS3Client{}).Read(context.Background(), "missing")
	assert.ErrorIs(t, err, ErrNotFound)
}

// --- Write ---

func TestWrite_StampsTimestamps(t *testing.T) {
	var written []byte
	mock := &mockS3Client{
		// Read returns NotFound -> Write will stamp a fresh _ca.
		putObjectFn: func(_ context.Context, p *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
			written, _ = io.ReadAll(p.Body)
			return &s3.PutObjectOutput{}, nil
		},
	}
	err := newConn(mock).Write(context.Background(), "k", json.RawMessage(`{"status":"pending"}`))
	require.NoError(t, err)

	var stored map[string]any
	require.NoError(t, json.Unmarshal(written, &stored))
	assert.Equal(t, "pending", stored["status"])
	assert.NotEmpty(t, stored["_ca"])
	assert.NotEmpty(t, stored["_ua"])
}

func TestWrite_PreservesCreatedAt(t *testing.T) {
	const origCA = "2026-01-01T00:00:00Z"
	existing, _ := json.Marshal(map[string]any{"status": "pending", "_ca": origCA, "_ua": origCA})
	var written []byte

	mock := &mockS3Client{
		getObjectFn: func(_ context.Context, _ *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
			return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(existing))}, nil
		},
		putObjectFn: func(_ context.Context, p *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
			written, _ = io.ReadAll(p.Body)
			return &s3.PutObjectOutput{}, nil
		},
	}
	err := newConn(mock).Write(context.Background(), "k", json.RawMessage(`{"status":"running"}`))
	require.NoError(t, err)

	var stored map[string]any
	require.NoError(t, json.Unmarshal(written, &stored))
	assert.Equal(t, origCA, stored["_ca"], "_ca must survive a Write overwrite")
}

// --- WriteConditional ---

func TestWriteConditional_Match(t *testing.T) {
	existing, _ := json.Marshal(map[string]any{"status": "pending", "_ca": "2026-01-01T00:00:00Z", "_ua": "2026-01-01T00:00:00Z"})
	wrote := false

	mock := &mockS3Client{
		getObjectFn: func(_ context.Context, _ *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
			return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(existing))}, nil
		},
		putObjectFn: func(_ context.Context, _ *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
			wrote = true
			return &s3.PutObjectOutput{}, nil
		},
	}
	err := newConn(mock).WriteConditional(context.Background(), "k", json.RawMessage(`{"status":"running"}`), "pending")
	require.NoError(t, err)
	assert.True(t, wrote)
}

func TestWriteConditional_StatusMismatch(t *testing.T) {
	existing, _ := json.Marshal(map[string]any{"status": "running", "_ca": "2026-01-01T00:00:00Z", "_ua": "2026-01-01T00:00:00Z"})

	mock := &mockS3Client{
		getObjectFn: func(_ context.Context, _ *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
			return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(existing))}, nil
		},
	}
	err := newConn(mock).WriteConditional(context.Background(), "k", json.RawMessage(`{"status":"succeeded"}`), "pending")
	assert.ErrorIs(t, err, ErrConditionFailed)
}

func TestWriteConditional_NotFound(t *testing.T) {
	err := newConn(&mockS3Client{}).WriteConditional(context.Background(), "missing", json.RawMessage(`{}`), "pending")
	assert.ErrorIs(t, err, ErrNotFound)
}

// --- Exists ---

func TestExists_True(t *testing.T) {
	mock := &mockS3Client{
		headObjectFn: func(_ context.Context, _ *s3.HeadObjectInput, _ ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
			return &s3.HeadObjectOutput{}, nil
		},
	}
	ok, err := newConn(mock).Exists(context.Background(), "k")
	require.NoError(t, err)
	assert.True(t, ok)
}

func TestExists_False(t *testing.T) {
	ok, err := newConn(&mockS3Client{}).Exists(context.Background(), "k")
	require.NoError(t, err)
	assert.False(t, ok)
}

// --- Delete ---

func TestDelete_Success(t *testing.T) {
	deleted := false
	mock := &mockS3Client{
		headObjectFn: func(_ context.Context, _ *s3.HeadObjectInput, _ ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
			return &s3.HeadObjectOutput{}, nil
		},
		deleteObjectFn: func(_ context.Context, _ *s3.DeleteObjectInput, _ ...func(*s3.Options)) (*s3.DeleteObjectOutput, error) {
			deleted = true
			return &s3.DeleteObjectOutput{}, nil
		},
	}
	err := newConn(mock).Delete(context.Background(), "k")
	require.NoError(t, err)
	assert.True(t, deleted)
}

func TestDelete_NotFound(t *testing.T) {
	err := newConn(&mockS3Client{}).Delete(context.Background(), "missing")
	assert.ErrorIs(t, err, ErrNotFound)
}

// --- List ---

func TestList_MultiPage(t *testing.T) {
	call := 0
	mock := &mockS3Client{
		listObjectsV2Fn: func(_ context.Context, _ *s3.ListObjectsV2Input, _ ...func(*s3.Options)) (*s3.ListObjectsV2Output, error) {
			call++
			if call == 1 {
				return &s3.ListObjectsV2Output{
					Contents:              []s3types.Object{{Key: aws.String("mesh/msg/a.json")}, {Key: aws.String("mesh/msg/b.json")}},
					IsTruncated:           aws.Bool(true),
					NextContinuationToken: aws.String("tok"),
				}, nil
			}
			return &s3.ListObjectsV2Output{
				Contents:    []s3types.Object{{Key: aws.String("mesh/msg/c.json")}},
				IsTruncated: aws.Bool(false),
			}, nil
		},
	}
	keys, err := newConn(mock).List(context.Background(), "")
	require.NoError(t, err)
	assert.Equal(t, []string{"a", "b", "c"}, keys)
	assert.Equal(t, 2, call, "must paginate")
}

// --- isNotFound ---

func TestIsNotFound_NoSuchKey(t *testing.T) {
	assert.True(t, isNotFound(&s3types.NoSuchKey{}))
}

func TestIsNotFound_NotFound(t *testing.T) {
	assert.True(t, isNotFound(&s3types.NotFound{}))
}

func TestIsNotFound_Other(t *testing.T) {
	assert.False(t, isNotFound(errors.New("connection refused")))
}

// --- buildStored / parseStored round-trip ---

func TestBuildParseStoredRoundTrip(t *testing.T) {
	ca := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	ua := time.Date(2026, 1, 2, 0, 0, 0, 0, time.UTC)

	stored, err := buildStored(json.RawMessage(`{"status":"running","progress":50}`), ca, ua)
	require.NoError(t, err)

	var raw map[string]any
	require.NoError(t, json.Unmarshal(stored, &raw))
	assert.NotEmpty(t, raw["_ca"], "_ca present in S3 doc")
	assert.NotEmpty(t, raw["_ua"], "_ua present in S3 doc")
	assert.Equal(t, "running", raw["status"])

	row, err := parseStored("msg/k1", stored)
	require.NoError(t, err)
	assert.Equal(t, "msg/k1", row.Key)
	assert.True(t, row.CreatedAt.Equal(ca))
	assert.True(t, row.UpdatedAt.Equal(ua))

	var val map[string]any
	require.NoError(t, json.Unmarshal(row.Value, &val))
	assert.Nil(t, val["_ca"], "_ca stripped from KVRow.Value")
	assert.Nil(t, val["_ua"], "_ua stripped from KVRow.Value")
	assert.InDelta(t, 50.0, val["progress"], 0.001)
}
