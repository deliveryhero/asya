# Transport Metrics Component Tests

Parametrized component tests for transport queue metrics functionality.

## Overview

These tests validate `GetQueueMetrics()` implementation across all transports using a fixture-based parametrized approach. The same test logic runs against all transports to ensure consistent behavior.

## Test Structure

- **`fixtures.go`**: Transport-specific test fixtures implementing `TransportFixture` interface
- **`metrics_test.go`**: Parametrized test cases that run against all fixtures

## Transport Fixtures

Each transport fixture implements:

- `Setup()`: Prepare transport for testing (create queues, etc.)
- `Teardown()`: Clean up after tests
- `GetConfig()`: Return transport config for metrics collection
- `PublishMessages()`: Publish test messages to verify metrics

## Running Tests

```bash
# Run all transport metrics component tests
cd testing/component/operator/transport_metrics
go test -tags=integration -v

# Run specific transport
go test -tags=integration -v -run TestGetQueueMetrics_Success/rabbitmq

# Run with environment configuration
RABBITMQ_HOST=localhost:5672 \
ASYA_SQS_ENDPOINT=http://localhost:9324 \
go test -tags=integration -v
```

## Test Cases

✅ **Success**: Validate metrics retrieval for existing queues
✅ **Queue Not Found**: Handle nonexistent queues gracefully
✅ **Empty Queue**: Verify 0/0 metrics for empty queues
✅ **With Messages**: Test metrics accuracy with ready/processing messages
✅ **Timeout**: Validate context timeout handling
✅ **Concurrent**: Test concurrent metrics collection

## Adding New Transports

To add a new transport (e.g., Kafka):

1. **Create fixture** in `fixtures.go`:
```go
type KafkaFixture struct {
    config *controller.KafkaConfig
}

func NewKafkaFixture() *KafkaFixture {
    // Read config from environment
    return &KafkaFixture{...}
}

func (f *KafkaFixture) Name() string { return "kafka" }
// Implement other TransportFixture methods
```

2. **Add to GetAllFixtures()**:
```go
func GetAllFixtures() []TransportFixture {
    return []TransportFixture{
        NewRabbitMQFixture(),
        NewSQSFixture(),
        NewKafkaFixture(),  // Add new transport
    }
}
```

3. **Run tests** - all parametrized tests automatically run for new transport

## Environment Variables

- `RABBITMQ_HOST`: RabbitMQ host (default: `localhost`)
- `ASYA_SQS_ENDPOINT`: SQS endpoint (default: `http://localhost:9324`)
- `AWS_REGION`: AWS region (default: `us-east-1`)

## Design Goals

- **Scalability**: Easily add new transports without duplicating test logic
- **Consistency**: Same tests ensure all transports behave identically
- **Isolation**: Each transport uses separate test queues
- **Flexibility**: Transport-specific behavior handled via fixtures
