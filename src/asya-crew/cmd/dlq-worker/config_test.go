package main

import (
	"os"
	"testing"
)

func clearEnv(t *testing.T) {
	t.Helper()
	for _, key := range []string{
		"DLQ_QUEUE_URL", "DLQ_TRANSPORT", "GATEWAY_URL",
		"S3_BUCKET", "S3_ENDPOINT", "S3_PREFIX", "S3_REGION", "SQS_REGION",
		"AWS_REGION", "LOG_LEVEL", "VISIBILITY_TIMEOUT", "WAIT_TIME_SECONDS",
	} {
		t.Setenv(key, "")
		os.Unsetenv(key)
	}
}

func setRequiredEnv(t *testing.T) {
	t.Helper()
	t.Setenv("DLQ_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789/my-dlq")
	t.Setenv("DLQ_TRANSPORT", "sqs")
	t.Setenv("AWS_REGION", "us-east-1")
}

func setRequiredEnvWithS3(t *testing.T) {
	t.Helper()
	setRequiredEnv(t)
	t.Setenv("S3_BUCKET", "my-bucket")
}

func TestLoadFromEnv_AllRequired(t *testing.T) {
	clearEnv(t)
	setRequiredEnvWithS3(t)

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.QueueURL != "https://sqs.us-east-1.amazonaws.com/123456789/my-dlq" {
		t.Errorf("QueueURL = %q", cfg.QueueURL)
	}
	if cfg.Transport != "sqs" {
		t.Errorf("Transport = %q", cfg.Transport)
	}
	if cfg.S3Bucket != "my-bucket" {
		t.Errorf("S3Bucket = %q", cfg.S3Bucket)
	}
	if cfg.SQSRegion != "us-east-1" {
		t.Errorf("SQSRegion = %q", cfg.SQSRegion)
	}
	if cfg.S3Region != "us-east-1" {
		t.Errorf("S3Region = %q", cfg.S3Region)
	}
}

func TestLoadFromEnv_NoS3Bucket_StdoutMode(t *testing.T) {
	clearEnv(t)
	setRequiredEnv(t)

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.S3Bucket != "" {
		t.Errorf("S3Bucket should be empty, got %q", cfg.S3Bucket)
	}
}

func TestLoadFromEnv_S3BucketWithoutRegion(t *testing.T) {
	clearEnv(t)
	t.Setenv("DLQ_QUEUE_URL", "https://sqs/dlq")
	t.Setenv("DLQ_TRANSPORT", "sqs")
	t.Setenv("SQS_REGION", "us-east-1")
	t.Setenv("S3_BUCKET", "my-bucket")
	// No S3_REGION or AWS_REGION

	_, err := LoadFromEnv()
	if err == nil {
		t.Fatal("expected error when S3_BUCKET is set without S3_REGION")
	}
}

func TestLoadFromEnv_Defaults(t *testing.T) {
	clearEnv(t)
	setRequiredEnvWithS3(t)

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.S3Prefix != "dlq/" {
		t.Errorf("S3Prefix default = %q, want %q", cfg.S3Prefix, "dlq/")
	}
	if cfg.LogLevel != "INFO" {
		t.Errorf("LogLevel default = %q, want %q", cfg.LogLevel, "INFO")
	}
	if cfg.VisibilityTimeout != 300 {
		t.Errorf("VisibilityTimeout default = %d, want 300", cfg.VisibilityTimeout)
	}
	if cfg.WaitTimeSeconds != 20 {
		t.Errorf("WaitTimeSeconds default = %d, want 20", cfg.WaitTimeSeconds)
	}
	if cfg.GatewayURL != "" {
		t.Errorf("GatewayURL should be empty, got %q", cfg.GatewayURL)
	}
}

func TestLoadFromEnv_MissingRequired(t *testing.T) {
	clearEnv(t)

	_, err := LoadFromEnv()
	if err == nil {
		t.Fatal("expected error for missing env vars")
	}
}

func TestLoadFromEnv_UnsupportedTransport(t *testing.T) {
	clearEnv(t)
	setRequiredEnvWithS3(t)
	t.Setenv("DLQ_TRANSPORT", "kafka")

	_, err := LoadFromEnv()
	if err == nil {
		t.Fatal("expected error for unsupported transport")
	}
}

func TestLoadFromEnv_CustomValues(t *testing.T) {
	clearEnv(t)
	setRequiredEnvWithS3(t)
	t.Setenv("S3_PREFIX", "custom-prefix/")
	t.Setenv("S3_ENDPOINT", "http://minio:9000")
	t.Setenv("GATEWAY_URL", "http://gateway:8080")
	t.Setenv("LOG_LEVEL", "DEBUG")
	t.Setenv("VISIBILITY_TIMEOUT", "600")
	t.Setenv("WAIT_TIME_SECONDS", "10")

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.S3Prefix != "custom-prefix/" {
		t.Errorf("S3Prefix = %q", cfg.S3Prefix)
	}
	if cfg.S3Endpoint != "http://minio:9000" {
		t.Errorf("S3Endpoint = %q", cfg.S3Endpoint)
	}
	if cfg.GatewayURL != "http://gateway:8080" {
		t.Errorf("GatewayURL = %q", cfg.GatewayURL)
	}
	if cfg.LogLevel != "DEBUG" {
		t.Errorf("LogLevel = %q", cfg.LogLevel)
	}
	if cfg.VisibilityTimeout != 600 {
		t.Errorf("VisibilityTimeout = %d", cfg.VisibilityTimeout)
	}
	if cfg.WaitTimeSeconds != 10 {
		t.Errorf("WaitTimeSeconds = %d", cfg.WaitTimeSeconds)
	}
}

func TestLoadFromEnv_InvalidVisibilityTimeout(t *testing.T) {
	clearEnv(t)
	setRequiredEnvWithS3(t)
	t.Setenv("VISIBILITY_TIMEOUT", "abc")

	_, err := LoadFromEnv()
	if err == nil {
		t.Fatal("expected error for invalid VISIBILITY_TIMEOUT")
	}
}

func TestLoadFromEnv_SeparateRegions(t *testing.T) {
	clearEnv(t)
	setRequiredEnvWithS3(t)
	t.Setenv("SQS_REGION", "eu-west-1")
	t.Setenv("S3_REGION", "ap-southeast-1")

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.SQSRegion != "eu-west-1" {
		t.Errorf("SQSRegion = %q, want eu-west-1", cfg.SQSRegion)
	}
	if cfg.S3Region != "ap-southeast-1" {
		t.Errorf("S3Region = %q, want ap-southeast-1", cfg.S3Region)
	}
}
