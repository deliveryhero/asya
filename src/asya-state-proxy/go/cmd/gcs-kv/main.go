package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"cloud.google.com/go/storage"
	"google.golang.org/api/option"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/gcskv"
	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/s3kv"
)

func main() {
	// Required env vars (fail fast on missing config per project policy):
	//   CONNECTOR_SOCKET   - Unix socket path
	//   STATE_BUCKET       - GCS bucket name
	//   STATE_PREFIX       - Key prefix inside bucket (e.g. "mesh/msg")
	// Optional:
	//   GCS_PROJECT        - GCP project ID (may be required in some envs)
	//   STORAGE_EMULATOR_HOST - Override for fake-gcs-server in tests

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

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	var clientOpts []option.ClientOption
	if emulator := os.Getenv("STORAGE_EMULATOR_HOST"); emulator != "" {
		clientOpts = append(clientOpts, option.WithEndpoint(emulator))
	}

	gcsClient, err := storage.NewClient(ctx, clientOpts...)
	if err != nil {
		slog.Error("init gcs client", "err", err)
		os.Exit(1)
	}
	defer gcsClient.Close()

	conn := gcskv.NewConnector(gcsClient, bucket, prefix, nil)

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
