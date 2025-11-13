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
	dbURL := getEnv("ASYA_DATABASE_URL", "")
	configPath := getEnv("ASYA_CONFIG_PATH", "")

	slog.Info("Starting Asya Gateway", "port", port, "logLevel", logLevel)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Initialize envelope store (PostgreSQL or in-memory)
	var jobStore jobs.JobStore
	if dbURL != "" {
		slog.Info("Using PostgreSQL envelope store")
		pgStore, err := jobs.NewPgStore(ctx, dbURL)
		if err != nil {
			slog.Error("Failed to create PostgreSQL store", "error", err)
			os.Exit(1)
		}
		defer pgStore.Close()
		jobStore = pgStore
	} else {
		slog.Info("Using in-memory envelope store (not recommended for production)")
		jobStore = jobs.NewStore()
	}

	// Initialize queue client (RabbitMQ or SQS)
	var queueClient queue.Client
	var err error

	// Check which transport is configured (SQS takes precedence if both are set)
	sqsEndpoint := getEnv("ASYA_SQS_ENDPOINT", "")
	rabbitmqURL := getEnv("ASYA_RABBITMQ_URL", "")

	if sqsEndpoint != "" || rabbitmqURL == "" {
		// Use SQS transport
		sqsRegion := getEnv("ASYA_SQS_REGION", "us-east-1")
		slog.Info("Using SQS transport", "region", sqsRegion, "endpoint", sqsEndpoint)

		visibilityTimeout := getEnvInt("ASYA_SQS_VISIBILITY_TIMEOUT", 300)
		waitTimeSeconds := getEnvInt("ASYA_SQS_WAIT_TIME_SECONDS", 20)

		queueClient, err = queue.NewSQSClient(ctx, queue.SQSConfig{
			Region:            sqsRegion,
			Endpoint:          sqsEndpoint,
			VisibilityTimeout: int32(visibilityTimeout), // #nosec G115 - config values bounded by reasonable defaults
			WaitTimeSeconds:   int32(waitTimeSeconds),   // #nosec G115 - config values bounded by reasonable defaults
		})
		if err != nil {
			slog.Error("Failed to create SQS client", "error", err)
			os.Exit(1)
		}
	} else {
		// Use RabbitMQ transport
		rabbitmqExchange := getEnv("ASYA_RABBITMQ_EXCHANGE", "asya")
		rabbitmqPoolSize := getEnvInt("ASYA_RABBITMQ_POOL_SIZE", 20)
		slog.Info("Using RabbitMQ transport", "url", rabbitmqURL, "exchange", rabbitmqExchange, "poolSize", rabbitmqPoolSize)

		queueClient, err = queue.NewRabbitMQClientPooled(rabbitmqURL, rabbitmqExchange, rabbitmqPoolSize)
		if err != nil {
			slog.Error("Failed to create RabbitMQ client", "error", err)
			os.Exit(1)
		}
	}
	defer func() { _ = queueClient.Close() }()

	// End queue consumers removed - use standalone end actors instead
	// Deploy happy-end and error-end actors to handle end queue processing
	slog.Info("Gateway uses standalone end actors for final status reporting",
		"info", "Deploy happy-end and error-end actors to handle end queues")

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

	// Create envelope handler for custom endpoints
	envelopeHandler := mcp.NewHandler(jobStore)
	envelopeHandler.SetServer(mcpServer) // For REST tool calls

	// Setup routes
	mux := http.NewServeMux()

	// MCP streamable HTTP endpoint (recommended, per MCP spec)
	mux.Handle("/mcp", mcpserver.NewStreamableHTTPServer(mcpServer.GetMCPServer()))

	// MCP SSE endpoint (deprecated but kept for backward compatibility with older clients)
	mux.Handle("/mcp/sse", mcpserver.NewSSEServer(mcpServer.GetMCPServer()))

	// REST endpoint for tool calls (simpler alternative to SSE-based MCP)
	mux.HandleFunc("/tools/call", envelopeHandler.HandleToolCall)

	// Envelope status endpoints (custom functionality)
	mux.HandleFunc("/envelopes/", func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/stream") {
			envelopeHandler.HandleEnvelopeStream(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/active") {
			envelopeHandler.HandleEnvelopeActive(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/progress") {
			envelopeHandler.HandleEnvelopeProgress(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/final") {
			envelopeHandler.HandleEnvelopeFinal(w, r)
		} else {
			envelopeHandler.HandleEnvelopeStatus(w, r)
		}
	})

	// Envelope creation endpoint (for fanout child envelopes from sidecar)
	mux.HandleFunc("/envelopes", envelopeHandler.HandleEnvelopeCreate)

	// Health check
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintln(w, "OK")
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
		slog.Info("MCP endpoint (streamable HTTP): POST /mcp (recommended)")
		slog.Info("MCP endpoint (SSE): /mcp/sse (deprecated, for backward compatibility)")
		slog.Info("REST tool endpoint: POST /tools/call (simple JSON API)")
		slog.Info("Envelope status: GET /envelopes/{id}")
		slog.Info("Envelope stream: GET /envelopes/{id}/stream (SSE)")
		slog.Info("Envelope active check: GET /envelopes/{id}/active (for actors)")
		slog.Info("Envelope progress: POST /envelopes/{id}/progress (from sidecar)")
		slog.Info("Envelope final status: POST /envelopes/{id}/final (for end actors)")

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
