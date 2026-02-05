package testing

import (
	"context"
	"fmt"
	"sync"

	"github.com/deliveryhero/asya/asya-sidecar/pkg/transport"
)

// MockTransport is a mock implementation of transport.Transport for testing
type MockTransport struct {
	mu       sync.RWMutex
	messages map[string][]QueuedMessage
	nextID   int
}

// QueuedMessage represents a message in the mock queue
type QueuedMessage struct {
	ID   string
	Body []byte
}

// NewMockTransport creates a new mock transport
func NewMockTransport() *MockTransport {
	return &MockTransport{
		messages: make(map[string][]QueuedMessage),
		nextID:   1,
	}
}

// Receive returns a mock message (not used in socket integration tests)
func (m *MockTransport) Receive(ctx context.Context, queueName string) (transport.QueueMessage, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	messages, exists := m.messages[queueName]
	if !exists || len(messages) == 0 {
		return transport.QueueMessage{}, fmt.Errorf("no messages in queue %s", queueName)
	}

	msg := messages[0]
	return transport.QueueMessage{
		ID:   msg.ID,
		Body: msg.Body,
	}, nil
}

// Send stores a message in the mock queue
func (m *MockTransport) Send(ctx context.Context, queueName string, body []byte) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	msgID := fmt.Sprintf("msg-%d", m.nextID)
	m.nextID++

	msg := QueuedMessage{
		ID:   msgID,
		Body: body,
	}

	m.messages[queueName] = append(m.messages[queueName], msg)
	return nil
}

// Ack acknowledges a message (no-op for mock)
func (m *MockTransport) Ack(ctx context.Context, msg transport.QueueMessage) error {
	return nil
}

// Nack negatively acknowledges a message (no-op for mock)
func (m *MockTransport) Nack(ctx context.Context, msg transport.QueueMessage) error {
	return nil
}

// Close closes the transport (no-op for mock)
func (m *MockTransport) Close() error {
	return nil
}

// GetMessages returns all messages sent to a specific queue
func (m *MockTransport) GetMessages(queueName string) []QueuedMessage {
	m.mu.RLock()
	defer m.mu.RUnlock()

	messages, exists := m.messages[queueName]
	if !exists {
		return nil
	}

	result := make([]QueuedMessage, len(messages))
	copy(result, messages)
	return result
}

// GetMessageCount returns the number of messages in a queue
func (m *MockTransport) GetMessageCount(queueName string) int {
	m.mu.RLock()
	defer m.mu.RUnlock()

	messages, exists := m.messages[queueName]
	if !exists {
		return 0
	}
	return len(messages)
}

// ClearQueue removes all messages from a queue
func (m *MockTransport) ClearQueue(queueName string) {
	m.mu.Lock()
	defer m.mu.Unlock()

	delete(m.messages, queueName)
}

// ClearAll removes all messages from all queues
func (m *MockTransport) ClearAll() {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.messages = make(map[string][]QueuedMessage)
	m.nextID = 1
}
