package transport

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

const (
	queuePrefix = "asya-"

	defaultQueueRetryMaxAttempts = 10
	defaultQueueRetryBackoff     = 1 * time.Second
)

// getQueueRetryMaxAttempts returns configured max retry attempts from environment or default
func getQueueRetryMaxAttempts() int {
	if val := os.Getenv("ASYA_QUEUE_RETRY_MAX_ATTEMPTS"); val != "" {
		if attempts, err := strconv.Atoi(val); err == nil && attempts > 0 {
			return attempts
		}
	}
	return defaultQueueRetryMaxAttempts
}

// getQueueRetryBackoff returns configured retry backoff duration from environment or default
func getQueueRetryBackoff() time.Duration {
	if val := os.Getenv("ASYA_QUEUE_RETRY_BACKOFF"); val != "" {
		if duration, err := time.ParseDuration(val); err == nil {
			return duration
		}
	}
	return defaultQueueRetryBackoff
}

// rabbitmqConnection defines the interface for RabbitMQ connection operations
type rabbitmqConnection interface {
	Channel() (*amqp.Channel, error)
	Close() error
}

// rabbitmqChannel defines the interface for RabbitMQ channel operations
type rabbitmqChannel interface {
	Qos(prefetchCount, prefetchSize int, global bool) error
	ExchangeDeclare(name, kind string, durable, autoDelete, internal, noWait bool, args amqp.Table) error
	QueueDeclare(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error)
	QueueDeclarePassive(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error)
	QueueBind(name, key, exchange string, noWait bool, args amqp.Table) error
	Consume(queue, consumer string, autoAck, exclusive, noLocal, noWait bool, args amqp.Table) (<-chan amqp.Delivery, error)
	PublishWithContext(ctx context.Context, exchange, key string, mandatory, immediate bool, msg amqp.Publishing) error
	Ack(tag uint64, multiple bool) error
	Nack(tag uint64, multiple, requeue bool) error
	Close() error
}

// RabbitMQTransport implements Transport interface for RabbitMQ
type RabbitMQTransport struct {
	conn          rabbitmqConnection
	channel       rabbitmqChannel
	exchange      string
	prefetchCount int
	consumer      <-chan amqp.Delivery // Single long-lived consumer
	consumerQueue string               // Queue name for the consumer
	amqpChannel   *amqp.Channel        // Store real AMQP channel to monitor errors
	amqpConn      *amqp.Connection     // Store real AMQP connection to monitor errors
	url           string               // Store URL for reconnection
}

// RabbitMQConfig holds RabbitMQ-specific configuration
type RabbitMQConfig struct {
	URL           string
	Exchange      string
	PrefetchCount int
}

// NewRabbitMQTransport creates a new RabbitMQ transport
func NewRabbitMQTransport(cfg RabbitMQConfig) (*RabbitMQTransport, error) {
	// Connect to RabbitMQ with retry logic for resilience during startup
	// This allows the sidecar to wait for RabbitMQ to become available during:
	// - Initial cluster deployment
	// - RabbitMQ pod restarts
	// - Network temporary failures
	var conn rabbitmqConnection
	var err error
	maxRetries := 5
	initialBackoff := 1 * time.Second

	for attempt := 0; attempt < maxRetries; attempt++ {
		conn, err = amqp.Dial(cfg.URL)
		if err == nil {
			break
		}

		if attempt < maxRetries-1 {
			backoff := initialBackoff * (1 << uint(attempt))
			slog.Warn("Failed to connect to RabbitMQ, retrying",
				"attempt", attempt+1,
				"maxRetries", maxRetries,
				"backoff", backoff,
				"error", err)
			time.Sleep(backoff)
		}
	}

	if err != nil {
		return nil, fmt.Errorf("failed to connect to RabbitMQ after %d attempts: %w", maxRetries, err)
	}

	slog.Info("Connected to RabbitMQ successfully")

	channel, err := conn.Channel()
	if err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("failed to open channel: %w", err)
	}

	// Set QoS (prefetch)
	if err := channel.Qos(cfg.PrefetchCount, 0, false); err != nil {
		_ = channel.Close()
		_ = conn.Close()
		return nil, fmt.Errorf("failed to set QoS: %w", err)
	}

	// Declare exchange
	if err := channel.ExchangeDeclare(
		cfg.Exchange,
		"topic",
		true,  // durable
		false, // auto-deleted
		false, // internal
		false, // no-wait
		nil,   // arguments
	); err != nil {
		_ = channel.Close()
		_ = conn.Close()
		return nil, fmt.Errorf("failed to declare exchange: %w", err)
	}

	realConn, ok := conn.(*amqp.Connection)
	if !ok {
		_ = channel.Close()
		_ = conn.Close()
		return nil, fmt.Errorf("failed to cast connection to *amqp.Connection")
	}

	return &RabbitMQTransport{
		conn:          conn,
		channel:       channel,
		exchange:      cfg.Exchange,
		prefetchCount: cfg.PrefetchCount,
		amqpChannel:   channel,
		amqpConn:      realConn,
		url:           cfg.URL,
	}, nil
}

