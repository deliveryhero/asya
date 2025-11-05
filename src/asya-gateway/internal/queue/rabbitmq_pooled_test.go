package queue

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestRabbitMQClientPooled_SendMessage(t *testing.T) {
	url := "amqp://guest:guest@localhost:5672/"
	client, err := NewRabbitMQClientPooled(url, "test-exchange", 5)
	if err != nil {
		t.Skipf("Skipping test - RabbitMQ not available: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	job := &types.Job{
		ID: "test-job-1",
		Route: types.Route{
			Steps:   []string{"test-queue"},
			Current: 0,
		},
		Payload: map[string]interface{}{
			"message": "test",
		},
	}

	err = client.SendMessage(ctx, job)
	if err != nil {
		t.Fatalf("Failed to send message: %v", err)
	}
}

func TestRabbitMQClientPooled_ConcurrentSend(t *testing.T) {
	url := "amqp://guest:guest@localhost:5672/"
	poolSize := 10
	client, err := NewRabbitMQClientPooled(url, "test-exchange", poolSize)
	if err != nil {
		t.Skipf("Skipping test - RabbitMQ not available: %v", err)
	}
	defer client.Close()

	ctx := context.Background()
	numGoroutines := 100
	numMessages := 10

	var wg sync.WaitGroup
	errors := make(chan error, numGoroutines*numMessages)

	// Send many messages concurrently
	for i := 0; i < numGoroutines; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()

			for j := 0; j < numMessages; j++ {
				job := &types.Job{
					ID: fmt.Sprintf("job-%d-%d", id, j),
					Route: types.Route{
						Steps:   []string{"test-queue"},
						Current: 0,
					},
					Payload: map[string]interface{}{
						"goroutine": id,
						"message":   j,
					},
				}

				if err := client.SendMessage(ctx, job); err != nil {
					errors <- err
					return
				}
			}
		}(i)
	}

	wg.Wait()
	close(errors)

	// Check for errors
	errorCount := 0
	for err := range errors {
		t.Errorf("Concurrent send error: %v", err)
		errorCount++
	}

	if errorCount > 0 {
		t.Fatalf("Got %d errors during concurrent send", errorCount)
	}
}

func TestRabbitMQClientPooled_SendWithDeadline(t *testing.T) {
	url := "amqp://guest:guest@localhost:5672/"
	client, err := NewRabbitMQClientPooled(url, "test-exchange", 5)
	if err != nil {
		t.Skipf("Skipping test - RabbitMQ not available: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	deadline := time.Now().Add(5 * time.Minute)
	job := &types.Job{
		ID: "test-job-deadline",
		Route: types.Route{
			Steps:   []string{"test-queue"},
			Current: 0,
		},
		Payload: map[string]interface{}{
			"message": "test with deadline",
		},
		Deadline: deadline,
	}

	err = client.SendMessage(ctx, job)
	if err != nil {
		t.Fatalf("Failed to send message with deadline: %v", err)
	}
}

func TestRabbitMQClientPooled_SendEmptyRoute(t *testing.T) {
	url := "amqp://guest:guest@localhost:5672/"
	client, err := NewRabbitMQClientPooled(url, "test-exchange", 5)
	if err != nil {
		t.Skipf("Skipping test - RabbitMQ not available: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	job := &types.Job{
		ID: "test-job-empty-route",
		Route: types.Route{
			Steps:   []string{}, // Empty route
			Current: 0,
		},
		Payload: map[string]interface{}{},
	}

	err = client.SendMessage(ctx, job)
	if err == nil {
		t.Error("Expected error for empty route, got nil")
	}
}

func TestRabbitMQClientPooled_ContextCancellation(t *testing.T) {
	url := "amqp://guest:guest@localhost:5672/"
	client, err := NewRabbitMQClientPooled(url, "test-exchange", 1)
	if err != nil {
		t.Skipf("Skipping test - RabbitMQ not available: %v", err)
	}
	defer client.Close()

	// Create a cancelled context
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	job := &types.Job{
		ID: "test-job-cancel",
		Route: types.Route{
			Steps:   []string{"test-queue"},
			Current: 0,
		},
		Payload: map[string]interface{}{},
	}

	err = client.SendMessage(ctx, job)
	if err == nil {
		t.Error("Expected error with cancelled context")
	}
}

// Benchmark: Compare pooled vs mutex-based performance
func BenchmarkRabbitMQClientPooled_Send(b *testing.B) {
	url := "amqp://guest:guest@localhost:5672/"
	client, err := NewRabbitMQClientPooled(url, "bench-exchange", 10)
	if err != nil {
		b.Skipf("Skipping benchmark - RabbitMQ not available: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		i := 0
		for pb.Next() {
			job := &types.Job{
				ID: fmt.Sprintf("bench-job-%d", i),
				Route: types.Route{
					Steps:   []string{"bench-queue"},
					Current: 0,
				},
				Payload: map[string]interface{}{
					"iteration": i,
				},
			}

			if err := client.SendMessage(ctx, job); err != nil {
				b.Fatal(err)
			}
			i++
		}
	})
}

func BenchmarkRabbitMQClient_SendWithMutex(b *testing.B) {
	url := "amqp://guest:guest@localhost:5672/"
	client, err := NewRabbitMQClient(url, "bench-exchange")
	if err != nil {
		b.Skipf("Skipping benchmark - RabbitMQ not available: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		i := 0
		for pb.Next() {
			job := &types.Job{
				ID: fmt.Sprintf("bench-job-%d", i),
				Route: types.Route{
					Steps:   []string{"bench-queue"},
					Current: 0,
				},
				Payload: map[string]interface{}{
					"iteration": i,
				},
			}

			if err := client.SendMessage(ctx, job); err != nil {
				b.Fatal(err)
			}
			i++
		}
	})
}
