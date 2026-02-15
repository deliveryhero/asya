package main

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// Storage persists DLQ messages for offline analysis.
type Storage interface {
	// Persist stores a message body under a deterministic key derived from the message ID.
	Persist(ctx context.Context, messageID string, body []byte) error
}

// s3PutObjectAPI is the minimal S3 interface needed for persistence.
type s3PutObjectAPI interface {
	PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

// s3Storage implements Storage using AWS S3 / MinIO.
type s3Storage struct {
	client s3PutObjectAPI
	bucket string
	prefix string
}

// S3StorageConfig holds S3 storage configuration.
type S3StorageConfig struct {
	Region   string
	Endpoint string // Custom endpoint for MinIO (optional)
	Bucket   string
	Prefix   string // Key prefix (e.g., "dlq/")
}

// NewS3Storage creates an S3-backed storage for DLQ message persistence.
func NewS3Storage(ctx context.Context, cfg S3StorageConfig) (Storage, error) {
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(cfg.Region),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config for S3: %w", err)
	}

	var client *s3.Client
	if cfg.Endpoint != "" {
		client = s3.NewFromConfig(awsCfg, func(o *s3.Options) {
			o.BaseEndpoint = aws.String(cfg.Endpoint)
			o.UsePathStyle = true // Required for MinIO
		})
	} else {
		client = s3.NewFromConfig(awsCfg)
	}

	return &s3Storage{
		client: client,
		bucket: cfg.Bucket,
		prefix: cfg.Prefix,
	}, nil
}

// newS3StorageWithClient creates an s3Storage with an injected client (for testing).
func newS3StorageWithClient(client s3PutObjectAPI, bucket, prefix string) Storage {
	return &s3Storage{
		client: client,
		bucket: bucket,
		prefix: prefix,
	}
}

// Persist stores the message body in S3 under key: {prefix}{date}/{messageID}.json
func (s *s3Storage) Persist(ctx context.Context, messageID string, body []byte) error {
	date := time.Now().UTC().Format("2006-01-02")
	key := fmt.Sprintf("%s%s/%s.json", s.prefix, date, messageID)

	_, err := s.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(s.bucket),
		Key:         aws.String(key),
		Body:        bytes.NewReader(body),
		ContentType: aws.String("application/json"),
	})
	if err != nil {
		return fmt.Errorf("failed to persist message %s to S3: %w", messageID, err)
	}

	slog.Info("Persisted DLQ message to S3", "bucket", s.bucket, "key", key)
	return nil
}

// stdoutStorage writes DLQ messages to stdout as structured log lines.
// Used when S3_BUCKET is not configured (development/debugging mode).
type stdoutStorage struct{}

// Persist writes the full message body to stdout via structured logging.
func (s *stdoutStorage) Persist(_ context.Context, messageID string, body []byte) error {
	slog.Info("DLQ message persisted to stdout", "message_id", messageID, "body", string(body))
	return nil
}
