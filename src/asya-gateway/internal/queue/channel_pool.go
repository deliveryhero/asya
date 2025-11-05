package queue

import (
	"context"
	"fmt"
	"sync"

	amqp "github.com/rabbitmq/amqp091-go"
)

// ChannelPool manages a pool of AMQP channels for concurrent use.
// AMQP channels are NOT thread-safe, so each goroutine needs its own channel.
// This pool provides efficient channel reuse without mutex contention.
type ChannelPool struct {
	conn     *amqp.Connection
	pool     chan *amqp.Channel // Buffered channel acts as semaphore
	maxSize  int
	exchange string
	mu       sync.Mutex // Protects pool creation/destruction only
	closed   bool
}

// NewChannelPool creates a new channel pool
func NewChannelPool(url, exchange string, poolSize int) (*ChannelPool, error) {
	if poolSize <= 0 {
		poolSize = 10 // Default pool size
	}

	// Create single connection (thread-safe)
	conn, err := amqp.Dial(url)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}

	p := &ChannelPool{
		conn:     conn,
		pool:     make(chan *amqp.Channel, poolSize),
		maxSize:  poolSize,
		exchange: exchange,
	}

	// Pre-populate pool with channels
	for i := 0; i < poolSize; i++ {
		ch, err := p.createChannel()
		if err != nil {
			p.Close()
			return nil, fmt.Errorf("failed to create initial channel %d: %w", i, err)
		}
		p.pool <- ch
	}

	return p, nil
}

// createChannel creates and configures a new channel
func (p *ChannelPool) createChannel() (*amqp.Channel, error) {
	ch, err := p.conn.Channel()
	if err != nil {
		return nil, fmt.Errorf("failed to open channel: %w", err)
	}

	// Declare exchange (idempotent)
	err = ch.ExchangeDeclare(
		p.exchange, // name
		"topic",    // type
		true,       // durable
		false,      // auto-deleted
		false,      // internal
		false,      // no-wait
		nil,        // arguments
	)
	if err != nil {
		ch.Close()
		return nil, fmt.Errorf("failed to declare exchange: %w", err)
	}

	return ch, nil
}

// Get retrieves a channel from the pool (blocks if pool is empty)
func (p *ChannelPool) Get(ctx context.Context) (*amqp.Channel, error) {
	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		return nil, fmt.Errorf("pool is closed")
	}
	p.mu.Unlock()

	select {
	case ch := <-p.pool:
		// Got a channel from pool - verify it's still open
		if ch.IsClosed() {
			// Channel closed, create a new one
			newCh, err := p.createChannel()
			if err != nil {
				return nil, fmt.Errorf("failed to recreate closed channel: %w", err)
			}
			return newCh, nil
		}
		return ch, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// Return returns a channel to the pool
func (p *ChannelPool) Return(ch *amqp.Channel) {
	if ch == nil {
		return
	}

	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		ch.Close()
		return
	}
	p.mu.Unlock()

	// Non-blocking return to pool
	select {
	case p.pool <- ch:
		// Successfully returned to pool
	default:
		// Pool is full (shouldn't happen with correct Get/Return pairing)
		// Close the extra channel
		ch.Close()
	}
}

// Close closes all channels in pool and the connection
func (p *ChannelPool) Close() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.closed {
		return nil
	}
	p.closed = true

	// Close all channels in pool
	close(p.pool)
	for ch := range p.pool {
		if ch != nil && !ch.IsClosed() {
			ch.Close()
		}
	}

	// Close connection
	if p.conn != nil && !p.conn.IsClosed() {
		return p.conn.Close()
	}

	return nil
}

// Size returns the current number of channels in the pool
func (p *ChannelPool) Size() int {
	return len(p.pool)
}

// Capacity returns the maximum pool size
func (p *ChannelPool) Capacity() int {
	return p.maxSize
}
