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
	"github.com/deliveryhero/asya/asya-gateway/internal/oauth"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/stateproxy"
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

	// Wire state proxy reader for GetTask history/artifact hydration.
	// When ASYA_PERSISTENCE_MOUNT is set, the gateway reads persisted envelope state
	// from the same filesystem mount used by x-sink / x-sump / x-pause crew actors.
	// If unset, history and artifacts are omitted from GetTask responses (spec-compliant).
	var spReader stateproxy.Reader
	if persistMount := os.Getenv("ASYA_PERSISTENCE_MOUNT"); persistMount != "" {
		slog.Info("State proxy reader enabled", "mount", persistMount)
		spReader = stateproxy.NewFileReader(persistMount)
	}

	storeAdapter := a2a.NewStoreAdapter(taskStore, spReader)
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

	// MCP auth: Phase 2 (API key) + Phase 3 (OAuth 2.1)
	var mcpAuthenticators []a2a.Authenticator
	mcpAPIKey := os.Getenv("ASYA_MCP_API_KEY")
	if mcpAPIKey != "" {
		slog.Info("MCP API Key authentication enabled")
		mcpAuthenticators = append(mcpAuthenticators, &a2a.BearerTokenAuthenticator{Token: mcpAPIKey})
	}

	var oauthSrv *oauth.Server
	if os.Getenv("ASYA_MCP_OAUTH_ENABLED") == "true" {
		oauthIssuer := os.Getenv("ASYA_MCP_OAUTH_ISSUER")
		oauthSecret := os.Getenv("ASYA_MCP_OAUTH_SECRET")
		oauthTokenTTL := getEnvInt("ASYA_MCP_OAUTH_TOKEN_TTL", 3600)
		if oauthIssuer == "" || oauthSecret == "" {
			slog.Error("ASYA_MCP_OAUTH_ENABLED=true requires ASYA_MCP_OAUTH_ISSUER and ASYA_MCP_OAUTH_SECRET")
			os.Exit(1)
		}
		pgStore, ok := taskStore.(*taskstore.PgStore)
		if !ok {
			slog.Error("OAuth 2.1 requires PostgreSQL (ASYA_DATABASE_URL must be set)")
			os.Exit(1)
		}
		srv, oauthErr := oauth.NewServer(pgStore.Pool(), oauth.Config{
			Issuer:            oauthIssuer,
			Secret:            []byte(oauthSecret),
			TokenTTL:          time.Duration(oauthTokenTTL) * time.Second,
			RegistrationToken: os.Getenv("ASYA_MCP_OAUTH_REGISTRATION_TOKEN"),
		})
		if oauthErr != nil {
			slog.Error("Failed to create OAuth server", "error", oauthErr)
			os.Exit(1)
		}
		oauthSrv = srv
		mcpAuthenticators = append(mcpAuthenticators,
			a2a.NewOAuthBearerAuthenticator([]byte(oauthSecret), oauthIssuer, oauthIssuer))
		slog.Info("MCP OAuth 2.1 authentication enabled", "issuer", oauthIssuer)
	}

	mcpMiddleware := a2a.MCPAuthMiddleware(mcpAuthenticators...)

	// Setup routes based on ASYA_GATEWAY_MODE
	mux := http.NewServeMux()
	mode := os.Getenv("ASYA_GATEWAY_MODE")
	if err := buildRoutes(mux, mode, taskHandler, mcpServer, a2aRootHandler, cardProducer, registry, apiKey, mcpMiddleware, oauthSrv); err != nil {
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
	a2aHandler http.Handler, cardProducer *a2a.CardProducer, mcpMiddleware func(http.Handler) http.Handler) {
	if mcpServer != nil {
		mux.Handle("/mcp", mcpMiddleware(mcpserver.NewStreamableHTTPServer(mcpServer.GetMCPServer())))
		mux.Handle("/mcp/sse", mcpMiddleware(mcpserver.NewSSEServer(mcpServer.GetMCPServer())))
	}
	if taskHandler != nil {
		mux.Handle("/tools/call", mcpMiddleware(http.HandlerFunc(taskHandler.HandleToolCall)))
	}
	if a2aHandler != nil {
		mux.Handle("/a2a/", a2aHandler)
	}
	if cardProducer != nil {
		// Agent card is public — no auth middleware
		mux.Handle("/.well-known/agent.json", a2asrv.NewAgentCardHandler(cardProducer))
	}
}

func registerOAuthRoutes(mux *http.ServeMux, oauthSrv *oauth.Server) {
	if oauthSrv == nil {
		return
	}
	// OAuth 2.1 discovery and flow endpoints are all public (called before auth is established)
	mux.HandleFunc("/.well-known/oauth-protected-resource", oauthSrv.HandleProtectedResourceMetadata)
	mux.HandleFunc("/.well-known/oauth-authorization-server", oauthSrv.HandleServerMetadata)
	mux.HandleFunc("/oauth/register", oauthSrv.HandleRegister)
	mux.HandleFunc("/oauth/authorize", oauthSrv.HandleAuthorize)
	mux.HandleFunc("/oauth/token", oauthSrv.HandleToken)
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
	registry *toolstore.Registry, apiKey string,
	mcpMiddleware func(http.Handler) http.Handler, oauthSrv *oauth.Server) error {
	if mcpMiddleware == nil {
		mcpMiddleware = func(h http.Handler) http.Handler { return h }
	}
	switch mode {
	case "api":
		registerAPIRoutes(mux, taskHandler, mcpServer, a2aHandler, cardProducer, mcpMiddleware)
		registerOAuthRoutes(mux, oauthSrv)
	case "mesh":
		registerMeshRoutes(mux, taskHandler, registry, apiKey)
	case "testing":
		registerAPIRoutes(mux, taskHandler, mcpServer, a2aHandler, cardProducer, mcpMiddleware)
		registerOAuthRoutes(mux, oauthSrv)
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
