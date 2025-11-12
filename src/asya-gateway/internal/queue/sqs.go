package queue

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sqs"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// Queue Naming Convention (All Transports):
//
// Actor names are transport-agnostic identifiers (e.g., "data-processor", "test-echo").
// All transports add an "asya-" prefix to actor names to create queue names.
//
// Examples:
//   - Actor "data-processor"  → Queue "asya-data-processor"
//   - Actor "test-echo"       → Queue "asya-test-echo"
//   - Actor "happy-end"       → Queue "asya-happy-end"
//
// The prefix is added by:
// - Gateway queue clients (rabbitmq.go and this file) when sending envelopes
// - Sidecar (router.go) when creating/consuming from queues
//
// This maintains consistent queue naming across all transport implementations.

// sqsClient defines the interface for SQS operations
type sqsClient interface {
	ReceiveMessage(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error)
	SendMessage(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error)
	DeleteMessage(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error)
	GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error)
}

// SQSClient implements the Client interface for AWS SQS
type SQSClient struct {
	client            sqsClient
	region            string
	baseURL           string
	visibilityTimeout int32
	waitTimeSeconds   int32
	queueURLCache     map[string]string
}

// SQSConfig holds SQS-specific configuration
type SQSConfig struct {
	Region            string
	Endpoint          string
	VisibilityTimeout int32
	WaitTimeSeconds   int32
}

// NewSQSClient creates a new SQS client
func NewSQSClient(ctx context.Context, cfg SQSConfig) (*SQSClient, error) {
	// Load AWS config with IRSA support (pod identity)
	loadOptions := []func(*config.LoadOptions) error{
		config.WithRegion(cfg.Region),
	}

	awsCfg, err := config.LoadDefaultConfig(ctx, loadOptions...)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	// Create SQS client with custom endpoint if provided (for LocalStack or custom SQS endpoints)
	var client *sqs.Client
	if cfg.Endpoint != "" {
		client = sqs.NewFromConfig(awsCfg, func(o *sqs.Options) {
			o.BaseEndpoint = aws.String(cfg.Endpoint)
		})
	} else {
		client = sqs.NewFromConfig(awsCfg)
	}

	// Set defaults
	visibilityTimeout := cfg.VisibilityTimeout
	if visibilityTimeout == 0 {
		visibilityTimeout = 300 // 5 minutes default
	}

	waitTimeSeconds := cfg.WaitTimeSeconds
	if waitTimeSeconds == 0 {
		waitTimeSeconds = 20 // Long polling default
	}

	return &SQSClient{
		client:            client,
		region:            cfg.Region,
		baseURL:           cfg.Endpoint,
		visibilityTimeout: visibilityTimeout,
		waitTimeSeconds:   waitTimeSeconds,
		queueURLCache:     make(map[string]string),
	}, nil
}

// resolveQueueURL resolves the full queue URL from queue name using GetQueueUrl API
func (c *SQSClient) resolveQueueURL(ctx context.Context, queueName string) (string, error) {
	// Check cache first
	if url, ok := c.queueURLCache[queueName]; ok {
		slog.Debug("SQS queue URL from cache", "queue", queueName, "url", url)
		return url, nil
	}

	slog.Debug("Resolving SQS queue URL", "queue", queueName, "baseURL", c.baseURL)

	// Use GetQueueUrl API for dynamic resolution
	result, err := c.client.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(queueName),
	})
	if err != nil {
		return "", fmt.Errorf("failed to resolve queue URL for %s: %w", queueName, err)
	}

	originalURL := aws.ToString(result.QueueUrl)
	queueURL := originalURL
	slog.Debug("SQS GetQueueUrl response", "queue", queueName, "originalURL", originalURL)

	// For LocalStack/custom endpoints: override hostname in returned URL
	// LocalStack returns virtual-host style URLs (http://sqs.{region}.localhost.localstack.cloud:4566/...)
	// which don't resolve in Docker networks. Replace with configured baseURL.
	if c.baseURL != "" {
		// Parse the returned URL to extract account ID and queue name
		// Format: http://host:port/account-id/queue-name
		parts := strings.Split(queueURL, "/")
		slog.Debug("Parsing queue URL", "queue", queueName, "parts", parts, "numParts", len(parts))
		if len(parts) >= 5 {
			// Reconstruct URL with configured baseURL
			accountID := parts[len(parts)-2]
			queue := parts[len(parts)-1]
			queueURL = fmt.Sprintf("%s/%s/%s", strings.TrimSuffix(c.baseURL, "/"), accountID, queue)
			slog.Info("Reconstructed SQS queue URL", "queue", queueName, "originalURL", originalURL, "reconstructedURL", queueURL, "accountID", accountID)
		} else {
			slog.Warn("Unable to reconstruct URL - insufficient parts", "queue", queueName, "originalURL", originalURL, "numParts", len(parts))
		}
	}

	// Cache it
	c.queueURLCache[queueName] = queueURL
	slog.Debug("Cached SQS queue URL", "queue", queueName, "url", queueURL)
	return queueURL, nil
}

