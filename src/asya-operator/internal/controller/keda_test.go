package controller

import (
	"context"
	"testing"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
	kedav1alpha1 "github.com/kedacore/keda/v2/apis/keda/v1alpha1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

const (
	testActorName      = "test-actor"
	testSQSQueueName   = "asya-test-actor"
	testSecretPassword = "password"
	testSecretName     = "rabbitmq-secret"
)

func TestResolveQueueIdentifier(t *testing.T) {
	r := &AsyncActorReconciler{}

	t.Run("RabbitMQ uses actor name", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "rabbitmq",
		}

		queueID, err := r.resolveQueueIdentifier(asya, transport)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if queueID != "asya-"+testActorName {
			t.Errorf("Expected queue ID 'asya-test-actor', got %q", queueID)
		}
	})

	t.Run("SQS uses asya- prefix + actor name", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "sqs",
			Config: &asyaconfig.SQSConfig{
				Region:    "us-east-1",
				AccountID: "123456789012",
			},
		}

		queueID, err := r.resolveQueueIdentifier(asya, transport)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		expected := testSQSQueueName
		if queueID != expected {
			t.Errorf("Expected queue ID %q, got %q", expected, queueID)
		}
	})

	t.Run("SQS with invalid config type uses asya- prefix", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type:   "sqs",
			Config: &asyaconfig.RabbitMQConfig{}, // Wrong config type, will still use asya- prefix
		}

		queueID, err := r.resolveQueueIdentifier(asya, transport)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		expected := testSQSQueueName
		if queueID != expected {
			t.Errorf("Expected queue ID %q, got %q", expected, queueID)
		}
	})

	t.Run("unknown transport uses actor name", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "unknown",
		}

		queueID, err := r.resolveQueueIdentifier(asya, transport)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if queueID != testActorName {
			t.Errorf("Expected queue ID 'test-actor', got %q", queueID)
		}
	})
}

func TestBuildKEDATriggers(t *testing.T) {
	r := &AsyncActorReconciler{
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				"rabbitmq": {
					Type:    "rabbitmq",
					Enabled: true,
					Config: &asyaconfig.RabbitMQConfig{
						Host:     "localhost",
						Port:     5672,
						Username: "guest",
					},
				},
				"sqs": {
					Type:    "sqs",
					Enabled: true,
					Config: &asyaconfig.SQSConfig{
						Region:    "us-east-1",
						AccountID: "123456789012",
					},
				},
			},
		},
	}

	t.Run("RabbitMQ trigger with default queue length", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "rabbitmq",
			},
		}

		triggers, err := r.buildKEDATriggers(context.Background(), asya)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if len(triggers) != 1 {
			t.Fatalf("Expected 1 trigger, got %d", len(triggers))
		}

		trigger := triggers[0]
		if trigger.Type != testTransportRabbitMQ {
			t.Errorf("Expected trigger type 'rabbitmq', got %q", trigger.Type)
		}
		if trigger.Metadata["queueName"] != "asya-test-actor" {
			t.Errorf("Expected queueName 'asya-test-actor', got %q", trigger.Metadata["queueName"])
		}
		if trigger.Metadata["value"] != "5" {
			t.Errorf("Expected value '5', got %q", trigger.Metadata["value"])
		}
	})

	t.Run("RabbitMQ trigger with custom queue length", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "rabbitmq",
				Scaling: asyav1alpha1.ScalingConfig{
					QueueLength: 10,
				},
			},
		}

		triggers, err := r.buildKEDATriggers(context.Background(), asya)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		trigger := triggers[0]
		if trigger.Metadata["value"] != "10" {
			t.Errorf("Expected value '10', got %q", trigger.Metadata["value"])
		}
	})

	t.Run("SQS trigger", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "sqs",
			},
		}

		triggers, err := r.buildKEDATriggers(context.Background(), asya)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if len(triggers) != 1 {
			t.Fatalf("Expected 1 trigger, got %d", len(triggers))
		}

		trigger := triggers[0]
		if trigger.Type != "aws-sqs-queue" {
			t.Errorf("Expected trigger type 'aws-sqs-queue', got %q", trigger.Type)
		}
		if trigger.Metadata["awsRegion"] != "us-east-1" {
			t.Errorf("Expected awsRegion 'us-east-1', got %q", trigger.Metadata["awsRegion"])
		}
	})

	t.Run("invalid transport returns error", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "invalid",
			},
		}

		_, err := r.buildKEDATriggers(context.Background(), asya)
		if err == nil {
			t.Error("Expected error for invalid transport")
		}
	})

	t.Run("unsupported transport type returns error", func(t *testing.T) {
		r2 := &AsyncActorReconciler{
			TransportRegistry: &asyaconfig.TransportRegistry{
				Transports: map[string]*asyaconfig.TransportConfig{
					"redis": {
						Type:    "redis",
						Enabled: true,
					},
				},
			},
		}

		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "redis",
			},
		}

		_, err := r2.buildKEDATriggers(context.Background(), asya)
		if err == nil {
			t.Error("Expected error for unsupported transport type 'redis'")
		}
	})
}