// ensureQueue checks if queue exists using passive declaration
// Does NOT create the queue - operator is responsible for queue creation
func (t *RabbitMQTransport) ensureQueue(queueName string) error {
	if t.channel == nil {
		return fmt.Errorf("channel is not available")
	}

	// Use passive declaration to check if queue exists without creating it
	_, err := t.channel.QueueDeclarePassive(
		queueName,
		true,  // durable
		false, // delete when unused
		false, // exclusive
		false, // no-wait
		nil,   // arguments
	)
	if err != nil {
		return fmt.Errorf("queue does not exist: %w", err)
	}

	return nil
}

// Receive receives a message from RabbitMQ
func (t *RabbitMQTransport) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	// Check if AMQP connection is closed and reconnect if needed
	if t.amqpConn != nil && t.amqpConn.IsClosed() {
		slog.Warn("AMQP connection is closed, reconnecting to RabbitMQ")

		var newConn *amqp.Connection
		var err error
		maxRetries := 5
		initialBackoff := 1 * time.Second

		for attempt := 0; attempt < maxRetries; attempt++ {
			newConn, err = amqp.Dial(t.url)
			if err == nil {
				break
			}

			if attempt < maxRetries-1 {
				backoff := initialBackoff * (1 << uint(attempt))
				slog.Warn("Failed to reconnect to RabbitMQ, retrying",
					"attempt", attempt+1,
					"maxRetries", maxRetries,
					"backoff", backoff,
					"error", err)
				time.Sleep(backoff)
			}
		}

		if err != nil {
			return QueueMessage{}, fmt.Errorf("failed to reconnect to RabbitMQ after %d attempts: %w", maxRetries, err)
		}

		slog.Info("Successfully reconnected to RabbitMQ")

		t.conn = newConn
		t.amqpConn = newConn
		t.channel = nil
		t.amqpChannel = nil
		t.consumer = nil
		t.consumerQueue = ""
	}

	// Check if AMQP channel is closed and recreate if needed
	if t.amqpChannel != nil && t.amqpChannel.IsClosed() {
		slog.Warn("AMQP channel is closed, recreating channel")
		newChannel, err := t.conn.Channel()
		if err != nil {
			return QueueMessage{}, fmt.Errorf("failed to recreate channel: %w", err)
		}

		// Set QoS (prefetch)
		if err := newChannel.Qos(t.prefetchCount, 0, false); err != nil {
			_ = newChannel.Close()
			return QueueMessage{}, fmt.Errorf("failed to set QoS on new channel: %w", err)
		}

		// Declare exchange
		if err := newChannel.ExchangeDeclare(
			t.exchange,
			"topic",
			true,  // durable
			false, // auto-deleted
			false, // internal
			false, // no-wait
			nil,   // arguments
		); err != nil {
			_ = newChannel.Close()
			return QueueMessage{}, fmt.Errorf("failed to declare exchange on new channel: %w", err)
		}

		t.channel = newChannel
		t.amqpChannel = newChannel
		t.consumer = nil
		t.consumerQueue = ""
		slog.Info("Successfully recreated AMQP channel")
	}

	// Initialize consumer if this is the first call or queue changed
	if t.consumer == nil || t.consumerQueue != queueName {
		slog.Info("Initializing consumer", "queue", queueName, "consumer_was_nil", t.consumer == nil)

		// Ensure queue exists and is bound to exchange with retry logic
		// This handles cases where queue is deleted externally (chaos scenarios)
		// and operator needs time to recreate it
		maxRetries := getQueueRetryMaxAttempts()
		initialBackoff := getQueueRetryBackoff()

		var msgs <-chan amqp.Delivery
		var err error

		for attempt := 0; attempt < maxRetries; attempt++ {
			// Try to ensure queue exists
			if err = t.ensureQueue(queueName); err != nil {
				if attempt < maxRetries-1 {
					backoff := initialBackoff * (1 << uint(attempt))
					slog.Warn("Failed to ensure queue exists, retrying",
						"queue", queueName,
						"attempt", attempt+1,
						"maxRetries", maxRetries,
						"backoff", backoff,
						"error", err)
					time.Sleep(backoff)
					continue
				}
				return QueueMessage{}, fmt.Errorf("failed to ensure queue after %d attempts: %w", maxRetries, err)
			}

			// Try to start consuming
			msgs, err = t.channel.Consume(
				queueName,
				"",    // consumer tag
				false, // auto-ack
				false, // exclusive
				false, // no-local
				false, // no-wait
				nil,   // args
			)
			if err == nil {
				break
			}

			if attempt < maxRetries-1 {
				backoff := initialBackoff * (1 << uint(attempt))
				slog.Warn("Failed to start consuming, retrying",
					"queue", queueName,
					"attempt", attempt+1,
					"maxRetries", maxRetries,
					"backoff", backoff,
					"error", err)
				time.Sleep(backoff)
			}
		}

		if err != nil {
			slog.Error("Failed to start consuming after retries", "queue", queueName, "error", err)
			return QueueMessage{}, fmt.Errorf("failed to start consuming after %d attempts: %w", maxRetries, err)
		}

		slog.Info("Consumer started successfully", "queue", queueName, "msgs_chan_nil", msgs == nil)

		t.consumer = msgs
		t.consumerQueue = queueName
		slog.Info("Consumer initialization complete", "queue", queueName)
	}

	// Wait for a message with context support
	slog.Info("Waiting for message from consumer channel", "queue", queueName, "consumer_nil", t.consumer == nil)

	// Check if consumer channel is nil (should never happen)
	if t.consumer == nil {
		return QueueMessage{}, fmt.Errorf("consumer channel is nil")
	}

	select {
	case msg, ok := <-t.consumer:
		slog.Info("Received message from consumer channel", "ok", ok, "queue", queueName, "message_id", msg.MessageId)
		if !ok {
			// Channel closed - reset consumer to trigger reconnection on next call
			t.consumer = nil
			t.consumerQueue = ""
			return QueueMessage{}, fmt.Errorf("channel closed")
		}

		// Convert AMQP headers to QueueMessage headers
		headers := make(map[string]string)
		headers["QueueName"] = queueName
		for k, v := range msg.Headers {
			headers[k] = fmt.Sprintf("%v", v)
		}

		return QueueMessage{
			ID:            msg.MessageId,
			Body:          msg.Body,
			ReceiptHandle: msg.DeliveryTag,
			Headers:       headers,
		}, nil

	case <-ctx.Done():
		slog.Info("Context cancelled while waiting for message", "queue", queueName, "err", ctx.Err())
		return QueueMessage{}, ctx.Err()
	}
}

