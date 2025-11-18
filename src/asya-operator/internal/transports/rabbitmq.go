package transports

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"

	amqp "github.com/rabbitmq/amqp091-go"
	corev1 "k8s.io/api/core/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
)

const (
	defaultRabbitMQUsername  = "guest"
	errInvalidRabbitMQConfig = "invalid RabbitMQ config type"
)

// RabbitMQTransport implements queue reconciliation for RabbitMQ
type RabbitMQTransport struct {
	k8sClient         client.Client
	transportRegistry *asyaconfig.TransportRegistry
}

// NewRabbitMQTransport creates a new RabbitMQ transport reconciler
func NewRabbitMQTransport(k8sClient client.Client, registry *asyaconfig.TransportRegistry) *RabbitMQTransport {
	return &RabbitMQTransport{
		k8sClient:         k8sClient,
		transportRegistry: registry,
	}
}

// ReconcileQueue creates or updates the RabbitMQ queue for an actor
func (t *RabbitMQTransport) ReconcileQueue(ctx context.Context, actor *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	transport, err := t.transportRegistry.GetTransport("rabbitmq")
	if err != nil {
		return err
	}

	rabbitmqConfig, ok := transport.Config.(*asyaconfig.RabbitMQConfig)
	if !ok {
		return errors.New(errInvalidRabbitMQConfig)
	}

	queueName := fmt.Sprintf("asya-%s", actor.Name)

	// Skip queue operations in test environments (e.g., envtest without real RabbitMQ)
	if os.Getenv("ASYA_SKIP_QUEUE_OPERATIONS") == "true" {
		logger.Info("Skipping RabbitMQ queue operations (ASYA_SKIP_QUEUE_OPERATIONS=true)", "queue", queueName)
		return nil
	}

	// Get RabbitMQ password from secret if configured
	password := rabbitmqConfig.Password
	if rabbitmqConfig.PasswordSecretRef != nil {
		var err error
		password, err = t.loadPassword(ctx, rabbitmqConfig, actor.Namespace)
		if err != nil {
			return fmt.Errorf("failed to load RabbitMQ password: %w", err)
		}
	}

	// Build AMQP URL
	port := rabbitmqConfig.Port
	if port == 0 {
		port = 5672
	}
	username := rabbitmqConfig.Username
	if username == "" {
		return fmt.Errorf("failed to load RabbitMQ username")
	}

	amqpURL := fmt.Sprintf("amqp://%s:%s@%s:%d/", username, password, rabbitmqConfig.Host, port)

	// Connect to RabbitMQ
	conn, err := amqp.Dial(amqpURL)
	if err != nil {
		return fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}
	defer func() {
		_ = conn.Close()
	}()

	ch, err := conn.Channel()
	if err != nil {
		return fmt.Errorf("failed to open channel: %w", err)
	}
	defer func() {
		_ = ch.Close()
	}()

	// Manual mode: validate queue exists
	if !rabbitmqConfig.Queues.AutoCreate {
		_, err = ch.QueueDeclarePassive(
			queueName,
			true,
			false,
			false,
			false,
			nil,
		)
		if err != nil {
			return fmt.Errorf("queue %s does not exist (autoCreate disabled): queues must be created externally in manual mode: %w", queueName, err)
		}
		logger.Info("RabbitMQ queue exists (autoCreate disabled)", "queue", queueName)
		return nil
	}

	// Auto mode: declare exchange and queue
	exchange := rabbitmqConfig.Exchange
	if exchange != "" {
		err = ch.ExchangeDeclare(
			exchange,
			"topic",
			true,
			false,
			false,
			false,
			nil,
		)
		if err != nil {
			return fmt.Errorf("failed to declare exchange: %w", err)
		}
	}

	// Create DLQ if enabled
	var dlqName string
	if rabbitmqConfig.Queues.DLQ.Enabled {
		dlqName = fmt.Sprintf("%s-dlq", queueName)
		_, err = ch.QueueDeclare(
			dlqName,
			true,
			false,
			false,
			false,
			nil,
		)
		if err != nil {
			return fmt.Errorf("failed to declare DLQ: %w", err)
		}

		logger.Info("RabbitMQ DLQ created", "dlq", dlqName)
	}

	// Declare main queue with DLQ configuration if enabled
	queueArgs := amqp.Table{}
	if rabbitmqConfig.Queues.DLQ.Enabled {
		queueArgs["x-dead-letter-exchange"] = ""
		queueArgs["x-dead-letter-routing-key"] = dlqName
	}

	_, err = ch.QueueDeclare(
		queueName,
		true,
		false,
		false,
		false,
		queueArgs,
	)
	if err != nil {
		// Queue exists with different configuration - delete and recreate
		if strings.Contains(err.Error(), "inequivalent arg") || strings.Contains(err.Error(), "PRECONDITION_FAILED") {
			logger.Info("Queue exists with different configuration - deleting and recreating", "queue", queueName)
			_, deleteErr := ch.QueueDelete(queueName, false, false, false)
			if deleteErr != nil {
				return fmt.Errorf("failed to delete queue for recreation: %w", deleteErr)
			}

			// Recreate queue
			_, err = ch.QueueDeclare(
				queueName,
				true,
				false,
				false,
				false,
				queueArgs,
			)
			if err != nil {
				return fmt.Errorf("failed to recreate queue: %w", err)
			}
		} else {
			return fmt.Errorf("failed to declare queue: %w", err)
		}
	}

	// Bind queue to exchange if configured
	if exchange != "" {
		err = ch.QueueBind(
			queueName,
			queueName,
			exchange,
			false,
			nil,
		)
		if err != nil {
			return fmt.Errorf("failed to bind queue to exchange: %w", err)
		}
	}

	logger.Info("RabbitMQ queue reconciled", "queue", queueName, "exchange", exchange, "dlq_enabled", rabbitmqConfig.Queues.DLQ.Enabled)
	return nil
}

