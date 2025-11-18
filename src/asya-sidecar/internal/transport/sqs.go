package transport

import (
	"context"
	"fmt"
	"log/slog"
	"net/url"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

// sqsClient defines the interface for SQS operations
type sqsClient interface {
	ReceiveMessage(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error)
	SendMessage(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error)
	DeleteMessage(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error)
	ChangeMessageVisibility(ctx context.Context, params *sqs.ChangeMessageVisibilityInput, optFns ...func(*sqs.Options)) (*sqs.ChangeMessageVisibilityOutput, error)
	GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error)
}

// SQSTransport implements Transport interface for AWS SQS
type SQSTransport struct {
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
	BaseURL           string
	VisibilityTimeout int32
	WaitTimeSeconds   int32
}

// NewSQSTransport creates a new SQS transport
func NewSQSTransport(ctx context.Context, cfg SQSConfig) (*SQSTransport, error) {
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
	if cfg.BaseURL != "" {
		client = sqs.NewFromConfig(awsCfg, func(o *sqs.Options) {
			o.BaseEndpoint = aws.String(cfg.BaseURL)
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

	return &SQSTransport{
		client:            client,
		region:            cfg.Region,
		baseURL:           cfg.BaseURL,
		visibilityTimeout: visibilityTimeout,
		waitTimeSeconds:   waitTimeSeconds,
		queueURLCache:     make(map[string]string),
	}, nil
}

// resolveQueueURL resolves the full queue URL from queue name using GetQueueUrl API
// with retry logic to handle cases where queue is temporarily missing
func (t *SQSTransport) resolveQueueURL(ctx context.Context, queueName string) (string, error) {
	// Check cache first
	if url, ok := t.queueURLCache[queueName]; ok {
		return url, nil
	}

	// Use GetQueueUrl API with retry logic for resilience
	// This handles cases where queue is deleted externally (chaos scenarios)
	// and operator needs time to recreate it
	maxRetries := getQueueRetryMaxAttempts()
	initialBackoff := getQueueRetryBackoff()

	var result *sqs.GetQueueUrlOutput
	var err error

	for attempt := 0; attempt < maxRetries; attempt++ {
		result, err = t.client.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
			QueueName: aws.String(queueName),
		})
		if err == nil {
			break
		}

		if attempt < maxRetries-1 {
			backoff := initialBackoff * (1 << uint(attempt))
			slog.Warn("Failed to resolve queue URL, retrying",
				"queue", queueName,
				"attempt", attempt+1,
				"maxRetries", maxRetries,
				"backoff", backoff,
				"error", err)
			time.Sleep(backoff)
		}
	}

	if err != nil {
		return "", fmt.Errorf("failed to resolve queue URL for %s after %d attempts: %w", queueName, maxRetries, err)
	}

	queueURL := aws.ToString(result.QueueUrl)

	// Rewrite queue URL to use configured baseURL if provided
	// This fixes localstack returning localhost.localstack.cloud hostnames
	if t.baseURL != "" {
		parsedBase, err := url.Parse(t.baseURL)
		if err == nil {
			parsedQueue, err := url.Parse(queueURL)
			if err == nil && parsedQueue.Host != parsedBase.Host {
				// Replace scheme and host, keep path
				parsedQueue.Scheme = parsedBase.Scheme
				parsedQueue.Host = parsedBase.Host
				queueURL = parsedQueue.String()
			}
		}
	}

	// Cache it
	t.queueURLCache[queueName] = queueURL
	return queueURL, nil
}

// splitReceiptHandle extracts queueURL and receiptHandle from stored format
func splitReceiptHandle(handle interface{}) (string, string, error) {
	str, ok := handle.(string)
	if !ok {
		return "", "", fmt.Errorf("invalid receipt handle type for SQS")
	}

	parts := strings.SplitN(str, "|", 2)
	if len(parts) != 2 {
		return "", "", fmt.Errorf("invalid receipt handle format")
	}

	return parts[0], parts[1], nil
}

// Receive receives a message from SQS with long polling
func (t *SQSTransport) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	queueURL, err := t.resolveQueueURL(ctx, queueName)
	if err != nil {
		return QueueMessage{}, fmt.Errorf("failed to resolve queue URL for %s: %w", queueName, err)
	}

	// Long polling loop - blocks until message arrives or context cancelled
	for {
		select {
		case <-ctx.Done():
			return QueueMessage{}, ctx.Err()
		default:
		}

		resp, err := t.client.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{
			QueueUrl:              aws.String(queueURL),
			MaxNumberOfMessages:   1,
			WaitTimeSeconds:       t.waitTimeSeconds,
			VisibilityTimeout:     t.visibilityTimeout,
			MessageAttributeNames: []string{"All"},
		})
		if err != nil {
			// Invalidate cache if queue no longer exists
			// This allows retry to fetch fresh queue URL after operator recreates it
			delete(t.queueURLCache, queueName)
			return QueueMessage{}, fmt.Errorf("failed to receive from SQS: %w", err)
		}

		if len(resp.Messages) == 0 {
			continue
		}

		msg := resp.Messages[0]

		// Convert SQS message attributes to headers
		headers := make(map[string]string)
		headers["QueueName"] = queueName
		for k, v := range msg.MessageAttributes {
			if v.StringValue != nil {
				headers[k] = *v.StringValue
			}
		}

		// Store receipt handle as "queueURL|receiptHandle"
		receiptHandle := fmt.Sprintf("%s|%s", queueURL, aws.ToString(msg.ReceiptHandle))

		return QueueMessage{
			ID:            aws.ToString(msg.MessageId),
			Body:          []byte(aws.ToString(msg.Body)),
			ReceiptHandle: receiptHandle,
			Headers:       headers,
		}, nil
	}
}