// sqsMessage wraps SQS message for the QueueMessage interface
type sqsMessage struct {
	body          []byte
	deliveryTag   uint64
	queueURL      string
	receiptHandle string
}

func (m *sqsMessage) Body() []byte {
	return m.body
}

func (m *sqsMessage) DeliveryTag() uint64 {
	return m.deliveryTag
}

// SendEnvelope sends an envelope to the current actor's queue in the route
func (c *SQSClient) SendEnvelope(ctx context.Context, envelope *types.Envelope) error {
	if len(envelope.Route.Actors) == 0 {
		return fmt.Errorf("route has no actors")
	}
	if envelope.Route.Current < 0 || envelope.Route.Current >= len(envelope.Route.Actors) {
		return fmt.Errorf("invalid route.current=%d for actors length %d", envelope.Route.Current, len(envelope.Route.Actors))
	}

	// Create actor envelope
	msg := ActorEnvelope{
		ID:      envelope.ID,
		Route:   envelope.Route,
		Payload: envelope.Payload,
	}

	// Add deadline if envelope has timeout
	if !envelope.Deadline.IsZero() {
		msg.Deadline = envelope.Deadline.Format("2006-01-02T15:04:05Z07:00")
	}

	// Marshal to JSON
	body, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("failed to marshal envelope: %w", err)
	}

	// Get queue URL for current actor
	// Add "asya-" prefix to convert actor name to queue name
	actorName := envelope.Route.Actors[envelope.Route.Current]
	queueName := fmt.Sprintf("asya-%s", actorName)
	queueURL, err := c.resolveQueueURL(ctx, queueName)
	if err != nil {
		return fmt.Errorf("failed to resolve queue URL: %w", err)
	}

	slog.Info("Sending envelope to SQS", "envelopeID", envelope.ID, "queue", queueName, "queueURL", queueURL)

	// Send message to SQS
	_, err = c.client.SendMessage(ctx, &sqs.SendMessageInput{
		QueueUrl:    aws.String(queueURL),
		MessageBody: aws.String(string(body)),
	})
	if err != nil {
		slog.Error("Failed to send to SQS", "envelopeID", envelope.ID, "queue", queueName, "queueURL", queueURL, "error", err)
		return fmt.Errorf("failed to send to SQS: %w", err)
	}

	slog.Info("Successfully sent envelope to SQS", "envelopeID", envelope.ID, "queue", queueName)
	return nil
}

// Receive receives a message from the specified queue
func (c *SQSClient) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	queueURL, err := c.resolveQueueURL(ctx, queueName)
	if err != nil {
		return nil, fmt.Errorf("failed to resolve queue URL: %w", err)
	}

	// Long polling loop
	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		resp, err := c.client.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{
			QueueUrl:              aws.String(queueURL),
			MaxNumberOfMessages:   1,
			WaitTimeSeconds:       c.waitTimeSeconds,
			VisibilityTimeout:     c.visibilityTimeout,
			MessageAttributeNames: []string{"All"},
		})
		if err != nil {
			return nil, fmt.Errorf("failed to receive from SQS: %w", err)
		}

		if len(resp.Messages) == 0 {
			continue
		}

		msg := resp.Messages[0]

		return &sqsMessage{
			body:          []byte(aws.ToString(msg.Body)),
			deliveryTag:   0,
			queueURL:      queueURL,
			receiptHandle: aws.ToString(msg.ReceiptHandle),
		}, nil
	}
}

// Ack acknowledges a message by deleting it from the queue
func (c *SQSClient) Ack(ctx context.Context, msg QueueMessage) error {
	sqsMsg, ok := msg.(*sqsMessage)
	if !ok {
		return fmt.Errorf("invalid message type: expected *sqsMessage")
	}

	_, err := c.client.DeleteMessage(ctx, &sqs.DeleteMessageInput{
		QueueUrl:      aws.String(sqsMsg.queueURL),
		ReceiptHandle: aws.String(sqsMsg.receiptHandle),
	})
	if err != nil {
		return fmt.Errorf("failed to ack message: %w", err)
	}

	return nil
}

// Close closes the SQS client (no-op for SQS)
func (c *SQSClient) Close() error {
	return nil
}
