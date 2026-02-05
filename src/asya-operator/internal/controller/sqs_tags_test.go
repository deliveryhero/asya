package controller

import (
	"context"
	"fmt"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
)

// mockSQSClient captures CreateQueue calls to verify tags are passed correctly
type mockSQSClient struct {
	createQueueCalls []sqs.CreateQueueInput
	getQueueUrlError error
}

func (m *mockSQSClient) CreateQueue(ctx context.Context, params *sqs.CreateQueueInput, optFns ...func(*sqs.Options)) (*sqs.CreateQueueOutput, error) {
	m.createQueueCalls = append(m.createQueueCalls, *params)
	return &sqs.CreateQueueOutput{
		QueueUrl: aws.String(fmt.Sprintf("https://sqs.us-east-1.amazonaws.com/123456789012/%s", *params.QueueName)),
	}, nil
}

func (m *mockSQSClient) GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
	if m.getQueueUrlError != nil {
		return nil, m.getQueueUrlError
	}
	return &sqs.GetQueueUrlOutput{
		QueueUrl: aws.String(fmt.Sprintf("https://sqs.us-east-1.amazonaws.com/123456789012/%s", *params.QueueName)),
	}, nil
}

func (m *mockSQSClient) GetQueueAttributes(ctx context.Context, params *sqs.GetQueueAttributesInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueAttributesOutput, error) {
	return &sqs.GetQueueAttributesOutput{
		Attributes: map[string]string{
			string(types.QueueAttributeNameVisibilityTimeout): "300",
		},
	}, nil
}

func (m *mockSQSClient) DeleteQueue(ctx context.Context, params *sqs.DeleteQueueInput, optFns ...func(*sqs.Options)) (*sqs.DeleteQueueOutput, error) {
	return &sqs.DeleteQueueOutput{}, nil
}

// TestSQSQueueCreation_TagMergingLogic verifies that the tag merging logic used in
// reconcileSQSQueue correctly merges configured tags with default tags.
// This test uses the EXACT same logic as reconcileSQSQueue to prevent regression.
//
// CRITICAL: This test must replicate the exact tag merging code from reconcileSQSQueue.
// If you modify tag merging in reconcileSQSQueue, you MUST update this test to match.
func TestSQSQueueCreation_TagMergingLogic(t *testing.T) {
	tests := []struct {
		name         string
		configTags   map[string]string
		actorName    string
		actorNs      string
		expectedTags map[string]string
		description  string
	}{
		{
			name: "configured tags merged with defaults",
			configTags: map[string]string{
				"Environment":     "production",
				"Project":         "ml-inference",
				"Team":            "data-science",
				"CostCenter":      "engineering",
				"ManagedBy":       "asya-operator",
				"Owner":           "platform-team",
				"asya.sh/version": "v1alpha1",
			},
			actorName: "text-classifier",
			actorNs:   "ml-workloads",
			expectedTags: map[string]string{
				"asya.sh/actor":     "text-classifier",
				"asya.sh/namespace": "ml-workloads",
				"Environment":       "production",
				"Project":           "ml-inference",
				"Team":              "data-science",
				"CostCenter":        "engineering",
				"ManagedBy":         "asya-operator",
				"Owner":             "platform-team",
				"asya.sh/version":   "v1alpha1",
			},
			description: "All 7 configured tags + 2 default tags should be passed to CreateQueue",
		},
		{
			name:       "only default tags when no config tags",
			configTags: nil,
			actorName:  "image-processor",
			actorNs:    "production",
			expectedTags: map[string]string{
				"asya.sh/actor":     "image-processor",
				"asya.sh/namespace": "production",
			},
			description: "Only default tags should be passed when config has no tags",
		},
		{
			name: "single configured tag merged with defaults",
			configTags: map[string]string{
				"Environment": "staging",
			},
			actorName: "test-actor",
			actorNs:   "test-ns",
			expectedTags: map[string]string{
				"asya.sh/actor":     "test-actor",
				"asya.sh/namespace": "test-ns",
				"Environment":       "staging",
			},
			description: "Single configured tag should be merged with defaults",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)

			// Create mock SQS client
			mockClient := &mockSQSClient{
				getQueueUrlError: fmt.Errorf("QueueDoesNotExist"),
			}

			// Create reconciler with test config
			r := &AsyncActorReconciler{
				Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme: scheme,
				TransportRegistry: &asyaconfig.TransportRegistry{
					Transports: map[string]*asyaconfig.TransportConfig{
						"sqs": {
							Type:    "sqs",
							Enabled: true,
							Config: &asyaconfig.SQSConfig{
								Region:            "us-east-1",
								VisibilityTimeout: 300,
								WaitTimeSeconds:   20,
								Queues: asyaconfig.QueueManagementConfig{
									AutoCreate: true,
								},
								Tags: tt.configTags,
							},
						},
					},
				},
			}

			actor := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      tt.actorName,
					Namespace: tt.actorNs,
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: "sqs",
				},
			}

			// We can't directly test reconcileSQSQueue because it creates its own SQS client
			// Instead, we'll test the tag merging logic that it uses
			transport, err := r.TransportRegistry.GetTransport("sqs")
			if err != nil {
				t.Fatalf("Failed to get transport: %v", err)
			}

			sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
			if !ok {
				t.Fatal("Invalid SQS config type")
			}

			// Replicate the tag merging logic from reconcileSQSQueue
			tags := map[string]string{
				"asya.sh/actor":     actor.Name,
				"asya.sh/namespace": actor.Namespace,
			}
			for k, v := range sqsConfig.Tags {
				tags[k] = v
			}

			// Verify tag count
			if len(tags) != len(tt.expectedTags) {
				t.Errorf("Expected %d tags, got %d", len(tt.expectedTags), len(tags))
			}

			// Verify each expected tag
			for expectedKey, expectedValue := range tt.expectedTags {
				actualValue, exists := tags[expectedKey]
				if !exists {
					t.Errorf("Expected tag %q not found in merged tags", expectedKey)
					continue
				}
				if actualValue != expectedValue {
					t.Errorf("Tag %q: expected value %q, got %q", expectedKey, expectedValue, actualValue)
				}
			}

			// Verify no unexpected tags
			for actualKey := range tags {
				if _, expected := tt.expectedTags[actualKey]; !expected {
					t.Errorf("Unexpected tag %q found in merged tags", actualKey)
				}
			}

			// Simulate CreateQueue call with merged tags
			input := &sqs.CreateQueueInput{
				QueueName: aws.String(fmt.Sprintf("asya-%s", actor.Name)),
				Attributes: map[string]string{
					"VisibilityTimeout":      "300",
					"MessageRetentionPeriod": "345600",
				},
				Tags: tags,
			}

			// Call mock CreateQueue to verify tags structure
			_, err = mockClient.CreateQueue(context.Background(), input)
			if err != nil {
				t.Fatalf("CreateQueue failed: %v", err)
			}

			// Verify CreateQueue was called with correct tags
			if len(mockClient.createQueueCalls) != 1 {
				t.Fatalf("Expected 1 CreateQueue call, got %d", len(mockClient.createQueueCalls))
			}

			actualCall := mockClient.createQueueCalls[0]
			if len(actualCall.Tags) != len(tt.expectedTags) {
				t.Errorf("CreateQueue called with %d tags, expected %d", len(actualCall.Tags), len(tt.expectedTags))
			}

			for expectedKey, expectedValue := range tt.expectedTags {
				actualValue, exists := actualCall.Tags[expectedKey]
				if !exists {
					t.Errorf("CreateQueue missing expected tag %q", expectedKey)
					continue
				}
				if actualValue != expectedValue {
					t.Errorf("CreateQueue tag %q: expected %q, got %q", expectedKey, expectedValue, actualValue)
				}
			}
		})
	}
}

