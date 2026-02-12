package main

import (
	"context"
	"io"
	"testing"

	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// mockS3Client implements s3PutObjectAPI for testing.
type mockS3Client struct {
	putFunc func(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

func (m *mockS3Client) PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	return m.putFunc(ctx, params, optFns...)
}

func TestS3Storage_Persist(t *testing.T) {
	var storedBucket, storedKey string
	var storedBody []byte

	mock := &mockS3Client{
		putFunc: func(_ context.Context, params *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
			storedBucket = *params.Bucket
			storedKey = *params.Key
			storedBody, _ = io.ReadAll(params.Body)
			return &s3.PutObjectOutput{}, nil
		},
	}

	storage := newS3StorageWithClient(mock, "test-bucket", "dlq/")

	body := []byte(`{"id":"msg-123","payload":{"data":"test"}}`)
	err := storage.Persist(context.Background(), "msg-123", body)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if storedBucket != "test-bucket" {
		t.Errorf("bucket = %q", storedBucket)
	}
	if storedKey == "" {
		t.Fatal("key should not be empty")
	}
	// Key format: dlq/{date}/msg-123.json
	if len(storedKey) < len("dlq/2024-01-01/msg-123.json") {
		t.Errorf("key too short: %q", storedKey)
	}
	if string(storedBody) != string(body) {
		t.Errorf("body mismatch: got %q", string(storedBody))
	}
}

func TestS3Storage_Persist_CustomPrefix(t *testing.T) {
	var storedKey string

	mock := &mockS3Client{
		putFunc: func(_ context.Context, params *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
			storedKey = *params.Key
			return &s3.PutObjectOutput{}, nil
		},
	}

	storage := newS3StorageWithClient(mock, "bucket", "custom/prefix/")

	err := storage.Persist(context.Background(), "id-456", []byte(`{}`))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if storedKey[:len("custom/prefix/")] != "custom/prefix/" {
		t.Errorf("key should start with custom/prefix/, got: %q", storedKey)
	}
}

func TestS3Storage_Persist_Error(t *testing.T) {
	mock := &mockS3Client{
		putFunc: func(_ context.Context, _ *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
			return nil, context.DeadlineExceeded
		},
	}

	storage := newS3StorageWithClient(mock, "bucket", "dlq/")

	err := storage.Persist(context.Background(), "msg-err", []byte(`{}`))
	if err == nil {
		t.Fatal("expected error from S3")
	}
}
