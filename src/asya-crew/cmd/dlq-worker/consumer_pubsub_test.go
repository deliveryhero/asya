package main

import (
	"context"
	"testing"

	pubsubpb "cloud.google.com/go/pubsub/v2/apiv1/pubsubpb"
)

// mockPubSubClient implements pubsubPullAPI for testing.
type mockPubSubClient struct {
	pullFunc        func(ctx context.Context, req *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error)
	acknowledgeFunc func(ctx context.Context, req *pubsubpb.AcknowledgeRequest) error
	closed          bool
}

func (m *mockPubSubClient) Pull(ctx context.Context, req *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error) {
	return m.pullFunc(ctx, req)
}

func (m *mockPubSubClient) Acknowledge(ctx context.Context, req *pubsubpb.AcknowledgeRequest) error {
	return m.acknowledgeFunc(ctx, req)
}

func (m *mockPubSubClient) Close() error {
	m.closed = true
	return nil
}

func TestPubSubConsumer_Receive(t *testing.T) {
	msgBody := []byte(`{"id":"test-123","payload":{"data":"hello"}}`)
	mock := &mockPubSubClient{
		pullFunc: func(_ context.Context, req *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error) {
			if req.Subscription != "projects/my-proj/subscriptions/my-dlq-sub" {
				t.Errorf("unexpected subscription: %s", req.Subscription)
			}
			if req.MaxMessages != 1 {
				t.Errorf("MaxMessages = %d, want 1", req.MaxMessages)
			}
			return &pubsubpb.PullResponse{
				ReceivedMessages: []*pubsubpb.ReceivedMessage{
					{
						AckId:   "ack-handle-abc",
						Message: &pubsubpb.PubsubMessage{Data: msgBody, MessageId: "ps-msg-id"},
					},
				},
			}, nil
		},
	}

	consumer := newPubSubConsumerWithClient(mock, "projects/my-proj/subscriptions/my-dlq-sub")

	msg, err := consumer.Receive(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(msg.Body) != string(msgBody) {
		t.Errorf("body = %q, want %q", string(msg.Body), string(msgBody))
	}
	if msg.ReceiptHandle != "ack-handle-abc" {
		t.Errorf("ReceiptHandle = %q, want %q", msg.ReceiptHandle, "ack-handle-abc")
	}
}

func TestPubSubConsumer_Receive_EmptyThenMessage(t *testing.T) {
	callCount := 0
	mock := &mockPubSubClient{
		pullFunc: func(_ context.Context, _ *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error) {
			callCount++
			if callCount == 1 {
				return &pubsubpb.PullResponse{ReceivedMessages: nil}, nil
			}
			return &pubsubpb.PullResponse{
				ReceivedMessages: []*pubsubpb.ReceivedMessage{
					{
						AckId:   "ack-delayed",
						Message: &pubsubpb.PubsubMessage{Data: []byte(`{"id":"delayed"}`), MessageId: "ps-delayed"},
					},
				},
			}, nil
		},
	}

	consumer := newPubSubConsumerWithClient(mock, "projects/p/subscriptions/s")

	msg, err := consumer.Receive(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(msg.Body) != `{"id":"delayed"}` {
		t.Errorf("body = %q", string(msg.Body))
	}
	if callCount != 2 {
		t.Errorf("expected 2 pull calls, got %d", callCount)
	}
}

func TestPubSubConsumer_Receive_ContextCancelled(t *testing.T) {
	mock := &mockPubSubClient{
		pullFunc: func(ctx context.Context, _ *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error) {
			return nil, ctx.Err()
		},
	}

	consumer := newPubSubConsumerWithClient(mock, "projects/p/subscriptions/s")
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := consumer.Receive(ctx)
	if err == nil {
		t.Fatal("expected error for cancelled context")
	}
}

func TestPubSubConsumer_Close_ReleasesClient(t *testing.T) {
	mock := &mockPubSubClient{}
	consumer := newPubSubConsumerWithClient(mock, "projects/p/subscriptions/s")

	if err := consumer.Close(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !mock.closed {
		t.Error("Close() should propagate to the underlying gRPC client")
	}
}

func TestPubSubConsumer_Ack(t *testing.T) {
	var ackedSub string
	var ackedIDs []string

	mock := &mockPubSubClient{
		acknowledgeFunc: func(_ context.Context, req *pubsubpb.AcknowledgeRequest) error {
			ackedSub = req.Subscription
			ackedIDs = req.AckIds
			return nil
		},
	}

	consumer := newPubSubConsumerWithClient(mock, "projects/my-proj/subscriptions/my-dlq-sub")

	err := consumer.Ack(context.Background(), &DLQMessage{
		ReceiptHandle: "ack-handle-xyz",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ackedSub != "projects/my-proj/subscriptions/my-dlq-sub" {
		t.Errorf("acked subscription = %q", ackedSub)
	}
	if len(ackedIDs) != 1 || ackedIDs[0] != "ack-handle-xyz" {
		t.Errorf("acked IDs = %v", ackedIDs)
	}
}
