package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"
)

func main() {
	// Set up structured logging
	logLevel := os.Getenv("LOG_LEVEL")
	if logLevel == "" {
		logLevel = "INFO"
	}
	var level slog.Level
	switch strings.ToUpper(logLevel) {
	case "DEBUG":
		level = slog.LevelDebug
	case "INFO":
		level = slog.LevelInfo
	case "WARN", "WARNING":
		level = slog.LevelWarn
	case "ERROR":
		level = slog.LevelError
	default:
		level = slog.LevelInfo
	}

	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: level,
	}))
	slog.SetDefault(logger)

	slog.Info("Starting DLQ Worker", "logLevel", logLevel)

	// Load configuration
	cfg, err := LoadFromEnv()
	if err != nil {
		slog.Error("Failed to load configuration", "error", err)
		os.Exit(1)
	}

	slog.Info("Configuration loaded",
		"transport", cfg.Transport,
		"queue_url", cfg.QueueURL,
		"s3_bucket", cfg.S3Bucket,
		"s3_prefix", cfg.S3Prefix,
		"gateway_url", cfg.GatewayURL)

	// Setup graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		sig := <-sigChan
		slog.Info("Received signal, initiating shutdown", "signal", sig)
		cancel()
	}()

	// Create consumer based on transport
	var consumer Consumer
	switch cfg.Transport {
	case "sqs":
		consumer, err = NewSQSConsumer(ctx, SQSConsumerConfig{
			Region:            cfg.SQSRegion,
			QueueURL:          cfg.QueueURL,
			VisibilityTimeout: cfg.VisibilityTimeout,
			WaitTimeSeconds:   cfg.WaitTimeSeconds,
		})
		if err != nil {
			slog.Error("Failed to create SQS consumer", "error", err)
			os.Exit(1)
		}
		slog.Info("SQS consumer initialized", "region", cfg.SQSRegion)
	default:
		slog.Error("Unsupported transport", "transport", cfg.Transport)
		os.Exit(1)
	}
	defer func() { _ = consumer.Close() }()

	// Create gateway reporter
	var gateway GatewayReporter
	if cfg.GatewayURL != "" {
		gateway = NewGatewayClient(cfg.GatewayURL)
		slog.Info("Gateway reporter configured", "url", cfg.GatewayURL)
	} else {
		gateway = &noopGateway{}
		slog.Info("No gateway URL configured, status reporting disabled")
	}

	// Create storage backend
	var storage Storage
	if cfg.S3Bucket != "" {
		storage, err = NewS3Storage(ctx, S3StorageConfig{
			Region:   cfg.S3Region,
			Endpoint: cfg.S3Endpoint,
			Bucket:   cfg.S3Bucket,
			Prefix:   cfg.S3Prefix,
		})
		if err != nil {
			slog.Error("Failed to create S3 storage", "error", err)
			os.Exit(1)
		}
		slog.Info("S3 storage initialized",
			"bucket", cfg.S3Bucket,
			"prefix", cfg.S3Prefix,
			"endpoint", cfg.S3Endpoint)
	} else {
		storage = &stdoutStorage{}
		slog.Info("S3 not configured, DLQ messages will be written to stdout")
	}

	// Create and run worker
	worker := NewWorker(consumer, gateway, storage)
	if err := worker.Run(ctx); err != nil {
		slog.Error("Worker error", "error", err)
		os.Exit(1)
	}

	slog.Info("DLQ Worker shutdown complete")
}