func TestBuildSQSTrigger(t *testing.T) {
	r := &AsyncActorReconciler{}

	t.Run("valid SQS config", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "sqs",
			Config: &asyaconfig.SQSConfig{
				Region:    "us-west-2",
				AccountID: "123456789012",
			},
		}

		triggers, err := r.buildSQSTrigger(asya, transport, "10")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if len(triggers) != 1 {
			t.Fatalf("Expected 1 trigger, got %d", len(triggers))
		}

		trigger := triggers[0]
		if trigger.Type != "aws-sqs-queue" {
			t.Errorf("Expected type 'aws-sqs-queue', got %q", trigger.Type)
		}
		if trigger.Metadata["queueLength"] != "10" {
			t.Errorf("Expected queueLength '10', got %q", trigger.Metadata["queueLength"])
		}
		if trigger.Metadata["identityOwner"] != "pod" {
			t.Errorf("Expected identityOwner 'pod', got %q", trigger.Metadata["identityOwner"])
		}
	})

	t.Run("invalid config type returns error", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type:   "sqs",
			Config: &asyaconfig.RabbitMQConfig{}, // Wrong type
		}

		_, err := r.buildSQSTrigger(asya, transport, "10")
		if err == nil {
			t.Error("Expected error for invalid config type")
		}
	})

	t.Run("missing region returns error", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type:   "sqs",
			Config: &asyaconfig.SQSConfig{},
		}

		_, err := r.buildSQSTrigger(asya, transport, "10")
		if err == nil {
			t.Error("Expected error for missing region")
		}
	})

	t.Run("missing accountID returns error", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "sqs",
			Config: &asyaconfig.SQSConfig{
				Region: "us-west-2",
			},
		}

		_, err := r.buildSQSTrigger(asya, transport, "10")
		if err == nil {
			t.Error("Expected error for missing accountID")
		}
	})

	t.Run("custom endpoint constructs queueURL correctly", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "sqs",
			Config: &asyaconfig.SQSConfig{
				Region:    "us-west-2",
				AccountID: "123456789012",
				Endpoint:  "http://localhost:4566",
			},
		}

		triggers, err := r.buildSQSTrigger(asya, transport, "10")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		trigger := triggers[0]
		expectedQueueURL := "http://localhost:4566/123456789012/asya-test-actor"
		if trigger.Metadata["queueURL"] != expectedQueueURL {
			t.Errorf("Expected queueURL %q, got %q", expectedQueueURL, trigger.Metadata["queueURL"])
		}
		if trigger.Metadata["awsEndpoint"] != "http://localhost:4566" {
			t.Errorf("Expected awsEndpoint 'http://localhost:4566', got %q", trigger.Metadata["awsEndpoint"])
		}
	})

	t.Run("AWS SQS constructs queueURL correctly", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "sqs",
			Config: &asyaconfig.SQSConfig{
				Region:    "eu-central-1",
				AccountID: "987654321098",
			},
		}

		triggers, err := r.buildSQSTrigger(asya, transport, "10")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		trigger := triggers[0]
		expectedQueueURL := "https://sqs.eu-central-1.amazonaws.com/987654321098/asya-test-actor"
		if trigger.Metadata["queueURL"] != expectedQueueURL {
			t.Errorf("Expected queueURL %q, got %q", expectedQueueURL, trigger.Metadata["queueURL"])
		}
		if _, hasEndpoint := trigger.Metadata["awsEndpoint"]; hasEndpoint {
			t.Error("Expected no awsEndpoint for standard AWS SQS")
		}
	})
}

