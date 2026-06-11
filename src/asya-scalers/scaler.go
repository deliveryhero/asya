package main

import (
	"context"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	pubsub "cloud.google.com/go/pubsub/v2/apiv1"
	pubsubpb "cloud.google.com/go/pubsub/v2/apiv1/pubsubpb"
	pb "github.com/deliveryhero/asya/scaler-pubsub/externalscaler"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const (
	defaultTargetValue = 5
	defaultMaxMessages = 100
	pullTimeout        = 500 * time.Millisecond
	metricName         = "pubsub_messages"
)

// pubsubAPI abstracts Pub/Sub operations for testing.
type pubsubAPI interface {
	Pull(ctx context.Context, req *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error)
	ModifyAckDeadline(ctx context.Context, req *pubsubpb.ModifyAckDeadlineRequest) error
	Close() error
}

type subscriberAdapter struct {
	client *pubsub.SubscriptionAdminClient
}

func (a *subscriberAdapter) Pull(ctx context.Context, req *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error) {
	return a.client.Pull(ctx, req)
}

func (a *subscriberAdapter) ModifyAckDeadline(ctx context.Context, req *pubsubpb.ModifyAckDeadlineRequest) error {
	return a.client.ModifyAckDeadline(ctx, req)
}

func (a *subscriberAdapter) Close() error {
	return a.client.Close()
}

// PubSubScaler implements KEDA's ExternalScaler gRPC interface.
type PubSubScaler struct {
	pb.UnimplementedExternalScalerServer
	client pubsubAPI
}

func NewPubSubScaler(client pubsubAPI) *PubSubScaler {
	return &PubSubScaler{client: client}
}

// IsActive returns true if there are pending messages in the subscription.
// Uses Pull(maxMessages=1) with a short timeout for instant detection.
func (s *PubSubScaler) IsActive(ctx context.Context, ref *pb.ScaledObjectRef) (*pb.IsActiveResponse, error) {
	sub := ref.ScalerMetadata["subscriptionName"]
	if sub == "" {
		return nil, fmt.Errorf("scalerMetadata.subscriptionName is required")
	}

	count, err := s.pullAndNack(ctx, sub, 1)
	if err != nil {
		slog.Error("IsActive pull failed", "subscription", sub, "error", err)
		return nil, err
	}

	active := count > 0
	slog.Debug("IsActive check", "subscription", sub, "active", active)
	return &pb.IsActiveResponse{Result: active}, nil
}

// StreamIsActive pushes active state changes to KEDA via server-streaming.
func (s *PubSubScaler) StreamIsActive(ref *pb.ScaledObjectRef, stream pb.ExternalScaler_StreamIsActiveServer) error {
	sub := ref.ScalerMetadata["subscriptionName"]
	if sub == "" {
		return fmt.Errorf("scalerMetadata.subscriptionName is required")
	}

	intervalStr := ref.ScalerMetadata["streamInterval"]
	interval := 5 * time.Second
	if intervalStr != "" {
		if d, err := time.ParseDuration(intervalStr); err == nil && d > 0 {
			interval = d
		}
	}

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-stream.Context().Done():
			return nil
		case <-ticker.C:
			count, err := s.pullAndNack(stream.Context(), sub, 1)
			if err != nil {
				slog.Warn("StreamIsActive pull failed", "subscription", sub, "error", err)
				continue
			}
			if err := stream.Send(&pb.IsActiveResponse{Result: count > 0}); err != nil {
				return err
			}
		}
	}
}

// GetMetricSpec returns the metric name and target value for KEDA's HPA.
func (s *PubSubScaler) GetMetricSpec(_ context.Context, ref *pb.ScaledObjectRef) (*pb.GetMetricSpecResponse, error) {
	target := int64(defaultTargetValue)
	if v, ok := ref.ScalerMetadata["targetValue"]; ok {
		if parsed, err := strconv.ParseInt(v, 10, 64); err == nil {
			target = parsed
		}
	}

	return &pb.GetMetricSpecResponse{
		MetricSpecs: []*pb.MetricSpec{{
			MetricName:      metricName,
			TargetSize:      target,
			TargetSizeFloat: float64(target),
		}},
	}, nil
}

// GetMetrics returns the approximate message count by pulling and nacking.
func (s *PubSubScaler) GetMetrics(ctx context.Context, req *pb.GetMetricsRequest) (*pb.GetMetricsResponse, error) {
	sub := req.ScaledObjectRef.ScalerMetadata["subscriptionName"]
	if sub == "" {
		return nil, fmt.Errorf("scalerMetadata.subscriptionName is required")
	}

	maxMsg := int32(defaultMaxMessages)
	if v, ok := req.ScaledObjectRef.ScalerMetadata["maxMessages"]; ok {
		if parsed, err := strconv.ParseInt(v, 10, 32); err == nil {
			maxMsg = int32(parsed)
		}
	}

	count, err := s.pullAndNack(ctx, sub, maxMsg)
	if err != nil {
		slog.Error("GetMetrics pull failed", "subscription", sub, "error", err)
		return nil, err
	}

	slog.Debug("GetMetrics", "subscription", sub, "count", count)
	return &pb.GetMetricsResponse{
		MetricValues: []*pb.MetricValue{{
			MetricName:       metricName,
			MetricValue:      int64(count),
			MetricValueFloat: float64(count),
		}},
	}, nil
}

// pullAndNack pulls up to maxMessages and immediately nacks them all
// by setting ack deadline to 0, making them available for actual consumers.
func (s *PubSubScaler) pullAndNack(ctx context.Context, subscription string, maxMessages int32) (int, error) {
	pullCtx, cancel := context.WithTimeout(ctx, pullTimeout)
	defer cancel()

	resp, err := s.client.Pull(pullCtx, &pubsubpb.PullRequest{
		Subscription: subscription,
		MaxMessages:  maxMessages,
	})
	if err != nil {
		// Subscription may not exist yet (Crossplane still creating it).
		// Return 0 instead of an error so KEDA reports inactive, not failed.
		// NotFound: subscription not created yet (Crossplane still provisioning).
		// DeadlineExceeded: Pub/Sub Pull is a long-poll — on empty queues the
		// server holds the connection until the context deadline, then returns
		// DeadlineExceeded. Both mean "no messages available".
		if status.Code(err) == codes.NotFound || status.Code(err) == codes.DeadlineExceeded {
			slog.Debug("No messages available", "subscription", subscription, "reason", status.Code(err))
			return 0, nil
		}
		return 0, fmt.Errorf("pull from %s: %w", subscription, err)
	}

	count := len(resp.ReceivedMessages)
	if count == 0 {
		return 0, nil
	}

	// Nack all messages by setting ack deadline to 0
	ackIDs := make([]string, count)
	for i, msg := range resp.ReceivedMessages {
		ackIDs[i] = msg.AckId
	}

	nackCtx, nackCancel := context.WithTimeout(ctx, pullTimeout)
	defer nackCancel()

	if err := s.client.ModifyAckDeadline(nackCtx, &pubsubpb.ModifyAckDeadlineRequest{
		Subscription:       subscription,
		AckIds:             ackIDs,
		AckDeadlineSeconds: 0,
	}); err != nil {
		slog.Warn("Failed to nack messages, they will be redelivered after ack deadline",
			"subscription", subscription, "count", count, "error", err)
	}

	return count, nil
}
