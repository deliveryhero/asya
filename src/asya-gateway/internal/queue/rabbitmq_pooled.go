package queue

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"

	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// consumerInfo holds a persistent consumer channel and its deliveries
type consumerInfo struct {
	channel    *amqp.Channel
	deliveries <-chan amqp.Delivery
}

// RabbitMQClientPooled sends envelopes to RabbitMQ using a channel pool
// for high-concurrency scenarios without mutex contention
type RabbitMQClientPooled struct {
	pool        *ChannelPool
	consumers   map[string]*consumerInfo
	consumersMu sync.Mutex
}

// NewRabbitMQClientPooled creates a new RabbitMQ client with channel pooling
func NewRabbitMQClientPooled(url, exchange string, poolSize int) (*RabbitMQClientPooled, error) {
	pool, err := NewChannelPool(url, exchange, poolSize)
	if err != nil {
		return nil, err
	}

	return &RabbitMQClientPooled{
		pool:      pool,
		consumers: make(map[string]*consumerInfo),
	}, nil
}

// SendEnvelope sends an envelope to the current actor's queue in the route
func (c *RabbitMQClientPooled) SendEnvelope(ctx context.Context, envelope *types.Envelope) error {
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

	// Get channel from pool
	ch, err := c.pool.Get(ctx)
	if err != nil {
		return fmt.Errorf("failed to get channel from pool: %w", err)
	}
	defer c.pool.Return(ch)

	// Send envelope to current actor's queue
	// Use actor name as routing key (sidecar binds queue with actor name, not "asya-" prefixed name)
	actorName := envelope.Route.Actors[envelope.Route.Current]
	routingKey := actorName
	err = ch.PublishWithContext(ctx,
		c.pool.exchange, // exchange
		routingKey,      // routing key (queue name)
		false,           // mandatory
		false,           // immediate
		amqp.Publishing{
			DeliveryMode: amqp.Persistent,
			ContentType:  "application/json",
			Body:         body,
		})
	if err != nil {
		return fmt.Errorf("failed to publish to RabbitMQ: %w", err)
	}

	return nil
}

// pooledRabbitMQMessage wraps amqp.Delivery and channel for pooled operations
// The channel must be kept with the envelope to properly acknowledge it later
type pooledRabbitMQMessage struct {
	delivery amqp.Delivery
	channel  *amqp.Channel
	pool     *ChannelPool
}

func (m *pooledRabbitMQMessage) Body() []byte {
	return m.delivery.Body
}

func (m *pooledRabbitMQMessage) DeliveryTag() uint64 {
	return m.delivery.DeliveryTag
}

// Receive receives a envelope from the specified queue using a persistent consumer
// This creates ONE consumer per queue (not per Receive call) to avoid consumer leaks
func (c *RabbitMQClientPooled) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	// Check if we already have a persistent consumer for this queue
	c.consumersMu.Lock()
	consumer, exists := c.consumers[queueName]

	if !exists {
		// Create a persistent consumer for this queue
		ch, err := c.pool.Get(ctx)
		if err != nil {
			c.consumersMu.Unlock()
			return nil, fmt.Errorf("failed to get channel from pool: %w", err)
		}

		// Declare queue (idempotent)
		_, err = ch.QueueDeclare(
			queueName, // name
			true,      // durable
			false,     // delete when unused
			false,     // exclusive
			false,     // no-wait
			nil,       // arguments
		)
		if err != nil {
			c.pool.Return(ch)
			c.consumersMu.Unlock()
			return nil, fmt.Errorf("failed to declare queue: %w", err)
		}

		// Bind queue to exchange
		err = ch.QueueBind(
			queueName,       // queue name
			queueName,       // routing key (same as queue name)
			c.pool.exchange, // exchange
			false,           // no-wait
			nil,             // args
		)
		if err != nil {
			c.pool.Return(ch)
			c.consumersMu.Unlock()
			return nil, fmt.Errorf("failed to bind queue: %w", err)
		}

		// Set QoS to fetch one envelope at a time
		err = ch.Qos(1, 0, false)
		if err != nil {
			c.pool.Return(ch)
			c.consumersMu.Unlock()
			return nil, fmt.Errorf("failed to set QoS: %w", err)
		}

		// Start persistent consumer (NOT cancelled after each envelope)
		deliveries, err := ch.Consume(
			queueName, // queue
			"",        // consumer tag (auto-generated)
			false,     // auto-ack
			false,     // exclusive
			false,     // no-local
			false,     // no-wait
			nil,       // args
		)
		if err != nil {
			c.pool.Return(ch)
			c.consumersMu.Unlock()
			return nil, fmt.Errorf("failed to start consume: %w", err)
		}

		// Store consumer info for reuse
		consumer = &consumerInfo{
			channel:    ch,
			deliveries: deliveries,
		}
		c.consumers[queueName] = consumer
	}
	c.consumersMu.Unlock()

	// Wait for envelope from persistent consumer
	select {
	case delivery, ok := <-consumer.deliveries:
		if !ok {
			// Consumer channel closed, remove from map and retry
			c.consumersMu.Lock()
			delete(c.consumers, queueName)
			c.consumersMu.Unlock()
			return nil, fmt.Errorf("delivery channel closed")
		}

		// Return envelope with the consumer's dedicated channel
		return &pooledRabbitMQMessage{
			delivery: delivery,
			channel:  consumer.channel,
			pool:     c.pool,
		}, nil

	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// Ack acknowledges a envelope
// Note: Channel is NOT returned to pool since it's a persistent consumer channel
func (c *RabbitMQClientPooled) Ack(ctx context.Context, msg QueueMessage) error {
	pooledMsg, ok := msg.(*pooledRabbitMQMessage)
	if !ok {
		return fmt.Errorf("invalid envelope type: expected *pooledRabbitMQMessage")
	}

	// Acknowledge on the same channel that received the envelope
	err := pooledMsg.channel.Ack(pooledMsg.delivery.DeliveryTag, false)
	if err != nil {
		return fmt.Errorf("failed to ack envelope: %w", err)
	}

	return nil
}

// Close closes all persistent consumers and the channel pool
func (c *RabbitMQClientPooled) Close() error {
	c.consumersMu.Lock()
	defer c.consumersMu.Unlock()

	// Close all persistent consumer channels
	for queueName, consumer := range c.consumers {
		if consumer.channel != nil {
			_ = consumer.channel.Cancel("", false)
			c.pool.Return(consumer.channel)
		}
		delete(c.consumers, queueName)
	}

	return c.pool.Close()
}
