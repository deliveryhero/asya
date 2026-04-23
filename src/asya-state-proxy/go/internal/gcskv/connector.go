// Package gcskv implements the state-proxy KV+query interface backed by
// Google Cloud Storage. It satisfies s3kv.StorageBackend so the shared
// DuckDB QueryEngine and HTTP server can be plugged in without duplication.
//
// Wire format is identical to s3kv: each object is a JSON file with embedded
// _ca/_ua timestamp fields. This makes the DuckDB /query path fully portable
// across S3 and GCS backends.
//
// Conditional writes use GCS object generation numbers for native
// compare-and-swap semantics — stronger than S3's ETag-based approach because
// the condition is evaluated server-side atomically by GCS.
package gcskv

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"time"

	"cloud.google.com/go/storage"
	"google.golang.org/api/iterator"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/s3kv"
)

// GCSObject is the subset of *storage.ObjectHandle used by the connector;
// enables mocking in tests.
type GCSObject interface {
	NewReader(ctx context.Context) (io.ReadCloser, error)
	NewWriter(ctx context.Context) io.WriteCloser
	NewWriterWithCondition(ctx context.Context, cond storage.Conditions) io.WriteCloser
	Attrs(ctx context.Context) (*storage.ObjectAttrs, error)
	Delete(ctx context.Context) error
}

// GCSBucket is the subset of *storage.BucketHandle used by the connector.
type GCSBucket interface {
	Object(name string) *storage.ObjectHandle
	Objects(ctx context.Context, q *storage.Query) *storage.ObjectIterator
}

// realObject wraps *storage.ObjectHandle to satisfy GCSObject.
type realObject struct{ h *storage.ObjectHandle }

func (o *realObject) NewReader(ctx context.Context) (io.ReadCloser, error) {
	return o.h.NewReader(ctx)
}
func (o *realObject) NewWriter(ctx context.Context) io.WriteCloser {
	return o.h.NewWriter(ctx)
}
func (o *realObject) NewWriterWithCondition(ctx context.Context, cond storage.Conditions) io.WriteCloser {
	return o.h.If(cond).NewWriter(ctx)
}
func (o *realObject) Attrs(ctx context.Context) (*storage.ObjectAttrs, error) {
	return o.h.Attrs(ctx)
}
func (o *realObject) Delete(ctx context.Context) error { return o.h.Delete(ctx) }

// realBucket wraps *storage.BucketHandle to satisfy GCSBucket.
type realBucket struct{ h *storage.BucketHandle }

func (b *realBucket) Object(name string) *storage.ObjectHandle { return b.h.Object(name) }
func (b *realBucket) Objects(ctx context.Context, q *storage.Query) *storage.ObjectIterator {
	return b.h.Objects(ctx, q)
}

// ListIterator abstracts *storage.ObjectIterator for testability.
// *storage.ObjectIterator satisfies this interface; tests can inject a mock.
type ListIterator interface {
	Next() (*storage.ObjectAttrs, error)
}

// BucketClient is the interface Connector needs for per-object access.
// Allows injecting a mock in tests.
type BucketClient interface {
	ObjectHandle(name string) GCSObject
	Objects(ctx context.Context, q *storage.Query) ListIterator
}

// gcsBackedBucket adapts *storage.BucketHandle to BucketClient.
type gcsBackedBucket struct{ h *storage.BucketHandle }

func (g *gcsBackedBucket) ObjectHandle(name string) GCSObject {
	return &realObject{h: g.h.Object(name)}
}
func (g *gcsBackedBucket) Objects(ctx context.Context, q *storage.Query) ListIterator {
	return g.h.Objects(ctx, q)
}

// Connector implements s3kv.StorageBackend backed by GCS.
type Connector struct {
	bucket BucketClient
	prefix string // prepended to every object name: {prefix}/{key}.json
	logger *slog.Logger
}

// NewConnector creates a GCS-backed connector.
// client is a *storage.Client; bucket is the GCS bucket name.
// prefix namespaces the keys (e.g. "mesh/msg").
func NewConnector(client *storage.Client, bucketName, prefix string, logger *slog.Logger) *Connector {
	if logger == nil {
		logger = slog.Default()
	}
	return &Connector{
		bucket: &gcsBackedBucket{h: client.Bucket(bucketName)},
		prefix: prefix,
		logger: logger,
	}
}

// newConnectorWithClient is used in tests to inject a mock BucketClient.
func newConnectorWithClient(bucket BucketClient, prefix string, logger *slog.Logger) *Connector {
	if logger == nil {
		logger = slog.Default()
	}
	return &Connector{bucket: bucket, prefix: prefix, logger: logger}
}

func (c *Connector) objectName(key string) string {
	if c.prefix != "" {
		return c.prefix + "/" + key + ".json"
	}
	return key + ".json"
}

func (c *Connector) logicalKey(name string) string {
	k := name
	if c.prefix != "" {
		k = strings.TrimPrefix(k, c.prefix+"/")
	}
	return strings.TrimSuffix(k, ".json")
}

