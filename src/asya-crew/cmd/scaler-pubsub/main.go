package main

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"

	pubsub "cloud.google.com/go/pubsub/v2/apiv1"
	pb "github.com/deliveryhero/asya/scaler-pubsub/externalscaler"
	"google.golang.org/api/option"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/reflection"
)

func main() {
	logLevel := os.Getenv("LOG_LEVEL")
	if logLevel == "" {
		logLevel = "INFO"
	}
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
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: level})))

	port := os.Getenv("SCALER_PORT")
	if port == "" {
		port = "6000"
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		sig := <-sigChan
		slog.Info("Received signal, shutting down", "signal", sig)
		cancel()
	}()

	emulatorHost := os.Getenv("PUBSUB_EMULATOR_HOST")
	slog.Info("Pub/Sub client config", "PUBSUB_EMULATOR_HOST", emulatorHost)

	var clientOpts []option.ClientOption
	if emulatorHost != "" {
		// The low-level apiv1 client does not respect PUBSUB_EMULATOR_HOST.
		// Manually configure endpoint and disable auth for emulator mode.
		clientOpts = append(clientOpts,
			option.WithEndpoint(emulatorHost),
			option.WithoutAuthentication(),
			option.WithGRPCDialOption(grpc.WithTransportCredentials(insecure.NewCredentials())),
		)
	}

	client, err := pubsub.NewSubscriptionAdminClient(ctx, clientOpts...)
	if err != nil {
		slog.Error("Failed to create Pub/Sub client", "error", err)
		os.Exit(1)
	}
	defer client.Close()

	scaler := NewPubSubScaler(&subscriberAdapter{client: client})

	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		slog.Error("Failed to listen", "port", port, "error", err)
		os.Exit(1)
	}

	srv := grpc.NewServer(grpc.Creds(insecure.NewCredentials()))
	pb.RegisterExternalScalerServer(srv, scaler)

	healthSrv := health.NewServer()
	healthpb.RegisterHealthServer(srv, healthSrv)
	healthSrv.SetServingStatus("", healthpb.HealthCheckResponse_SERVING)

	reflection.Register(srv)

	go func() {
		<-ctx.Done()
		slog.Info("Graceful shutdown initiated")
		srv.GracefulStop()
	}()

	slog.Info("KEDA Pub/Sub external scaler starting", "port", port)
	if err := srv.Serve(lis); err != nil {
		slog.Error("Server error", "error", err)
		os.Exit(1)
	}
	slog.Info("Server stopped")
}