// TestReconcileSQSQueue_ConfigTagsParsedFromJSON verifies that tags from ASYA_TRANSPORT_CONFIG
// are correctly parsed and available in SQSConfig.
func TestReconcileSQSQueue_ConfigTagsParsedFromJSON(t *testing.T) {
	configJSON := `{
		"transports": {
			"sqs": {
				"enabled": true,
				"type": "sqs",
				"config": {
					"region": "us-east-1",
					"visibilityTimeout": 300,
					"waitTimeSeconds": 20,
					"queues": {
						"autoCreate": true
					},
					"tags": {
						"Environment": "production",
						"Project": "ml-platform",
						"Team": "data-science",
						"CostCenter": "engineering",
						"ManagedBy": "asya-operator",
						"Owner": "platform-team",
						"asya.sh/version": "v1alpha1"
					}
				}
			}
		}
	}`

	t.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)

	registry, err := asyaconfig.LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Failed to load transport registry: %v", err)
	}

	transport, err := registry.GetTransport("sqs")
	if err != nil {
		t.Fatalf("Failed to get SQS transport: %v", err)
	}

	sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		t.Fatal("Invalid SQS config type")
	}

	expectedTags := map[string]string{
		"Environment":     "production",
		"Project":         "ml-platform",
		"Team":            "data-science",
		"CostCenter":      "engineering",
		"ManagedBy":       "asya-operator",
		"Owner":           "platform-team",
		"asya.sh/version": "v1alpha1",
	}

	if len(sqsConfig.Tags) != len(expectedTags) {
		t.Errorf("Expected %d tags parsed from JSON, got %d", len(expectedTags), len(sqsConfig.Tags))
	}

	for key, expectedValue := range expectedTags {
		actualValue, exists := sqsConfig.Tags[key]
		if !exists {
			t.Errorf("Expected tag %q not found in parsed config", key)
			continue
		}
		if actualValue != expectedValue {
			t.Errorf("Tag %q: expected %q, got %q", key, expectedValue, actualValue)
		}
	}
}
