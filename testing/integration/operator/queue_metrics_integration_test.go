//go:build integration

package integration

import (
	"context"
	"fmt"
	"testing"
	"time"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	"github.com/asya/operator/internal/config"
	controller "github.com/asya/operator/internal/controller"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

// TestGetSQSQueueMetrics_WithStaticCredentials verifies that getSQSQueueMetrics
// correctly reads credentials from secrets and uses them to authenticate with SQS.
// This test prevents regression of the bug where GetQueueMetrics attempted IMDS
// authentication instead of using static credentials from secrets.
func TestGetSQSQueueMetrics_WithStaticCredentials(t *testing.T) {
	// This test requires LocalStack or real SQS endpoint
	endpoint := "http://localhost:4566" // LocalStack default
	region := "us-east-1"
	accessKey := "test"
	secretKey := "test"

	// Create secret with credentials
	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "sqs-creds",
			Namespace: "test-ns",
		},
		Data: map[string][]byte{
			"access-key-id":     []byte(accessKey),
			"secret-access-key": []byte(secretKey),
		},
	}

	// Create AsyncActor
	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "test-ns",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: "sqs",
		},
	}

	// Create SQS config with credentials
	sqsConfig := &config.SQSConfig{
		Region:            region,
		Endpoint:          endpoint,
		VisibilityTimeout: 30,
		WaitTimeSeconds:   20,
		Credentials: &config.SQSCredentialsConfig{
			AccessKeyIdSecretRef: &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "sqs-creds"},
				Key:                  "access-key-id",
			},
			SecretAccessKeySecretRef: &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "sqs-creds"},
				Key:                  "secret-access-key",
			},
		},
	}

	// Create fake client with secret
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(secret, asya).
		Build()

	// Create transport registry
	registry := &config.TransportRegistry{
		Transports: map[string]*config.TransportConfig{
			"sqs": {
				Type:    "sqs",
				Enabled: true,
				Config:  sqsConfig,
			},
		},
	}

	// Create reconciler
	reconciler := &controller.AsyncActorReconciler{
		Client:            fakeClient,
		Scheme:            scheme,
		TransportRegistry: registry,
	}

	// Create queue in LocalStack first
	ctx := context.Background()
	queueName := "test-queue-metrics-creds"

	// Try to create SQS client - this will fail if LocalStack is not running
	sqsClient, err := reconciler.CreateSQSClient(ctx, sqsConfig, "test-ns")
	if err != nil {
		t.Skipf("Skipping test: could not create SQS client (LocalStack may not be running): %v", err)
	}

	// Create queue with timeout to avoid hanging if LocalStack is not reachable
	createCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	_, err = sqsClient.CreateQueue(createCtx, &sqs.CreateQueueInput{
		QueueName: aws.String(queueName),
	})
	if err != nil {
		t.Skipf("Skipping test: could not create queue in LocalStack: %v", err)
	}

	// Cleanup
	defer func() {
		urlResult, _ := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
			QueueName: aws.String(queueName),
		})
		if urlResult != nil {
			sqsClient.DeleteQueue(ctx, &sqs.DeleteQueueInput{
				QueueUrl: urlResult.QueueUrl,
			})
		}
	}()

	// Test: Call GetSQSQueueMetrics
	metrics, err := reconciler.GetSQSQueueMetrics(ctx, asya, queueName)
	if err != nil {
		t.Fatalf("getSQSQueueMetrics failed: %v", err)
	}

	// Verify metrics were returned
	if metrics == nil {
		t.Fatal("Expected non-nil metrics")
	}

	if metrics.Queued < 0 {
		t.Errorf("Expected non-negative Queued value, got %d", metrics.Queued)
	}

	if metrics.Processing == nil {
		t.Error("Expected non-nil Processing value")
	} else if *metrics.Processing < 0 {
		t.Errorf("Expected non-negative Processing value, got %d", *metrics.Processing)
	}

	t.Logf("Successfully retrieved queue metrics with static credentials: queued=%d, processing=%d",
		metrics.Queued, *metrics.Processing)
}

// TestGetSQSQueueMetrics_MissingCredentials verifies that getSQSQueueMetrics
// returns an error when credentials are missing from secrets
func TestGetSQSQueueMetrics_MissingCredentials(t *testing.T) {
	// Create AsyncActor
	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "test-ns",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: "sqs",
		},
	}

	// Create SQS config with credentials that reference non-existent secret
	sqsConfig := &config.SQSConfig{
		Region:            "us-east-1",
		Endpoint:          "http://localhost:4566",
		VisibilityTimeout: 30,
		Credentials: &config.SQSCredentialsConfig{
			AccessKeyIdSecretRef: &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "missing-secret"},
				Key:                  "access-key-id",
			},
		},
	}

	// Create fake client WITHOUT the secret
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	_ = asyav1alpha1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(asya).
		Build()

	// Create transport registry
	registry := &config.TransportRegistry{
		Transports: map[string]*config.TransportConfig{
			"sqs": {
				Type:    "sqs",
				Enabled: true,
				Config:  sqsConfig,
			},
		},
	}

	// Create reconciler
	reconciler := &controller.AsyncActorReconciler{
		Client:            fakeClient,
		Scheme:            scheme,
		TransportRegistry: registry,
	}

	// Test: Call GetSQSQueueMetrics - should fail because secret doesn't exist
	ctx := context.Background()
	_, err := reconciler.GetSQSQueueMetrics(ctx, asya, "test-queue")

	if err == nil {
		t.Fatal("Expected error when credentials secret is missing, got nil")
	}

	expectedErr := "failed to create SQS client"
	if fmt.Sprintf("%v", err)[:len(expectedErr)] != expectedErr {
		t.Errorf("Expected error containing '%s', got: %v", expectedErr, err)
	}

	t.Logf("Correctly returned error for missing credentials: %v", err)
}
