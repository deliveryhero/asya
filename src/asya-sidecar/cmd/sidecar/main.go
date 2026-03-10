package main

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/metrics"
	"github.com/deliveryhero/asya/asya-sidecar/internal/router"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
)

// verifySocketConnection attempts to connect to the Unix socket to verify it's accessible
func verifySocketConnection(socketPath string) error {
	slog.Debug("Verifying socket connection", "socket", socketPath)

	conn, err := os.Stat(socketPath)
	if err != nil {
		return fmt.Errorf("socket file does not exist or is not accessible: %w", err)
	}

	if conn.Mode()&os.ModeSocket == 0 {
		return fmt.Errorf("path exists but is not a socket: %s (mode: %s)", socketPath, conn.Mode())
	}

	testCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	var dialer net.Dialer
	testConn, err := dialer.DialContext(testCtx, "unix", socketPath)
	if err != nil {
		return fmt.Errorf("socket exists but connection failed - runtime may not be listening or socket is in different filesystem namespace: %w", err)
	}
	_ = testConn.Close()

	slog.Debug("Socket connection verified successfully", "socket", socketPath)
	return nil
}

// waitForGateway polls the gateway health endpoint until it responds or maxWait elapses.
// Each attempt uses a 5-second connect timeout. On failure the loop sleeps 5 seconds
// before the next attempt, respecting ctx cancellation. Returns nil once the gateway
// is reachable or when ctx is canceled (graceful shutdown); returns an error only
// when maxWait is exhausted.
func waitForGateway(ctx context.Context, r *router.Router, maxWait time.Duration) error {
	slog.Info("Waiting for gateway to become ready", "maxWait", maxWait)
	start := time.Now()
	pollInterval := 5 * time.Second

	for {
		attemptCtx, attemptCancel := context.WithTimeout(ctx, 5*time.Second)
		err := r.CheckGatewayHealth(attemptCtx)
		attemptCancel()

		if err == nil {
			elapsed := time.Since(start)
			slog.Info("Gateway health check passed", "waitTime", elapsed)
			return nil
		}

		elapsed := time.Since(start)
		if elapsed >= maxWait {
			return fmt.Errorf("gateway not ready after %v: %w", maxWait, err)
		}

		slog.Warn("Gateway not ready, retrying", "error", err, "elapsed", elapsed, "retryIn", pollInterval)
		t := time.NewTimer(pollInterval)
		select {
		case <-ctx.Done():
			t.Stop()
			return nil
		case <-t.C:
		}
	}
}

