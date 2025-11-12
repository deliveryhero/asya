package transport

import (
	"context"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
)

const (
	testQueueName = "test-queue"
	testQueueURL  = "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue"
)

// mockSQSClient is a mock implementation of the SQS client for testing
type mockSQSClient struct {
	receiveMessageFunc          func(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error)
	sendMessageFunc             func(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error)
	deleteMessageFunc           func(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error)
	changeMessageVisibilityFunc func(ctx context.Context, params *sqs.ChangeMessageVisibilityInput, optFns ...func(*sqs.Options)) (*sqs.ChangeMessageVisibilityOutput, error)
	getQueueUrlFunc             func(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error)
}

func (m *mockSQSClient) ReceiveMessage(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
	if m.receiveMessageFunc != nil {
		return m.receiveMessageFunc(ctx, params, optFns...)
	}
	return nil, nil
}

func (m *mockSQSClient) SendMessage(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error) {
	if m.sendMessageFunc != nil {
		return m.sendMessageFunc(ctx, params, optFns...)
	}
	return nil, nil
}

func (m *mockSQSClient) DeleteMessage(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error) {
	if m.deleteMessageFunc != nil {
		return m.deleteMessageFunc(ctx, params, optFns...)
	}
	return nil, nil
}

func (m *mockSQSClient) ChangeMessageVisibility(ctx context.Context, params *sqs.ChangeMessageVisibilityInput, optFns ...func(*sqs.Options)) (*sqs.ChangeMessageVisibilityOutput, error) {
	if m.changeMessageVisibilityFunc != nil {
		return m.changeMessageVisibilityFunc(ctx, params, optFns...)
	}
	return nil, nil
}

func (m *mockSQSClient) GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
	if m.getQueueUrlFunc != nil {
		return m.getQueueUrlFunc(ctx, params, optFns...)
	}
	return nil, nil
}

// createMockSQSTransport creates an SQSTransport with a mock client for testing
func createMockSQSTransport(mockClient *mockSQSClient) *SQSTransport {
	return createMockSQSTransportWithTimeout(mockClient, 300)
}

func createMockSQSTransportWithTimeout(mockClient *mockSQSClient, visibilityTimeout int32) *SQSTransport {
	return &SQSTransport{
		client:            mockClient,
		region:            "us-east-1",
		visibilityTimeout: visibilityTimeout,
		waitTimeSeconds:   20,
		queueURLCache:     make(map[string]string),
	}
}

func TestSQSTransport_ResolveQueueURL(t *testing.T) {
	ctx := context.Background()
	queueName := testQueueName
	queueURL := testQueueURL

	t.Run("successful resolution via API", func(t *testing.T) {
		callCount := 0
		mockClient := &mockSQSClient{
			getQueueUrlFunc: func(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
				callCount++
				if *params.QueueName != queueName {
					t.Errorf("QueueName = %v, want %v", *params.QueueName, queueName)
				}
				return &sqs.GetQueueUrlOutput{
					QueueUrl: aws.String(queueURL),
				}, nil
			},
		}

		transport := createMockSQSTransport(mockClient)

		got, err := transport.resolveQueueURL(ctx, queueName)
		if err != nil {
			t.Errorf("resolveQueueURL() error = %v, want nil", err)
		}
		if got != queueURL {
			t.Errorf("resolveQueueURL() = %v, want %v", got, queueURL)
		}

		got2, err := transport.resolveQueueURL(ctx, queueName)
		if err != nil {
			t.Errorf("cached resolveQueueURL() error = %v, want nil", err)
		}
		if got2 != queueURL {
			t.Errorf("cached resolveQueueURL() = %v, want %v", got2, queueURL)
		}

		if callCount != 1 {
			t.Errorf("GetQueueUrl called %d times, want 1 (should be cached)", callCount)
		}
	})
}

