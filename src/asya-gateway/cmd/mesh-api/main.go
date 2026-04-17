package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/mesh"
	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/store"
	"github.com/deliveryhero/asya/asya-gateway/internal/tracing"
)

func main() {
	// Set up structured logging
	logLevel := os.Getenv("ASYA_LOG_LEVEL")
	var level slog.Level
	switch strings.ToUpper(logLevel) {
	case "DEBUG":
		level = slog.LevelDebug
	case "WARN", "WARNING":
		level = slog.LevelWarn
	case "ERROR":
		level = slog.LevelError
	default:
		level = slog.LevelInfo
	}
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: level}))
	slog.SetDefault(logger)

	// Required env vars (no defaults per project policy):
	//   ASYA_MESH_EXTERNAL_PORT  - external API port (e.g. 8080)
	//   ASYA_MESH_INTERNAL_PORT  - internal sidecar port (e.g. 8081)
	//   ASYA_STATEPROXY_SOCKET   - Unix socket path to pg-kv connector
	//   ASYA_INTERNAL_URL        - URL sidecars use for callbacks
	//                              (stamped as x-asya-gateway-url)
	extPort := os.Getenv("ASYA_MESH_EXTERNAL_PORT")
	intPort := os.Getenv("ASYA_MESH_INTERNAL_PORT")
	socketPath := os.Getenv("ASYA_STATEPROXY_SOCKET")
	gatewayURL := os.Getenv("ASYA_INTERNAL_URL")

	// Fail fast on missing config
	for _, kv := range []struct{ k, v string }{
		{"ASYA_MESH_EXTERNAL_PORT", extPort},
		{"ASYA_MESH_INTERNAL_PORT", intPort},
		{"ASYA_STATEPROXY_SOCKET", socketPath},
		{"ASYA_INTERNAL_URL", gatewayURL},
	} {
		if kv.v == "" {
			slog.Error("Required env var missing", "var", kv.k)
			os.Exit(1)
		}
	}

	ctx, cancel := signal.NotifyContext(context.Background(),
		syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	// OTEL tracing (optional)
	namespace := os.Getenv("ASYA_NAMESPACE")
	shutdown, _ := tracing.Init(
		os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
		"asya-mesh-api", namespace)
	defer func() {
		shutCtx, c := context.WithTimeout(context.Background(), 5*time.Second)
		defer c()
		_ = shutdown(shutCtx)
	}()

	// MessageStore over state-proxy HTTP client
	msgStore := store.NewStateProxyStore(socketPath)

	// Queue client (reuse existing queue initialization pattern)
	queueClient, err := initQueueClient(ctx)
	if err != nil {
		slog.Error("Failed to create queue client", "error", err)
		os.Exit(1)
	}
	defer func() { _ = queueClient.Close() }()

	sender := mesh.NewQueueClientSender(queueClient)
	handler := mesh.NewHandler(msgStore, sender, gatewayURL)

	// External server (port 8080)
	extMux := http.NewServeMux()
	handler.RegisterExternal(extMux)
	extMux.HandleFunc("/health", healthHandler)

	// Internal server (port 8081)
	intMux := http.NewServeMux()
	handler.RegisterInternal(intMux)
	intMux.HandleFunc("/health", healthHandler)

	extServer := &http.Server{
		Addr:        ":" + extPort,
		Handler:     extMux,
		ReadTimeout: 30 * time.Second,
		IdleTimeout: 120 * time.Second,
	}
	intServer := &http.Server{
		Addr:         ":" + intPort,
		Handler:      intMux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 60 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		slog.Info("External API listening", "port", extPort)
		if err := extServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("External server failed", "error", err)
		}
	}()
	go func() {
		slog.Info("Internal API listening", "port", intPort)
		if err := intServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("Internal server failed", "error", err)
		}
	}()

	<-ctx.Done()
	slog.Info("Shutting down mesh-api")
	shutCtx, shutCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutCancel()
	_ = extServer.Shutdown(shutCtx)
	_ = intServer.Shutdown(shutCtx)
	slog.Info("Mesh-API shutdown complete")
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = fmt.Fprintln(w, "OK")
}

// requireEnv returns the value of the environment variable or exits with an error.
func requireEnv(key string) string {
	value := os.Getenv(key)
	if value == "" {
		slog.Error("Required env var missing", "var", key)
		os.Exit(1)
	}
	return value
}

func initQueueClient(ctx context.Context) (queue.Client, error) {
	transport := os.Getenv("ASYA_QUEUE_TRANSPORT")
	if transport == "" {
		slog.Error("Required env var missing", "var", "ASYA_QUEUE_TRANSPORT")
		os.Exit(1)
	}

	switch transport {
	case "pubsub":
		projectID := requireEnv("ASYA_PUBSUB_PROJECT_ID")
		namespace := requireEnv("ASYA_NAMESPACE")
		endpoint := os.Getenv("ASYA_PUBSUB_ENDPOINT")
		slog.Info("Using Pub/Sub transport", "projectID", projectID, "namespace", namespace, "endpoint", endpoint)

		return queue.NewPubSubClient(ctx, queue.PubSubConfig{
			ProjectID: projectID,
			Endpoint:  endpoint,
			Namespace: namespace,
		})

	case "sqs":
		region := requireEnv("ASYA_SQS_REGION")
		namespace := requireEnv("ASYA_NAMESPACE")
		endpoint := os.Getenv("ASYA_SQS_ENDPOINT")
		slog.Info("Using SQS transport", "region", region, "namespace", namespace, "endpoint", endpoint)

		return queue.NewSQSClient(ctx, queue.SQSConfig{
			Region:    region,
			Endpoint:  endpoint,
			Namespace: namespace,
		})

	case "rabbitmq":
		rabbitmqURL := requireEnv("ASYA_RABBITMQ_URL")
		rabbitmqExchange := requireEnv("ASYA_RABBITMQ_EXCHANGE")
		slog.Info("Using RabbitMQ transport", "url", rabbitmqURL, "exchange", rabbitmqExchange)

		return queue.NewRabbitMQClientPooled(rabbitmqURL, rabbitmqExchange, 20)

	default:
		return nil, fmt.Errorf("unknown queue transport: %q (expected pubsub, sqs, or rabbitmq)", transport)
	}
}