// waitForRuntime polls for runtime ready signal before starting message consumption
func waitForRuntime(ctx context.Context, readyFile string, socketPath string, maxWait time.Duration) error {
	slog.Info("Waiting for runtime to become ready", "file", readyFile, "socket", socketPath, "maxWait", maxWait)

	start := time.Now()
	pollInterval := 500 * time.Millisecond
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if _, err := os.Stat(readyFile); err == nil {
				slog.Debug("Runtime ready file found, verifying socket connection", "file", readyFile)

				if err := verifySocketConnection(socketPath); err != nil {
					slog.Warn("Runtime ready file exists but socket connection failed", "error", err, "socket", socketPath)

					elapsed := time.Since(start)
					if elapsed >= maxWait {
						return fmt.Errorf("socket connection verification failed after %v: %w", maxWait, err)
					}
					continue
				}

				elapsed := time.Since(start)
				slog.Info("Runtime ready and socket verified", "file", readyFile, "socket", socketPath, "waitTime", elapsed)
				return nil
			}

			elapsed := time.Since(start)
			if elapsed >= maxWait {
				return fmt.Errorf("runtime ready signal not detected after %v (file: %s)", maxWait, readyFile)
			}

			if int(elapsed.Seconds())%10 == 0 && elapsed.Milliseconds()%1000 < int64(pollInterval.Milliseconds()) {
				slog.Debug("Still waiting for runtime", "file", readyFile, "elapsed", elapsed)
			}
		}
	}
}

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

	slog.Info("Configuration loaded", "actor", cfg.ActorName, "transport", cfg.TransportType)

	// Create transport based on configuration
	var tp transport.Transport
	switch cfg.TransportType {
	case "rabbitmq":
		tp, err = transport.NewRabbitMQTransport(transport.RabbitMQConfig{
			URL:           cfg.RabbitMQURL,
			Exchange:      cfg.RabbitMQExchange,
			PrefetchCount: cfg.RabbitMQPrefetch,
			Namespace:     cfg.Namespace,
		})
		if err != nil {
			slog.Error("Failed to create RabbitMQ transport", "error", err)
			os.Exit(1)
		}
		slog.Info("RabbitMQ transport initialized", "exchange", cfg.RabbitMQExchange)
	case "sqs":
		initCtx := context.Background()
		visibilityTimeout := cfg.SQSVisibilityTimeout
		if visibilityTimeout == 0 {
			visibilityTimeout = int32(cfg.Timeout.Seconds() * 2)
		}
		tp, err = transport.NewSQSTransport(initCtx, transport.SQSConfig{
			Region:            cfg.SQSRegion,
			BaseURL:           cfg.SQSBaseURL,
			VisibilityTimeout: visibilityTimeout,
			WaitTimeSeconds:   cfg.SQSWaitTimeSeconds,
		})
		if err != nil {
			slog.Error("Failed to create SQS transport", "error", err)
			os.Exit(1)
		}
		slog.Info("SQS transport initialized",
			"region", cfg.SQSRegion,
			"baseURL", cfg.SQSBaseURL,
			"visibilityTimeout", visibilityTimeout,
			"waitTimeSeconds", cfg.SQSWaitTimeSeconds)
	case "pubsub":
		initCtx := context.Background()
		tp, err = transport.NewPubSubTransport(initCtx, transport.PubSubConfig{
			ProjectID: cfg.PubSubProjectID,
			Endpoint:  cfg.PubSubEndpoint,
		})
		if err != nil {
			slog.Error("Failed to create Pub/Sub transport", "error", err)
			os.Exit(1)
		}
		slog.Info("Pub/Sub transport initialized",
			"projectID", cfg.PubSubProjectID,
			"endpoint", cfg.PubSubEndpoint)
	case "socket":
		// Socket transport uses Unix domain sockets on a shared Docker volume.
		// FOR LOCAL DOCKER COMPOSE TESTING ONLY — no persistence, no broker, no K8s support.
		// See docs/architecture/transports/socket.md for constraints and setup guide.
		tp, err = transport.NewSocketTransport(transport.SocketConfig{
			MeshDir: cfg.MeshDir,
		})
		if err != nil {
			slog.Error("Failed to create socket transport", "error", err)
			os.Exit(1)
		}
		slog.Info("Socket transport initialized", "meshDir", cfg.MeshDir)
	default:
		slog.Error("Unsupported transport type", "transport", cfg.TransportType)
		os.Exit(1)
	}
	defer func() { _ = tp.Close() }()

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

	// Wait for runtime to become ready before starting message consumption
	readyFile := filepath.Join(filepath.Dir(cfg.SocketPath), "runtime-ready")
	maxWaitStr := os.Getenv("ASYA_RUNTIME_READY_TIMEOUT")
	maxWait := 5 * time.Minute
	if maxWaitStr != "" {
		if parsedDuration, err := time.ParseDuration(maxWaitStr); err == nil {
			maxWait = parsedDuration
		}
	}

	if err := waitForRuntime(ctx, readyFile, cfg.SocketPath, maxWait); err != nil {
		slog.Error("Runtime did not become ready in time", "error", err)
		os.Exit(1)
	}

	// Wait for gateway to become ready if gateway URL is configured.
	// Retries every 5 seconds up to ASYA_GATEWAY_READY_TIMEOUT (default 5m) so that
	// actor sidecars do not enter CrashLoopBackOff when the mesh gateway pod starts
	// concurrently (e.g. during a fresh cluster deployment or rolling upgrade).
	if cfg.GatewayURL != "" {
		slog.Info("Checking gateway health", "url", cfg.GatewayURL)
		gwMaxWaitStr := os.Getenv("ASYA_GATEWAY_READY_TIMEOUT")
		gwMaxWait := 5 * time.Minute
		if gwMaxWaitStr != "" {
			if d, err := time.ParseDuration(gwMaxWaitStr); err == nil {
				gwMaxWait = d
			} else {
				slog.Warn("Invalid format for ASYA_GATEWAY_READY_TIMEOUT, using default", "value", gwMaxWaitStr, "error", err)
			}
		}
		if err := waitForGateway(ctx, r, gwMaxWait); err != nil {
			slog.Error("Gateway health check failed - sidecar cannot start", "error", err, "gateway_url", cfg.GatewayURL)
			os.Exit(1)
		}
	} else {
		slog.Info("No gateway configured, skipping gateway health check")
	}

	// Run router
	slog.Info("Starting message processing")
	if err := r.Run(ctx); err != nil && err != context.Canceled {
		slog.Error("Router error", "error", err)
		os.Exit(1)
	}

	slog.Info("Sidecar shutdown complete")
}
