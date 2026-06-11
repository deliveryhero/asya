package main

import (
	"context"
	"fmt"
	"testing"

	pubsubpb "cloud.google.com/go/pubsub/v2/apiv1/pubsubpb"
	pb "github.com/deliveryhero/asya/asya-scalers/externalscaler"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type mockPubSub struct {
	pullResp *pubsubpb.PullResponse
	pullErr  error
	nackErr  error
	pullReqs []*pubsubpb.PullRequest
	nackReqs []*pubsubpb.ModifyAckDeadlineRequest
}

func (m *mockPubSub) Pull(_ context.Context, req *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error) {
	m.pullReqs = append(m.pullReqs, req)
	return m.pullResp, m.pullErr
}

func (m *mockPubSub) ModifyAckDeadline(_ context.Context, req *pubsubpb.ModifyAckDeadlineRequest) error {
	m.nackReqs = append(m.nackReqs, req)
	return m.nackErr
}

func (m *mockPubSub) Close() error { return nil }

func TestIsActive_WithMessages(t *testing.T) {
	mock := &mockPubSub{
		pullResp: &pubsubpb.PullResponse{
			ReceivedMessages: []*pubsubpb.ReceivedMessage{
				{AckId: "ack-1", Message: &pubsubpb.PubsubMessage{Data: []byte("test")}},
			},
		},
	}
	scaler := NewPubSubScaler(mock)

	resp, err := scaler.IsActive(context.Background(), &pb.ScaledObjectRef{
		ScalerMetadata: map[string]string{"subscriptionName": "projects/p/subscriptions/s"},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !resp.Result {
		t.Error("expected IsActive=true when messages exist")
	}
	if len(mock.nackReqs) != 1 {
		t.Errorf("expected 1 nack request, got %d", len(mock.nackReqs))
	}
	if mock.nackReqs[0].AckDeadlineSeconds != 0 {
		t.Errorf("expected ack deadline 0 (nack), got %d", mock.nackReqs[0].AckDeadlineSeconds)
	}
}

func TestIsActive_NoMessages(t *testing.T) {
	mock := &mockPubSub{
		pullResp: &pubsubpb.PullResponse{},
	}
	scaler := NewPubSubScaler(mock)

	resp, err := scaler.IsActive(context.Background(), &pb.ScaledObjectRef{
		ScalerMetadata: map[string]string{"subscriptionName": "projects/p/subscriptions/s"},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.Result {
		t.Error("expected IsActive=false when no messages")
	}
	if len(mock.nackReqs) != 0 {
		t.Errorf("expected 0 nack requests, got %d", len(mock.nackReqs))
	}
}

func TestIsActive_MissingSubscription(t *testing.T) {
	scaler := NewPubSubScaler(&mockPubSub{})

	_, err := scaler.IsActive(context.Background(), &pb.ScaledObjectRef{
		ScalerMetadata: map[string]string{},
	})
	if err == nil {
		t.Error("expected error for missing subscriptionName")
	}
}

func TestIsActive_PullError(t *testing.T) {
	mock := &mockPubSub{
		pullErr: fmt.Errorf("connection refused"),
	}
	scaler := NewPubSubScaler(mock)

	_, err := scaler.IsActive(context.Background(), &pb.ScaledObjectRef{
		ScalerMetadata: map[string]string{"subscriptionName": "projects/p/subscriptions/s"},
	})
	if err == nil {
		t.Error("expected error when pull fails")
	}
}

func TestIsActive_DeadlineExceeded_ReturnsInactive(t *testing.T) {
	mock := &mockPubSub{
		pullErr: status.Error(codes.DeadlineExceeded, "context deadline exceeded"),
	}
	scaler := NewPubSubScaler(mock)

	resp, err := scaler.IsActive(context.Background(), &pb.ScaledObjectRef{
		ScalerMetadata: map[string]string{"subscriptionName": "projects/p/subscriptions/s"},
	})
	if err != nil {
		t.Fatalf("DeadlineExceeded should not return error, got: %v", err)
	}
	if resp.Result {
		t.Error("expected IsActive=false for empty queue (DeadlineExceeded)")
	}
}

func TestGetMetrics_DeadlineExceeded_ReturnsZero(t *testing.T) {
	mock := &mockPubSub{
		pullErr: status.Error(codes.DeadlineExceeded, "context deadline exceeded"),
	}
	scaler := NewPubSubScaler(mock)

	resp, err := scaler.GetMetrics(context.Background(), &pb.GetMetricsRequest{
		ScaledObjectRef: &pb.ScaledObjectRef{
			ScalerMetadata: map[string]string{"subscriptionName": "projects/p/subscriptions/s"},
		},
		MetricName: metricName,
	})
	if err != nil {
		t.Fatalf("DeadlineExceeded should not return error, got: %v", err)
	}
	if resp.MetricValues[0].MetricValue != 0 {
		t.Errorf("expected 0 messages, got %d", resp.MetricValues[0].MetricValue)
	}
}

func TestIsActive_NotFound_ReturnsInactive(t *testing.T) {
	mock := &mockPubSub{
		pullErr: status.Error(codes.NotFound, "resource not found"),
	}
	scaler := NewPubSubScaler(mock)

	resp, err := scaler.IsActive(context.Background(), &pb.ScaledObjectRef{
		ScalerMetadata: map[string]string{"subscriptionName": "projects/p/subscriptions/s"},
	})
	if err != nil {
		t.Fatalf("NotFound should not return error, got: %v", err)
	}
	if resp.Result {
		t.Error("expected IsActive=false for missing subscription")
	}
}

func TestGetMetricSpec_Default(t *testing.T) {
	scaler := NewPubSubScaler(&mockPubSub{})

	resp, err := scaler.GetMetricSpec(context.Background(), &pb.ScaledObjectRef{
		ScalerMetadata: map[string]string{},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.MetricSpecs) != 1 {
		t.Fatalf("expected 1 metric spec, got %d", len(resp.MetricSpecs))
	}
	spec := resp.MetricSpecs[0]
	if spec.MetricName != metricName {
		t.Errorf("expected metric name %q, got %q", metricName, spec.MetricName)
	}
	if spec.TargetSize != defaultTargetValue {
		t.Errorf("expected target %d, got %d", defaultTargetValue, spec.TargetSize)
	}
}

func TestGetMetricSpec_CustomTarget(t *testing.T) {
	scaler := NewPubSubScaler(&mockPubSub{})

	resp, err := scaler.GetMetricSpec(context.Background(), &pb.ScaledObjectRef{
		ScalerMetadata: map[string]string{"targetValue": "20"},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.MetricSpecs[0].TargetSize != 20 {
		t.Errorf("expected target 20, got %d", resp.MetricSpecs[0].TargetSize)
	}
}

func TestGetMetrics_ReturnsCount(t *testing.T) {
	msgs := make([]*pubsubpb.ReceivedMessage, 3)
	for i := range msgs {
		msgs[i] = &pubsubpb.ReceivedMessage{
			AckId:   fmt.Sprintf("ack-%d", i),
			Message: &pubsubpb.PubsubMessage{Data: []byte("data")},
		}
	}
	mock := &mockPubSub{
		pullResp: &pubsubpb.PullResponse{ReceivedMessages: msgs},
	}
	scaler := NewPubSubScaler(mock)

	resp, err := scaler.GetMetrics(context.Background(), &pb.GetMetricsRequest{
		ScaledObjectRef: &pb.ScaledObjectRef{
			ScalerMetadata: map[string]string{"subscriptionName": "projects/p/subscriptions/s"},
		},
		MetricName: metricName,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.MetricValues) != 1 {
		t.Fatalf("expected 1 metric value, got %d", len(resp.MetricValues))
	}
	if resp.MetricValues[0].MetricValue != 3 {
		t.Errorf("expected count 3, got %d", resp.MetricValues[0].MetricValue)
	}
	// Verify pull used default maxMessages
	if mock.pullReqs[0].MaxMessages != defaultMaxMessages {
		t.Errorf("expected maxMessages=%d, got %d", defaultMaxMessages, mock.pullReqs[0].MaxMessages)
	}
}

func TestGetMetrics_CustomMaxMessages(t *testing.T) {
	mock := &mockPubSub{
		pullResp: &pubsubpb.PullResponse{},
	}
	scaler := NewPubSubScaler(mock)

	_, err := scaler.GetMetrics(context.Background(), &pb.GetMetricsRequest{
		ScaledObjectRef: &pb.ScaledObjectRef{
			ScalerMetadata: map[string]string{
				"subscriptionName": "projects/p/subscriptions/s",
				"maxMessages":      "50",
			},
		},
		MetricName: metricName,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if mock.pullReqs[0].MaxMessages != 50 {
		t.Errorf("expected maxMessages=50, got %d", mock.pullReqs[0].MaxMessages)
	}
}
