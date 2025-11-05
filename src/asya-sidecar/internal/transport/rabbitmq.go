package transport

import (
	"context"
	"fmt"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// RabbitMQTransport implements Transport interface for RabbitMQ
type RabbitMQTransport struct {
	conn          *amqp.Connection
	channel       *amqp.Channel
	exchange      string
	prefetchCount int
	consumer      <-chan amqp.Delivery // Single long-lived consumer
	consumerQueue string               // Queue name for the consumer
}

// RabbitMQConfig holds RabbitMQ-specific configuration
type RabbitMQConfig struct {
	URL           string
	Exchange      string
	PrefetchCount int
}

// NewRabbitMQTransport creates a new RabbitMQ transport
func NewRabbitMQTransport(cfg RabbitMQConfig) (*RabbitMQTransport, error) {
	conn, err := amqp.Dial(cfg.URL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}

	channel, err := conn.Channel()
	if err != nil {
		conn.Close()
		return nil, fmt.Errorf("failed to open channel: %w", err)
	}

	// Set QoS (prefetch)
	if err := channel.Qos(cfg.PrefetchCount, 0, false); err != nil {
		channel.Close()
		conn.Close()
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
		channel.Close()
		conn.Close()
		return nil, fmt.Errorf("failed to declare exchange: %w", err)
	}

	return &RabbitMQTransport{
		conn:          conn,
		channel:       channel,
		exchange:      cfg.Exchange,
		prefetchCount: cfg.PrefetchCount,
	}, nil
}

// ensureQueue declares a queue if it doesn't exist
func (t *RabbitMQTransport) ensureQueue(queueName string) error {
	_, err := t.channel.QueueDeclare(
		queueName,
		true,  // durable
		false, // delete when unused
		false, // exclusive
		false, // no-wait
		nil,   // arguments
	)
	if err != nil {
		return fmt.Errorf("failed to declare queue: %w", err)
	}

	// Bind queue to exchange with routing key = queue name
	if err := t.channel.QueueBind(
		queueName,
		queueName, // routing key
		t.exchange,
		false,
		nil,
	); err != nil {
		return fmt.Errorf("failed to bind queue: %w", err)
	}

	return nil
}

// Receive receives a message from RabbitMQ
func (t *RabbitMQTransport) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	// Ensure queue exists
	if err := t.ensureQueue(queueName); err != nil {
		return QueueMessage{}, err
	}

	// Initialize consumer if this is the first call or queue changed
	if t.consumer == nil || t.consumerQueue != queueName {
		// Cancel previous consumer if it exists
		if t.consumer != nil {
			// Note: We can't easily cancel the consumer here, so we'll just create a new one
			// This should only happen once per sidecar (queue name shouldn't change)
		}

		// Start consuming
		msgs, err := t.channel.Consume(
			queueName,
			"",    // consumer tag
			false, // auto-ack
			false, // exclusive
			false, // no-local
			false, // no-wait
			nil,   // args
		)
		if err != nil {
			return QueueMessage{}, fmt.Errorf("failed to start consuming: %w", err)
		}

		t.consumer = msgs
		t.consumerQueue = queueName
	}

	// Wait for a message with context support
	select {
	case msg, ok := <-t.consumer:
		if !ok {
			return QueueMessage{}, fmt.Errorf("channel closed")
		}

		// Convert headers to attributes
		attrs := make(map[string]string)
		attrs["QueueName"] = queueName
		for k, v := range msg.Headers {
			attrs[k] = fmt.Sprintf("%v", v)
		}

		return QueueMessage{
			ID:            msg.MessageId,
			Body:          msg.Body,
			ReceiptHandle: msg.DeliveryTag,
			Attributes:    attrs,
		}, nil

	case <-ctx.Done():
		return QueueMessage{}, ctx.Err()
	}
}

// Send sends a message to RabbitMQ
func (t *RabbitMQTransport) Send(ctx context.Context, queueName string, body []byte) error {
	// Ensure queue exists
	if err := t.ensureQueue(queueName); err != nil {
		return err
	}

	// Publish message
	err := t.channel.PublishWithContext(
		ctx,
		t.exchange,
		queueName, // routing key
		false,     // mandatory
		false,     // immediate
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
