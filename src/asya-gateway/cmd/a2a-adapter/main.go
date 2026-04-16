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

	"github.com/a2aproject/a2a-go/a2asrv"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/internal/watcher"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: parseLogLevel(os.Getenv("ASYA_LOG_LEVEL")),
	})))

	meshAPIURL := requireEnv("MESH_API_URL")
	ingressURL := requireEnv("MESH_INGRESS_URL")
	configDir := requireEnv("ASYA_A2A_CONFIG_DIR")
	port := getEnv("ASYA_A2A_PORT", "8083")

	// Initialize mesh client
	mc := meshclient.New(meshAPIURL, ingressURL)

	// Load agent registry from ConfigMap
	registry := a2aadapter.NewAgentRegistry()
	if err := registry.LoadFromDir(configDir); err != nil {
		slog.Error("Failed to load A2A agent config", "dir", configDir, "error", err)
		os.Exit(1)
	}

	// Create A2A executor and store adapter
	executor := a2aadapter.NewExecutor(registry, mc)
	storeAdapter := a2aadapter.NewStoreAdapter(mc)
	cardProducer := a2aadapter.NewCardProducer(registry)

	// Create A2A handler using a2a-go library
	a2aHandler := a2asrv.NewHandler(executor,
		a2asrv.WithTaskStore(storeAdapter),
	)
	a2aHTTPHandler := a2asrv.NewJSONRPCHandler(a2aHandler,
		a2asrv.WithKeepAlive(15*time.Second),
	)

	// Start ConfigMap watcher for hot-reload
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	pollInterval := parseDuration(getEnv("ASYA_A2A_POLL_INTERVAL", "10s"), 10*time.Second)
	go watcher.Watch(ctx, configDir, pollInterval, func(dir string) error {
		return registry.LoadFromDir(dir)
	})

	// Create HTTP server
	mux := http.NewServeMux()
	mux.Handle("/a2a/", a2aHTTPHandler)
	mux.Handle("/.well-known/agent.json", a2asrv.NewAgentCardHandler(cardProducer))
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintln(w, "OK")
	})

	srv := &http.Server{
		Addr:    ":" + port,
		Handler: mux,
	}

	// Graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		slog.Info("A2A adapter listening", "port", port, "config", configDir)
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
