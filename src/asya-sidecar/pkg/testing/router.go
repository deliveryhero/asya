package testing

import (
	"context"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/router"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	internaltransport "github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/transport"
)

// EnvelopeProcessor is the interface for processing envelopes
type EnvelopeProcessor interface {
	ProcessEnvelope(ctx context.Context, msg transport.QueueMessage) error
}

// NewTestRouter creates a router for testing with the given configuration
func NewTestRouter(socketPath string, timeout time.Duration, mockTransport *MockTransport) EnvelopeProcessor {
	runtimeClient := runtime.NewClient(socketPath, timeout)

	cfg := &config.Config{
		ActorName:     "test-actor",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		SocketPath:    socketPath,
		Timeout:       timeout,
	}

	adapter := &mockTransportAdapter{mock: mockTransport}
	r := router.NewRouter(cfg, adapter, runtimeClient, nil)
	return &envelopeProcessor{router: r}
}

// envelopeProcessor adapts the internal router to the public EnvelopeProcessor interface
type envelopeProcessor struct {
	router *router.Router
}

func (ep *envelopeProcessor) ProcessEnvelope(ctx context.Context, msg transport.QueueMessage) error {
	internalMsg := internaltransport.QueueMessage{
		ID:            msg.ID,
		Body:          msg.Body,
		ReceiptHandle: msg.ReceiptHandle,
		Headers:       msg.Headers,
	}
	return ep.router.ProcessEnvelope(ctx, internalMsg)
}

// mockTransportAdapter adapts the public MockTransport to internal transport.Transport
type mockTransportAdapter struct {
	mock *MockTransport
}

func (mta *mockTransportAdapter) Receive(ctx context.Context, queueName string) (internaltransport.QueueMessage, error) {
	msg, err := mta.mock.Receive(ctx, queueName)
	if err != nil {
		return internaltransport.QueueMessage{}, err
	}
	return internaltransport.QueueMessage{
		ID:            msg.ID,
		Body:          msg.Body,
		ReceiptHandle: msg.ReceiptHandle,
		Headers:       msg.Headers,
	}, nil
}

func (mta *mockTransportAdapter) Send(ctx context.Context, queueName string, body []byte) error {
	return mta.mock.Send(ctx, queueName, body)
}

func (mta *mockTransportAdapter) Ack(ctx context.Context, msg internaltransport.QueueMessage) error {
	publicMsg := transport.QueueMessage{
		ID:            msg.ID,
		Body:          msg.Body,
		ReceiptHandle: msg.ReceiptHandle,
		Headers:       msg.Headers,
	}
	return mta.mock.Ack(ctx, publicMsg)
}

func (mta *mockTransportAdapter) Nack(ctx context.Context, msg internaltransport.QueueMessage) error {
	publicMsg := transport.QueueMessage{
		ID:            msg.ID,
		Body:          msg.Body,
		ReceiptHandle: msg.ReceiptHandle,
		Headers:       msg.Headers,
	}
	return mta.mock.Nack(ctx, publicMsg)
}

func (mta *mockTransportAdapter) Close() error {
	return mta.mock.Close()
}
