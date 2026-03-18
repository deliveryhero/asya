package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"time"

	"cloud.google.com/go/storage"
)

// gcsObjectWriterAPI abstracts GCS object write operations for testability.
type gcsObjectWriterAPI interface {
	Write(p []byte) (int, error)
	Close() error
}

// gcsWriterFactory creates GCS object writers.
type gcsWriterFactory interface {
	NewWriter(ctx context.Context, bucket, key string) (gcsObjectWriterAPI, error)
}

// gcsClientFactory is the production implementation of gcsWriterFactory.
type gcsClientFactory struct {
	client *storage.Client
}

func (f *gcsClientFactory) NewWriter(ctx context.Context, bucket, key string) (gcsObjectWriterAPI, error) {
	w := f.client.Bucket(bucket).Object(key).NewWriter(ctx)
	w.ContentType = "application/json"
	return w, nil
}

// gcsStorage implements Storage using Google Cloud Storage.
type gcsStorage struct {
	factory gcsWriterFactory
	bucket  string
	prefix  string
}

// GCSStorageConfig holds GCS storage configuration.
type GCSStorageConfig struct {
	Bucket string
	Prefix string
}

// NewGCSStorage creates a GCS-backed storage for DLQ message persistence.
// Authentication uses Application Default Credentials (Workload Identity on GKE).
func NewGCSStorage(ctx context.Context, cfg GCSStorageConfig) (Storage, error) {
	client, err := storage.NewClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create GCS client: %w", err)
	}
	return &gcsStorage{
		factory: &gcsClientFactory{client: client},
		bucket:  cfg.Bucket,
		prefix:  cfg.Prefix,
	}, nil
}

// newGCSStorageWithFactory creates a gcsStorage with an injected factory (for testing).
func newGCSStorageWithFactory(factory gcsWriterFactory, bucket, prefix string) Storage {
	return &gcsStorage{
		factory: factory,
		bucket:  bucket,
		prefix:  prefix,
	}
}

// Persist stores the message body in GCS under key: {prefix}{date}/{messageID}.json
func (s *gcsStorage) Persist(ctx context.Context, messageID string, body []byte) error {
	date := time.Now().UTC().Format("2006-01-02")
	key := fmt.Sprintf("%s%s/%s.json", s.prefix, date, messageID)

	w, err := s.factory.NewWriter(ctx, s.bucket, key)
	if err != nil {
		return fmt.Errorf("failed to create GCS writer for message %s: %w", messageID, err)
	}

	if _, err := io.Copy(w, bytes.NewReader(body)); err != nil {
		return fmt.Errorf("failed to write message %s to GCS: %w", messageID, err)
	}

	if err := w.Close(); err != nil {
		return fmt.Errorf("failed to close GCS writer for message %s: %w", messageID, err)
	}

	slog.Info("Persisted DLQ message to GCS", "bucket", s.bucket, "key", key)
	return nil
}
