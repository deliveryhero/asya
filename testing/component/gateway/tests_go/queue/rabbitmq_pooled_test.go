//go:build integration

package queue

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestRabbitMQClientPooled_SendMessage(t *testing.T) {
	url := getRabbitMQURL()
	client, err := queue.NewRabbitMQClientPooled(url, "test-exchange", 5)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	job := &types.Envelope{
		ID: "test-job-1",
		Route: types.Route{
			Actors:  []string{"test-queue"},
			Current: 0,
		},
		Payload: map[string]interface{}{
			"envelope": "test",
		},
	}

	err = client.SendEnvelope(ctx, job)
	if err != nil {
		t.Fatalf("Failed to send envelope: %v", err)
	}
}

func TestRabbitMQClientPooled_ConcurrentSend(t *testing.T) {
	url := getRabbitMQURL()
	poolSize := 10
	client, err := queue.NewRabbitMQClientPooled(url, "test-exchange", poolSize)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer client.Close()

	ctx := context.Background()
	numGoroutines := 100
	numMessages := 10

	var wg sync.WaitGroup
	errors := make(chan error, numGoroutines*numMessages)

	// Send many envelopes concurrently
	for i := 0; i < numGoroutines; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()

			for j := 0; j < numMessages; j++ {
				job := &types.Envelope{
					ID: fmt.Sprintf("job-%d-%d", id, j),
					Route: types.Route{
						Actors:  []string{"test-queue"},
						Current: 0,
					},
					Payload: map[string]interface{}{
						"goroutine": id,
						"envelope":  j,
					},
				}

				if err := client.SendEnvelope(ctx, job); err != nil {
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
	url := getRabbitMQURL()
	client, err := queue.NewRabbitMQClientPooled(url, "test-exchange", 5)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	deadline := time.Now().Add(5 * time.Minute)
	job := &types.Envelope{
		ID: "test-job-deadline",
		Route: types.Route{
			Actors:  []string{"test-queue"},
			Current: 0,
		},
		Payload: map[string]interface{}{
			"envelope": "test with deadline",
		},
		Deadline: deadline,
	}

	err = client.SendEnvelope(ctx, job)
	if err != nil {
		t.Fatalf("Failed to send envelope with deadline: %v", err)
	}
}

func TestRabbitMQClientPooled_SendEmptyRoute(t *testing.T) {
	url := getRabbitMQURL()
	client, err := queue.NewRabbitMQClientPooled(url, "test-exchange", 5)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	job := &types.Envelope{
		ID: "test-job-empty-route",
		Route: types.Route{
			Actors:  []string{}, // Empty route
			Current: 0,
		},
		Payload: map[string]interface{}{},
	}

	err = client.SendEnvelope(ctx, job)
	if err == nil {
		t.Error("Expected error for empty route, got nil")
	}
}

func TestRabbitMQClientPooled_ContextCancellation(t *testing.T) {
	url := getRabbitMQURL()
	client, err := queue.NewRabbitMQClientPooled(url, "test-exchange", 1)
	if err != nil {
		t.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer client.Close()

	// Create a cancelled context
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	job := &types.Envelope{
		ID: "test-job-cancel",
		Route: types.Route{
			Actors:  []string{"test-queue"},
			Current: 0,
		},
		Payload: map[string]interface{}{},
	}

	err = client.SendEnvelope(ctx, job)
	if err == nil {
		t.Error("Expected error with cancelled context")
	}
}

// Benchmark: Compare pooled vs mutex-based performance
func BenchmarkRabbitMQClientPooled_Send(b *testing.B) {
	url := getRabbitMQURL()
	client, err := queue.NewRabbitMQClientPooled(url, "bench-exchange", 10)
	if err != nil {
		b.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		i := 0
		for pb.Next() {
			job := &types.Envelope{
				ID: fmt.Sprintf("bench-job-%d", i),
				Route: types.Route{
					Actors:  []string{"bench-queue"},
					Current: 0,
				},
				Payload: map[string]interface{}{
					"iteration": i,
				},
			}

			if err := client.SendEnvelope(ctx, job); err != nil {
				b.Fatal(err)
			}
			i++
		}
	})
}

func BenchmarkRabbitMQClient_SendWithMutex(b *testing.B) {
	url := getRabbitMQURL()
	client, err := queue.NewRabbitMQClient(url, "bench-exchange")
	if err != nil {
		b.Fatalf("Failed to connect to RabbitMQ: %v", err)
	}
	defer client.Close()

	ctx := context.Background()

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		i := 0
		for pb.Next() {
			job := &types.Envelope{
				ID: fmt.Sprintf("bench-job-%d", i),
				Route: types.Route{
					Actors:  []string{"bench-queue"},
					Current: 0,
				},
				Payload: map[string]interface{}{
					"iteration": i,
				},
			}

			if err := client.SendEnvelope(ctx, job); err != nil {
				b.Fatal(err)
			}
			i++
		}
	})
}
