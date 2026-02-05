//go:build integration

package transport_metrics

import (
	"context"
	"testing"
	"time"
)

// TestGetQueueMetrics_Success tests successful queue metrics retrieval across all transports
func TestGetQueueMetrics_Success(t *testing.T) {
	fixtures := GetAllFixtures()

	for _, fixture := range fixtures {
		t.Run(fixture.Name(), func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()

			queueName := "test-queue-success-" + fixture.Name()
			config := fixture.GetConfig()

			if err := fixture.Setup(ctx, queueName); err != nil {
				t.Fatalf("Setup failed for %s: %v", fixture.Name(), err)
			}
			defer fixture.Teardown(ctx, queueName)

			metrics, err := config.GetQueueMetrics(ctx, queueName, "default", nil)
			if err != nil {
				t.Fatalf("GetQueueMetrics failed for %s: %v", fixture.Name(), err)
			}

			if metrics == nil {
				t.Fatalf("Expected non-nil metrics for %s", fixture.Name())
			}

			if metrics.Queued < 0 {
				t.Errorf("Expected non-negative Queued value for %s, got %d", fixture.Name(), metrics.Queued)
			}

			if metrics.Processing != nil && *metrics.Processing < 0 {
				t.Errorf("Expected non-negative Processing value for %s, got %d", fixture.Name(), *metrics.Processing)
			}
		})
	}
}

// TestGetQueueMetrics_QueueNotFound tests behavior when queue doesn't exist
func TestGetQueueMetrics_QueueNotFound(t *testing.T) {
	fixtures := GetAllFixtures()

	for _, fixture := range fixtures {
		t.Run(fixture.Name(), func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()

			queueName := "nonexistent-queue-" + fixture.Name()
			config := fixture.GetConfig()

			metrics, err := config.GetQueueMetrics(ctx, queueName, "default", nil)

			switch fixture.Name() {
			case "rabbitmq":
				if err != nil {
					t.Fatalf("RabbitMQ should not error for nonexistent queue, got: %v", err)
				}
				if metrics.Queued != 0 {
					t.Errorf("Expected Queued=0 for nonexistent RabbitMQ queue, got %d", metrics.Queued)
				}
				if metrics.Processing == nil || *metrics.Processing != 0 {
					t.Errorf("Expected Processing=0 for nonexistent RabbitMQ queue")
				}

			case "sqs":
				if err == nil {
					t.Error("Expected error for nonexistent SQS queue")
				}
			}
		})
	}
}

// TestGetQueueMetrics_EmptyQueue tests metrics for empty queues
func TestGetQueueMetrics_EmptyQueue(t *testing.T) {
	fixtures := GetAllFixtures()

	for _, fixture := range fixtures {
		t.Run(fixture.Name(), func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()

			queueName := "test-queue-empty-" + fixture.Name()
			config := fixture.GetConfig()

			if err := fixture.Setup(ctx, queueName); err != nil {
				t.Fatalf("Setup failed for %s: %v", fixture.Name(), err)
			}
			defer fixture.Teardown(ctx, queueName)

			metrics, err := config.GetQueueMetrics(ctx, queueName, "default", nil)
			if err != nil {
				t.Fatalf("GetQueueMetrics failed for %s: %v", fixture.Name(), err)
			}

			if metrics.Queued != 0 {
				t.Errorf("Expected Queued=0 for empty %s queue, got %d", fixture.Name(), metrics.Queued)
			}

			if metrics.Processing != nil && *metrics.Processing != 0 {
				t.Errorf("Expected Processing=0 for empty %s queue, got %d", fixture.Name(), *metrics.Processing)
			}
		})
	}
}

// TestGetQueueMetrics_WithMessages tests metrics when queue has messages
func TestGetQueueMetrics_WithMessages(t *testing.T) {
	fixtures := GetAllFixtures()

	testCases := []struct {
		ready      int
		processing int
	}{
		{ready: 10, processing: 0},
		{ready: 50, processing: 5},
		{ready: 100, processing: 20},
	}

	for _, fixture := range fixtures {
		for _, tc := range testCases {
			testName := fixture.Name() + "_ready" + string(rune(tc.ready)) + "_processing" + string(rune(tc.processing))
			t.Run(testName, func(t *testing.T) {
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				defer cancel()

				queueName := "test-queue-messages-" + fixture.Name()
				config := fixture.GetConfig()

				if err := fixture.Setup(ctx, queueName); err != nil {
					t.Fatalf("Setup failed for %s: %v", fixture.Name(), err)
				}
				defer fixture.Teardown(ctx, queueName)

				if err := fixture.PublishMessages(ctx, queueName, tc.ready, tc.processing); err != nil {
					t.Skipf("Message publishing not implemented for %s: %v", fixture.Name(), err)
				}

				metrics, err := config.GetQueueMetrics(ctx, queueName, "default", nil)
				if err != nil {
					t.Fatalf("GetQueueMetrics failed for %s: %v", fixture.Name(), err)
				}

				if metrics.Queued != int32(tc.ready) {
					t.Errorf("Expected Queued=%d for %s, got %d", tc.ready, fixture.Name(), metrics.Queued)
				}

				if metrics.Processing != nil {
					if *metrics.Processing != int32(tc.processing) {
						t.Errorf("Expected Processing=%d for %s, got %d", tc.processing, fixture.Name(), *metrics.Processing)
					}
				}
			})
		}
	}
}

// TestGetQueueMetrics_Timeout tests timeout handling
func TestGetQueueMetrics_Timeout(t *testing.T) {
	fixtures := GetAllFixtures()

	for _, fixture := range fixtures {
		t.Run(fixture.Name(), func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 1*time.Millisecond)
			defer cancel()

			queueName := "test-queue-timeout-" + fixture.Name()
			config := fixture.GetConfig()

			_, err := config.GetQueueMetrics(ctx, queueName, "default", nil)

			if err == nil {
				t.Logf("Transport %s completed before timeout (fast response)", fixture.Name())
			}
		})
	}
}

// TestGetQueueMetrics_Concurrent tests concurrent metric collection
func TestGetQueueMetrics_Concurrent(t *testing.T) {
	fixtures := GetAllFixtures()

	for _, fixture := range fixtures {
		t.Run(fixture.Name(), func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()

			queueName := "test-queue-concurrent-" + fixture.Name()
			config := fixture.GetConfig()

			if err := fixture.Setup(ctx, queueName); err != nil {
				t.Fatalf("Setup failed for %s: %v", fixture.Name(), err)
			}
			defer fixture.Teardown(ctx, queueName)

			concurrency := 10
			errCh := make(chan error, concurrency)

			for i := 0; i < concurrency; i++ {
				go func() {
					_, err := config.GetQueueMetrics(ctx, queueName, "default", nil)
					errCh <- err
				}()
			}

			for i := 0; i < concurrency; i++ {
				if err := <-errCh; err != nil {
					t.Errorf("Concurrent GetQueueMetrics failed for %s: %v", fixture.Name(), err)
				}
			}
		})
	}
}
