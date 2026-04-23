package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/pg"
	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/pvckv"
)

func main() {
	// Required env vars (no defaults per project policy):
	//   CONNECTOR_SOCKET  - Unix socket path
	//   PVC_KV_MODE       - "inmem" | "pvc"
	// Required for pvc mode:
	//   PVC_KV_BASE_DIR   - storage root directory
	// Optional:
	//   PVC_KV_PARTITION  - "true" enables active/ + archive/ subdirs
	//   PVC_KV_ARCHIVE_STATUSES - comma-separated statuses to archive on delete

	socketPath := os.Getenv("CONNECTOR_SOCKET")
	mode := os.Getenv("PVC_KV_MODE")

	if socketPath == "" {
		slog.Error("CONNECTOR_SOCKET required")
		os.Exit(1)
	}
	if mode == "" {
		slog.Error("PVC_KV_MODE required")
		os.Exit(1)
	}

	cfg := pvckv.Config{
		Mode:      mode,
		BaseDir:   os.Getenv("PVC_KV_BASE_DIR"),
		Partition: os.Getenv("PVC_KV_PARTITION") == "true",
	}

	if raw := os.Getenv("PVC_KV_ARCHIVE_STATUSES"); raw != "" {
		for _, s := range strings.Split(raw, ",") {
			if s = strings.TrimSpace(s); s != "" {
				cfg.ArchiveStatuses = append(cfg.ArchiveStatuses, s)
			}
		}
	}

	if mode == "pvc" && cfg.BaseDir == "" {
		slog.Error("PVC_KV_BASE_DIR required for pvc mode")
		os.Exit(1)
	}

	conn, err := pvckv.NewConnector(cfg)
	if err != nil {
		slog.Error("Failed to create connector", "error", err)
		os.Exit(1)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	handler := pg.NewHTTPHandler(conn)

	slog.Info("Starting pvc-kv state proxy", "mode", mode, "socket", socketPath)
	if err := pg.ListenUnixSocket(ctx, socketPath, handler); err != nil {
		slog.Error("Server failed", "error", err)
		os.Exit(1)
	}
}
