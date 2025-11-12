package queue

import (
	"context"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

// mockSQSClient implements sqsClient interface for testing
type mockSQSClient struct {
	mock.Mock
}

func (m *mockSQSClient) ReceiveMessage(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
	args := m.Called(ctx, params)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).(*sqs.ReceiveMessageOutput), args.Error(1)
}

func (m *mockSQSClient) SendMessage(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error) {
	args := m.Called(ctx, params)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).(*sqs.SendMessageOutput), args.Error(1)
}

func (m *mockSQSClient) DeleteMessage(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error) {
	args := m.Called(ctx, params)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).(*sqs.DeleteMessageOutput), args.Error(1)
}

func (m *mockSQSClient) GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
	args := m.Called(ctx, params)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).(*sqs.GetQueueUrlOutput), args.Error(1)
}

// TestSQSQueueNaming tests that actor names are prefixed with "asya-" for SQS queue names
// This is SQS-specific behavior: actor "data-processor" -> queue "asya-data-processor"
func TestSQSQueueNaming(t *testing.T) {
	tests := []struct {
		name          string
		actorName     string
		expectedQueue string
	}{
		{
			name:          "simple actor name",
			actorName:     "data-processor",
			expectedQueue: "asya-data-processor",
		},
		{
			name:          "test actor name",
			actorName:     "test-echo",
			expectedQueue: "asya-test-echo",
		},
		{
			name:          "crew actor name",
			actorName:     "happy-end",
			expectedQueue: "asya-happy-end",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockClient := new(mockSQSClient)

			// Mock GetQueueUrl to capture what queue name is requested
			mockClient.On("GetQueueUrl", mock.Anything, mock.MatchedBy(func(params *sqs.GetQueueUrlInput) bool {
				// Verify the queue name has the asya- prefix
				return *params.QueueName == tt.expectedQueue
			})).Return(&sqs.GetQueueUrlOutput{
				QueueUrl: stringPtr("http://sqs:4566/000000000000/" + tt.expectedQueue),
			}, nil)

			mockClient.On("SendMessage", mock.Anything, mock.Anything).Return(&sqs.SendMessageOutput{}, nil)

			sqsClient := &SQSClient{
				client:        mockClient,
				region:        "us-east-1",
				baseURL:       "http://sqs:4566",
				queueURLCache: make(map[string]string),
			}

			envelope := &types.Envelope{
				ID: "test-envelope-1",
				Route: types.Route{
					Actors:  []string{tt.actorName}, // Actor name without prefix
					Current: 0,
				},
				Payload:  map[string]interface{}{"test": "data"},
				Deadline: time.Now().Add(30 * time.Second),
			}

			err := sqsClient.SendEnvelope(context.Background(), envelope)
			assert.NoError(t, err)

			// Verify GetQueueUrl was called with the prefixed queue name
			mockClient.AssertExpectations(t)
		})
	}
}

func stringPtr(s string) *string {
	return &s
}
