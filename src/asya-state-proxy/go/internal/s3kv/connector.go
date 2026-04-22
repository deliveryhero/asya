package s3kv

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
)

// ErrNotFound is returned when a key does not exist in S3.
var ErrNotFound = errors.New("key not found")

// ErrConditionFailed is returned when a conditional write's precondition is not met.
var ErrConditionFailed = errors.New("condition failed")

// S3Client is the subset of s3.Client used by the connector; enables mocking in tests.
type S3Client interface {
	GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
	DeleteObject(ctx context.Context, params *s3.DeleteObjectInput, optFns ...func(*s3.Options)) (*s3.DeleteObjectOutput, error)
	HeadObject(ctx context.Context, params *s3.HeadObjectInput, optFns ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
	ListObjectsV2(ctx context.Context, params *s3.ListObjectsV2Input, optFns ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
}

// KVRow mirrors the pg.KVRow contract so mesh-api can swap connectors without
// changing the client: GET /keys/{key} returns this struct as JSON.
type KVRow struct {
	Key       string          `json:"key"`
	Value     json.RawMessage `json:"value"`
	CreatedAt time.Time       `json:"created_at"`
	UpdatedAt time.Time       `json:"updated_at"`
}

// storedDoc is the on-disk layout of each S3 object.
// Fields beginning with _ are connector-internal and are stripped from KVRow.Value.
type storedDoc struct {
	CreatedAt time.Time       `json:"_ca"`
	UpdatedAt time.Time       `json:"_ua"`
	Fields    map[string]any  `json:"-"` // all other fields (application data)
}

// Connector implements state-proxy KV operations backed by S3.
type Connector struct {
	client S3Client
	bucket string
	prefix string // prepended to every key: s3://{bucket}/{prefix}/{key}.json
	logger *slog.Logger
}

// NewConnector creates a new S3 connector.
// prefix is the key namespace, e.g. "mesh/msg". May be empty.
func NewConnector(client S3Client, bucket, prefix string, logger *slog.Logger) *Connector {
	if logger == nil {
		logger = slog.Default()
	}
	return &Connector{client: client, bucket: bucket, prefix: prefix, logger: logger}
}

// objectKey returns the S3 object key for a logical key.
func (c *Connector) objectKey(key string) string {
	if c.prefix != "" {
		return c.prefix + "/" + key + ".json"
	}
	return key + ".json"
}

// logicalKey extracts the logical key from a full S3 object key.
func (c *Connector) logicalKey(objectKey string) string {
	k := objectKey
	if c.prefix != "" {
		k = strings.TrimPrefix(k, c.prefix+"/")
	}
	return strings.TrimSuffix(k, ".json")
}

// Read fetches a document from S3. Returns ErrNotFound if missing.
func (c *Connector) Read(ctx context.Context, key string) (*KVRow, error) {
	out, err := c.client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(c.bucket),
		Key:    aws.String(c.objectKey(key)),
	})
	if err != nil {
		if isNotFound(err) {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("s3 get %s: %w", key, err)
	}
	defer out.Body.Close()

	raw, err := io.ReadAll(out.Body)
	if err != nil {
		return nil, fmt.Errorf("s3 read body %s: %w", key, err)
	}

	return parseStored(key, raw)
}

// Write stores a JSON document under key. On first write, _ca (created_at) is
// stamped to now. On overwrite, _ca is preserved from the existing document.
func (c *Connector) Write(ctx context.Context, key string, value json.RawMessage) error {
	createdAt := time.Now().UTC()

	// Preserve created_at if the document already exists.
	if existing, err := c.Read(ctx, key); err == nil {
		createdAt = existing.CreatedAt
	}

	doc, err := buildStored(value, createdAt, time.Now().UTC())
	if err != nil {
		return fmt.Errorf("build stored doc %s: %w", key, err)
	}

	return c.putObject(ctx, key, doc)
}

// WriteConditional writes a document only if the current value's "status" field
// matches ifStatus. Returns ErrConditionFailed on mismatch (concurrent update),
// ErrNotFound if the key does not exist.
func (c *Connector) WriteConditional(ctx context.Context, key string, value json.RawMessage, ifStatus string) error {
	existing, err := c.Read(ctx, key)
	if err != nil {
		return err // ErrNotFound propagates
	}

	// Extract current status from the stored value.
	var current map[string]any
	if err := json.Unmarshal(existing.Value, &current); err != nil {
		return fmt.Errorf("parse existing value for %s: %w", key, err)
	}
	currentStatus, _ := current["status"].(string)
	if currentStatus != ifStatus {
		return ErrConditionFailed
	}

	doc, err := buildStored(value, existing.CreatedAt, time.Now().UTC())
	if err != nil {
		return fmt.Errorf("build stored doc %s: %w", key, err)
	}

	return c.putObject(ctx, key, doc)
}

// Exists returns true if the key has an object in S3.
func (c *Connector) Exists(ctx context.Context, key string) (bool, error) {
	_, err := c.client.HeadObject(ctx, &s3.HeadObjectInput{
		Bucket: aws.String(c.bucket),
		Key:    aws.String(c.objectKey(key)),
	})
	if err != nil {
		if isNotFound(err) {
			return false, nil
		}
		return false, fmt.Errorf("s3 head %s: %w", key, err)
	}
	return true, nil
}

// Delete removes a key. Returns ErrNotFound if the key does not exist.
func (c *Connector) Delete(ctx context.Context, key string) error {
	exists, err := c.Exists(ctx, key)
	if err != nil {
		return err
	}
	if !exists {
		return ErrNotFound
	}
	if _, err := c.client.DeleteObject(ctx, &s3.DeleteObjectInput{
		Bucket: aws.String(c.bucket),
		Key:    aws.String(c.objectKey(key)),
	}); err != nil {
		return fmt.Errorf("s3 delete %s: %w", key, err)
	}
	c.logger.Debug("delete", "key", key)
	return nil
}

// List returns all logical keys whose object key starts with the given prefix.
func (c *Connector) List(ctx context.Context, keyPrefix string) ([]string, error) {
	s3Prefix := c.objectKey(keyPrefix)
	// objectKey appends ".json" but listing needs a directory prefix (no suffix).
	s3Prefix = strings.TrimSuffix(s3Prefix, ".json")

	paginator := s3.NewListObjectsV2Paginator(c.client, &s3.ListObjectsV2Input{
		Bucket: aws.String(c.bucket),
		Prefix: aws.String(s3Prefix),
	})

	var keys []string
	for paginator.HasMorePages() {
		page, err := paginator.NextPage(ctx)
		if err != nil {
			return nil, fmt.Errorf("s3 list prefix=%s: %w", keyPrefix, err)
		}
		for _, obj := range page.Contents {
			keys = append(keys, c.logicalKey(aws.ToString(obj.Key)))
		}
	}
	c.logger.Debug("list", "prefix", keyPrefix, "count", len(keys))
	return keys, nil
}

// putObject serialises doc and writes it to S3.
func (c *Connector) putObject(ctx context.Context, key string, doc []byte) error {
	_, err := c.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(c.bucket),
		Key:         aws.String(c.objectKey(key)),
		Body:        bytes.NewReader(doc),
		ContentType: aws.String("application/json"),
	})
	if err != nil {
		return fmt.Errorf("s3 put %s: %w", key, err)
	}
	c.logger.Debug("write", "key", key, "size", len(doc))
	return nil
}

