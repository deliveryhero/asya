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

	"github.com/a2aproject/a2a-go/a2asrv"
	mcpserver "github.com/mark3labs/mcp-go/server"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2a"
	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/mcp"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/internal/toolstore"
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

	slog.Info("Starting Asya Gateway", "port", port, "logLevel", logLevel)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Initialize task store (PostgreSQL or in-memory)
	var taskStore taskstore.TaskStore
	if dbURL != "" {
		slog.Info("Using PostgreSQL task store")
		pgStore, err := taskstore.NewPgStore(ctx, dbURL)
		if err != nil {
			slog.Error("Failed to create PostgreSQL store", "error", err)
			os.Exit(1)
		}
		defer pgStore.Close()
		taskStore = pgStore
	} else {
		slog.Info("Using in-memory task store (not recommended for production)")
		taskStore = taskstore.NewStore()
	}

	// Initialize queue client (Pub/Sub, SQS, or RabbitMQ)
	queueClient, err := initQueueClient(ctx)
	if err != nil {
		slog.Error("Failed to create queue client", "error", err)
		os.Exit(1)
	}
	defer func() { _ = queueClient.Close() }()

	// End queue consumers removed - use standalone end actors instead
	// Deploy x-sink and x-sump actors to handle end queue processing
	slog.Info("Gateway uses standalone end actors for final status reporting",
		"info", "Deploy x-sink and x-sump actors to handle end queues")

	// Initialize tool registry
	var registry *toolstore.Registry
	if pgStore, ok := taskStore.(*taskstore.PgStore); ok {
		var err error
		registry, err = toolstore.NewRegistry(ctx, pgStore.Pool())
		if err != nil {
			slog.Error("Failed to create DB-backed tool registry", "error", err)
			os.Exit(1)
		}
		slog.Info("Using DB-backed tool registry")
	} else {
		registry = toolstore.NewInMemoryRegistry()
		slog.Info("Using in-memory tool registry")
	}

	// Load tool configuration from YAML (if configured)
	var cfg *config.Config
	configPath := getEnv("ASYA_CONFIG_PATH", "")
	if configPath != "" {
		var err error
		cfg, err = config.LoadConfig(configPath)
		if err != nil {
			slog.Error("Failed to load config", "path", configPath, "error", err)
			os.Exit(1)
		}
		slog.Info("Loaded tool configuration", "path", configPath, "tools", len(cfg.Tools))
	}

	// Create MCP server
	mcpServer := mcp.NewServer(taskStore, queueClient, cfg)

	// Create task handler for custom endpoints
	taskHandler := mcp.NewHandler(taskStore)
	taskHandler.SetServer(mcpServer) // For REST tool calls

	// Setup routes
	mux := http.NewServeMux()

	// MCP streamable HTTP endpoint (recommended, per MCP spec)
	mux.Handle("/mcp", mcpserver.NewStreamableHTTPServer(mcpServer.GetMCPServer()))

	// MCP SSE endpoint (deprecated but kept for backward compatibility with older clients)
	mux.Handle("/mcp/sse", mcpserver.NewSSEServer(mcpServer.GetMCPServer()))

	// REST endpoint for tool calls (simpler alternative to SSE-based MCP)
	mux.HandleFunc("/tools/call", taskHandler.HandleToolCall)

	// Tool registration endpoint
	exposeHandler := toolstore.NewHandler(registry)
	mux.HandleFunc("/mesh/expose", exposeHandler.HandleExpose)

	// Mesh status endpoints (custom functionality)
	mux.HandleFunc("/mesh/", func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/stream") {
			taskHandler.HandleMeshStream(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/active") {
			taskHandler.HandleMeshActive(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/progress") {
			taskHandler.HandleMeshProgress(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/final") {
			taskHandler.HandleMeshFinal(w, r)
		} else if strings.HasSuffix(r.URL.Path, "/fly") {
			taskHandler.HandleMeshFly(w, r)
		} else {
			taskHandler.HandleMeshStatus(w, r)
		}
	})

	// Mesh creation endpoint (for fanout child mesh from sidecar)
	mux.HandleFunc("/mesh", taskHandler.HandleMeshCreate)

	// Health check
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintln(w, "OK")
	})

	// A2A setup using a2a-go library
	namespace := getEnv("ASYA_NAMESPACE", "default")
	executor := a2a.NewExecutor(queueClient, taskStore, registry, namespace)
	storeAdapter := a2a.NewStoreAdapter(taskStore)
	cardProducer := a2a.NewCardProducer(registry)

	a2aHandler := a2asrv.NewHandler(executor,
		a2asrv.WithTaskStore(storeAdapter),
	)
	a2aHTTPHandler := a2asrv.NewJSONRPCHandler(a2aHandler,
		a2asrv.WithKeepAlive(15*time.Second),
	)

	// Mount A2A endpoints (with optional API key auth)
	apiKey := os.Getenv("ASYA_A2A_API_KEY")
	var a2aRootHandler http.Handler = a2aHTTPHandler
	if apiKey != "" {
		slog.Info("A2A API Key authentication enabled")
		a2aRootHandler = a2a.APIKeyMiddleware(apiKey)(a2aHTTPHandler)
	}
	mux.Handle("/a2a/", a2aRootHandler)

	// Agent card is public — middleware bypass handles unauthenticated access
	mux.Handle("/.well-known/agent.json", a2asrv.NewAgentCardHandler(cardProducer))

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
		slog.Info("Mesh status: GET /mesh/{id}")
		slog.Info("Mesh stream: GET /mesh/{id}/stream (SSE)")
		slog.Info("Mesh active check: GET /mesh/{id}/active (for actors)")
		slog.Info("Mesh progress: POST /mesh/{id}/progress (from sidecar)")
		slog.Info("Mesh final status: POST /mesh/{id}/final (for end actors)")
		slog.Info("A2A endpoint (JSON-RPC): POST /a2a/ (via a2a-go)")
		slog.Info("A2A Agent Card: GET /.well-known/agent.json")
		slog.Info("Tool registration: POST/GET /mesh/expose")

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

