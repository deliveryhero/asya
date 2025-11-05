package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/router"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
)

func main() {
	// Set up structured logging with level control
	logLevel := os.Getenv("ASYA_LOG_LEVEL")
	if logLevel == "" {
		logLevel = "INFO"
	}
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

	slog.Info("Starting Asya Actor Sidecar", "logLevel", logLevel)

	// Load configuration
	cfg, err := config.LoadFromEnv()
	if err != nil {
		slog.Error("Failed to load configuration", "error", err)
		os.Exit(1)
	}

	slog.Info("Configuration loaded", "queue", cfg.QueueName)

	// Create RabbitMQ transport
	tp, err := transport.NewRabbitMQTransport(transport.RabbitMQConfig{
		URL:           cfg.RabbitMQURL,
		Exchange:      cfg.RabbitMQExchange,
		PrefetchCount: cfg.RabbitMQPrefetch,
	})
	if err != nil {
		slog.Error("Failed to create RabbitMQ transport", "error", err)
		os.Exit(1)
	}
	slog.Info("Using RabbitMQ transport")
	defer tp.Close()

	// Create runtime client
	runtimeClient := runtime.NewClient(cfg.SocketPath, cfg.Timeout)
	slog.Info("Runtime client configured", "socket", cfg.SocketPath, "timeout", cfg.Timeout)

	// Initialize metrics
	var m *metrics.Metrics
	if cfg.MetricsEnabled {
		slog.Info("Metrics enabled", "addr", cfg.MetricsAddr, "namespace", cfg.MetricsNamespace)
		m = metrics.NewMetrics(cfg.MetricsNamespace, cfg.CustomMetrics)
		slog.Info("Initialized custom metrics", "count", len(cfg.CustomMetrics))
	} else {
		slog.Info("Metrics disabled")
	}

	// Create router
	r := router.NewRouter(cfg, tp, runtimeClient, m)

	// Setup graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		sig := <-sigChan
		slog.Info("Received signal, initiating shutdown", "signal", sig)
		cancel()
	}()

	// Start metrics server if enabled
	if cfg.MetricsEnabled && m != nil {
		go func() {
			if err := m.StartMetricsServer(ctx, cfg.MetricsAddr); err != nil {
				slog.Error("Metrics server error", "error", err)
			}
		}()
		slog.Info("Metrics server started", "addr", cfg.MetricsAddr)
	}

	// Run router
	slog.Info("Starting message processing")
	if err := r.Run(ctx); err != nil && err != context.Canceled {
		slog.Error("Router error", "error", err)
		os.Exit(1)
	}

	slog.Info("Sidecar shutdown complete")
}
