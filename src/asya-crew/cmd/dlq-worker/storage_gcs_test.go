package main

import (
	"bytes"
	"context"
	"io"
	"testing"
)

// mockGCSWriter implements gcsObjectWriterAPI for testing.
type mockGCSWriter struct {
	buf    bytes.Buffer
	closed bool
	err    error
}

func (m *mockGCSWriter) Write(p []byte) (int, error) {
	if m.err != nil {
		return 0, m.err
	}
	return m.buf.Write(p)
}

func (m *mockGCSWriter) Close() error {
	m.closed = true
	return nil
}

// mockGCSWriterFactory implements gcsWriterFactory for testing.
type mockGCSWriterFactory struct {
	newWriterFunc func(ctx context.Context, bucket, key string) (gcsObjectWriterAPI, error)
}

func (m *mockGCSWriterFactory) NewWriter(ctx context.Context, bucket, key string) (gcsObjectWriterAPI, error) {
	return m.newWriterFunc(ctx, bucket, key)
}

func TestGCSStorage_Persist(t *testing.T) {
	var storedBucket, storedKey string
	var writer *mockGCSWriter

	factory := &mockGCSWriterFactory{
		newWriterFunc: func(_ context.Context, bucket, key string) (gcsObjectWriterAPI, error) {
			storedBucket = bucket
			storedKey = key
			writer = &mockGCSWriter{}
			return writer, nil
		},
	}

	storage := newGCSStorageWithFactory(factory, "test-bucket", "dlq/")

	body := []byte(`{"id":"msg-123","payload":{"data":"test"}}`)
	err := storage.Persist(context.Background(), "msg-123", body)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if storedBucket != "test-bucket" {
		t.Errorf("bucket = %q, want %q", storedBucket, "test-bucket")
	}
	if storedKey == "" {
		t.Fatal("key should not be empty")
	}
	// Key format: dlq/{date}/msg-123.json
	if len(storedKey) < len("dlq/2024-01-01/msg-123.json") {
		t.Errorf("key too short: %q", storedKey)
	}
	if !writer.closed {
		t.Error("writer should be closed after Persist")
	}
	if !bytes.Equal(writer.buf.Bytes(), body) {
		t.Errorf("body mismatch: got %q, want %q", writer.buf.Bytes(), body)
	}
}

func TestGCSStorage_Persist_CustomPrefix(t *testing.T) {
	var storedKey string

	factory := &mockGCSWriterFactory{
		newWriterFunc: func(_ context.Context, _, key string) (gcsObjectWriterAPI, error) {
			storedKey = key
			return &mockGCSWriter{}, nil
		},
	}

	storage := newGCSStorageWithFactory(factory, "bucket", "custom/prefix/")

	err := storage.Persist(context.Background(), "id-456", []byte(`{}`))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(storedKey) < len("custom/prefix/") || storedKey[:len("custom/prefix/")] != "custom/prefix/" {
		t.Errorf("key should start with custom/prefix/, got: %q", storedKey)
	}
}

func TestGCSStorage_Persist_WriteError(t *testing.T) {
	factory := &mockGCSWriterFactory{
		newWriterFunc: func(_ context.Context, _, _ string) (gcsObjectWriterAPI, error) {
			return &mockGCSWriter{err: io.ErrClosedPipe}, nil
		},
	}

	storage := newGCSStorageWithFactory(factory, "bucket", "dlq/")

	err := storage.Persist(context.Background(), "msg-err", []byte(`{}`))
	if err == nil {
		t.Fatal("expected error from GCS write")
	}
}