// Send sends a message to RabbitMQ
func (t *RabbitMQTransport) Send(ctx context.Context, queueName string, body []byte) error {
	// Ensure queue exists
	if err := t.ensureQueue(queueName); err != nil {
		return err
	}

	// Derive routing key from queue name by stripping queue prefix
	routingKey := queueName
	if len(queueName) > len(queuePrefix) && queueName[:len(queuePrefix)] == queuePrefix {
		routingKey = queueName[len(queuePrefix):]
	}

	// Publish message
	err := t.channel.PublishWithContext(
		ctx,
		t.exchange,
		routingKey, // routing key (actor name without prefix)
		false,      // mandatory
		false,      // immediate
		amqp.Publishing{
			DeliveryMode: amqp.Persistent,
			ContentType:  "application/json",
			Body:         body,
			Timestamp:    time.Now(),
		},
	)
	if err != nil {
		return fmt.Errorf("failed to publish to RabbitMQ: %w", err)
	}

	return nil
}

// Ack acknowledges a message
func (t *RabbitMQTransport) Ack(ctx context.Context, msg QueueMessage) error {
	deliveryTag, ok := msg.ReceiptHandle.(uint64)
	if !ok {
		return fmt.Errorf("invalid receipt handle type for RabbitMQ")
	}

	if err := t.channel.Ack(deliveryTag, false); err != nil {
		return fmt.Errorf("failed to ack message: %w", err)
	}

	return nil
}

// Nack negatively acknowledges a message (requeue)
func (t *RabbitMQTransport) Nack(ctx context.Context, msg QueueMessage) error {
	deliveryTag, ok := msg.ReceiptHandle.(uint64)
	if !ok {
		return fmt.Errorf("invalid receipt handle type for RabbitMQ")
	}

	if err := t.channel.Nack(deliveryTag, false, true); err != nil {
		return fmt.Errorf("failed to nack message: %w", err)
	}

	return nil
}

// Close closes the RabbitMQ connection
func (t *RabbitMQTransport) Close() error {
	if err := t.channel.Close(); err != nil {
		return err
	}
	return t.conn.Close()
}
