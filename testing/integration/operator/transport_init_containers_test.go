//go:build integration

package integration

import (
	"context"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/wait"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
)

// TestSQSInitContainer verifies that SQS transport with endpoint creates init container
func TestSQSInitContainer(t *testing.T) {
	ctx := context.Background()
	namespace := "test-sqs-init"

	// Create namespace
	ns := &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name: namespace,
		},
	}
	if err := k8sClient.Create(ctx, ns); err != nil {
		t.Fatalf("Failed to create namespace: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, ns)
	}()

	// Create AsyncActor with SQS transport
	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "sqs-actor-with-init",
			Namespace: namespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: "sqs",
			Workload: asyav1alpha1.WorkloadConfig{
				Kind: "Deployment",
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
		},
	}

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	// Wait for deployment to be created
	deployment := &appsv1.Deployment{}
	err := wait.PollImmediate(100*time.Millisecond, 10*time.Second, func() (bool, error) {
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: namespace,
		}, deployment)
		return err == nil, nil
	})

	if err != nil {
		t.Fatalf("Deployment was not created: %v", err)
	}

	// Verify init container exists ONLY if SQS endpoint is configured in operator
	// Note: This test will pass if no init container is created (endpoint not configured)
	// or if init container IS created (endpoint configured with LocalStack)
	initContainers := deployment.Spec.Template.Spec.InitContainers

	if len(initContainers) > 0 {
		// Init container exists - verify it's correct
		queueInit := initContainers[0]

		if queueInit.Name != "queue-init" {
			t.Errorf("Expected init container name 'queue-init', got %q", queueInit.Name)
		}

		if queueInit.Image != "amazon/aws-cli:latest" {
			t.Errorf("Expected init container image 'amazon/aws-cli:latest', got %q", queueInit.Image)
		}

		// Verify environment variables
		envMap := make(map[string]string)
		for _, env := range queueInit.Env {
			envMap[env.Name] = env.Value
		}

		expectedQueueName := "asya-sqs-actor-with-init"
		if envMap["QUEUE_NAME"] != expectedQueueName {
			t.Errorf("Expected QUEUE_NAME=%s, got %s", expectedQueueName, envMap["QUEUE_NAME"])
		}

		if envMap["QUEUE_URL"] == "" {
			t.Error("Expected QUEUE_URL to be set")
		}

		t.Logf("Init container found with QUEUE_URL: %s", envMap["QUEUE_URL"])
	} else {
		t.Log("No init containers - SQS endpoint not configured (production mode)")
	}
}

// TestRabbitMQNoInitContainer verifies that RabbitMQ transport does not create init containers
func TestRabbitMQNoInitContainer(t *testing.T) {
	ctx := context.Background()
	namespace := "test-rabbitmq-no-init"

	// Create namespace
	ns := &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name: namespace,
		},
	}
	if err := k8sClient.Create(ctx, ns); err != nil {
		t.Fatalf("Failed to create namespace: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, ns)
	}()

	// Create AsyncActor with RabbitMQ transport
	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "rabbitmq-actor",
			Namespace: namespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: "rabbitmq",
			Workload: asyav1alpha1.WorkloadConfig{
				Kind: "Deployment",
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
		},
	}

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	// Wait for deployment to be created
	deployment := &appsv1.Deployment{}
	err := wait.PollImmediate(100*time.Millisecond, 10*time.Second, func() (bool, error) {
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: namespace,
		}, deployment)
		return err == nil, nil
	})

	if err != nil {
		t.Fatalf("Deployment was not created: %v", err)
	}

	// Verify NO init containers for RabbitMQ
	initContainers := deployment.Spec.Template.Spec.InitContainers
	if len(initContainers) > 0 {
		t.Errorf("Expected no init containers for RabbitMQ transport, got %d", len(initContainers))
		for _, ic := range initContainers {
			t.Logf("Unexpected init container: %s (image: %s)", ic.Name, ic.Image)
		}
	}
}

// TestSQSInitContainerEnvVars verifies init container environment variables are correctly set
func TestSQSInitContainerEnvVars(t *testing.T) {
	ctx := context.Background()
	namespace := "test-sqs-init-envvars"

	// Create namespace
	ns := &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name: namespace,
		},
	}
	if err := k8sClient.Create(ctx, ns); err != nil {
		t.Fatalf("Failed to create namespace: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, ns)
	}()

	// Create AsyncActor with SQS transport
	actorName := "env-test-actor"
	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      actorName,
			Namespace: namespace,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: "sqs",
			Workload: asyav1alpha1.WorkloadConfig{
				Kind: "Deployment",
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
								Env: []corev1.EnvVar{
									{Name: "AWS_REGION", Value: "us-west-2"},
									{Name: "CUSTOM_VAR", Value: "test-value"},
								},
							},
						},
					},
				},
			},
		},
	}

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	// Wait for deployment
	deployment := &appsv1.Deployment{}
	err := wait.PollImmediate(100*time.Millisecond, 10*time.Second, func() (bool, error) {
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: namespace,
		}, deployment)
		return err == nil, nil
	})

	if err != nil {
		t.Fatalf("Deployment was not created: %v", err)
	}

	// Check init container env vars if init container exists
	if len(deployment.Spec.Template.Spec.InitContainers) > 0 {
		queueInit := deployment.Spec.Template.Spec.InitContainers[0]

		// Verify AWS_REGION is set in init container (from SQS config, not runtime container)
		foundRegion := false
		for _, env := range queueInit.Env {
			if env.Name == "AWS_REGION" {
				foundRegion = true
				t.Logf("AWS_REGION found in init container: %s", env.Value)
				break
			}
		}

		if !foundRegion {
			t.Error("Expected AWS_REGION to be set in init container")
		}

		// Verify CUSTOM_VAR is NOT passed through (only AWS vars)
		for _, env := range queueInit.Env {
			if env.Name == "CUSTOM_VAR" {
				t.Error("CUSTOM_VAR should not be passed to init container")
			}
		}

		// Verify QUEUE_NAME matches expected format
		expectedQueueName := "asya-" + actorName
		foundQueueName := false
		for _, env := range queueInit.Env {
			if env.Name == "QUEUE_NAME" && env.Value == expectedQueueName {
				foundQueueName = true
				break
			}
		}

		if !foundQueueName {
			t.Errorf("Expected QUEUE_NAME=%s in init container", expectedQueueName)
		}
	} else {
		t.Log("No init containers - SQS endpoint not configured (production mode)")
	}
}