func initQueueClient(ctx context.Context) (queue.Client, error) {
	pubsubProjectID := getEnv("ASYA_PUBSUB_PROJECT_ID", "")
	sqsEndpoint := getEnv("ASYA_SQS_ENDPOINT", "")
	rabbitmqURL := getEnv("ASYA_RABBITMQ_URL", "")

	if pubsubProjectID != "" {
		pubsubEndpoint := getEnv("ASYA_PUBSUB_ENDPOINT", "")
		namespace := getEnv("ASYA_NAMESPACE", "default")
		slog.Info("Using Pub/Sub transport", "projectID", pubsubProjectID, "namespace", namespace, "endpoint", pubsubEndpoint)

		return queue.NewPubSubClient(ctx, queue.PubSubConfig{
			ProjectID: pubsubProjectID,
			Endpoint:  pubsubEndpoint,
			Namespace: namespace,
		})
	}

	if sqsEndpoint != "" || rabbitmqURL == "" {
		sqsRegion := getEnv("ASYA_SQS_REGION", "us-east-1")
		namespace := getEnv("ASYA_NAMESPACE", "default")
		slog.Info("Using SQS transport", "region", sqsRegion, "namespace", namespace, "endpoint", sqsEndpoint)

		visibilityTimeout := getEnvInt("ASYA_SQS_VISIBILITY_TIMEOUT", 300)
		waitTimeSeconds := getEnvInt("ASYA_SQS_WAIT_TIME_SECONDS", 20)

		return queue.NewSQSClient(ctx, queue.SQSConfig{
			Region:            sqsRegion,
			Endpoint:          sqsEndpoint,
			Namespace:         namespace,
			VisibilityTimeout: int32(visibilityTimeout), // #nosec G115 - config values bounded by reasonable defaults
			WaitTimeSeconds:   int32(waitTimeSeconds),   // #nosec G115 - config values bounded by reasonable defaults
		})
	}

	rabbitmqExchange := getEnv("ASYA_RABBITMQ_EXCHANGE", "asya")
	rabbitmqPoolSize := getEnvInt("ASYA_RABBITMQ_POOL_SIZE", 20)
	slog.Info("Using RabbitMQ transport", "url", rabbitmqURL, "exchange", rabbitmqExchange, "poolSize", rabbitmqPoolSize)

	return queue.NewRabbitMQClientPooled(rabbitmqURL, rabbitmqExchange, rabbitmqPoolSize)
}
