package transport

import (
	"context"
	"errors"
	"testing"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// mockRabbitMQConnection is a mock implementation of rabbitmqConnection for testing
type mockRabbitMQConnection struct {
	channelFunc func() (*amqp.Channel, error)
	closeFunc   func() error
}

func (m *mockRabbitMQConnection) Channel() (*amqp.Channel, error) {
	if m.channelFunc != nil {
		return m.channelFunc()
	}
	return nil, nil
}

func (m *mockRabbitMQConnection) Close() error {
	if m.closeFunc != nil {
		return m.closeFunc()
	}
	return nil
}

// mockRabbitMQChannel is a mock implementation of rabbitmqChannel for testing
type mockRabbitMQChannel struct {
	qosFunc                  func(prefetchCount, prefetchSize int, global bool) error
	exchangeDeclareFunc      func(name, kind string, durable, autoDelete, internal, noWait bool, args amqp.Table) error
	queueDeclareFunc         func(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error)
	queueDeclarePassiveFunc  func(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error)
	queueBindFunc            func(name, key, exchange string, noWait bool, args amqp.Table) error
	consumeFunc              func(queue, consumer string, autoAck, exclusive, noLocal, noWait bool, args amqp.Table) (<-chan amqp.Delivery, error)
	publishWithContextFunc   func(ctx context.Context, exchange, key string, mandatory, immediate bool, msg amqp.Publishing) error
	ackFunc                  func(tag uint64, multiple bool) error
	nackFunc                 func(tag uint64, multiple, requeue bool) error
	closeFunc                func() error
	deliveryChan             chan amqp.Delivery
	closeChanOnConsumeCancel bool
}

func (m *mockRabbitMQChannel) Qos(prefetchCount, prefetchSize int, global bool) error {
	if m.qosFunc != nil {
		return m.qosFunc(prefetchCount, prefetchSize, global)
	}
	return nil
}

func (m *mockRabbitMQChannel) ExchangeDeclare(name, kind string, durable, autoDelete, internal, noWait bool, args amqp.Table) error {
	if m.exchangeDeclareFunc != nil {
		return m.exchangeDeclareFunc(name, kind, durable, autoDelete, internal, noWait, args)
	}
	return nil
}

func (m *mockRabbitMQChannel) QueueDeclare(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error) {
	if m.queueDeclareFunc != nil {
		return m.queueDeclareFunc(name, durable, autoDelete, exclusive, noWait, args)
	}
	return amqp.Queue{Name: name}, nil
}

func (m *mockRabbitMQChannel) QueueDeclarePassive(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error) {
	if m.queueDeclarePassiveFunc != nil {
		return m.queueDeclarePassiveFunc(name, durable, autoDelete, exclusive, noWait, args)
	}
	return amqp.Queue{Name: name}, nil
}

func (m *mockRabbitMQChannel) QueueBind(name, key, exchange string, noWait bool, args amqp.Table) error {
	if m.queueBindFunc != nil {
		return m.queueBindFunc(name, key, exchange, noWait, args)
	}
	return nil
}

func (m *mockRabbitMQChannel) Consume(queue, consumer string, autoAck, exclusive, noLocal, noWait bool, args amqp.Table) (<-chan amqp.Delivery, error) {
	if m.consumeFunc != nil {
		return m.consumeFunc(queue, consumer, autoAck, exclusive, noLocal, noWait, args)
	}
	if m.deliveryChan != nil {
		if m.closeChanOnConsumeCancel {
			go func() {
				close(m.deliveryChan)
			}()
		}
		return m.deliveryChan, nil
	}
	return make(<-chan amqp.Delivery), nil
}

func (m *mockRabbitMQChannel) PublishWithContext(ctx context.Context, exchange, key string, mandatory, immediate bool, msg amqp.Publishing) error {
	if m.publishWithContextFunc != nil {
		return m.publishWithContextFunc(ctx, exchange, key, mandatory, immediate, msg)
	}
	return nil
}

func (m *mockRabbitMQChannel) Ack(tag uint64, multiple bool) error {
	if m.ackFunc != nil {
		return m.ackFunc(tag, multiple)
	}
	return nil
}

func (m *mockRabbitMQChannel) Nack(tag uint64, multiple, requeue bool) error {
	if m.nackFunc != nil {
		return m.nackFunc(tag, multiple, requeue)
	}
	return nil
}

func (m *mockRabbitMQChannel) Close() error {
	if m.closeFunc != nil {
		return m.closeFunc()
	}
	return nil
}

// createMockRabbitMQTransport creates a RabbitMQTransport with mock connection/channel for testing
func createMockRabbitMQTransport(mockConn rabbitmqConnection, mockChannel rabbitmqChannel) *RabbitMQTransport {
	// For amqpChannel, use the real channel if it's provided and is of the right type
	var amqpChan *amqp.Channel
	if ch, ok := mockChannel.(*amqp.Channel); ok {
		amqpChan = ch
	}

	return &RabbitMQTransport{
		conn:          mockConn,
		channel:       mockChannel,
		exchange:      "test-exchange",
		prefetchCount: 1,
		amqpChannel:   amqpChan,
	}
}

func TestRabbitMQTransport_EnsureQueue(t *testing.T) {
	queueName := testQueueName

	t.Run("successful queue existence check", func(t *testing.T) {
		queueChecked := false

		mockChannel := &mockRabbitMQChannel{
			queueDeclarePassiveFunc: func(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error) {
				if name != queueName {
					t.Errorf("QueueDeclarePassive name = %v, want %v", name, queueName)
				}
				if !durable {
					t.Error("QueueDeclarePassive durable = false, want true")
				}
				queueChecked = true
				return amqp.Queue{Name: name}, nil
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		err := transport.ensureQueue(queueName)
		if err != nil {
			t.Errorf("ensureQueue() error = %v, want nil", err)
		}
		if !queueChecked {
			t.Error("QueueDeclarePassive was not called")
		}
	})

	t.Run("queue does not exist", func(t *testing.T) {
		mockChannel := &mockRabbitMQChannel{
			queueDeclarePassiveFunc: func(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error) {
				return amqp.Queue{}, errors.New("queue not found")
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		err := transport.ensureQueue(queueName)
		if err == nil {
			t.Error("ensureQueue() error = nil, want error")
		}
	})

}

func TestRabbitMQTransport_Receive(t *testing.T) {
	ctx := context.Background()
	queueName := testQueueName

	t.Run("receive message with headers", func(t *testing.T) {
		deliveryChan := make(chan amqp.Delivery, 1)
		deliveryChan <- amqp.Delivery{
			MessageId:   "msg-123",
			Body:        []byte(`{"test":"message"}`),
			DeliveryTag: uint64(42),
			Headers: amqp.Table{
				"trace_id": "trace-xyz",
				"priority": "high",
			},
		}

		mockChannel := &mockRabbitMQChannel{
			deliveryChan: deliveryChan,
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		msg, err := transport.Receive(ctx, queueName)
		if err != nil {
			t.Errorf("Receive() error = %v, want nil", err)
		}

		if msg.ID != "msg-123" {
			t.Errorf("ID = %v, want msg-123", msg.ID)
		}
		if string(msg.Body) != `{"test":"message"}` {
			t.Errorf("Body = %v, want {\"test\":\"message\"}", string(msg.Body))
		}
		if msg.ReceiptHandle != uint64(42) {
			t.Errorf("ReceiptHandle = %v, want 42", msg.ReceiptHandle)
		}
		if msg.Headers["trace_id"] != "trace-xyz" {
			t.Errorf("Headers[trace_id] = %v, want trace-xyz", msg.Headers["trace_id"])
		}
		if msg.Headers["QueueName"] != queueName {
			t.Errorf("Headers[QueueName] = %v, want %v", msg.Headers["QueueName"], queueName)
		}
	})

	t.Run("context cancellation", func(t *testing.T) {
		deliveryChan := make(chan amqp.Delivery)

		mockChannel := &mockRabbitMQChannel{
			deliveryChan: deliveryChan,
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		cancelCtx, cancel := context.WithCancel(ctx)
		cancel()

		_, err := transport.Receive(cancelCtx, queueName)
		if err != context.Canceled {
			t.Errorf("Receive() error = %v, want context.Canceled", err)
		}
	})

	t.Run("channel closed", func(t *testing.T) {
		mockChannel := &mockRabbitMQChannel{
			closeChanOnConsumeCancel: true,
			deliveryChan:             make(chan amqp.Delivery),
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		_, err := transport.Receive(ctx, queueName)
		if err == nil {
			t.Error("Receive() error = nil, want channel closed error")
		}
	})

	t.Run("consume initialization failure", func(t *testing.T) {
		t.Setenv("ASYA_QUEUE_RETRY_MAX_ATTEMPTS", "2")
		t.Setenv("ASYA_QUEUE_RETRY_BACKOFF", "10ms")

		mockChannel := &mockRabbitMQChannel{
			consumeFunc: func(queue, consumer string, autoAck, exclusive, noLocal, noWait bool, args amqp.Table) (<-chan amqp.Delivery, error) {
				return nil, errors.New("consume failed")
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		_, err := transport.Receive(ctx, queueName)
		if err == nil {
			t.Error("Receive() error = nil, want consume error")
		}
	})
}

func TestRabbitMQTransport_Send(t *testing.T) {
	ctx := context.Background()
	queueName := testQueueName
	exchange := "test-exchange"
	messageBody := []byte(`{"test":"message"}`)

	t.Run("successful send", func(t *testing.T) {
		publishCalled := false

		mockChannel := &mockRabbitMQChannel{
			publishWithContextFunc: func(ctx context.Context, ex, key string, mandatory, immediate bool, msg amqp.Publishing) error {
				if ex != exchange {
					t.Errorf("exchange = %v, want %v", ex, exchange)
				}
				if key != queueName {
					t.Errorf("routing key = %v, want %v", key, queueName)
				}
				if string(msg.Body) != string(messageBody) {
					t.Errorf("Body = %v, want %v", string(msg.Body), string(messageBody))
				}
				if msg.DeliveryMode != amqp.Persistent {
					t.Error("DeliveryMode != Persistent")
				}
				if msg.ContentType != "application/json" {
					t.Errorf("ContentType = %v, want application/json", msg.ContentType)
				}
				publishCalled = true
				return nil
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		err := transport.Send(ctx, queueName, messageBody)
		if err != nil {
			t.Errorf("Send() error = %v, want nil", err)
		}
		if !publishCalled {
			t.Error("PublishWithContext was not called")
		}
	})

	t.Run("publish failure", func(t *testing.T) {
		mockChannel := &mockRabbitMQChannel{
			publishWithContextFunc: func(ctx context.Context, ex, key string, mandatory, immediate bool, msg amqp.Publishing) error {
				return errors.New("publish failed")
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		err := transport.Send(ctx, queueName, messageBody)
		if err == nil {
			t.Error("Send() error = nil, want error")
		}
	})

	t.Run("queue ensure failure", func(t *testing.T) {
		mockChannel := &mockRabbitMQChannel{
			queueDeclarePassiveFunc: func(name string, durable, autoDelete, exclusive, noWait bool, args amqp.Table) (amqp.Queue, error) {
				return amqp.Queue{}, errors.New("queue does not exist")
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		err := transport.Send(ctx, queueName, messageBody)
		if err == nil {
			t.Error("Send() error = nil, want queue ensure error")
		}
	})
}

func TestRabbitMQTransport_Ack(t *testing.T) {
	ctx := context.Background()
	deliveryTag := uint64(42)

	t.Run("successful ack", func(t *testing.T) {
		ackCalled := false

		mockChannel := &mockRabbitMQChannel{
			ackFunc: func(tag uint64, multiple bool) error {
				if tag != deliveryTag {
					t.Errorf("tag = %v, want %v", tag, deliveryTag)
				}
				if multiple {
					t.Error("multiple = true, want false")
				}
				ackCalled = true
				return nil
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		msg := QueueMessage{
			ReceiptHandle: deliveryTag,
		}

		err := transport.Ack(ctx, msg)
		if err != nil {
			t.Errorf("Ack() error = %v, want nil", err)
		}
		if !ackCalled {
			t.Error("Ack was not called")
		}
	})

	t.Run("invalid receipt handle type", func(t *testing.T) {
		transport := createMockRabbitMQTransport(nil, &mockRabbitMQChannel{})

		msg := QueueMessage{
			ReceiptHandle: "invalid-type",
		}

		err := transport.Ack(ctx, msg)
		if err == nil {
			t.Error("Ack() error = nil, want type error")
		}
	})

	t.Run("ack failure", func(t *testing.T) {
		mockChannel := &mockRabbitMQChannel{
			ackFunc: func(tag uint64, multiple bool) error {
				return errors.New("ack failed")
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		msg := QueueMessage{
			ReceiptHandle: deliveryTag,
		}

		err := transport.Ack(ctx, msg)
		if err == nil {
			t.Error("Ack() error = nil, want error")
		}
	})
}

func TestRabbitMQTransport_Nack(t *testing.T) {
	ctx := context.Background()
	deliveryTag := uint64(42)

	t.Run("successful nack with requeue", func(t *testing.T) {
		nackCalled := false

		mockChannel := &mockRabbitMQChannel{
			nackFunc: func(tag uint64, multiple, requeue bool) error {
				if tag != deliveryTag {
					t.Errorf("tag = %v, want %v", tag, deliveryTag)
				}
				if multiple {
					t.Error("multiple = true, want false")
				}
				if !requeue {
					t.Error("requeue = false, want true")
				}
				nackCalled = true
				return nil
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		msg := QueueMessage{
			ReceiptHandle: deliveryTag,
		}

		err := transport.Nack(ctx, msg)
		if err != nil {
			t.Errorf("Nack() error = %v, want nil", err)
		}
		if !nackCalled {
			t.Error("Nack was not called")
		}
	})

	t.Run("invalid receipt handle type", func(t *testing.T) {
		transport := createMockRabbitMQTransport(nil, &mockRabbitMQChannel{})

		msg := QueueMessage{
			ReceiptHandle: "invalid-type",
		}

		err := transport.Nack(ctx, msg)
		if err == nil {
			t.Error("Nack() error = nil, want type error")
		}
	})

	t.Run("nack failure", func(t *testing.T) {
		mockChannel := &mockRabbitMQChannel{
			nackFunc: func(tag uint64, multiple, requeue bool) error {
				return errors.New("nack failed")
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		msg := QueueMessage{
			ReceiptHandle: deliveryTag,
		}

		err := transport.Nack(ctx, msg)
		if err == nil {
			t.Error("Nack() error = nil, want error")
		}
	})
}

func TestRabbitMQTransport_Close(t *testing.T) {
	t.Run("successful close", func(t *testing.T) {
		channelClosed := false
		connClosed := false

		mockChannel := &mockRabbitMQChannel{
			closeFunc: func() error {
				channelClosed = true
				return nil
			},
		}

		mockConn := &mockRabbitMQConnection{
			closeFunc: func() error {
				connClosed = true
				return nil
			},
		}

		transport := createMockRabbitMQTransport(mockConn, mockChannel)

		err := transport.Close()
		if err != nil {
			t.Errorf("Close() error = %v, want nil", err)
		}
		if !channelClosed {
			t.Error("Channel.Close was not called")
		}
		if !connClosed {
			t.Error("Connection.Close was not called")
		}
	})

	t.Run("channel close failure", func(t *testing.T) {
		mockChannel := &mockRabbitMQChannel{
			closeFunc: func() error {
				return errors.New("channel close failed")
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		err := transport.Close()
		if err == nil {
			t.Error("Close() error = nil, want error")
		}
	})

	t.Run("connection close failure", func(t *testing.T) {
		mockChannel := &mockRabbitMQChannel{
			closeFunc: func() error {
				return nil
			},
		}

		mockConn := &mockRabbitMQConnection{
			closeFunc: func() error {
				return errors.New("connection close failed")
			},
		}

		transport := createMockRabbitMQTransport(mockConn, mockChannel)

		err := transport.Close()
		if err == nil {
			t.Error("Close() error = nil, want error")
		}
	})
}

func TestRabbitMQTransport_ReceiveConsumerCaching(t *testing.T) {
	ctx := context.Background()
	queueName := testQueueName

	t.Run("consumer reused for same queue", func(t *testing.T) {
		consumeCallCount := 0

		deliveryChan := make(chan amqp.Delivery, 2)
		deliveryChan <- amqp.Delivery{
			MessageId:   "msg-1",
			Body:        []byte("message-1"),
			DeliveryTag: uint64(1),
		}
		deliveryChan <- amqp.Delivery{
			MessageId:   "msg-2",
			Body:        []byte("message-2"),
			DeliveryTag: uint64(2),
		}

		mockChannel := &mockRabbitMQChannel{
			consumeFunc: func(queue, consumer string, autoAck, exclusive, noLocal, noWait bool, args amqp.Table) (<-chan amqp.Delivery, error) {
				consumeCallCount++
				return deliveryChan, nil
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		msg1, err := transport.Receive(ctx, queueName)
		if err != nil {
			t.Errorf("First Receive() error = %v, want nil", err)
		}
		if msg1.ID != "msg-1" {
			t.Errorf("First message ID = %v, want msg-1", msg1.ID)
		}

		msg2, err := transport.Receive(ctx, queueName)
		if err != nil {
			t.Errorf("Second Receive() error = %v, want nil", err)
		}
		if msg2.ID != "msg-2" {
			t.Errorf("Second message ID = %v, want msg-2", msg2.ID)
		}

		if consumeCallCount != 1 {
			t.Errorf("Consume call count = %v, want 1 (consumer should be reused)", consumeCallCount)
		}
	})
}

func TestRabbitMQTransport_SendTimestamp(t *testing.T) {
	ctx := context.Background()
	queueName := testQueueName
	messageBody := []byte(`{"test":"message"}`)

	t.Run("timestamp is set on publish", func(t *testing.T) {
		beforeTime := time.Now()
		var publishedTime time.Time

		mockChannel := &mockRabbitMQChannel{
			publishWithContextFunc: func(ctx context.Context, ex, key string, mandatory, immediate bool, msg amqp.Publishing) error {
				publishedTime = msg.Timestamp
				return nil
			},
		}

		transport := createMockRabbitMQTransport(nil, mockChannel)

		err := transport.Send(ctx, queueName, messageBody)
		if err != nil {
			t.Errorf("Send() error = %v, want nil", err)
		}

		afterTime := time.Now()

		if publishedTime.Before(beforeTime) || publishedTime.After(afterTime) {
			t.Errorf("Timestamp %v not in expected range [%v, %v]", publishedTime, beforeTime, afterTime)
		}
	})
}
