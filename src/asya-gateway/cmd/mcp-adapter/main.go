package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	mcpserver "github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/mcpadapter"
	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/internal/watcher"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: parseLogLevel(os.Getenv("ASYA_LOG_LEVEL")),
	})))

	meshAPIURL := requireEnv("MESH_API_URL")
	ingressURL := requireEnv("MESH_INGRESS_URL")
	configDir := requireEnv("ASYA_MCP_CONFIG_DIR")
	port := getEnv("ASYA_MCP_PORT", "8082")

	// Initialize mesh client
	mc := meshclient.New(meshAPIURL, ingressURL)

	// Load tool registry from ConfigMap
	registry := mcpadapter.NewRegistry()
	if err := registry.LoadFromDir(configDir); err != nil {
		slog.Error("Failed to load MCP tool config", "dir", configDir, "error", err)
		os.Exit(1)
	}

	// Create MCP handler
	handler := mcpadapter.NewHandler(registry, mc)
	handler.SyncTools()

	// Start ConfigMap watcher for hot-reload
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	pollInterval := parseDuration(getEnv("ASYA_MCP_POLL_INTERVAL", "10s"), 10*time.Second)
	go watcher.Watch(ctx, configDir, pollInterval, func(dir string) error {
		if err := registry.LoadFromDir(dir); err != nil {
			return err
		}
		handler.SyncTools()
		return nil
	})

	// Create HTTP server with MCP Streamable HTTP
	mux := http.NewServeMux()

	streamable := mcpserver.NewStreamableHTTPServer(handler.MCPServer())
	mux.Handle("/mcp", streamable)
	mux.Handle("/mcp/", streamable)

	sseServer := mcpserver.NewSSEServer(handler.MCPServer())
	mux.Handle("/mcp/sse", sseServer)

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintln(w, "OK")
	})

	srv := &http.Server{
		Addr:              ":" + port,
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	// Graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		slog.Info("MCP adapter listening", "port", port, "config", configDir)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("Server failed", "error", err)
			os.Exit(1)
		}
	}()

	sig := <-sigChan
	slog.Info("Shutting down", "signal", sig)

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	_ = srv.Shutdown(shutdownCtx)
}

func requireEnv(key string) string {
	val := os.Getenv(key)
	if val == "" {
		slog.Error("Required environment variable not set", "key", key)
		os.Exit(1)
	}
	return val
}

func getEnv(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}

func parseLogLevel(s string) slog.Level {
	switch s {
	case "DEBUG":
		return slog.LevelDebug
	case "WARN", "WARNING":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func parseDuration(s string, fallback time.Duration) time.Duration {
	d, err := time.ParseDuration(s)
	if err != nil {
		return fallback
	}
	return d
}
