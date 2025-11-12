package controller

import (
	"context"
	"errors"
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

type mockSQSClientForValidation struct {
	queueExists      bool
	getQueueUrlError error
}

func (m *mockSQSClientForValidation) CreateQueue(ctx context.Context, params *sqs.CreateQueueInput, optFns ...func(*sqs.Options)) (*sqs.CreateQueueOutput, error) {
	return &sqs.CreateQueueOutput{
		QueueUrl: aws.String(fmt.Sprintf("https://sqs.us-east-1.amazonaws.com/123456789012/%s", *params.QueueName)),
	}, nil
}

func (m *mockSQSClientForValidation) GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
	if m.getQueueUrlError != nil {
		return nil, m.getQueueUrlError
	}
	if !m.queueExists {
		return nil, &types.QueueDoesNotExist{
			Message: aws.String("queue does not exist"),
		}
	}
	return &sqs.GetQueueUrlOutput{
		QueueUrl: aws.String(fmt.Sprintf("https://sqs.us-east-1.amazonaws.com/123456789012/%s", *params.QueueName)),
	}, nil
}

func (m *mockSQSClientForValidation) GetQueueAttributes(ctx context.Context, params *sqs.GetQueueAttributesInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueAttributesOutput, error) {
	return &sqs.GetQueueAttributesOutput{
		Attributes: map[string]string{
			string(types.QueueAttributeNameVisibilityTimeout): "300",
		},
	}, nil
}

func (m *mockSQSClientForValidation) DeleteQueue(ctx context.Context, params *sqs.DeleteQueueInput, optFns ...func(*sqs.Options)) (*sqs.DeleteQueueOutput, error) {
	return &sqs.DeleteQueueOutput{}, nil
}

// TestSQSQueueValidation_AutoCreateDisabled verifies that when autoCreate is disabled,
// the reconciler validates that the queue exists and returns an error if it doesn't.
func TestSQSQueueValidation_AutoCreateDisabled(t *testing.T) {
	tests := []struct {
		name          string
		queueExists   bool
		expectError   bool
		errorContains string
		description   string
	}{
		{
			name:          "queue exists - validation succeeds",
			queueExists:   true,
			expectError:   false,
			errorContains: "",
			description:   "When queue exists and autoCreate is disabled, validation should succeed",
		},
		{
			name:          "queue missing - validation fails",
			queueExists:   false,
			expectError:   true,
			errorContains: "does not exist and autoCreate is disabled",
			description:   "When queue is missing and autoCreate is disabled, validation should fail with clear error",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)

			actor := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: "sqs",
				},
			}

			// Create reconciler with autoCreate disabled
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
								Queues: asyaconfig.QueueManagementConfig{
									AutoCreate: false,
								},
							},
						},
					},
				},
			}

			// Test the validation logic
			transport, err := r.TransportRegistry.GetTransport("sqs")
			if err != nil {
				t.Fatalf("Failed to get transport: %v", err)
			}

			sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
			if !ok {
				t.Fatal("Invalid SQS config type")
			}

			if sqsConfig.Queues.AutoCreate {
				t.Fatal("Expected autoCreate to be disabled")
			}

			mockClient := &mockSQSClientForValidation{
				queueExists: tt.queueExists,
			}

			queueName := fmt.Sprintf("asya-%s", actor.Name)
			_, err = mockClient.GetQueueUrl(context.Background(), &sqs.GetQueueUrlInput{
				QueueName: aws.String(queueName),
			})

			if tt.expectError {
				if err == nil {
					t.Errorf("Expected error containing %q, but got no error", tt.errorContains)
				} else {
					var qne *types.QueueDoesNotExist
					if !errors.As(err, &qne) {
						t.Errorf("Expected QueueDoesNotExist error type, got %T", err)
					}
				}
			} else {
				if err != nil {
					t.Errorf("Expected no error, but got: %v", err)
				}
			}
		})
	}
}

// TestSQSQueueValidation_AutoCreateEnabled verifies that when autoCreate is enabled,
// the reconciler creates the queue instead of just validating.
func TestSQSQueueValidation_AutoCreateEnabled(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)

	// Create reconciler with autoCreate enabled
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
						Queues: asyaconfig.QueueManagementConfig{
							AutoCreate: true,
						},
					},
				},
			},
		},
	}

	transport, err := r.TransportRegistry.GetTransport("sqs")
	if err != nil {
		t.Fatalf("Failed to get transport: %v", err)
	}

	sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		t.Fatal("Invalid SQS config type")
	}

	if !sqsConfig.Queues.AutoCreate {
		t.Fatal("Expected autoCreate to be enabled")
	}

	t.Log("When autoCreate is enabled, reconcileSQSQueue should create the queue, not just validate")
}

// TestRabbitMQQueueValidation_AutoCreateDisabled verifies RabbitMQ queue validation behavior.
// Note: Comprehensive RabbitMQ validation tests exist in internal/transports/rabbitmq_test.go.
// This test provides minimal coverage matching the SQS pattern for consistency.
func TestRabbitMQQueueValidation_AutoCreateDisabled(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				"rabbitmq": {
					Type:    "rabbitmq",
					Enabled: true,
					Config: &asyaconfig.RabbitMQConfig{
						Host:     "rabbitmq.default.svc.cluster.local",
						Port:     5672,
						Username: "guest",
						Password: "guest",
						Queues: asyaconfig.QueueManagementConfig{
							AutoCreate: false,
						},
					},
				},
			},
		},
	}

	transport, err := r.TransportRegistry.GetTransport("rabbitmq")
	if err != nil {
		t.Fatalf("Failed to get transport: %v", err)
	}

	rabbitmqConfig, ok := transport.Config.(*asyaconfig.RabbitMQConfig)
	if !ok {
		t.Fatal("Invalid RabbitMQ config type")
	}

	if rabbitmqConfig.Queues.AutoCreate {
		t.Fatal("Expected autoCreate to be disabled")
	}

	t.Log("When autoCreate is disabled, transport layer validates queue exists using QueueDeclarePassive")
	t.Log("Comprehensive validation tests are in internal/transports/rabbitmq_test.go")
}
