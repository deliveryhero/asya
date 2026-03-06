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

	// Initialize tool registry from PostgreSQL
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

	// Create MCP server (reads tools from DB-backed registry)
	mcpServer := mcp.NewServer(taskStore, queueClient, registry)

	// Create task handler for custom endpoints
	taskHandler := mcp.NewHandler(taskStore)
	taskHandler.SetServer(mcpServer) // For REST tool calls

	// API key for endpoint auth (shared by A2A and /mesh/expose)
	apiKey := os.Getenv("ASYA_A2A_API_KEY")

	// A2A setup using a2a-go library
	namespace := getEnv("ASYA_NAMESPACE", "default")
	executor := a2a.NewExecutor(queueClient, taskStore, registry, namespace)
	storeAdapter := a2a.NewStoreAdapter(taskStore)
	cardProducer := a2a.NewCardProducer(registry)

	extendedCardProducer := a2a.NewExtendedCardProducer(registry)
	a2aHandler := a2asrv.NewHandler(executor,
		a2asrv.WithTaskStore(storeAdapter),
		a2asrv.WithExtendedAgentCardProducer(extendedCardProducer),
	)
	a2aHTTPHandler := a2asrv.NewJSONRPCHandler(a2aHandler,
		a2asrv.WithKeepAlive(15*time.Second),
	)

	// Build authenticator chain (API Key + JWT)
	var authenticators []a2a.Authenticator
	if apiKey != "" {
		slog.Info("A2A API Key authentication enabled")
		authenticators = append(authenticators, &a2a.APIKeyAuthenticator{Key: apiKey})
	}

	jwksURL := os.Getenv("ASYA_A2A_JWT_JWKS_URL")
	jwtIssuer := os.Getenv("ASYA_A2A_JWT_ISSUER")
	jwtAudience := os.Getenv("ASYA_A2A_JWT_AUDIENCE")
	if jwksURL != "" && jwtIssuer != "" && jwtAudience != "" {
		jwtAuth, err := a2a.NewJWTAuthenticator(jwksURL, jwtIssuer, jwtAudience)
		if err != nil {
			slog.Error("Failed to create JWT authenticator", "error", err)
			os.Exit(1)
		}
		defer jwtAuth.Close()
		slog.Info("A2A JWT authentication enabled", "jwks_url", jwksURL, "issuer", jwtIssuer)
		authenticators = append(authenticators, jwtAuth)
	}

	var a2aRootHandler http.Handler = a2aHTTPHandler
	if len(authenticators) > 0 {
		a2aRootHandler = a2a.A2AAuthMiddleware(authenticators...)(a2aHTTPHandler)
	}

	// Setup routes based on ASYA_GATEWAY_MODE
	mux := http.NewServeMux()
	mode := os.Getenv("ASYA_GATEWAY_MODE")
	if err := buildRoutes(mux, mode, taskHandler, mcpServer, a2aRootHandler, cardProducer, registry, apiKey); err != nil {
		slog.Error("Invalid gateway mode", "error", err)
		os.Exit(1)
	}
	slog.Info("Gateway mode", "mode", mode)

	// Setup graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	server := &http.Server{
		Addr:    fmt.Sprintf(":%s", port),
		Handler: mux,
	}

	// Start server in goroutine
	go func() {
		slog.Info("Server listening", "addr", server.Addr, "mode", mode)
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

func registerAPIRoutes(mux *http.ServeMux, taskHandler *mcp.Handler, mcpServer *mcp.Server,
	a2aHandler http.Handler, cardProducer *a2a.CardProducer) {
	if mcpServer != nil {
		mux.Handle("/mcp", mcpserver.NewStreamableHTTPServer(mcpServer.GetMCPServer()))
		mux.Handle("/mcp/sse", mcpserver.NewSSEServer(mcpServer.GetMCPServer()))
	}
	if taskHandler != nil {
		mux.HandleFunc("/tools/call", taskHandler.HandleToolCall)
	}
	if a2aHandler != nil {
		mux.Handle("/a2a/", a2aHandler)
	}
	if cardProducer != nil {
		// Agent card is public — no auth middleware
		mux.Handle("/.well-known/agent.json", a2asrv.NewAgentCardHandler(cardProducer))
	}
}

func registerMeshRoutes(mux *http.ServeMux, taskHandler *mcp.Handler,
	registry *toolstore.Registry, apiKey string) {
	if registry != nil {
		exposeHandler := toolstore.NewHandler(registry)
		var exposeHTTPHandler http.Handler = http.HandlerFunc(exposeHandler.HandleExpose)
		if apiKey != "" {
			exposeHTTPHandler = a2a.APIKeyMiddleware(apiKey)(exposeHTTPHandler)
		}
		mux.Handle("/mesh/expose", exposeHTTPHandler)
	}
	if taskHandler != nil {
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
		mux.HandleFunc("/mesh", taskHandler.HandleMeshCreate)
	}
}

func buildRoutes(mux *http.ServeMux, mode string, taskHandler *mcp.Handler,
	mcpServer *mcp.Server, a2aHandler http.Handler, cardProducer *a2a.CardProducer,
	registry *toolstore.Registry, apiKey string) error {
	switch mode {
	case "api":
		registerAPIRoutes(mux, taskHandler, mcpServer, a2aHandler, cardProducer)
	case "mesh":
		registerMeshRoutes(mux, taskHandler, registry, apiKey)
	case "testing":
		registerAPIRoutes(mux, taskHandler, mcpServer, a2aHandler, cardProducer)
		registerMeshRoutes(mux, taskHandler, registry, apiKey)
	default:
		return fmt.Errorf("ASYA_GATEWAY_MODE must be set to api|mesh|testing, got: %q", mode)
	}
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintln(w, "OK")
	})
	return nil
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