func TestSQSTransport_SplitReceiptHandle(t *testing.T) {
	tests := []struct {
		name         string
		handle       interface{}
		wantQueueURL string
		wantReceipt  string
		wantErr      bool
	}{
		{
			name:         "valid handle",
			handle:       "https://sqs.us-east-1.amazonaws.com/123/queue|receipt-123",
			wantQueueURL: "https://sqs.us-east-1.amazonaws.com/123/queue",
			wantReceipt:  "receipt-123",
			wantErr:      false,
		},
		{
			name:    "invalid type",
			handle:  123,
			wantErr: true,
		},
		{
			name:    "missing separator",
			handle:  "no-separator",
			wantErr: true,
		},
		{
			name:         "receipt with pipe character",
			handle:       "https://sqs/queue|receipt|with|pipes",
			wantQueueURL: "https://sqs/queue",
			wantReceipt:  "receipt|with|pipes",
			wantErr:      false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			queueURL, receipt, err := splitReceiptHandle(tt.handle)
			if (err != nil) != tt.wantErr {
				t.Errorf("splitReceiptHandle() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !tt.wantErr {
				if queueURL != tt.wantQueueURL {
					t.Errorf("queueURL = %v, want %v", queueURL, tt.wantQueueURL)
				}
				if receipt != tt.wantReceipt {
					t.Errorf("receipt = %v, want %v", receipt, tt.wantReceipt)
				}
			}
		})
	}
}

func TestSQSTransport_Send(t *testing.T) {
	ctx := context.Background()
	queueName := testQueueName
	messageBody := []byte(`{"test":"message"}`)
	queueURL := testQueueURL

	t.Run("successful send", func(t *testing.T) {
		mockClient := &mockSQSClient{
			getQueueUrlFunc: func(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
				return &sqs.GetQueueUrlOutput{
					QueueUrl: aws.String(queueURL),
				}, nil
			},
			sendMessageFunc: func(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error) {
				if *params.QueueUrl != queueURL {
					t.Errorf("QueueUrl = %v, want %v", *params.QueueUrl, queueURL)
				}
				if *params.MessageBody != string(messageBody) {
					t.Errorf("MessageBody = %v, want %v", *params.MessageBody, string(messageBody))
				}
				return &sqs.SendMessageOutput{
					MessageId: aws.String("msg-123"),
				}, nil
			},
		}

		transport := createMockSQSTransport(mockClient)

		err := transport.Send(ctx, queueName, messageBody)
		if err != nil {
			t.Errorf("Send() error = %v, want nil", err)
		}
	})
}

func TestSQSTransport_Receive(t *testing.T) {
	ctx := context.Background()
	queueName := testQueueName
	queueURL := testQueueURL

	t.Run("receive message with attributes", func(t *testing.T) {
		mockClient := &mockSQSClient{
			getQueueUrlFunc: func(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
				return &sqs.GetQueueUrlOutput{
					QueueUrl: aws.String(queueURL),
				}, nil
			},
			receiveMessageFunc: func(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
				if *params.QueueUrl != queueURL {
					t.Errorf("QueueUrl = %v, want %v", *params.QueueUrl, queueURL)
				}
				if params.MaxNumberOfMessages != 1 {
					t.Errorf("MaxNumberOfMessages = %v, want 1", params.MaxNumberOfMessages)
				}
				if params.WaitTimeSeconds != 20 {
					t.Errorf("WaitTimeSeconds = %v, want 20", params.WaitTimeSeconds)
				}
				if params.VisibilityTimeout != 300 {
					t.Errorf("VisibilityTimeout = %v, want 300", params.VisibilityTimeout)
				}

				return &sqs.ReceiveMessageOutput{
					Messages: []types.Message{
						{
							MessageId:     aws.String("msg-123"),
							Body:          aws.String(`{"test":"message"}`),
							ReceiptHandle: aws.String("receipt-handle-123"),
							MessageAttributes: map[string]types.MessageAttributeValue{
								"trace_id": {
									DataType:    aws.String("String"),
									StringValue: aws.String("trace-xyz"),
								},
							},
						},
					},
				}, nil
			},
		}

		transport := createMockSQSTransport(mockClient)

		receiveCtx, cancel := context.WithCancel(ctx)
		defer cancel()

		msgChan := make(chan QueueMessage, 1)
		errChan := make(chan error, 1)

		go func() {
			msg, err := transport.Receive(receiveCtx, queueName)
			if err != nil {
				errChan <- err
				return
			}
			msgChan <- msg
		}()

		select {
		case msg := <-msgChan:
			if msg.ID != "msg-123" {
				t.Errorf("ID = %v, want msg-123", msg.ID)
			}
			if string(msg.Body) != `{"test":"message"}` {
				t.Errorf("Body = %v, want {\"test\":\"message\"}", string(msg.Body))
			}
			expectedHandle := queueURL + "|receipt-handle-123"
			if msg.ReceiptHandle != expectedHandle {
				t.Errorf("ReceiptHandle = %v, want %v", msg.ReceiptHandle, expectedHandle)
			}
			if msg.Headers["trace_id"] != "trace-xyz" {
				t.Errorf("Headers[trace_id] = %v, want trace-xyz", msg.Headers["trace_id"])
			}
			if msg.Headers["QueueName"] != queueName {
				t.Errorf("Headers[QueueName] = %v, want %v", msg.Headers["QueueName"], queueName)
			}
		case err := <-errChan:
			t.Errorf("Receive() error = %v, want nil", err)
		case <-ctx.Done():
			t.Error("Receive() timed out")
		}
	})

	t.Run("context cancellation", func(t *testing.T) {
		mockClient := &mockSQSClient{
			getQueueUrlFunc: func(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
				return &sqs.GetQueueUrlOutput{
					QueueUrl: aws.String(queueURL),
				}, nil
			},
			receiveMessageFunc: func(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
				return &sqs.ReceiveMessageOutput{
					Messages: []types.Message{},
				}, nil
			},
		}

		transport := createMockSQSTransport(mockClient)

		cancelCtx, cancel := context.WithCancel(ctx)
		cancel()

		_, err := transport.Receive(cancelCtx, queueName)
		if err != context.Canceled {
			t.Errorf("Receive() error = %v, want context.Canceled", err)
		}
	})
}

