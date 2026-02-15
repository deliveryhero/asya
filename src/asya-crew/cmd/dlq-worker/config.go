package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config holds DLQ worker configuration loaded from environment variables.
type Config struct {
	QueueURL          string // DLQ_QUEUE_URL: Full SQS queue URL for the DLQ
	Transport         string // DLQ_TRANSPORT: Transport type (sqs)
	GatewayURL        string // GATEWAY_URL: Gateway base URL for status reporting (optional)
	S3Bucket          string // S3_BUCKET: S3 bucket for message persistence
	S3Endpoint        string // S3_ENDPOINT: Custom S3 endpoint for MinIO (optional)
	S3Prefix          string // S3_PREFIX: Key prefix for stored messages (default: "dlq/")
	S3Region          string // S3_REGION or AWS_REGION: S3 region
	SQSRegion         string // SQS_REGION or AWS_REGION: SQS region
	LogLevel          string // LOG_LEVEL: Logging level (default: "INFO")
	VisibilityTimeout int32  // VISIBILITY_TIMEOUT: SQS visibility timeout in seconds (default: 300)
	WaitTimeSeconds   int32  // WAIT_TIME_SECONDS: SQS long polling wait time (default: 20)
}

// LoadFromEnv loads configuration from environment variables.
// Follows fail-fast strategy: required variables must be set.
func LoadFromEnv() (*Config, error) {
	cfg := &Config{
		QueueURL:   os.Getenv("DLQ_QUEUE_URL"),
		Transport:  os.Getenv("DLQ_TRANSPORT"),
		GatewayURL: os.Getenv("GATEWAY_URL"),
		S3Bucket:   os.Getenv("S3_BUCKET"),
		S3Endpoint: os.Getenv("S3_ENDPOINT"),
		S3Prefix:   os.Getenv("S3_PREFIX"),
		S3Region:   os.Getenv("S3_REGION"),
		SQSRegion:  os.Getenv("SQS_REGION"),
		LogLevel:   os.Getenv("LOG_LEVEL"),
	}

	// Defaults
	if cfg.S3Prefix == "" {
		cfg.S3Prefix = "dlq/"
	}
	if cfg.LogLevel == "" {
		cfg.LogLevel = "INFO"
	}
	if cfg.S3Region == "" {
		cfg.S3Region = os.Getenv("AWS_REGION")
	}
	if cfg.SQSRegion == "" {
		cfg.SQSRegion = os.Getenv("AWS_REGION")
	}

	// Parse optional integer configs
	if v := os.Getenv("VISIBILITY_TIMEOUT"); v != "" {
		n, err := strconv.ParseInt(v, 10, 32)
		if err != nil {
			return nil, fmt.Errorf("invalid VISIBILITY_TIMEOUT: %w", err)
		}
		cfg.VisibilityTimeout = int32(n)
	} else {
		cfg.VisibilityTimeout = 300
	}

	if v := os.Getenv("WAIT_TIME_SECONDS"); v != "" {
		n, err := strconv.ParseInt(v, 10, 32)
		if err != nil {
			return nil, fmt.Errorf("invalid WAIT_TIME_SECONDS: %w", err)
		}
		cfg.WaitTimeSeconds = int32(n)
	} else {
		cfg.WaitTimeSeconds = 20
	}

	// Validate required fields
	var missing []string
	if cfg.QueueURL == "" {
		missing = append(missing, "DLQ_QUEUE_URL")
	}
	if cfg.Transport == "" {
		missing = append(missing, "DLQ_TRANSPORT")
	}
	if cfg.SQSRegion == "" {
		missing = append(missing, "SQS_REGION or AWS_REGION")
	}
	// S3_BUCKET is optional: when unset, messages are written to stdout
	// S3_REGION is only required when S3_BUCKET is set
	if cfg.S3Bucket != "" && cfg.S3Region == "" {
		missing = append(missing, "S3_REGION or AWS_REGION (required when S3_BUCKET is set)")
	}

	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required environment variables: %s", strings.Join(missing, ", "))
	}

	// Validate transport type
	if cfg.Transport != "sqs" {
		return nil, fmt.Errorf("unsupported DLQ_TRANSPORT: %q (supported: sqs)", cfg.Transport)
	}

	return cfg, nil
}
