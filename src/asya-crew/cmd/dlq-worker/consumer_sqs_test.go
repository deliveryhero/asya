package main

import (
	"context"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	sqstypes "github.com/aws/aws-sdk-go-v2/service/sqs/types"
)

// mockSQSClient implements sqsAPI for testing.
type mockSQSClient struct {
	receiveFunc func(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error)
	deleteFunc  func(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error)
}

func (m *mockSQSClient) ReceiveMessage(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
	return m.receiveFunc(ctx, params, optFns...)
}

func (m *mockSQSClient) DeleteMessage(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error) {
	return m.deleteFunc(ctx, params, optFns...)
}

func TestSQSConsumer_Receive(t *testing.T) {
	msgBody := `{"id":"test-123","payload":{"data":"hello"}}`
	mock := &mockSQSClient{
		receiveFunc: func(_ context.Context, params *sqs.ReceiveMessageInput, _ ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
			if aws.ToString(params.QueueUrl) != "https://sqs.us-east-1.amazonaws.com/123/dlq" {
				t.Errorf("unexpected queue URL: %s", aws.ToString(params.QueueUrl))
			}
			return &sqs.ReceiveMessageOutput{
				Messages: []sqstypes.Message{
					{
						Body:          aws.String(msgBody),
						ReceiptHandle: aws.String("receipt-abc"),
						MessageId:     aws.String("sqs-msg-id"),
					},
				},
			}, nil
		},
	}

	consumer := newSQSConsumerWithClient(mock, "https://sqs.us-east-1.amazonaws.com/123/dlq", 300, 20)

	msg, err := consumer.Receive(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(msg.Body) != msgBody {
		t.Errorf("body = %q, want %q", string(msg.Body), msgBody)
	}
	if msg.ReceiptHandle != "receipt-abc" {
		t.Errorf("receipt handle = %q", msg.ReceiptHandle)
	}
}

func TestSQSConsumer_Receive_ContextCancelled(t *testing.T) {
	mock := &mockSQSClient{
		receiveFunc: func(ctx context.Context, _ *sqs.ReceiveMessageInput, _ ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
			return nil, ctx.Err()
		},
	}

	consumer := newSQSConsumerWithClient(mock, "https://sqs/dlq", 300, 20)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := consumer.Receive(ctx)
	if err == nil {
		t.Fatal("expected error for cancelled context")
	}
}

func TestSQSConsumer_Ack(t *testing.T) {
	var deletedQueue, deletedReceipt string
	mock := &mockSQSClient{
		deleteFunc: func(_ context.Context, params *sqs.DeleteMessageInput, _ ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error) {
			deletedQueue = aws.ToString(params.QueueUrl)
			deletedReceipt = aws.ToString(params.ReceiptHandle)
			return &sqs.DeleteMessageOutput{}, nil
		},
	}

	consumer := newSQSConsumerWithClient(mock, "https://sqs/dlq", 300, 20)

	err := consumer.Ack(context.Background(), &DLQMessage{
		ReceiptHandle: "receipt-xyz",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if deletedQueue != "https://sqs/dlq" {
		t.Errorf("deleted from queue = %q", deletedQueue)
	}
	if deletedReceipt != "receipt-xyz" {
		t.Errorf("deleted receipt = %q", deletedReceipt)
	}
}

func TestSQSConsumer_Receive_EmptyThenMessage(t *testing.T) {
	callCount := 0
	mock := &mockSQSClient{
		receiveFunc: func(_ context.Context, _ *sqs.ReceiveMessageInput, _ ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
			callCount++
			if callCount == 1 {
				return &sqs.ReceiveMessageOutput{Messages: nil}, nil
			}
			return &sqs.ReceiveMessageOutput{
				Messages: []sqstypes.Message{
					{
						Body:          aws.String(`{"id":"delayed-msg"}`),
						ReceiptHandle: aws.String("receipt-delayed"),
					},
				},
			}, nil
		},
	}

	consumer := newSQSConsumerWithClient(mock, "https://sqs/dlq", 300, 0)

	msg, err := consumer.Receive(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(msg.Body) != `{"id":"delayed-msg"}` {
		t.Errorf("body = %q", string(msg.Body))
	}
	if callCount != 2 {
		t.Errorf("expected 2 receive calls, got %d", callCount)
	}
}
