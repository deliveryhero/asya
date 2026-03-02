package transport

import (
	"context"
	"errors"
	"testing"
)

// mockPubSubMessage is a mock implementation of pubsubMessage for testing
type mockPubSubMessage struct {
	id         string
	data       []byte
	attributes map[string]string
	ackFunc    func()
	nackFunc   func()
}

func (m *mockPubSubMessage) ID() string                    { return m.id }
func (m *mockPubSubMessage) Data() []byte                  { return m.data }
func (m *mockPubSubMessage) Attributes() map[string]string { return m.attributes }
func (m *mockPubSubMessage) Ack() {
	if m.ackFunc != nil {
		m.ackFunc()
	}
}
func (m *mockPubSubMessage) Nack() {
	if m.nackFunc != nil {
		m.nackFunc()
	}
}

// mockPubSubClient is a mock implementation of pubsubClient for testing
type mockPubSubClient struct {
	publishFunc func(ctx context.Context, topicID string, data []byte, attributes map[string]string) (string, error)
	pullFunc    func(ctx context.Context, subscriptionID string) (pubsubMessage, error)
	closeFunc   func() error
}

func (m *mockPubSubClient) Publish(ctx context.Context, topicID string, data []byte, attributes map[string]string) (string, error) {
	if m.publishFunc != nil {
		return m.publishFunc(ctx, topicID, data, attributes)
	}
	return "", nil
}

func (m *mockPubSubClient) Pull(ctx context.Context, subscriptionID string) (pubsubMessage, error) {
	if m.pullFunc != nil {
		return m.pullFunc(ctx, subscriptionID)
	}
	return nil, nil
}

func (m *mockPubSubClient) Close() error {
	if m.closeFunc != nil {
		return m.closeFunc()
	}
	return nil
}

// createMockPubSubTransport creates a PubSubTransport with a mock client for testing
func createMockPubSubTransport(mockClient *mockPubSubClient) *PubSubTransport {
	return &PubSubTransport{
		client:    mockClient,
		projectID: "test-project",
	}
}

func TestPubSubTransport_Send(t *testing.T) {
	ctx := context.Background()
	topicName := "test-topic"
	messageBody := []byte(`{"test":"message"}`)

	t.Run("successful send", func(t *testing.T) {
		mockClient := &mockPubSubClient{
			publishFunc: func(ctx context.Context, topicID string, data []byte, attributes map[string]string) (string, error) {
				if topicID != topicName {
					t.Errorf("topicID = %v, want %v", topicID, topicName)
				}
				if string(data) != string(messageBody) {
					t.Errorf("data = %v, want %v", string(data), string(messageBody))
				}
				if attributes != nil {
					t.Errorf("attributes = %v, want nil", attributes)
				}
				return "msg-123", nil
			},
		}

		transport := createMockPubSubTransport(mockClient)

		err := transport.Send(ctx, topicName, messageBody)
		if err != nil {
			t.Errorf("Send() error = %v, want nil", err)
		}
	})

	t.Run("publish error", func(t *testing.T) {
		mockClient := &mockPubSubClient{
			publishFunc: func(ctx context.Context, topicID string, data []byte, attributes map[string]string) (string, error) {
				return "", errors.New("publish failed")
			},
		}

		transport := createMockPubSubTransport(mockClient)

		err := transport.Send(ctx, topicName, messageBody)
		if err == nil {
			t.Error("Send() error = nil, want error")
		}
	})
}

func TestPubSubTransport_Receive(t *testing.T) {
	ctx := context.Background()
	subscriptionName := "test-subscription"

	t.Run("receive message with attributes", func(t *testing.T) {
		mockMsg := &mockPubSubMessage{
			id:   "msg-123",
			data: []byte(`{"test":"message"}`),
			attributes: map[string]string{
				"trace_id": "trace-xyz",
			},
		}

		mockClient := &mockPubSubClient{
			pullFunc: func(ctx context.Context, subscriptionID string) (pubsubMessage, error) {
				if subscriptionID != subscriptionName {
					t.Errorf("subscriptionID = %v, want %v", subscriptionID, subscriptionName)
				}
				return mockMsg, nil
			},
		}

		transport := createMockPubSubTransport(mockClient)

		msg, err := transport.Receive(ctx, subscriptionName)
		if err != nil {
			t.Errorf("Receive() error = %v, want nil", err)
		}
		if msg.ID != "msg-123" {
			t.Errorf("ID = %v, want msg-123", msg.ID)
		}
		if string(msg.Body) != `{"test":"message"}` {
			t.Errorf("Body = %v, want {\"test\":\"message\"}", string(msg.Body))
		}
		if msg.Headers["trace_id"] != "trace-xyz" {
			t.Errorf("Headers[trace_id] = %v, want trace-xyz", msg.Headers["trace_id"])
		}
		if msg.Headers["QueueName"] != subscriptionName {
			t.Errorf("Headers[QueueName] = %v, want %v", msg.Headers["QueueName"], subscriptionName)
		}

		// Verify receipt handle stores the pubsubMessage
		_, ok := msg.ReceiptHandle.(pubsubMessage)
		if !ok {
			t.Errorf("ReceiptHandle type = %T, want pubsubMessage", msg.ReceiptHandle)
		}
	})

	t.Run("receive message without attributes", func(t *testing.T) {
		mockMsg := &mockPubSubMessage{
			id:         "msg-456",
			data:       []byte(`{"data":"value"}`),
			attributes: nil,
		}

		mockClient := &mockPubSubClient{
			pullFunc: func(ctx context.Context, subscriptionID string) (pubsubMessage, error) {
				return mockMsg, nil
			},
		}

		transport := createMockPubSubTransport(mockClient)

		msg, err := transport.Receive(ctx, subscriptionName)
		if err != nil {
			t.Errorf("Receive() error = %v, want nil", err)
		}
		if msg.ID != "msg-456" {
			t.Errorf("ID = %v, want msg-456", msg.ID)
		}
		if msg.Headers["QueueName"] != subscriptionName {
			t.Errorf("Headers[QueueName] = %v, want %v", msg.Headers["QueueName"], subscriptionName)
		}
	})
}