func TestSQSTransport_Ack(t *testing.T) {
	ctx := context.Background()
	queueURL := testQueueURL
	receiptHandle := "receipt-handle-123"

	t.Run("successful ack", func(t *testing.T) {
		mockClient := &mockSQSClient{
			deleteMessageFunc: func(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error) {
				if *params.QueueUrl != queueURL {
					t.Errorf("QueueUrl = %v, want %v", *params.QueueUrl, queueURL)
				}
				if *params.ReceiptHandle != receiptHandle {
					t.Errorf("ReceiptHandle = %v, want %v", *params.ReceiptHandle, receiptHandle)
				}
				return &sqs.DeleteMessageOutput{}, nil
			},
		}

		transport := createMockSQSTransport(mockClient)

		msg := QueueMessage{
			ReceiptHandle: queueURL + "|" + receiptHandle,
		}

		err := transport.Ack(ctx, msg)
		if err != nil {
			t.Errorf("Ack() error = %v, want nil", err)
		}
	})

	t.Run("invalid receipt handle", func(t *testing.T) {
		transport := createMockSQSTransport(nil)

		msg := QueueMessage{
			ReceiptHandle: 123,
		}

		err := transport.Ack(ctx, msg)
		if err == nil {
			t.Error("Ack() error = nil, want error")
		}
	})
}

func TestSQSTransport_Nack(t *testing.T) {
	ctx := context.Background()
	queueURL := testQueueURL
	receiptHandle := "receipt-handle-123"

	t.Run("successful nack with visibility timeout 0", func(t *testing.T) {
		mockClient := &mockSQSClient{
			changeMessageVisibilityFunc: func(ctx context.Context, params *sqs.ChangeMessageVisibilityInput, optFns ...func(*sqs.Options)) (*sqs.ChangeMessageVisibilityOutput, error) {
				if *params.QueueUrl != queueURL {
					t.Errorf("QueueUrl = %v, want %v", *params.QueueUrl, queueURL)
				}
				if *params.ReceiptHandle != receiptHandle {
					t.Errorf("ReceiptHandle = %v, want %v", *params.ReceiptHandle, receiptHandle)
				}
				if params.VisibilityTimeout != 0 {
					t.Errorf("VisibilityTimeout = %v, want 0", params.VisibilityTimeout)
				}
				return &sqs.ChangeMessageVisibilityOutput{}, nil
			},
		}

		transport := createMockSQSTransport(mockClient)

		msg := QueueMessage{
			ReceiptHandle: queueURL + "|" + receiptHandle,
		}

		err := transport.Nack(ctx, msg)
		if err != nil {
			t.Errorf("Nack() error = %v, want nil", err)
		}
	})

	t.Run("invalid receipt handle", func(t *testing.T) {
		transport := createMockSQSTransport(nil)

		msg := QueueMessage{
			ReceiptHandle: "no-separator",
		}

		err := transport.Nack(ctx, msg)
		if err == nil {
			t.Error("Nack() error = nil, want error")
		}
	})
}

func TestSQSTransport_Close(t *testing.T) {
	transport := createMockSQSTransport(nil)
	err := transport.Close()
	if err != nil {
		t.Errorf("Close() error = %v, want nil", err)
	}
}
