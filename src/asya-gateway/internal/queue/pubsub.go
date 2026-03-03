package queue

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"sync"

	"cloud.google.com/go/pubsub" //nolint:staticcheck // v2 migration planned

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// PubSubClient implements the Client interface for Google Cloud Pub/Sub
type PubSubClient struct {
	client     *pubsub.Client
	namespace  string
	projectID  string
	topicCache map[string]*pubsub.Topic
	mu         sync.Mutex
}

// PubSubConfig holds Pub/Sub-specific configuration
type PubSubConfig struct {
	ProjectID string
	Endpoint  string
	Namespace string
}

// NewPubSubClient creates a new Pub/Sub client
func NewPubSubClient(ctx context.Context, cfg PubSubConfig) (*PubSubClient, error) {
	// Set emulator host env var if endpoint is provided
	if cfg.Endpoint != "" {
		if err := os.Setenv("PUBSUB_EMULATOR_HOST", cfg.Endpoint); err != nil {
			return nil, fmt.Errorf("failed to set PUBSUB_EMULATOR_HOST: %w", err)
		}
	}

	client, err := pubsub.NewClient(ctx, cfg.ProjectID)
	if err != nil {
		return nil, fmt.Errorf("failed to create Pub/Sub client: %w", err)
	}

	return &PubSubClient{
		client:     client,
		namespace:  cfg.Namespace,
		projectID:  cfg.ProjectID,
		topicCache: make(map[string]*pubsub.Topic),
	}, nil
}

// getOrCreateTopic returns a cached topic reference, creating it if needed
func (c *PubSubClient) getOrCreateTopic(topicID string) *pubsub.Topic {
	c.mu.Lock()
	defer c.mu.Unlock()

	if topic, ok := c.topicCache[topicID]; ok {
		return topic
	}

	topic := c.client.Topic(topicID)
	c.topicCache[topicID] = topic
	return topic
}

// SendMessage sends a message to the current actor's topic
func (c *PubSubClient) SendMessage(ctx context.Context, task *types.Task) error {
	actorMsg, err := NewActorEnvelope(task)
	if err != nil {
		return err
	}

	body, err := json.Marshal(actorMsg)
	if err != nil {
		return fmt.Errorf("failed to marshal message: %w", err)
	}

	actorName := task.Route.Curr
	topicID := fmt.Sprintf("asya-%s-%s", c.namespace, actorName)

	slog.Info("Sending message to Pub/Sub", "taskID", task.ID, "topic", topicID)

	topic := c.getOrCreateTopic(topicID)
	result := topic.Publish(ctx, &pubsub.Message{
		Data: body,
	})

	serverID, err := result.Get(ctx)
	if err != nil {
		slog.Error("Failed to publish to Pub/Sub", "taskID", task.ID, "topic", topicID, "error", err)
		return fmt.Errorf("failed to publish to Pub/Sub: %w", err)
	}

	slog.Info("Successfully sent message to Pub/Sub", "taskID", task.ID, "topic", topicID, "serverID", serverID)
	return nil
}

// pubsubQueueMessage wraps a Pub/Sub message for the QueueMessage interface
type pubsubQueueMessage struct {
	body []byte
	tag  uint64
	msg  *pubsub.Message
}

func (m *pubsubQueueMessage) Body() []byte {
	return m.body
}

func (m *pubsubQueueMessage) DeliveryTag() uint64 {
	return m.tag
}

// Receive receives a message from the specified subscription.
// The subscription name follows the same convention as the topic: asya-{namespace}-{actorName}
func (c *PubSubClient) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	sub := c.client.Subscription(queueName)
	sub.ReceiveSettings.MaxOutstandingMessages = 1

	msgCh := make(chan *pubsub.Message, 1)
	errCh := make(chan error, 1)

	cctx, cancel := context.WithCancel(ctx)
	defer cancel()

	go func() {
		err := sub.Receive(cctx, func(_ context.Context, msg *pubsub.Message) {
			msgCh <- msg
			cancel()
		})
		if err != nil {
			errCh <- err
		}
	}()

	select {
	case msg := <-msgCh:
		return &pubsubQueueMessage{
			body: msg.Data,
			tag:  0,
			msg:  msg,
		}, nil
	case err := <-errCh:
		return nil, fmt.Errorf("failed to receive from Pub/Sub: %w", err)
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// Ack acknowledges a Pub/Sub message
func (c *PubSubClient) Ack(_ context.Context, msg QueueMessage) error {
	psMsg, ok := msg.(*pubsubQueueMessage)
	if !ok {
		return fmt.Errorf("invalid message type: expected *pubsubQueueMessage")
	}

	psMsg.msg.Ack()
	return nil
}

// Close stops all cached topics and closes the Pub/Sub client
func (c *PubSubClient) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	for _, topic := range c.topicCache {
		topic.Stop()
	}

	return c.client.Close()
}
