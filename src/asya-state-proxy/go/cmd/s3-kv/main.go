package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/s3kv"
)

func main() {
	// Required env vars (fail fast on missing config per project policy):
	//   CONNECTOR_SOCKET   - Unix socket path
	//   STATE_BUCKET       - S3 bucket name
	//   STATE_PREFIX       - Key prefix inside bucket (e.g. "mesh/msg")
	// Optional:
	//   AWS_REGION         - AWS region (default: us-east-1 — SDK needs a region)
	//   AWS_ENDPOINT_URL   - Override for MinIO / LocalStack

	socketPath := os.Getenv("CONNECTOR_SOCKET")
	bucket := os.Getenv("STATE_BUCKET")
	prefix := os.Getenv("STATE_PREFIX")

	if socketPath == "" {
		slog.Error("CONNECTOR_SOCKET required")
		os.Exit(1)
	}
	if bucket == "" {
		slog.Error("STATE_BUCKET required")
		os.Exit(1)
	}
	if prefix == "" {
		slog.Error("STATE_PREFIX required")
		os.Exit(1)
	}

	region := os.Getenv("AWS_REGION")
	if region == "" {
		region = "us-east-1"
	}
	endpoint := os.Getenv("AWS_ENDPOINT_URL")

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	awsCfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
	if err != nil {
		slog.Error("load aws config", "err", err)
		os.Exit(1)
	}

	var s3Opts []func(*s3.Options)
	if endpoint != "" {
		s3Opts = append(s3Opts, func(o *s3.Options) {
			o.BaseEndpoint = &endpoint
			o.UsePathStyle = true
		})
	}
	s3Client := s3.NewFromConfig(awsCfg, s3Opts...)

	conn := s3kv.NewConnector(s3Client, bucket, prefix, nil)

	qe, err := s3kv.NewQueryEngine(conn, nil)
	if err != nil {
		slog.Error("init duckdb query engine", "err", err)
		os.Exit(1)
	}
	defer qe.Close()

	sc := s3kv.NewServerConnector(conn, qe)
	handler := s3kv.NewHTTPHandler(sc)

	if err := s3kv.ListenUnixSocket(ctx, socketPath, handler); err != nil {
		slog.Error("server error", "err", err)
		os.Exit(1)
	}
}
