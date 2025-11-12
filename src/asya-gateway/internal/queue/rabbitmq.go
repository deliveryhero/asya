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
//   - Actor "happy-end"       → Queue "asya-happy-end"
//
// The prefix is added by:
// - Gateway queue clients (this file and sqs.go) when sending envelopes
// - Sidecar (router.go) when creating/consuming from queues
//
// This maintains consistent queue naming across all transport implementations.

// RabbitMQClient sends envelopes to RabbitMQ
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

// SendEnvelope sends an envelope to the current actor's queue in the route
func (c *RabbitMQClient) SendEnvelope(ctx context.Context, envelope *types.Envelope) error {
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

	// Send envelope to current actor's queue
	// Use actor name as routing key (sidecar binds queue with actor name, not "asya-" prefixed name)
	actorName := envelope.Route.Actors[envelope.Route.Current]
	routingKey := actorName

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

// Receive receives a envelope from the specified queue
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

	// Get a single envelope
	delivery, ok, err := c.ch.Get(queueName, false) // autoAck=false
	if err != nil {
		return nil, fmt.Errorf("failed to get envelope: %w", err)
	}

	if !ok {
		// No envelope available
		return nil, fmt.Errorf("no envelope available")
	}

	return &rabbitMQMessage{delivery: delivery}, nil
}

// Ack acknowledges a envelope
func (c *RabbitMQClient) Ack(ctx context.Context, msg QueueMessage) error {
	rmqMsg, ok := msg.(*rabbitMQMessage)
	if !ok {
		return fmt.Errorf("invalid envelope type")
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
