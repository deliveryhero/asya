package transport

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"cloud.google.com/go/pubsub" //nolint:staticcheck // v2 migration planned
	pubsubapi "cloud.google.com/go/pubsub/apiv1"
	"cloud.google.com/go/pubsub/apiv1/pubsubpb" //nolint:staticcheck // v2 migration planned
	"google.golang.org/api/option"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// pubsubMessage abstracts a received Pub/Sub message for testability
type pubsubMessage interface {
	ID() string
	Data() []byte
	Attributes() map[string]string
	Ack()
	Nack()
}

// pubsubClient abstracts Google Cloud Pub/Sub operations for testability
type pubsubClient interface {
	Publish(ctx context.Context, topicID string, data []byte, attributes map[string]string) (string, error)
	Pull(ctx context.Context, subscriptionID string) (pubsubMessage, error)
	Close() error
}

// realPubSubMessage wraps a synchronously pulled Pub/Sub message
type realPubSubMessage struct {
	id         string
	data       []byte
	attributes map[string]string
	ackID      string
	subscriber *pubsubapi.SubscriberClient
	subPath    string
}

func (m *realPubSubMessage) ID() string                    { return m.id }
func (m *realPubSubMessage) Data() []byte                  { return m.data }
func (m *realPubSubMessage) Attributes() map[string]string { return m.attributes }

func (m *realPubSubMessage) Ack() {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	err := m.subscriber.Acknowledge(ctx, &pubsubpb.AcknowledgeRequest{ //nolint:staticcheck // v2 migration planned
		Subscription: m.subPath,
		AckIds:       []string{m.ackID},
	})
	if err != nil {
		slog.Error("Pub/Sub acknowledge failed", "subscription", m.subPath, "ackID", m.ackID, "error", err)
	}
}

func (m *realPubSubMessage) Nack() {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	err := m.subscriber.ModifyAckDeadline(ctx, &pubsubpb.ModifyAckDeadlineRequest{ //nolint:staticcheck // v2 migration planned
		Subscription:       m.subPath,
		AckIds:             []string{m.ackID},
		AckDeadlineSeconds: 0,
	})
	if err != nil {
		slog.Error("Pub/Sub nack (ModifyAckDeadline=0) failed", "subscription", m.subPath, "ackID", m.ackID, "error", err)
	}
}

// realPubSubClient wraps Pub/Sub clients for publishing (high-level) and pulling (low-level)
type realPubSubClient struct {
	publisher  *pubsub.Client
	subscriber *pubsubapi.SubscriberClient
	projectID  string
	mu         sync.Mutex
	topicCache map[string]*pubsub.Topic
}

func (c *realPubSubClient) getTopic(topicID string) *pubsub.Topic {
	c.mu.Lock()
	defer c.mu.Unlock()

	if topic, ok := c.topicCache[topicID]; ok {
		return topic
	}

	topic := c.publisher.Topic(topicID)
	c.topicCache[topicID] = topic
	return topic
}

func (c *realPubSubClient) Publish(ctx context.Context, topicID string, data []byte, attributes map[string]string) (string, error) {
	topic := c.getTopic(topicID)
	result := topic.Publish(ctx, &pubsub.Message{
		Data:       data,
		Attributes: attributes,
	})
	return result.Get(ctx)
}

// Pull uses the synchronous Pull RPC to receive a single message.
// Blocks until a message is available or the context is cancelled.
func (c *realPubSubClient) Pull(ctx context.Context, subscriptionID string) (pubsubMessage, error) {
	subPath := fmt.Sprintf("projects/%s/subscriptions/%s", c.projectID, subscriptionID)

	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		resp, err := c.subscriber.Pull(ctx, &pubsubpb.PullRequest{ //nolint:staticcheck // v2 migration planned
			Subscription: subPath,
			MaxMessages:  1,
		})
		if err != nil {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			return nil, fmt.Errorf("pull from subscription %s failed: %w", subscriptionID, err)
		}

		if len(resp.ReceivedMessages) == 0 {
			continue
		}

		rmsg := resp.ReceivedMessages[0]
		return &realPubSubMessage{
			id:         rmsg.Message.MessageId,
			data:       rmsg.Message.Data,
			attributes: rmsg.Message.Attributes,
			ackID:      rmsg.AckId,
			subscriber: c.subscriber,
			subPath:    subPath,
		}, nil
	}
}

