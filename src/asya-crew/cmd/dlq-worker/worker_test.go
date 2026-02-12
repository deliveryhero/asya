package main

import (
	"context"
	"errors"
	"testing"
)

// --- Test doubles ---

type fakeConsumer struct {
	messages []*DLQMessage
	idx      int
	acked    []*DLQMessage
}

func (f *fakeConsumer) Receive(ctx context.Context) (*DLQMessage, error) {
	if f.idx >= len(f.messages) {
		<-ctx.Done()
		return nil, ctx.Err()
	}
	msg := f.messages[f.idx]
	f.idx++
	return msg, nil
}

func (f *fakeConsumer) Ack(_ context.Context, msg *DLQMessage) error {
	f.acked = append(f.acked, msg)
	return nil
}

func (f *fakeConsumer) Close() error { return nil }

type fakeGateway struct {
	reported []string
	err      error
}

func (f *fakeGateway) ReportFailure(_ context.Context, taskID, _ string) error {
	f.reported = append(f.reported, taskID)
	return f.err
}

type fakeStorage struct {
	persisted map[string][]byte
	err       error
}

func (f *fakeStorage) Persist(_ context.Context, messageID string, body []byte) error {
	if f.err != nil {
		return f.err
	}
	f.persisted[messageID] = body
	return nil
}

// --- Tests ---

func TestWorker_ProcessesMessage(t *testing.T) {
	consumer := &fakeConsumer{
		messages: []*DLQMessage{
			{Body: []byte(`{"id":"msg-001","payload":{"data":"test"}}`), ReceiptHandle: "r1"},
		},
	}
	gateway := &fakeGateway{}
	storage := &fakeStorage{persisted: make(map[string][]byte)}

	worker := NewWorker(consumer, gateway, storage)

	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		// Cancel after first message is processed
		for len(consumer.acked) == 0 {
			// busy wait
		}
		cancel()
	}()

	_ = worker.Run(ctx)

	// Verify gateway was called
	if len(gateway.reported) != 1 || gateway.reported[0] != "msg-001" {
		t.Errorf("gateway reported = %v", gateway.reported)
	}

	// Verify S3 persistence
	if _, ok := storage.persisted["msg-001"]; !ok {
		t.Error("message not persisted to S3")
	}

	// Verify ACK
	if len(consumer.acked) != 1 {
		t.Errorf("acked = %d, want 1", len(consumer.acked))
	}
}

func TestWorker_MalformedMessage_StillAcks(t *testing.T) {
	consumer := &fakeConsumer{
		messages: []*DLQMessage{
			{Body: []byte(`not-json`), ReceiptHandle: "r1"},
		},
	}
	gateway := &fakeGateway{}
	storage := &fakeStorage{persisted: make(map[string][]byte)}

	worker := NewWorker(consumer, gateway, storage)

	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		for len(consumer.acked) == 0 {
		}
		cancel()
	}()

	_ = worker.Run(ctx)

	// Malformed messages should be ACKed to prevent infinite redelivery
	if len(consumer.acked) != 1 {
		t.Errorf("acked = %d, want 1 (malformed should be ACKed)", len(consumer.acked))
	}

	// Should NOT have called gateway or storage
	if len(gateway.reported) != 0 {
		t.Errorf("gateway should not be called for malformed messages")
	}
	if len(storage.persisted) != 0 {
		t.Errorf("storage should not be called for malformed messages")
	}
}

func TestWorker_MissingID_StillAcks(t *testing.T) {
	consumer := &fakeConsumer{
		messages: []*DLQMessage{
			{Body: []byte(`{"payload":"no-id"}`), ReceiptHandle: "r1"},
		},
	}
	gateway := &fakeGateway{}
	storage := &fakeStorage{persisted: make(map[string][]byte)}

	worker := NewWorker(consumer, gateway, storage)

	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		for len(consumer.acked) == 0 {
		}
		cancel()
	}()

	_ = worker.Run(ctx)

	if len(consumer.acked) != 1 {
		t.Errorf("acked = %d, want 1", len(consumer.acked))
	}
}

func TestWorker_GatewayFailure_StillPersists(t *testing.T) {
	consumer := &fakeConsumer{
		messages: []*DLQMessage{
			{Body: []byte(`{"id":"msg-002"}`), ReceiptHandle: "r1"},
		},
	}
	gateway := &fakeGateway{err: errors.New("gateway down")}
	storage := &fakeStorage{persisted: make(map[string][]byte)}

	worker := NewWorker(consumer, gateway, storage)

	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		for len(consumer.acked) == 0 {
		}
		cancel()
	}()

	_ = worker.Run(ctx)

	// S3 should still succeed
	if _, ok := storage.persisted["msg-002"]; !ok {
		t.Error("should persist even when gateway fails")
	}

	// Message should be ACKed
	if len(consumer.acked) != 1 {
		t.Errorf("acked = %d, want 1", len(consumer.acked))
	}
}

func TestWorker_S3Failure_DoesNotAck(t *testing.T) {
	consumer := &fakeConsumer{
		messages: []*DLQMessage{
			{Body: []byte(`{"id":"msg-003"}`), ReceiptHandle: "r1"},
		},
	}
	gateway := &fakeGateway{}
	storage := &fakeStorage{persisted: make(map[string][]byte), err: errors.New("s3 down")}

	worker := NewWorker(consumer, gateway, storage)

	ctx, cancel := context.WithCancel(context.Background())

	// Process one message (will fail on S3, then block on Receive)
	go func() {
		// Wait for gateway to be called (happens before S3)
		for len(gateway.reported) == 0 {
		}
		// Give processOne time to attempt S3 and return error
		cancel()
	}()

	_ = worker.Run(ctx)

	// Message should NOT be ACKed when S3 fails
	if len(consumer.acked) != 0 {
		t.Errorf("acked = %d, want 0 (should not ACK when S3 fails)", len(consumer.acked))
	}
}

func TestExtractMessageID(t *testing.T) {
	tests := []struct {
		name    string
		body    string
		wantID  string
		wantErr bool
	}{
		{
			name:   "valid message",
			body:   `{"id":"test-123","route":{"actors":["a","b"],"current":0},"payload":{}}`,
			wantID: "test-123",
		},
		{
			name:    "missing id",
			body:    `{"route":{"actors":["a"],"current":0},"payload":{}}`,
			wantErr: true,
		},
		{
			name:    "empty id",
			body:    `{"id":"","payload":{}}`,
			wantErr: true,
		},
		{
			name:    "invalid json",
			body:    `not json`,
			wantErr: true,
		},
		{
			name:    "empty body",
			body:    ``,
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			id, err := extractMessageID([]byte(tt.body))
			if tt.wantErr {
				if err == nil {
					t.Error("expected error")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if id != tt.wantID {
				t.Errorf("id = %q, want %q", id, tt.wantID)
			}
		})
	}
}
