//go:build integration

package queue

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	amqp "github.com/rabbitmq/amqp091-go"
)

func TestChannelPool_Creation(t *testing.T) {
	url := getRabbitMQURL()
	pool, err := queue.NewChannelPool(url, "test-exchange", 5)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer pool.Close()

	if pool.Capacity() != 5 {
		t.Errorf("Expected capacity 5, got %d", pool.Capacity())
	}

	if pool.Size() != 5 {
		t.Errorf("Expected pool size 5, got %d", pool.Size())
	}
}

func TestChannelPool_GetReturn(t *testing.T) {
	url := getRabbitMQURL()
	pool, err := queue.NewChannelPool(url, "test-exchange", 3)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer pool.Close()

	ctx := context.Background()

	// Get a channel
	ch, err := pool.Get(ctx)
	if err != nil {
		t.Fatalf("Failed to get channel: %v", err)
	}

	if ch == nil {
		t.Fatal("Got nil channel")
	}

	// Pool should have one less channel
	if pool.Size() != 2 {
		t.Errorf("Expected pool size 2 after Get, got %d", pool.Size())
	}

	// Return channel
	pool.Return(ch)

	// Pool should be back to full
	if pool.Size() != 3 {
		t.Errorf("Expected pool size 3 after Return, got %d", pool.Size())
	}
}

func TestChannelPool_ConcurrentAccess(t *testing.T) {
	url := getRabbitMQURL()
	poolSize := 10
	pool, err := queue.NewChannelPool(url, "test-exchange", poolSize)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer pool.Close()

	ctx := context.Background()
	numGoroutines := 100
	numOperations := 10

	var wg sync.WaitGroup
	errors := make(chan error, numGoroutines*numOperations)

	// Spawn many goroutines that all try to get/return channels
	for i := 0; i < numGoroutines; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()

			for j := 0; j < numOperations; j++ {
				ch, err := pool.Get(ctx)
				if err != nil {
					errors <- err
					return
				}

				// Simulate some work
				time.Sleep(1 * time.Millisecond)

				pool.Return(ch)
			}
		}(i)
	}

	wg.Wait()
	close(errors)

	// Check for errors
	for err := range errors {
		t.Errorf("Concurrent access error: %v", err)
	}

	// Pool should be back to full size
	if pool.Size() != poolSize {
		t.Errorf("Expected pool size %d after concurrent access, got %d", poolSize, pool.Size())
	}
}

func TestChannelPool_ContextCancellation(t *testing.T) {
	url := getRabbitMQURL()
	pool, err := queue.NewChannelPool(url, "test-exchange", 1)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer pool.Close()

	ctx := context.Background()

	// Get the only channel
	ch, err := pool.Get(ctx)
	if err != nil {
		t.Fatalf("Failed to get channel: %v", err)
	}

	// Try to get another with cancelled context
	cancelCtx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err = pool.Get(cancelCtx)
	if err == nil {
		t.Error("Expected error when getting channel with cancelled context")
	}
	if err != context.Canceled {
		t.Errorf("Expected context.Canceled error, got: %v", err)
	}

	// Return the channel
	pool.Return(ch)
}

func TestChannelPool_CloseWhileInUse(t *testing.T) {
	url := getRabbitMQURL()
	pool, err := queue.NewChannelPool(url, "test-exchange", 2)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}

	ctx := context.Background()

	// Get a channel
	ch, err := pool.Get(ctx)
	if err != nil {
		t.Fatalf("Failed to get channel: %v", err)
	}

	// Close pool while channel is out
	pool.Close()

	// Try to return channel to closed pool
	pool.Return(ch)

	// Verify pool is closed
	_, err = pool.Get(ctx)
	if err == nil {
		t.Error("Expected error when getting from closed pool")
	}
}

func TestChannelPool_BoundedConcurrency(t *testing.T) {
	url := getRabbitMQURL()
	poolSize := 5
	pool, err := queue.NewChannelPool(url, "test-exchange", poolSize)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer pool.Close()

	ctx := context.Background()

	// Get all channels from pool
	channels := make([]*amqp.Channel, poolSize)
	for i := 0; i < poolSize; i++ {
		ch, err := pool.Get(ctx)
		if err != nil {
			t.Fatalf("Failed to get channel %d: %v", i, err)
		}
		channels[i] = ch
	}

	// Pool should be empty
	if pool.Size() != 0 {
		t.Errorf("Expected pool size 0 when all channels taken, got %d", pool.Size())
	}

	// Try to get another channel with timeout (should block)
	timeoutCtx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	_, err = pool.Get(timeoutCtx)
	if err == nil {
		t.Error("Expected timeout error when pool is exhausted")
	}

	// Return all channels
	for _, ch := range channels {
		pool.Return(ch)
	}

	// Pool should be full again
	if pool.Size() != poolSize {
		t.Errorf("Expected pool size %d after returning all channels, got %d", poolSize, pool.Size())
	}
}

func TestChannelPool_AutoRecovery(t *testing.T) {
	url := getRabbitMQURL()
	pool, err := queue.NewChannelPool(url, "test-exchange", 2)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer pool.Close()

	ctx := context.Background()

	// Get a channel
	ch, err := pool.Get(ctx)
	if err != nil {
		t.Fatalf("Failed to get channel: %v", err)
	}

	// Manually close the channel to simulate failure
	ch.Close()

	// Return the closed channel
	pool.Return(ch)

	// Get channel again - should get a fresh one
	ch2, err := pool.Get(ctx)
	if err != nil {
		t.Fatalf("Failed to get channel after close: %v", err)
	}

	if ch2.IsClosed() {
		t.Error("Expected fresh channel, got closed channel")
	}

	pool.Return(ch2)
}

// Benchmark tests
func BenchmarkChannelPool_GetReturn(b *testing.B) {
	url := getRabbitMQURL()
	pool, err := queue.NewChannelPool(url, "bench-exchange", 10)
	if err != nil {
		b.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer pool.Close()

	ctx := context.Background()

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			ch, err := pool.Get(ctx)
			if err != nil {
				b.Fatal(err)
			}
			pool.Return(ch)
		}
	})
}

func BenchmarkChannelPool_PublishWithPool(b *testing.B) {
	url := getRabbitMQURL()
	pool, err := queue.NewChannelPool(url, "bench-exchange", 10)
	if err != nil {
		b.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer pool.Close()

	ctx := context.Background()
	envelope := []byte(`{"test":"envelope"}`)

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			ch, err := pool.Get(ctx)
			if err != nil {
				b.Fatal(err)
			}

			err = ch.PublishWithContext(ctx, "bench-exchange", "test-queue", false, false, amqp.Publishing{
				ContentType:  "application/json",
				Body:         envelope,
				DeliveryMode: amqp.Persistent,
			})
			if err != nil {
				b.Fatal(err)
			}

			pool.Return(ch)
		}
	})
}