func TestBuildRabbitMQTrigger(t *testing.T) {
	r := &AsyncActorReconciler{}

	t.Run("valid RabbitMQ config", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "rabbitmq",
			Config: &asyaconfig.RabbitMQConfig{
				Host:     "rabbitmq.default.svc",
				Port:     5672,
				Username: "admin",
			},
		}

		triggers, err := r.buildRabbitMQTrigger(context.Background(), asya, transport, "20")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if len(triggers) != 1 {
			t.Fatalf("Expected 1 trigger, got %d", len(triggers))
		}

		trigger := triggers[0]
		if trigger.Type != testTransportRabbitMQ {
			t.Errorf("Expected type 'rabbitmq', got %q", trigger.Type)
		}
		if trigger.Metadata["value"] != "20" {
			t.Errorf("Expected value '20', got %q", trigger.Metadata["value"])
		}
		if trigger.Metadata["mode"] != "QueueLength" {
			t.Errorf("Expected mode 'QueueLength', got %q", trigger.Metadata["mode"])
		}
	})

	t.Run("invalid config type returns error", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type:   "rabbitmq",
			Config: &asyaconfig.SQSConfig{}, // Wrong type
		}

		_, err := r.buildRabbitMQTrigger(context.Background(), asya, transport, "20")
		if err == nil {
			t.Error("Expected error for invalid config type")
		}
	})

	t.Run("missing host returns error", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "rabbitmq",
			Config: &asyaconfig.RabbitMQConfig{
				Port:     5672,
				Username: "admin",
			},
		}

		_, err := r.buildRabbitMQTrigger(context.Background(), asya, transport, "20")
		if err == nil {
			t.Error("Expected error for missing host")
		}
	})

	t.Run("missing port returns error", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "rabbitmq",
			Config: &asyaconfig.RabbitMQConfig{
				Host:     "rabbitmq.default.svc",
				Username: "admin",
			},
		}

		_, err := r.buildRabbitMQTrigger(context.Background(), asya, transport, "20")
		if err == nil {
			t.Error("Expected error for missing port")
		}
	})

	t.Run("missing username returns error", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name: testActorName,
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "rabbitmq",
			Config: &asyaconfig.RabbitMQConfig{
				Host: "rabbitmq.default.svc",
				Port: 5672,
			},
		}

		_, err := r.buildRabbitMQTrigger(context.Background(), asya, transport, "20")
		if err == nil {
			t.Error("Expected error for missing username")
		}
	})

	t.Run("with password secret ref creates auth reference", func(t *testing.T) {
		schemeBuilder := runtime.NewSchemeBuilder(
			scheme.AddToScheme,
			asyav1alpha1.AddToScheme,
			kedav1alpha1.AddToScheme,
		)
		testScheme := runtime.NewScheme()
		if err := schemeBuilder.AddToScheme(testScheme); err != nil {
			t.Fatalf("Failed to build scheme: %v", err)
		}

		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "test-actor",
				Namespace: "default",
			},
		}
		transport := &asyaconfig.TransportConfig{
			Type: "rabbitmq",
			Config: &asyaconfig.RabbitMQConfig{
				Host:     "rabbitmq.default.svc",
				Port:     5672,
				Username: "admin",
				PasswordSecretRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: "rabbitmq-secret",
					},
					Key: "password",
				},
			},
		}

		fakeClient := fake.NewClientBuilder().
			WithScheme(testScheme).
			Build()

		r := &AsyncActorReconciler{
			Client: fakeClient,
			Scheme: testScheme,
		}

		triggers, err := r.buildRabbitMQTrigger(context.Background(), asya, transport, "20")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if len(triggers) != 1 {
			t.Fatalf("Expected 1 trigger, got %d", len(triggers))
		}

		trigger := triggers[0]
		if trigger.AuthenticationRef == nil {
			t.Error("Expected AuthenticationRef to be set")
		} else if trigger.AuthenticationRef.Name != "test-actor-trigger-auth" {
			t.Errorf("Expected AuthenticationRef name 'test-actor-trigger-auth', got %q", trigger.AuthenticationRef.Name)
		}
	})
}