func TestPubSubTransport_Receive_ContextCancellation(t *testing.T) {
	ctx := context.Background()

	t.Run("context cancelled", func(t *testing.T) {
		mockClient := &mockPubSubClient{
			pullFunc: func(ctx context.Context, subscriptionID string) (pubsubMessage, error) {
				return nil, context.Canceled
			},
		}

		transport := createMockPubSubTransport(mockClient)

		cancelCtx, cancel := context.WithCancel(ctx)
		cancel()

		_, err := transport.Receive(cancelCtx, "test-subscription")
		if err == nil {
			t.Error("Receive() error = nil, want error")
		}
	})
}

func TestPubSubTransport_Ack(t *testing.T) {
	ctx := context.Background()

	t.Run("successful ack", func(t *testing.T) {
		acked := false
		mockMsg := &mockPubSubMessage{
			id: "msg-123",
			ackFunc: func() {
				acked = true
			},
		}

		transport := createMockPubSubTransport(&mockPubSubClient{})

		msg := QueueMessage{
			ID:            "msg-123",
			ReceiptHandle: mockMsg,
		}

		err := transport.Ack(ctx, msg)
		if err != nil {
			t.Errorf("Ack() error = %v, want nil", err)
		}
		if !acked {
			t.Error("Ack() did not call message Ack()")
		}
	})

	t.Run("invalid receipt handle type", func(t *testing.T) {
		transport := createMockPubSubTransport(&mockPubSubClient{})

		msg := QueueMessage{
			ID:            "msg-123",
			ReceiptHandle: "invalid-type",
		}

		err := transport.Ack(ctx, msg)
		if err == nil {
			t.Error("Ack() error = nil, want error for invalid receipt handle type")
		}
	})
}

func TestPubSubTransport_Requeue(t *testing.T) {
	ctx := context.Background()

	t.Run("successful requeue", func(t *testing.T) {
		nacked := false
		mockMsg := &mockPubSubMessage{
			id: "msg-123",
			nackFunc: func() {
				nacked = true
			},
		}

		transport := createMockPubSubTransport(&mockPubSubClient{})

		msg := QueueMessage{
			ID:            "msg-123",
			ReceiptHandle: mockMsg,
		}

		err := transport.Requeue(ctx, msg)
		if err != nil {
			t.Errorf("Requeue() error = %v, want nil", err)
		}
		if !nacked {
			t.Error("Requeue() did not call message Nack()")
		}
	})

	t.Run("invalid receipt handle type", func(t *testing.T) {
		transport := createMockPubSubTransport(&mockPubSubClient{})

		msg := QueueMessage{
			ID:            "msg-123",
			ReceiptHandle: 123,
		}

		err := transport.Requeue(ctx, msg)
		if err == nil {
			t.Error("Requeue() error = nil, want error for invalid receipt handle type")
		}
	})
}

func TestPubSubTransport_SendWithDelay(t *testing.T) {
	ctx := context.Background()

	t.Run("returns ErrDelayNotSupported", func(t *testing.T) {
		transport := createMockPubSubTransport(&mockPubSubClient{})

		err := transport.SendWithDelay(ctx, "test-topic", []byte("test"), 30)
		if !errors.Is(err, ErrDelayNotSupported) {
			t.Errorf("SendWithDelay() error = %v, want ErrDelayNotSupported", err)
		}
	})
}

func TestPubSubTransport_Close(t *testing.T) {
	t.Run("successful close", func(t *testing.T) {
		closed := false
		mockClient := &mockPubSubClient{
			closeFunc: func() error {
				closed = true
				return nil
			},
		}

		transport := createMockPubSubTransport(mockClient)

		err := transport.Close()
		if err != nil {
			t.Errorf("Close() error = %v, want nil", err)
		}
		if !closed {
			t.Error("Close() did not call client Close()")
		}
	})

	t.Run("close error", func(t *testing.T) {
		mockClient := &mockPubSubClient{
			closeFunc: func() error {
				return errors.New("close failed")
			},
		}

		transport := createMockPubSubTransport(mockClient)

		err := transport.Close()
		if err == nil {
			t.Error("Close() error = nil, want error")
		}
	})
}
