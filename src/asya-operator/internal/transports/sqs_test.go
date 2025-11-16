package transports

import (
	"context"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
)

const (
	testErrorSQSTransportNotFound = "transport 'sqs' not found in operator configuration"
	testErrorInvalidSQSConfig     = "invalid SQS config type"
)

func TestSQSTransport_ReconcileQueue_AutoCreateDisabled(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeSQS: {
				Type:    transportTypeSQS,
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
	}

	transport := NewSQSTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeSQS,
		},
	}

	err := transport.ReconcileQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when autoCreate is disabled and no SQS connection, got nil")
	}

	expectedSubstring := "failed to get SQS queue URL"
	if !strings.Contains(err.Error(), expectedSubstring) {
		t.Errorf("Expected error containing %q, got: %v", expectedSubstring, err)
	}
}

func TestSQSTransport_ReconcileQueue_TransportNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: make(map[string]*asyaconfig.TransportConfig),
	}

	transport := NewSQSTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeSQS,
		},
	}

	err := transport.ReconcileQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when transport not found, got nil")
	}

	if err.Error() != testErrorSQSTransportNotFound {
		t.Errorf("Expected error %q, got %q", testErrorSQSTransportNotFound, err.Error())
	}
}

func TestSQSTransport_ReconcileQueue_InvalidConfigType(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeSQS: {
				Type:    transportTypeSQS,
				Enabled: true,
				Config: &asyaconfig.RabbitMQConfig{
					Host: "rabbitmq.default.svc.cluster.local",
					Port: 5672,
				},
			},
		},
	}

	transport := NewSQSTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeSQS,
		},
	}

	err := transport.ReconcileQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error for invalid config type, got nil")
	}

	if err.Error() != testErrorInvalidSQSConfig {
		t.Errorf("Expected %q error, got %q", testErrorInvalidSQSConfig, err.Error())
	}
}

func TestSQSTransport_DeleteQueue_TransportNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: make(map[string]*asyaconfig.TransportConfig),
	}

	transport := NewSQSTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeSQS,
		},
	}

	err := transport.DeleteQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when transport not found, got nil")
	}

	if err.Error() != testErrorSQSTransportNotFound {
		t.Errorf("Expected error %q, got %q", testErrorSQSTransportNotFound, err.Error())
	}
}

func TestSQSTransport_DeleteQueue_InvalidConfigType(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeSQS: {
				Type:    transportTypeSQS,
				Enabled: true,
				Config: &asyaconfig.RabbitMQConfig{
					Host: "rabbitmq.default.svc.cluster.local",
					Port: 5672,
				},
			},
		},
	}

	transport := NewSQSTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeSQS,
		},
	}

	err := transport.DeleteQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error for invalid config type, got nil")
	}

	if err.Error() != testErrorInvalidSQSConfig {
		t.Errorf("Expected %q error, got %q", testErrorInvalidSQSConfig, err.Error())
	}
}

func TestSQSTransport_ReconcileServiceAccount_NoActorRoleArn(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeSQS: {
				Type:    transportTypeSQS,
				Enabled: true,
				Config: &asyaconfig.SQSConfig{
					Region:            "us-east-1",
					ActorRoleArn:      "",
					VisibilityTimeout: 300,
				},
			},
		},
	}

	transport := NewSQSTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeSQS,
		},
	}

	err := transport.ReconcileServiceAccount(context.Background(), actor)
	if err != nil {
		t.Fatalf("Expected no error when actorRoleArn is empty (should skip), got: %v", err)
	}
}

func TestSQSTransport_ReconcileServiceAccount_TransportNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: make(map[string]*asyaconfig.TransportConfig),
	}

	transport := NewSQSTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeSQS,
		},
	}

	err := transport.ReconcileServiceAccount(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when transport not found, got nil")
	}

	if err.Error() != testErrorSQSTransportNotFound {
		t.Errorf("Expected error %q, got %q", testErrorSQSTransportNotFound, err.Error())
	}
}

func TestSQSTransport_ReconcileServiceAccount_InvalidConfigType(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeSQS: {
				Type:    transportTypeSQS,
				Enabled: true,
				Config: &asyaconfig.RabbitMQConfig{
					Host: "rabbitmq.default.svc.cluster.local",
					Port: 5672,
				},
			},
		},
	}

	transport := NewSQSTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeSQS,
		},
	}

	err := transport.ReconcileServiceAccount(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error for invalid config type, got nil")
	}

	if err.Error() != testErrorInvalidSQSConfig {
		t.Errorf("Expected %q error, got %q", testErrorInvalidSQSConfig, err.Error())
	}
}

func TestSQSConfig_TagsMerging(t *testing.T) {
	tests := []struct {
		name         string
		configTags   map[string]string
		actorName    string
		actorNs      string
		expectedTags map[string]string
		description  string
	}{
		{
			name:       "no configured tags - only defaults",
			configTags: nil,
			actorName:  "my-actor",
			actorNs:    "production",
			expectedTags: map[string]string{
				"asya.sh/actor":     "my-actor",
				"asya.sh/namespace": "production",
			},
			description: "Default tags should be added when no custom tags configured",
		},
		{
			name: "configured tags merged with defaults",
			configTags: map[string]string{
				"environment": "staging",
				"team":        "ml-platform",
				"cost-center": "1234",
			},
			actorName: "model-inference",
			actorNs:   "ml-workloads",
			expectedTags: map[string]string{
				"asya.sh/actor":     "model-inference",
				"asya.sh/namespace": "ml-workloads",
				"environment":       "staging",
				"team":              "ml-platform",
				"cost-center":       "1234",
			},
			description: "Custom tags should be merged with default tags",
		},
		{
			name: "custom tags can override defaults",
			configTags: map[string]string{
				"asya.sh/actor":     "custom-actor",
				"asya.sh/namespace": "custom-ns",
				"extra":             "tag",
			},
			actorName: "original-actor",
			actorNs:   "original-ns",
			expectedTags: map[string]string{
				"asya.sh/actor":     "custom-actor",
				"asya.sh/namespace": "custom-ns",
				"extra":             "tag",
			},
			description: "Custom tags can override default tags if needed",
		},
		{
			name:       "empty configured tags - only defaults",
			configTags: map[string]string{},
			actorName:  "test-actor",
			actorNs:    "test-ns",
			expectedTags: map[string]string{
				"asya.sh/actor":     "test-actor",
				"asya.sh/namespace": "test-ns",
			},
			description: "Empty tag map should result in only default tags",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tags := map[string]string{
				"asya.sh/actor":     tt.actorName,
				"asya.sh/namespace": tt.actorNs,
			}
			for k, v := range tt.configTags {
				tags[k] = v
			}

			if len(tags) != len(tt.expectedTags) {
				t.Errorf("Expected %d tags, got %d", len(tt.expectedTags), len(tags))
			}

			for k, expectedV := range tt.expectedTags {
				if actualV, ok := tags[k]; !ok {
					t.Errorf("Expected tag %q not found in result", k)
				} else if actualV != expectedV {
					t.Errorf("Tag %q: expected value %q, got %q", k, expectedV, actualV)
				}
			}
		})
	}
}
