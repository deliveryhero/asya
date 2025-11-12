//go:build integration

package transport_metrics

import (
	"context"
	"fmt"
	"os"

	asyaconfig "github.com/asya/operator/internal/config"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	amqp "github.com/rabbitmq/amqp091-go"
)

// TransportFixture defines the interface for transport test fixtures
type TransportFixture interface {
	// Name returns the transport name
	Name() string

	// Setup prepares the transport for testing (e.g., creates queues)
	Setup(ctx context.Context, queueName string) error

	// Teardown cleans up after tests
	Teardown(ctx context.Context, queueName string) error

	// GetConfig returns the transport config for testing
	GetConfig() asyaconfig.TransportSpecificConfig

	// PublishMessages publishes test messages to the queue
	PublishMessages(ctx context.Context, queueName string, ready, processing int) error
}

// RabbitMQFixture implements TransportFixture for RabbitMQ
type RabbitMQFixture struct {
	config *asyaconfig.RabbitMQConfig
}

// NewRabbitMQFixture creates a new RabbitMQ test fixture
func NewRabbitMQFixture() *RabbitMQFixture {
	host := os.Getenv("RABBITMQ_HOST")
	if host == "" {
		host = "localhost"
	}

	return &RabbitMQFixture{
		config: &asyaconfig.RabbitMQConfig{
			Host:     host,
			Port:     5672,
			Username: "guest",
			Password: "guest",
		},
	}
}

func (f *RabbitMQFixture) Name() string {
	return "rabbitmq"
}

func (f *RabbitMQFixture) Setup(ctx context.Context, queueName string) error {
	url := fmt.Sprintf("amqp://%s:%s@%s:%d/", f.config.Username, f.config.Password, f.config.Host, f.config.Port)
	conn, err := amqp.Dial(url)
	if err != nil {
		return fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}
	defer conn.Close()

	ch, err := conn.Channel()
	if err != nil {
		return fmt.Errorf("failed to open channel: %w", err)
	}
	defer ch.Close()

	_, err = ch.QueueDeclare(
		queueName,
		true,
		false,
		false,
		false,
		nil,
	)
	if err != nil {
		return fmt.Errorf("failed to declare queue: %w", err)
	}

	return nil
}

func (f *RabbitMQFixture) Teardown(ctx context.Context, queueName string) error {
	url := fmt.Sprintf("amqp://%s:%s@%s:%d/", f.config.Username, f.config.Password, f.config.Host, f.config.Port)
	conn, err := amqp.Dial(url)
	if err != nil {
		return fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}
	defer conn.Close()

	ch, err := conn.Channel()
	if err != nil {
		return fmt.Errorf("failed to open channel: %w", err)
	}
	defer ch.Close()

	_, err = ch.QueueDelete(queueName, false, false, false)
	if err != nil {
		return fmt.Errorf("failed to delete queue: %w", err)
	}

	return nil
}

func (f *RabbitMQFixture) GetConfig() asyaconfig.TransportSpecificConfig {
	return f.config
}

func (f *RabbitMQFixture) PublishMessages(ctx context.Context, queueName string, ready, processing int) error {
	return fmt.Errorf("not implemented: RabbitMQ message publishing for tests")
}

// SQSFixture implements TransportFixture for SQS
type SQSFixture struct {
	config *asyaconfig.SQSConfig
}

// NewSQSFixture creates a new SQS test fixture
func NewSQSFixture() *SQSFixture {
	endpoint := os.Getenv("ASYA_SQS_ENDPOINT")
	if endpoint == "" {
		endpoint = "http://localhost:9324"
	}

	region := os.Getenv("AWS_REGION")
	if region == "" {
		region = "us-east-1"
	}

	return &SQSFixture{
		config: &asyaconfig.SQSConfig{
			Region:            region,
			Endpoint:          endpoint,
			VisibilityTimeout: 30,
			WaitTimeSeconds:   1,
		},
	}
}

func (f *SQSFixture) Name() string {
	return "sqs"
}

func (f *SQSFixture) Setup(ctx context.Context, queueName string) error {
	client, err := f.getSQSClient(ctx)
	if err != nil {
		return err
	}

	_, err = client.CreateQueue(ctx, &sqs.CreateQueueInput{
		QueueName: aws.String(queueName),
	})
	if err != nil {
		return fmt.Errorf("failed to create SQS queue: %w", err)
	}

	return nil
}

func (f *SQSFixture) Teardown(ctx context.Context, queueName string) error {
	client, err := f.getSQSClient(ctx)
	if err != nil {
		return err
	}

	result, err := client.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(queueName),
	})
	if err != nil {
		return nil
	}

	_, err = client.DeleteQueue(ctx, &sqs.DeleteQueueInput{
		QueueUrl: result.QueueUrl,
	})
	if err != nil {
		return fmt.Errorf("failed to delete SQS queue: %w", err)
	}

	return nil
}

func (f *SQSFixture) getSQSClient(ctx context.Context) (*sqs.Client, error) {
	configOpts := []func(*config.LoadOptions) error{
		config.WithRegion(f.config.Region),
	}

	if f.config.Endpoint != "" {
		configOpts = append(configOpts, config.WithEndpointResolverWithOptions(
			aws.EndpointResolverWithOptionsFunc(func(service, region string, options ...interface{}) (aws.Endpoint, error) {
				return aws.Endpoint{
					URL:               f.config.Endpoint,
					HostnameImmutable: true,
				}, nil
			}),
		))
	}

	awsConfig, err := config.LoadDefaultConfig(ctx, configOpts...)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	return sqs.NewFromConfig(awsConfig), nil
}

func (f *SQSFixture) GetConfig() asyaconfig.TransportSpecificConfig {
	return f.config
}

func (f *SQSFixture) PublishMessages(ctx context.Context, queueName string, ready, processing int) error {
	return fmt.Errorf("not implemented: SQS message publishing for tests")
}

// GetAllFixtures returns all available transport fixtures for parametrized testing
func GetAllFixtures() []TransportFixture {
	return []TransportFixture{
		NewRabbitMQFixture(),
		NewSQSFixture(),
	}
}
