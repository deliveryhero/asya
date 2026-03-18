package main

import (
	"context"
	"fmt"
	"log/slog"

	pubsub "cloud.google.com/go/pubsub/v2/apiv1"
	pubsubpb "cloud.google.com/go/pubsub/v2/apiv1/pubsubpb"
)

// pubsubPullAPI defines the Pub/Sub operations used by the consumer.
// Enables mock injection for unit testing without gax variadic options.
type pubsubPullAPI interface {
	Pull(ctx context.Context, req *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error)
	Acknowledge(ctx context.Context, req *pubsubpb.AcknowledgeRequest) error
}

// subscriberClientAdapter adapts the real gRPC SubscriptionAdminClient to pubsubPullAPI.
type subscriberClientAdapter struct {
	client *pubsub.SubscriptionAdminClient
}

func (a *subscriberClientAdapter) Pull(ctx context.Context, req *pubsubpb.PullRequest) (*pubsubpb.PullResponse, error) {
	return a.client.Pull(ctx, req)
}

func (a *subscriberClientAdapter) Acknowledge(ctx context.Context, req *pubsubpb.AcknowledgeRequest) error {
	return a.client.Acknowledge(ctx, req)
}

// PubSubConsumer polls a Pub/Sub dead letter subscription using the native gRPC Pull API.
type PubSubConsumer struct {
	client       pubsubPullAPI
	subscription string // full resource name: projects/{project}/subscriptions/{sub}
}

// PubSubConsumerConfig holds Pub/Sub consumer configuration.
type PubSubConsumerConfig struct {
	GCPProject   string
	Subscription string // full subscription resource name
}

// NewPubSubConsumer creates a new Pub/Sub DLQ consumer using the native gRPC Pull API.
func NewPubSubConsumer(ctx context.Context, cfg PubSubConsumerConfig) (*PubSubConsumer, error) {
	client, err := pubsub.NewSubscriptionAdminClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create Pub/Sub subscriber client: %w", err)
	}
	return &PubSubConsumer{
		client:       &subscriberClientAdapter{client: client},
		subscription: cfg.Subscription,
	}, nil
}

// newPubSubConsumerWithClient creates a PubSubConsumer with an injected client (for testing).
func newPubSubConsumerWithClient(client pubsubPullAPI, subscription string) *PubSubConsumer {
	return &PubSubConsumer{
		client:       client,
		subscription: subscription,
	}
}

// Receive blocks until a message arrives on the dead letter subscription or context is cancelled.
func (c *PubSubConsumer) Receive(ctx context.Context) (*DLQMessage, error) {
	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		resp, err := c.client.Pull(ctx, &pubsubpb.PullRequest{
			Subscription: c.subscription,
			MaxMessages:  1,
		})
		if err != nil {
			return nil, fmt.Errorf("failed to pull from Pub/Sub DLQ: %w", err)
		}

		if len(resp.ReceivedMessages) == 0 {
			slog.Debug("No messages in Pub/Sub DLQ, polling again")
			continue
		}

		msg := resp.ReceivedMessages[0]
		return &DLQMessage{
			Body:          msg.Message.Data,
			ReceiptHandle: msg.AckId,
		}, nil
	}
}

// Ack acknowledges (deletes) a message from the dead letter subscription.
func (c *PubSubConsumer) Ack(ctx context.Context, msg *DLQMessage) error {
	err := c.client.Acknowledge(ctx, &pubsubpb.AcknowledgeRequest{
		Subscription: c.subscription,
		AckIds:       []string{msg.ReceiptHandle},
	})
	if err != nil {
		return fmt.Errorf("failed to acknowledge Pub/Sub DLQ message: %w", err)
	}
	return nil
}

// Close is a no-op for the Pub/Sub consumer (client lifecycle managed externally).
func (c *PubSubConsumer) Close() error {
	return nil
}