func TestReconcileTriggerAuthentication(t *testing.T) {
	schemeBuilder := runtime.NewSchemeBuilder(
		scheme.AddToScheme,
		asyav1alpha1.AddToScheme,
		kedav1alpha1.AddToScheme,
	)
	testScheme := runtime.NewScheme()
	if err := schemeBuilder.AddToScheme(testScheme); err != nil {
		t.Fatalf("Failed to build scheme: %v", err)
	}

	t.Run("RabbitMQ with password secret ref", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "test-actor",
				Namespace: "default",
			},
		}

		transport := &asyaconfig.TransportConfig{
			Type: "rabbitmq",
			Config: &asyaconfig.RabbitMQConfig{
				Host:     "rabbitmq.default.svc",
				Port:     5672,
				Username: "guest",
				PasswordSecretRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: "rabbitmq-secret",
					},
					Key: "password",
				},
			},
		}

		fakeClient := fake.NewClientBuilder().
			WithScheme(testScheme).
			Build()

		r := &AsyncActorReconciler{
			Client: fakeClient,
			Scheme: testScheme,
		}

		err := r.reconcileTriggerAuthentication(context.Background(), asya, transport)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		triggerAuth := &kedav1alpha1.TriggerAuthentication{}
		err = fakeClient.Get(context.Background(),
			client.ObjectKey{Name: "test-actor-trigger-auth", Namespace: "default"},
			triggerAuth)
		if err != nil {
			t.Fatalf("Failed to get TriggerAuthentication: %v", err)
		}

		if len(triggerAuth.Spec.SecretTargetRef) != 2 {
			t.Fatalf("Expected 2 SecretTargetRef (username and password), got %d", len(triggerAuth.Spec.SecretTargetRef))
		}

		usernameRef := triggerAuth.Spec.SecretTargetRef[0]
		if usernameRef.Parameter != "username" {
			t.Errorf("Expected parameter 'username', got %q", usernameRef.Parameter)
		}
		if usernameRef.Name != testSecretName {
			t.Errorf("Expected secret name 'rabbitmq-secret', got %q", usernameRef.Name)
		}
		if usernameRef.Key != "username" {
			t.Errorf("Expected secret key 'username', got %q", usernameRef.Key)
		}

		passwordRef := triggerAuth.Spec.SecretTargetRef[1]
		if passwordRef.Parameter != testSecretPassword {
			t.Errorf("Expected parameter 'password', got %q", passwordRef.Parameter)
		}
		if passwordRef.Name != testSecretName {
			t.Errorf("Expected secret name 'rabbitmq-secret', got %q", passwordRef.Name)
		}
		if passwordRef.Key != testSecretPassword {
			t.Errorf("Expected secret key 'password', got %q", passwordRef.Key)
		}
	})

	t.Run("SQS with pod identity", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "test-actor",
				Namespace: "default",
			},
		}

		transport := &asyaconfig.TransportConfig{
			Type: "sqs",
			Config: &asyaconfig.SQSConfig{
				Region:    "us-east-1",
				AccountID: "123456789012",
			},
		}

		fakeClient := fake.NewClientBuilder().
			WithScheme(testScheme).
			Build()

		r := &AsyncActorReconciler{
			Client: fakeClient,
			Scheme: testScheme,
		}

		err := r.reconcileTriggerAuthentication(context.Background(), asya, transport)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		triggerAuth := &kedav1alpha1.TriggerAuthentication{}
		err = fakeClient.Get(context.Background(),
			client.ObjectKey{Name: "test-actor-trigger-auth", Namespace: "default"},
			triggerAuth)
		if err != nil {
			t.Fatalf("Failed to get TriggerAuthentication: %v", err)
		}

		if triggerAuth.Spec.PodIdentity == nil {
			t.Error("Expected PodIdentity to be set for SQS")
		} else if triggerAuth.Spec.PodIdentity.Provider != "aws" {
			t.Errorf("Expected PodIdentity provider 'aws', got %q", triggerAuth.Spec.PodIdentity.Provider)
		}
	})
}