// Send sends a message to SQS
func (t *SQSTransport) Send(ctx context.Context, queueName string, body []byte) error {
	queueURL, err := t.resolveQueueURL(ctx, queueName)
	if err != nil {
		slog.Error("Failed to resolve queue URL", "queueName", queueName, "error", err)
		return fmt.Errorf("failed to resolve queue URL for %s: %w", queueName, err)
	}

	result, err := t.client.SendMessage(ctx, &sqs.SendMessageInput{
		QueueUrl:    aws.String(queueURL),
		MessageBody: aws.String(string(body)),
	})
	if err != nil {
		slog.Error("SQS SendMessage failed", "queueName", queueName, "queueURL", queueURL, "error", err)
		return fmt.Errorf("failed to send to SQS: %w", err)
	}

	slog.Info("SQS message sent successfully", "queueName", queueName, "messageId", aws.ToString(result.MessageId))
	return nil
}

// Ack acknowledges a message by deleting it from the queue
func (t *SQSTransport) Ack(ctx context.Context, msg QueueMessage) error {
	queueURL, receiptHandle, err := splitReceiptHandle(msg.ReceiptHandle)
	if err != nil {
		return err
	}

	_, err = t.client.DeleteMessage(ctx, &sqs.DeleteMessageInput{
		QueueUrl:      aws.String(queueURL),
		ReceiptHandle: aws.String(receiptHandle),
	})
	if err != nil {
		return fmt.Errorf("failed to ack message: %w", err)
	}

	return nil
}

// Nack negatively acknowledges a message by setting visibility timeout to 0
// This makes the message immediately available for redelivery
func (t *SQSTransport) Nack(ctx context.Context, msg QueueMessage) error {
	queueURL, receiptHandle, err := splitReceiptHandle(msg.ReceiptHandle)
	if err != nil {
		return err
	}

	_, err = t.client.ChangeMessageVisibility(ctx, &sqs.ChangeMessageVisibilityInput{
		QueueUrl:          aws.String(queueURL),
		ReceiptHandle:     aws.String(receiptHandle),
		VisibilityTimeout: 0,
	})
	if err != nil {
		return fmt.Errorf("failed to nack message: %w", err)
	}

	return nil
}

// Close closes the SQS transport (no-op for SQS client)
func (t *SQSTransport) Close() error {
	return nil
}
