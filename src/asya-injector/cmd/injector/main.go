package main

import (
	"context"
	"crypto/tls"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/deliveryhero/asya/asya-injector/internal/config"
	"github.com/deliveryhero/asya/asya-injector/internal/webhook"

	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"sigs.k8s.io/controller-runtime/pkg/client"
	k8sconfig "sigs.k8s.io/controller-runtime/pkg/client/config"
)

func main() {
	var (
		port     int
		certFile string
		keyFile  string
	)

	flag.IntVar(&port, "port", 8443, "Webhook server port")
	flag.StringVar(&certFile, "cert-file", "/etc/webhook/certs/tls.crt", "Path to TLS certificate")
	flag.StringVar(&keyFile, "key-file", "/etc/webhook/certs/tls.key", "Path to TLS private key")
	flag.Parse()

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

	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: level,
	}))
	slog.SetDefault(logger)

	slog.Info("Starting asya-injector webhook", "port", port)

	// Load configuration
	cfg := config.LoadFromEnv()
	slog.Info("Loaded configuration",
		"sidecarImage", cfg.SidecarImage,
		"runtimeConfigMap", cfg.RuntimeConfigMap,
	)

	// Set up Kubernetes client
	restConfig, err := k8sconfig.GetConfig()
	if err != nil {
		slog.Error("Failed to get Kubernetes config", "error", err)
		os.Exit(1)
	}

	k8sClient, err := client.New(restConfig, client.Options{})
	if err != nil {
		slog.Error("Failed to create Kubernetes client", "error", err)
		os.Exit(1)
	}

	dynamicClient, err := dynamic.NewForConfig(restConfig)
	if err != nil {
		slog.Error("Failed to create dynamic client", "error", err)
		os.Exit(1)
	}

	// Create webhook handler
	handler := webhook.NewHandler(k8sClient, dynamicClient, cfg)

	// Setup HTTP routes
	mux := http.NewServeMux()
	mux.HandleFunc("/mutate", handler.HandleMutate)
	mux.HandleFunc("/healthz", handleHealthz)
	mux.HandleFunc("/readyz", handleReadyz(restConfig))

	// Create TLS server
	server := &http.Server{
		Addr:              fmt.Sprintf(":%d", port),
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
	}

	// Check if TLS certificates exist
	if _, err := os.Stat(certFile); err == nil {
		slog.Info("TLS certificates found, starting HTTPS server", "cert", certFile, "key", keyFile)

		tlsConfig := &tls.Config{
			MinVersion: tls.VersionTLS12,
		}
		server.TLSConfig = tlsConfig

		go func() {
			if err := server.ListenAndServeTLS(certFile, keyFile); err != nil && err != http.ErrServerClosed {
				slog.Error("Server failed", "error", err)
				os.Exit(1)
			}
		}()
	} else {
		slog.Warn("TLS certificates not found, starting HTTP server (development mode only)")
		go func() {
			if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
				slog.Error("Server failed", "error", err)
				os.Exit(1)
			}
		}()
	}

	slog.Info("Server started", "addr", server.Addr)

	// Wait for shutdown signal
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	sig := <-sigChan
	slog.Info("Received signal, initiating shutdown", "signal", sig)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := server.Shutdown(ctx); err != nil {
		slog.Error("Server shutdown error", "error", err)
	}

	slog.Info("Injector shutdown complete")
}

func handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = fmt.Fprintln(w, "OK")
}

func handleReadyz(restConfig *rest.Config) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Check if we can connect to the Kubernetes API
		clientset, err := kubernetes.NewForConfig(restConfig)
		if err != nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = fmt.Fprintln(w, "Not ready: cannot create Kubernetes client")
			return
		}

		_, err = clientset.Discovery().ServerVersion()
		if err != nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = fmt.Fprintln(w, "Not ready: cannot connect to Kubernetes API")
			return
		}

		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintln(w, "OK")
	}
}