// buildStored merges _ca/_ua timestamps into the application value JSON.
// The merged object is what gets stored in S3 and read by DuckDB.
func buildStored(value json.RawMessage, createdAt, updatedAt time.Time) ([]byte, error) {
	var fields map[string]any
	if err := json.Unmarshal(value, &fields); err != nil {
		return nil, fmt.Errorf("unmarshal value: %w", err)
	}
	fields["_ca"] = createdAt.Format(time.RFC3339Nano)
	fields["_ua"] = updatedAt.Format(time.RFC3339Nano)
	return json.Marshal(fields)
}

// parseStored extracts _ca/_ua from a raw stored document and returns a KVRow
// whose Value contains only the application fields (no _ca/_ua).
func parseStored(key string, raw []byte) (*KVRow, error) {
	var fields map[string]any
	if err := json.Unmarshal(raw, &fields); err != nil {
		return nil, fmt.Errorf("unmarshal stored doc for %s: %w", key, err)
	}

	createdAt := extractTime(fields, "_ca")
	updatedAt := extractTime(fields, "_ua")
	delete(fields, "_ca")
	delete(fields, "_ua")

	value, err := json.Marshal(fields)
	if err != nil {
		return nil, fmt.Errorf("marshal value for %s: %w", key, err)
	}

	return &KVRow{
		Key:       key,
		Value:     value,
		CreatedAt: createdAt,
		UpdatedAt: updatedAt,
	}, nil
}

func extractTime(fields map[string]any, key string) time.Time {
	s, _ := fields[key].(string)
	if s == "" {
		return time.Time{}
	}
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return time.Time{}
	}
	return t
}

// isNotFound returns true for S3 404 / NoSuchKey errors.
func isNotFound(err error) bool {
	var nsk *s3types.NoSuchKey
	if errors.As(err, &nsk) {
		return true
	}
	var nf *s3types.NotFound
	if errors.As(err, &nf) {
		return true
	}
	// aws-sdk-go-v2 wraps some 404s without typed errors.
	msg := err.Error()
	return strings.Contains(msg, "StatusCode: 404") ||
		strings.Contains(msg, "NoSuchKey") ||
		strings.Contains(msg, "404")
}