func TestReconcileScaledObject_KEDAStabilization(t *testing.T) {
	testScheme := runtime.NewScheme()
	_ = scheme.AddToScheme(testScheme)
	_ = asyav1alpha1.AddToScheme(testScheme)
	_ = kedav1alpha1.AddToScheme(testScheme)

	t.Run("default cooldown period is 300s", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "test-actor",
				Namespace: "default",
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "sqs",
				Scaling: asyav1alpha1.ScalingConfig{
					Enabled:     true,
					MinReplicas: func() *int32 { v := int32(0); return &v }(),
					MaxReplicas: func() *int32 { v := int32(10); return &v }(),
				},
			},
		}

		fakeClient := fake.NewClientBuilder().
			WithScheme(testScheme).
			WithObjects(asya).
			Build()

		r := &AsyncActorReconciler{
			Client: fakeClient,
			Scheme: testScheme,
			TransportRegistry: &asyaconfig.TransportRegistry{
				Transports: map[string]*asyaconfig.TransportConfig{
					"sqs": {
						Type:    "sqs",
						Enabled: true,
						Config: &asyaconfig.SQSConfig{
							Region:    "us-east-1",
							AccountID: "123456789012",
						},
					},
				},
			},
		}

		err := r.reconcileScaledObject(context.Background(), asya)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		scaledObject := &kedav1alpha1.ScaledObject{}
		err = fakeClient.Get(context.Background(),
			client.ObjectKey{Name: "test-actor", Namespace: "default"},
			scaledObject)
		if err != nil {
			t.Fatalf("Failed to get ScaledObject: %v", err)
		}

		if scaledObject.Spec.CooldownPeriod == nil {
			t.Fatal("Expected CooldownPeriod to be set")
		}
		if *scaledObject.Spec.CooldownPeriod != 300 {
			t.Errorf("Expected default cooldownPeriod 300s, got %d", *scaledObject.Spec.CooldownPeriod)
		}
	})

	t.Run("custom cooldown period overrides default", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "test-actor",
				Namespace: "default",
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "sqs",
				Scaling: asyav1alpha1.ScalingConfig{
					Enabled:        true,
					CooldownPeriod: 600,
				},
			},
		}

		fakeClient := fake.NewClientBuilder().
			WithScheme(testScheme).
			WithObjects(asya).
			Build()

		r := &AsyncActorReconciler{
			Client: fakeClient,
			Scheme: testScheme,
			TransportRegistry: &asyaconfig.TransportRegistry{
				Transports: map[string]*asyaconfig.TransportConfig{
					"sqs": {
						Type:    "sqs",
						Enabled: true,
						Config: &asyaconfig.SQSConfig{
							Region:    "us-east-1",
							AccountID: "123456789012",
						},
					},
				},
			},
		}

		err := r.reconcileScaledObject(context.Background(), asya)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		scaledObject := &kedav1alpha1.ScaledObject{}
		err = fakeClient.Get(context.Background(),
			client.ObjectKey{Name: "test-actor", Namespace: "default"},
			scaledObject)
		if err != nil {
			t.Fatalf("Failed to get ScaledObject: %v", err)
		}

		if scaledObject.Spec.CooldownPeriod == nil {
			t.Fatal("Expected CooldownPeriod to be set")
		}
		if *scaledObject.Spec.CooldownPeriod != 600 {
			t.Errorf("Expected custom cooldownPeriod 600s, got %d", *scaledObject.Spec.CooldownPeriod)
		}
	})

	t.Run("HPA behavior with stabilization windows configured", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "test-actor",
				Namespace: "default",
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "sqs",
				Scaling: asyav1alpha1.ScalingConfig{
					Enabled: true,
				},
			},
		}

		fakeClient := fake.NewClientBuilder().
			WithScheme(testScheme).
			WithObjects(asya).
			Build()

		r := &AsyncActorReconciler{
			Client: fakeClient,
			Scheme: testScheme,
			TransportRegistry: &asyaconfig.TransportRegistry{
				Transports: map[string]*asyaconfig.TransportConfig{
					"sqs": {
						Type:    "sqs",
						Enabled: true,
						Config: &asyaconfig.SQSConfig{
							Region:    "us-east-1",
							AccountID: "123456789012",
						},
					},
				},
			},
		}

		err := r.reconcileScaledObject(context.Background(), asya)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		scaledObject := &kedav1alpha1.ScaledObject{}
		err = fakeClient.Get(context.Background(),
			client.ObjectKey{Name: "test-actor", Namespace: "default"},
			scaledObject)
		if err != nil {
			t.Fatalf("Failed to get ScaledObject: %v", err)
		}

		if scaledObject.Spec.Advanced == nil {
			t.Fatal("Expected Advanced config to be set")
		}
		if scaledObject.Spec.Advanced.HorizontalPodAutoscalerConfig == nil {
			t.Fatal("Expected HorizontalPodAutoscalerConfig to be set")
		}
		if scaledObject.Spec.Advanced.HorizontalPodAutoscalerConfig.Behavior == nil {
			t.Fatal("Expected Behavior to be set")
		}

		behavior := scaledObject.Spec.Advanced.HorizontalPodAutoscalerConfig.Behavior

		if behavior.ScaleDown == nil {
			t.Fatal("Expected ScaleDown rules to be set")
		}
		if behavior.ScaleDown.StabilizationWindowSeconds == nil {
			t.Fatal("Expected ScaleDown stabilization window to be set")
		}
		if *behavior.ScaleDown.StabilizationWindowSeconds != 300 {
			t.Errorf("Expected ScaleDown stabilization window 300s, got %d", *behavior.ScaleDown.StabilizationWindowSeconds)
		}
		if len(behavior.ScaleDown.Policies) != 1 {
			t.Fatalf("Expected 1 ScaleDown policy, got %d", len(behavior.ScaleDown.Policies))
		}
		if behavior.ScaleDown.Policies[0].Value != 1 {
			t.Errorf("Expected ScaleDown policy value 1, got %d", behavior.ScaleDown.Policies[0].Value)
		}

		if behavior.ScaleUp == nil {
			t.Fatal("Expected ScaleUp rules to be set")
		}
		if behavior.ScaleUp.StabilizationWindowSeconds == nil {
			t.Fatal("Expected ScaleUp stabilization window to be set")
		}
		if *behavior.ScaleUp.StabilizationWindowSeconds != 0 {
			t.Errorf("Expected ScaleUp stabilization window 0s, got %d", *behavior.ScaleUp.StabilizationWindowSeconds)
		}
		if len(behavior.ScaleUp.Policies) != 2 {
			t.Fatalf("Expected 2 ScaleUp policies, got %d", len(behavior.ScaleUp.Policies))
		}
	})

	t.Run("existing ScaledObject with incorrect ownership gets deleted and recreated", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "test-actor",
				Namespace: "default",
				UID:       "new-asya-uid",
			},
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "sqs",
				Scaling: asyav1alpha1.ScalingConfig{
					Enabled: true,
				},
			},
		}

		oldOwnerUID := types.UID("old-asya-uid")
		trueVal := true
		existingScaledObject := &kedav1alpha1.ScaledObject{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "test-actor",
				Namespace: "default",
				OwnerReferences: []metav1.OwnerReference{
					{
						APIVersion: "asya.sh/v1alpha1",
						Kind:       "AsyncActor",
						Name:       "test-actor",
						UID:        oldOwnerUID,
						Controller: &trueVal,
					},
				},
			},
		}

		fakeClient := fake.NewClientBuilder().
			WithScheme(testScheme).
			WithObjects(asya, existingScaledObject).
			Build()

		r := &AsyncActorReconciler{
			Client: fakeClient,
			Scheme: testScheme,
			TransportRegistry: &asyaconfig.TransportRegistry{
				Transports: map[string]*asyaconfig.TransportConfig{
					"sqs": {
						Type:    "sqs",
						Enabled: true,
						Config: &asyaconfig.SQSConfig{
							Region:    "us-east-1",
							AccountID: "123456789012",
						},
					},
				},
			},
		}

		err := r.reconcileScaledObject(context.Background(), asya)
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		scaledObject := &kedav1alpha1.ScaledObject{}
		err = fakeClient.Get(context.Background(),
			client.ObjectKey{Name: "test-actor", Namespace: "default"},
			scaledObject)
		if err != nil {
			t.Fatalf("Failed to get ScaledObject: %v", err)
		}

		hasCorrectOwner := false
		for _, ownerRef := range scaledObject.OwnerReferences {
			if ownerRef.Controller != nil && *ownerRef.Controller &&
				ownerRef.UID == asya.UID {
				hasCorrectOwner = true
				break
			}
			if ownerRef.UID == oldOwnerUID {
				t.Errorf("ScaledObject still has old owner UID %s", oldOwnerUID)
			}
		}
		if !hasCorrectOwner {
			t.Error("ScaledObject does not have correct owner reference")
		}
	})
}