// Read fetches and deserialises a document from GCS.
func (c *Connector) Read(ctx context.Context, key string) (*s3kv.KVRow, error) {
	r, err := c.bucket.ObjectHandle(c.objectName(key)).NewReader(ctx)
	if err != nil {
		if errors.Is(err, storage.ErrObjectNotExist) {
			return nil, s3kv.ErrNotFound
		}
		return nil, fmt.Errorf("gcs read %s: %w", key, err)
	}
	defer r.Close()
	raw, err := io.ReadAll(r)
	if err != nil {
		return nil, fmt.Errorf("gcs read body %s: %w", key, err)
	}
	return s3kv.ParseStored(key, raw)
}

// Write stores a JSON document. _ca (created_at) is preserved on overwrite.
func (c *Connector) Write(ctx context.Context, key string, value json.RawMessage) error {
	createdAt := time.Now().UTC()
	if existing, err := c.Read(ctx, key); err == nil {
		createdAt = existing.CreatedAt
	}
	doc, err := s3kv.BuildStored(value, createdAt, time.Now().UTC())
	if err != nil {
		return fmt.Errorf("build stored %s: %w", key, err)
	}
	return c.writeRaw(ctx, c.objectName(key), doc, storage.Conditions{})
}

// WriteConditional writes only if the current "status" field equals ifStatus.
// Uses GCS generation-based CAS: read generation → write with GenerationMatch.
// Returns ErrConditionFailed if the generation has advanced (concurrent write).
func (c *Connector) WriteConditional(ctx context.Context, key string, value json.RawMessage, ifStatus string) error {
	attrs, err := c.bucket.ObjectHandle(c.objectName(key)).Attrs(ctx)
	if err != nil {
		if errors.Is(err, storage.ErrObjectNotExist) {
			return s3kv.ErrNotFound
		}
		return fmt.Errorf("gcs attrs %s: %w", key, err)
	}

	existing, err := c.Read(ctx, key)
	if err != nil {
		return err
	}
	var current map[string]any
	if err := json.Unmarshal(existing.Value, &current); err != nil {
		return fmt.Errorf("parse existing %s: %w", key, err)
	}
	if cur, _ := current["status"].(string); cur != ifStatus {
		return s3kv.ErrConditionFailed
	}

	doc, err := s3kv.BuildStored(value, existing.CreatedAt, time.Now().UTC())
	if err != nil {
		return fmt.Errorf("build stored %s: %w", key, err)
	}
	err = c.writeRaw(ctx, c.objectName(key), doc,
		storage.Conditions{GenerationMatch: attrs.Generation})
	if err != nil {
		// GCS returns a 412 Precondition Failed when generation doesn't match.
		if strings.Contains(err.Error(), "conditionNotMet") ||
			strings.Contains(err.Error(), "412") {
			return s3kv.ErrConditionFailed
		}
		return err
	}
	return nil
}

// Exists returns true if the key exists in GCS.
func (c *Connector) Exists(ctx context.Context, key string) (bool, error) {
	_, err := c.bucket.ObjectHandle(c.objectName(key)).Attrs(ctx)
	if err != nil {
		if errors.Is(err, storage.ErrObjectNotExist) {
			return false, nil
		}
		return false, fmt.Errorf("gcs attrs %s: %w", key, err)
	}
	return true, nil
}

// Delete removes a key. Returns ErrNotFound if it does not exist.
func (c *Connector) Delete(ctx context.Context, key string) error {
	err := c.bucket.ObjectHandle(c.objectName(key)).Delete(ctx)
	if err != nil {
		if errors.Is(err, storage.ErrObjectNotExist) {
			return s3kv.ErrNotFound
		}
		return fmt.Errorf("gcs delete %s: %w", key, err)
	}
	c.logger.Debug("delete", "key", key)
	return nil
}

// List returns all logical keys whose object name starts with the given prefix.
func (c *Connector) List(ctx context.Context, keyPrefix string) ([]string, error) {
	objPrefix := c.objectName(keyPrefix)
	objPrefix = strings.TrimSuffix(objPrefix, ".json") // directory prefix, no suffix

	q := &storage.Query{Prefix: objPrefix}
	iter := c.bucket.Objects(ctx, q)
	var keys []string
	for {
		attrs, err := iter.Next()
		if errors.Is(err, iterator.Done) {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("gcs list prefix=%s: %w", keyPrefix, err)
		}
		keys = append(keys, c.logicalKey(attrs.Name))
	}
	c.logger.Debug("list", "prefix", keyPrefix, "count", len(keys))
	return keys, nil
}

func (c *Connector) writeRaw(ctx context.Context, name string, doc []byte, cond storage.Conditions) error {
	var w io.WriteCloser
	if cond == (storage.Conditions{}) {
		w = c.bucket.ObjectHandle(name).NewWriter(ctx)
	} else {
		w = c.bucket.ObjectHandle(name).NewWriterWithCondition(ctx, cond)
	}
	if _, err := w.Write(doc); err != nil {
		w.Close() // nolint:errcheck
		return fmt.Errorf("gcs write %s: %w", name, err)
	}
	if err := w.Close(); err != nil {
		return fmt.Errorf("gcs close %s: %w", name, err)
	}
	c.logger.Debug("write", "name", name, "size", len(doc))
	return nil
}