// DeleteQueue deletes the RabbitMQ queue for an actor
func (t *RabbitMQTransport) DeleteQueue(ctx context.Context, actor *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	transport, err := t.transportRegistry.GetTransport("rabbitmq")
	if err != nil {
		return err
	}

	rabbitmqConfig, ok := transport.Config.(*asyaconfig.RabbitMQConfig)
	if !ok {
		return errors.New(errInvalidRabbitMQConfig)
	}

	queueName := fmt.Sprintf("asya-%s", actor.Name)

	// Get RabbitMQ password from secret if configured
	password := rabbitmqConfig.Password
	if rabbitmqConfig.PasswordSecretRef != nil {
		var err error
		password, err = t.loadPassword(ctx, rabbitmqConfig, actor.Namespace)
		if err != nil {
			return fmt.Errorf("failed to load RabbitMQ password: %w", err)
		}
	}

	// Build AMQP URL
	port := rabbitmqConfig.Port
	if port == 0 {
		port = 5672
	}
	username := rabbitmqConfig.Username
	if username == "" {
		username = defaultRabbitMQUsername
	}

	amqpURL := fmt.Sprintf("amqp://%s:%s@%s:%d/", username, password, rabbitmqConfig.Host, port)

	// Connect to RabbitMQ
	conn, err := amqp.Dial(amqpURL)
	if err != nil {
		return fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}
	defer func() {
		_ = conn.Close()
	}()

	ch, err := conn.Channel()
	if err != nil {
		return fmt.Errorf("failed to open channel: %w", err)
	}
	defer func() {
		_ = ch.Close()
	}()

	// Delete main queue
	_, err = ch.QueueDelete(queueName, false, false, false)
	if err != nil {
		return fmt.Errorf("failed to delete queue: %w", err)
	}

	// Delete DLQ if it exists
	if rabbitmqConfig.Queues.DLQ.Enabled {
		dlqName := fmt.Sprintf("%s-dlq", queueName)
		_, err = ch.QueueDelete(dlqName, false, false, false)
		if err != nil {
			logger.Info("Failed to delete DLQ (may not exist)", "dlq", dlqName, "error", err)
		} else {
			logger.Info("RabbitMQ DLQ deleted", "dlq", dlqName)
		}
	}

	logger.Info("RabbitMQ queue deleted", "queue", queueName)
	return nil
}

// loadPassword loads RabbitMQ password from Kubernetes secret
func (t *RabbitMQTransport) loadPassword(ctx context.Context, rabbitmqConfig *asyaconfig.RabbitMQConfig, namespace string) (string, error) {
	secret := &corev1.Secret{}
	secretKey := client.ObjectKey{
		Name:      rabbitmqConfig.PasswordSecretRef.Name,
		Namespace: namespace,
	}

	if err := t.k8sClient.Get(ctx, secretKey, secret); err != nil {
		return "", fmt.Errorf("failed to get RabbitMQ password secret: %w", err)
	}

	passwordBytes, ok := secret.Data[rabbitmqConfig.PasswordSecretRef.Key]
	if !ok {
		return "", fmt.Errorf("key %s not found in secret %s", rabbitmqConfig.PasswordSecretRef.Key, rabbitmqConfig.PasswordSecretRef.Name)
	}

	return string(passwordBytes), nil
}

// QueueExists checks if a RabbitMQ queue exists using the Management API
func (t *RabbitMQTransport) QueueExists(ctx context.Context, queueName, namespace string) (bool, error) {
	logger := log.FromContext(ctx)

	// Skip in test environments
	if os.Getenv("ASYA_SKIP_QUEUE_OPERATIONS") == "true" {
		logger.V(1).Info("Skipping RabbitMQ queue existence check (ASYA_SKIP_QUEUE_OPERATIONS=true)", "queue", queueName)
		return true, nil
	}

	transport, err := t.transportRegistry.GetTransport("rabbitmq")
	if err != nil {
		return false, err
	}

	rabbitmqConfig, ok := transport.Config.(*asyaconfig.RabbitMQConfig)
	if !ok {
		return false, fmt.Errorf("invalid RabbitMQ config type")
	}

	// Get RabbitMQ password from secret if configured
	password := rabbitmqConfig.Password
	if rabbitmqConfig.PasswordSecretRef != nil {
		var err error
		password, err = t.loadPassword(ctx, rabbitmqConfig, "default")
		if err != nil {
			return false, fmt.Errorf("failed to load RabbitMQ password: %w", err)
		}
	}

	// Build AMQP URL
	port := rabbitmqConfig.Port
	if port == 0 {
		port = 5672
	}
	username := rabbitmqConfig.Username
	if username == "" {
		username = defaultRabbitMQUsername
	}

	amqpURL := fmt.Sprintf("amqp://%s:%s@%s:%d/", username, password, rabbitmqConfig.Host, port)

	// Connect to RabbitMQ
	conn, err := amqp.Dial(amqpURL)
	if err != nil {
		return false, fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}
	defer func() {
		_ = conn.Close()
	}()

	ch, err := conn.Channel()
	if err != nil {
		return false, fmt.Errorf("failed to open channel: %w", err)
	}
	defer func() {
		_ = ch.Close()
	}()

	// Use passive declaration to check existence without creating
	_, err = ch.QueueDeclarePassive(
		queueName,
		true,
		false,
		false,
		false,
		nil,
	)

	if err != nil {
		if strings.Contains(err.Error(), "NOT_FOUND") || strings.Contains(err.Error(), "404") {
			return false, nil
		}
		return false, fmt.Errorf("failed to check queue existence: %w", err)
	}

	return true, nil
}
