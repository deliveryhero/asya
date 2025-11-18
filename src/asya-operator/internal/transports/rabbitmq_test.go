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
	testActorName        = "test-actor"
	testActorNamespace   = "default"
	errTransportNotFound = "transport 'rabbitmq' not found in operator configuration"
)

func TestRabbitMQTransport_ReconcileQueue_AutoCreateDisabled(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeRabbitMQ: {
				Type:    transportTypeRabbitMQ,
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
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeRabbitMQ,
		},
	}

	err := transport.ReconcileQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when autoCreate is disabled and no RabbitMQ connection, got nil")
	}

	expectedSubstring := "failed to connect to RabbitMQ"
	if !strings.Contains(err.Error(), expectedSubstring) {
		t.Errorf("Expected error containing %q, got: %v", expectedSubstring, err)
	}
}

func TestRabbitMQTransport_ReconcileQueue_TransportNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: make(map[string]*asyaconfig.TransportConfig),
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeRabbitMQ,
		},
	}

	err := transport.ReconcileQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when transport not found, got nil")
	}

	if err.Error() != errTransportNotFound {
		t.Errorf("Expected error %q, got %q", errTransportNotFound, err.Error())
	}
}

func TestRabbitMQTransport_ReconcileQueue_InvalidConfigType(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeRabbitMQ: {
				Type:    transportTypeRabbitMQ,
				Enabled: true,
				Config: &asyaconfig.SQSConfig{
					Region: "us-east-1",
				},
			},
		},
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeRabbitMQ,
		},
	}

	err := transport.ReconcileQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error for invalid config type, got nil")
	}

	if err.Error() != errInvalidRabbitMQConfig {
		t.Errorf("Expected %q error, got %q", errInvalidRabbitMQConfig, err.Error())
	}
}

func TestRabbitMQTransport_ReconcileQueue_PasswordSecretNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeRabbitMQ: {
				Type:    transportTypeRabbitMQ,
				Enabled: true,
				Config: &asyaconfig.RabbitMQConfig{
					Host:     "rabbitmq.default.svc.cluster.local",
					Port:     5672,
					Username: "guest",
					PasswordSecretRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: "nonexistent-secret",
						},
						Key: "password",
					},
					Queues: asyaconfig.QueueManagementConfig{
						AutoCreate: true,
					},
				},
			},
		},
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeRabbitMQ,
		},
	}

	err := transport.ReconcileQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when password secret not found, got nil")
	}

	if err.Error() != "failed to load RabbitMQ password: failed to get RabbitMQ password secret: secrets \"nonexistent-secret\" not found" {
		t.Errorf("Unexpected error message: %v", err)
	}
}

func TestRabbitMQTransport_ReconcileQueue_PasswordSecretMissingKey(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "rabbitmq-secret",
			Namespace: testActorNamespace,
		},
		Data: map[string][]byte{
			"wrong-key": []byte("guest"),
		},
	}

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(secret).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeRabbitMQ: {
				Type:    transportTypeRabbitMQ,
				Enabled: true,
				Config: &asyaconfig.RabbitMQConfig{
					Host:     "rabbitmq.default.svc.cluster.local",
					Port:     5672,
					Username: "guest",
					PasswordSecretRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: "rabbitmq-secret",
						},
						Key: "password",
					},
					Queues: asyaconfig.QueueManagementConfig{
						AutoCreate: true,
					},
				},
			},
		},
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeRabbitMQ,
		},
	}

	err := transport.ReconcileQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when password key not found in secret, got nil")
	}

	expectedError := "failed to load RabbitMQ password: key password not found in secret rabbitmq-secret"
	if err.Error() != expectedError {
		t.Errorf("Expected error %q, got %q", expectedError, err.Error())
	}
}

func TestRabbitMQTransport_DeleteQueue_TransportNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: make(map[string]*asyaconfig.TransportConfig),
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeRabbitMQ,
		},
	}

	err := transport.DeleteQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error when transport not found, got nil")
	}

	if err.Error() != errTransportNotFound {
		t.Errorf("Expected error %q, got %q", errTransportNotFound, err.Error())
	}
}

func TestRabbitMQTransport_DeleteQueue_InvalidConfigType(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeRabbitMQ: {
				Type:    transportTypeRabbitMQ,
				Enabled: true,
				Config: &asyaconfig.SQSConfig{
					Region: "us-east-1",
				},
			},
		},
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      testActorName,
			Namespace: testActorNamespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: transportTypeRabbitMQ,
		},
	}

	err := transport.DeleteQueue(context.Background(), actor)
	if err == nil {
		t.Fatal("Expected error for invalid config type, got nil")
	}

	if err.Error() != errInvalidRabbitMQConfig {
		t.Errorf("Expected %q error, got %q", errInvalidRabbitMQConfig, err.Error())
	}
}

func TestRabbitMQTransport_QueueExists_TransportNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: make(map[string]*asyaconfig.TransportConfig),
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	exists, err := transport.QueueExists(context.Background(), "asya-test-queue", "default")
	if err == nil {
		t.Fatal("Expected error when transport not found, got nil")
	}

	if exists {
		t.Error("Expected exists=false when transport not found")
	}

	expectedError := "transport 'rabbitmq' not found in operator configuration"
	if err.Error() != expectedError {
		t.Errorf("Expected error %q, got %q", expectedError, err.Error())
	}
}

func TestRabbitMQTransport_QueueExists_InvalidConfigType(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	registry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			transportTypeRabbitMQ: {
				Type:    transportTypeRabbitMQ,
				Enabled: true,
				Config: &asyaconfig.SQSConfig{
					Region: "us-east-1",
				},
			},
		},
	}

	transport := NewRabbitMQTransport(fakeClient, registry)

	exists, err := transport.QueueExists(context.Background(), "asya-test-queue", "default")
	if err == nil {
		t.Fatal("Expected error for invalid config type, got nil")
	}

	if exists {
		t.Error("Expected exists=false for invalid config type")
	}

	expectedError := "invalid RabbitMQ config type"
	if err.Error() != expectedError {
		t.Errorf("Expected %q error, got %q", expectedError, err.Error())
	}
}
