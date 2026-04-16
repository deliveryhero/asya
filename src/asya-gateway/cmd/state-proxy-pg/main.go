package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/deliveryhero/asya/asya-gateway/internal/stateproxypg"
)

func main() {
	// Required env vars (no defaults per project policy):
	//   CONNECTOR_SOCKET      - Unix socket path
	//   STATE_PROXY_PG_URL    - PostgreSQL connection string
	// Optional:
	//   STATE_PROXY_PG_INDEXES - Comma-separated index expressions
	socketPath := os.Getenv("CONNECTOR_SOCKET")
	pgURL := os.Getenv("STATE_PROXY_PG_URL")

	if socketPath == "" {
		slog.Error("CONNECTOR_SOCKET required")
		os.Exit(1)
	}
	if pgURL == "" {
		slog.Error("STATE_PROXY_PG_URL required")
		os.Exit(1)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	pool, err := pgxpool.New(ctx, pgURL)
	if err != nil {
		slog.Error("Failed to create PG pool", "error", err)
		os.Exit(1)
	}
	defer pool.Close()

	// Verify connectivity
	if err := pool.Ping(ctx); err != nil {
		slog.Error("Failed to ping PG", "error", err)
		os.Exit(1)
	}

	// Ensure schema
	if err := stateproxypg.EnsureSchema(ctx, pool); err != nil {
		slog.Error("Failed to ensure schema", "error", err)
		os.Exit(1)
	}

	// Create expression indexes from env var
	indexSpec := os.Getenv("STATE_PROXY_PG_INDEXES")
	if err := stateproxypg.EnsureIndexes(ctx, pool, indexSpec); err != nil {
		slog.Error("Failed to create indexes", "error", err)
		os.Exit(1)
	}

	conn := stateproxypg.NewConnector(pool)
	handler := stateproxypg.NewHTTPHandler(conn)

	if err := stateproxypg.ListenUnixSocket(ctx, socketPath, handler); err != nil {
		slog.Error("Server failed", "error", err)
		os.Exit(1)
	}
}
