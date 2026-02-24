package queue

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"

	amqp "github.com/rabbitmq/amqp091-go"

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
//   - Actor "x-sink"          → Queue "asya-x-sink"
//
// The prefix is added by:
// - Gateway queue clients (this file and sqs.go) when sending messages
// - Sidecar (router.go) when creating/consuming from queues
//
// This maintains consistent queue naming across all transport implementations.

// RabbitMQClient sends messages to RabbitMQ
type RabbitMQClient struct {
	conn     *amqp.Connection
	ch       *amqp.Channel
	exchange string
	mu       sync.Mutex // Protects channel access for thread-safety
}

// NewRabbitMQClient creates a new RabbitMQ client
func NewRabbitMQClient(url, exchange string) (*RabbitMQClient, error) {
	conn, err := amqp.Dial(url)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}

	ch, err := conn.Channel()
	if err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("failed to open channel: %w", err)
	}

	// Declare exchange
	err = ch.ExchangeDeclare(
		exchange, // name
		"topic",  // type
		true,     // durable
		false,    // auto-deleted
		false,    // internal
		false,    // no-wait
		nil,      // arguments
	)
	if err != nil {
		_ = ch.Close()
		_ = conn.Close()
		return nil, fmt.Errorf("failed to declare exchange: %w", err)
	}

	return &RabbitMQClient{
		conn:     conn,
		ch:       ch,
		exchange: exchange,
	}, nil
}

// SendMessage sends a message to the current actor's queue in the route
func (c *RabbitMQClient) SendMessage(ctx context.Context, task *types.Task) error {
	actorMsg, err := NewActorMessage(task)
	if err != nil {
		return err
	}

	// Marshal to JSON
	body, err := json.Marshal(actorMsg)
	if err != nil {
		return fmt.Errorf("failed to marshal message: %w", err)
	}

	// Send message to current actor's queue
	// Use actor name as routing key (sidecar binds queue with actor name, not "asya-" prefixed name)
	routingKey := task.Route.Curr

	// Protect channel access with mutex for thread-safety
	c.mu.Lock()
	err = c.ch.PublishWithContext(ctx,
		c.exchange, // exchange
		routingKey, // routing key (queue name)
		false,      // mandatory
		false,      // immediate
		amqp.Publishing{
			DeliveryMode: amqp.Persistent,
			ContentType:  "application/json",
			Body:         body,
		})
	c.mu.Unlock()

	if err != nil {
		return fmt.Errorf("failed to publish to RabbitMQ: %w", err)
	}

	return nil
}

// rabbitMQMessage wraps amqp.Delivery to implement QueueMessage
type rabbitMQMessage struct {
	delivery amqp.Delivery
}

func (m *rabbitMQMessage) Body() []byte {
	return m.delivery.Body
}

func (m *rabbitMQMessage) DeliveryTag() uint64 {
	return m.delivery.DeliveryTag
}

// Receive receives a message from the specified queue
func (c *RabbitMQClient) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	// Declare queue (idempotent)
	_, err := c.ch.QueueDeclare(
		queueName, // name
		true,      // durable
		false,     // delete when unused
		false,     // exclusive
		false,     // no-wait
		nil,       // arguments
	)
	if err != nil {
		return nil, fmt.Errorf("failed to declare queue: %w", err)
	}

	// Bind queue to exchange
	err = c.ch.QueueBind(
		queueName,  // queue name
		queueName,  // routing key (same as queue name)
		c.exchange, // exchange
		false,      // no-wait
		nil,        // args
	)
	if err != nil {
		return nil, fmt.Errorf("failed to bind queue: %w", err)
	}

	// Get a single message
	delivery, ok, err := c.ch.Get(queueName, false) // autoAck=false
	if err != nil {
		return nil, fmt.Errorf("failed to get message: %w", err)
	}

	if !ok {
		// No message available
		return nil, fmt.Errorf("no message available")
	}

	return &rabbitMQMessage{delivery: delivery}, nil
}

// Ack acknowledges a message
func (c *RabbitMQClient) Ack(ctx context.Context, msg QueueMessage) error {
	rmqMsg, ok := msg.(*rabbitMQMessage)
	if !ok {
		return fmt.Errorf("invalid message type")
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	return c.ch.Ack(rmqMsg.delivery.DeliveryTag, false)
}

// Close closes the RabbitMQ connection
func (c *RabbitMQClient) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.ch != nil {
		_ = c.ch.Close()
	}
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}