func (c *realPubSubClient) Close() error {
	c.mu.Lock()
	for _, topic := range c.topicCache {
		topic.Stop()
	}
	c.topicCache = make(map[string]*pubsub.Topic)
	c.mu.Unlock()

	errSubscriber := c.subscriber.Close()
	errPublisher := c.publisher.Close()
	return errors.Join(errSubscriber, errPublisher)
}

// PubSubTransport implements Transport interface for Google Cloud Pub/Sub
type PubSubTransport struct {
	client    pubsubClient
	projectID string
}

// PubSubConfig holds Pub/Sub-specific configuration
type PubSubConfig struct {
	ProjectID string
	Endpoint  string
}

// NewPubSubTransport creates a new Pub/Sub transport
func NewPubSubTransport(ctx context.Context, cfg PubSubConfig) (*PubSubTransport, error) {
	var opts []option.ClientOption

	if cfg.Endpoint != "" {
		opts = append(opts,
			option.WithEndpoint(cfg.Endpoint),
			option.WithoutAuthentication(),
			option.WithGRPCDialOption(grpc.WithTransportCredentials(insecure.NewCredentials())),
		)
	}

	publisher, err := pubsub.NewClient(ctx, cfg.ProjectID, opts...)
	if err != nil {
		return nil, fmt.Errorf("failed to create Pub/Sub publisher client: %w", err)
	}

	subscriber, err := pubsubapi.NewSubscriberClient(ctx, opts...)
	if err != nil {
		_ = publisher.Close()
		return nil, fmt.Errorf("failed to create Pub/Sub subscriber client: %w", err)
	}

	return &PubSubTransport{
		client: &realPubSubClient{
			publisher:  publisher,
			subscriber: subscriber,
			projectID:  cfg.ProjectID,
			topicCache: make(map[string]*pubsub.Topic),
		},
		projectID: cfg.ProjectID,
	}, nil
}

// Receive receives a message from a Pub/Sub subscription using synchronous Pull
func (t *PubSubTransport) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	msg, err := t.client.Pull(ctx, queueName)
	if err != nil {
		return QueueMessage{}, fmt.Errorf("failed to pull from Pub/Sub subscription %s: %w", queueName, err)
	}

	headers := make(map[string]string)
	headers["QueueName"] = queueName
	for k, v := range msg.Attributes() {
		headers[k] = v
	}

	return QueueMessage{
		ID:            msg.ID(),
		Body:          msg.Data(),
		ReceiptHandle: msg,
		Headers:       headers,
	}, nil
}

// Send sends a message to a Pub/Sub topic
func (t *PubSubTransport) Send(ctx context.Context, queueName string, body []byte) error {
	msgID, err := t.client.Publish(ctx, queueName, body, nil)
	if err != nil {
		slog.Error("Pub/Sub publish failed", "topic", queueName, "error", err)
		return fmt.Errorf("failed to publish to Pub/Sub topic %s: %w", queueName, err)
	}

	slog.Info("Pub/Sub message published", "topic", queueName, "messageId", msgID)
	return nil
}

// SendWithDelay returns ErrDelayNotSupported; Pub/Sub does not support delayed delivery
func (t *PubSubTransport) SendWithDelay(_ context.Context, _ string, _ []byte, _ time.Duration) error {
	return ErrDelayNotSupported
}

// Ack acknowledges a Pub/Sub message
func (t *PubSubTransport) Ack(_ context.Context, msg QueueMessage) error {
	psMsg, ok := msg.ReceiptHandle.(pubsubMessage)
	if !ok {
		return fmt.Errorf("invalid receipt handle type for Pub/Sub: expected pubsubMessage, got %T", msg.ReceiptHandle)
	}

	psMsg.Ack()
	return nil
}

// Requeue returns a message to the subscription for redelivery via Nack
func (t *PubSubTransport) Requeue(_ context.Context, msg QueueMessage) error {
	psMsg, ok := msg.ReceiptHandle.(pubsubMessage)
	if !ok {
		return fmt.Errorf("invalid receipt handle type for Pub/Sub: expected pubsubMessage, got %T", msg.ReceiptHandle)
	}

	psMsg.Nack()
	return nil
}

// Close closes the Pub/Sub client
func (t *PubSubTransport) Close() error {
	return t.client.Close()
}
