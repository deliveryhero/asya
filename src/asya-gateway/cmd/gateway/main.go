package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	mcpserver "github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/internal/mcp"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
)

func main() {
	// Set up structured logging with level control
	logLevel := getEnv("ASYA_LOG_LEVEL", "INFO")
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

	// Load configuration from environment
	port := getEnv("ASYA_GATEWAY_PORT", "8080")
	rabbitmqURL := getEnv("ASYA_RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
	rabbitmqExchange := getEnv("ASYA_RABBITMQ_EXCHANGE", "asya")
	rabbitmqPoolSize := getEnvInt("ASYA_RABBITMQ_POOL_SIZE", 20) // Default 20 channels
	dbURL := getEnv("ASYA_DATABASE_URL", "")
	configPath := getEnv("ASYA_CONFIG_PATH", "")

	slog.Info("Starting Asya Gateway", "port", port, "logLevel", logLevel)
	slog.Info("RabbitMQ configuration", "url", rabbitmqURL, "exchange", rabbitmqExchange, "poolSize", rabbitmqPoolSize)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Initialize job store (PostgreSQL or in-memory)
	var jobStore jobs.JobStore
	if dbURL != "" {
		slog.Info("Using PostgreSQL job store")
		pgStore, err := jobs.NewPgStore(ctx, dbURL)
		if err != nil {
			slog.Error("Failed to create PostgreSQL store", "error", err)
			os.Exit(1)
		}
		defer pgStore.Close()
		jobStore = pgStore
	} else {
		slog.Info("Using in-memory job store (not recommended for production)")
		jobStore = jobs.NewStore()
	}

	// Create RabbitMQ client with channel pooling for high concurrency
	queueClient, err := queue.NewRabbitMQClientPooled(rabbitmqURL, rabbitmqExchange, rabbitmqPoolSize)
	if err != nil {
		slog.Error("Failed to create RabbitMQ client", "error", err)
		os.Exit(1)
	}
	defer queueClient.Close()

	// Terminal queue consumers removed - use standalone terminal actors instead
	// Deploy happy-end and error-end actors to handle terminal queue processing
	slog.Info("Gateway uses standalone terminal actors for final status reporting",
		"info", "Deploy happy-end and error-end actors to handle terminal queues")

	// Load tool configuration if provided
	var toolConfig *config.Config
	if configPath != "" {
		slog.Info("Loading tool configuration", "path", configPath)
		cfg, err := config.LoadConfig(configPath)
		if err != nil {
			slog.Error("Failed to load config", "error", err)
			os.Exit(1)
		}
		toolConfig = cfg
		slog.Info("Loaded tools from configuration", "count", len(cfg.Tools))
	} else {
		slog.Info("No ASYA_CONFIG_PATH provided, using default tools")
	}

	// Create MCP server with mark3labs/mcp-go (minimal boilerplate!)
	mcpServer := mcp.NewServer(jobStore, queueClient, toolConfig)

	// Create job handler for custom endpoints
	jobHandler := mcp.NewHandler(jobStore)
	jobHandler.SetServer(mcpServer) // For REST tool calls

	// Setup routes
	mux := http.NewServeMux()

	// MCP endpoint using mark3labs/mcp-go built-in HTTP handler
	// This replaces all the manual JSON-RPC handling!
	mux.Handle("/mcp", mcpserver.NewStreamableHTTPServer(mcpServer.GetMCPServer()))

	// REST endpoint for tool calls (simpler alternative to SSE-based MCP)
	mux.HandleFunc("/tools/call", jobHandler.HandleToolCall)

	// Job status endpoints (custom functionality)
	mux.HandleFunc("/jobs/", func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/stream") {
			jobHandler.HandleJobStream(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/active") {
			jobHandler.HandleJobActive(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/heartbeat") {
			jobHandler.HandleJobHeartbeat(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/progress") {
			jobHandler.HandleJobProgress(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/final") {
			jobHandler.HandleJobFinal(w, r)
		} else {
			jobHandler.HandleJobStatus(w, r)
		}
	})

	// Health check
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprintln(w, "OK")
	})

	// Setup graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	server := &http.Server{
		Addr:    fmt.Sprintf(":%s", port),
		Handler: mux,
	}

	// Start server in goroutine
	go func() {
		slog.Info("Server listening", "addr", server.Addr)
		slog.Info("MCP endpoint: POST /mcp (using mark3labs/mcp-go)")
		slog.Info("REST tool endpoint: POST /tools/call (simple JSON API)")
		slog.Info("Job status: GET /jobs/{id}")
		slog.Info("Job stream: GET /jobs/{id}/stream (SSE)")
		slog.Info("Job active check: GET /jobs/{id}/active (for actors)")
		slog.Info("Job heartbeat: POST /jobs/{id}/heartbeat (for actors)")
		slog.Info("Job progress: POST /jobs/{id}/progress (for actors)")
		slog.Info("Job final status: POST /jobs/{id}/final (for terminal actors)")

		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("Server failed", "error", err)
		}
	}()

	// Wait for shutdown signal
	sig := <-sigChan
	slog.Info("Received signal, initiating shutdown", "signal", sig)

	// Graceful shutdown with timeout
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	if err := server.Shutdown(shutdownCtx); err != nil {
		slog.Error("Server shutdown error", "error", err)
	}

	slog.Info("Gateway shutdown complete")
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvInt(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil {
			return parsed
		}
		slog.Warn("Invalid integer value, using default", "key", key, "value", value, "default", defaultValue)
	}
	return defaultValue
}
