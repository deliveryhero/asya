package main

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

// sqsAPI defines the SQS operations used by the consumer.
// Enables mock injection for unit testing.
type sqsAPI interface {
	ReceiveMessage(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error)
	DeleteMessage(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error)
}

// SQSConsumer polls an SQS DLQ using the native AWS SDK.
type SQSConsumer struct {
	client            sqsAPI
	queueURL          string
	visibilityTimeout int32
	waitTimeSeconds   int32
}

// SQSConsumerConfig holds SQS consumer configuration.
type SQSConsumerConfig struct {
	Region            string
	BaseURL           string // Custom endpoint for LocalStack/MinIO
	QueueURL          string
	VisibilityTimeout int32
	WaitTimeSeconds   int32
}

// NewSQSConsumer creates a new SQS DLQ consumer using native AWS SDK.
func NewSQSConsumer(ctx context.Context, cfg SQSConsumerConfig) (*SQSConsumer, error) {
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(cfg.Region),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	var client *sqs.Client
	if cfg.BaseURL != "" {
		client = sqs.NewFromConfig(awsCfg, func(o *sqs.Options) {
			o.BaseEndpoint = aws.String(cfg.BaseURL)
		})
	} else {
		client = sqs.NewFromConfig(awsCfg)
	}

	return &SQSConsumer{
		client:            client,
		queueURL:          cfg.QueueURL,
		visibilityTimeout: cfg.VisibilityTimeout,
		waitTimeSeconds:   cfg.WaitTimeSeconds,
	}, nil
}

// newSQSConsumerWithClient creates an SQSConsumer with an injected client (for testing).
func newSQSConsumerWithClient(client sqsAPI, queueURL string, visibilityTimeout, waitTimeSeconds int32) *SQSConsumer {
	return &SQSConsumer{
		client:            client,
		queueURL:          queueURL,
		visibilityTimeout: visibilityTimeout,
		waitTimeSeconds:   waitTimeSeconds,
	}
}

// Receive blocks until a message arrives on the DLQ or context is cancelled.
func (c *SQSConsumer) Receive(ctx context.Context) (*DLQMessage, error) {
	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		resp, err := c.client.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{
			QueueUrl:          aws.String(c.queueURL),
			MaxNumberOfMessages: 1,
			WaitTimeSeconds:   c.waitTimeSeconds,
			VisibilityTimeout: c.visibilityTimeout,
		})
		if err != nil {
			return nil, fmt.Errorf("failed to receive from SQS DLQ: %w", err)
		}

		if len(resp.Messages) == 0 {
			slog.Debug("No messages in DLQ, polling again")
			continue
		}

		msg := resp.Messages[0]
		return &DLQMessage{
			Body:          []byte(aws.ToString(msg.Body)),
			ReceiptHandle: aws.ToString(msg.ReceiptHandle),
		}, nil
	}
}

// Ack deletes a message from the DLQ after successful processing.
func (c *SQSConsumer) Ack(ctx context.Context, msg *DLQMessage) error {
	_, err := c.client.DeleteMessage(ctx, &sqs.DeleteMessageInput{
		QueueUrl:      aws.String(c.queueURL),
		ReceiptHandle: aws.String(msg.ReceiptHandle),
	})
	if err != nil {
		return fmt.Errorf("failed to delete message from DLQ: %w", err)
	}
	return nil
}

// Close is a no-op for the SQS consumer (SDK client has no close method).
func (c *SQSConsumer) Close() error {
	return nil
}
