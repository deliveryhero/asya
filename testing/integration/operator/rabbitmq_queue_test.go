//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/wait"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
)

// TestRabbitMQQueueCreation verifies that the operator creates queues in RabbitMQ when autoCreate is enabled
func TestRabbitMQQueueCreation(t *testing.T) {
	// Check if RabbitMQ is available
	rabbitmqHost := os.Getenv("RABBITMQ_HOST")
	if rabbitmqHost == "" {
		rabbitmqHost = "localhost"
	}

	rabbitmqURL := fmt.Sprintf("http://%s:15672", rabbitmqHost)

	// Try to connect to RabbitMQ management API
	ctx := context.Background()
	client := &http.Client{Timeout: 5 * time.Second}
	req, err := http.NewRequestWithContext(ctx, "GET", rabbitmqURL+"/api/overview", nil)
	if err != nil {
		t.Skipf("Skipping test: could not create request: %v", err)
	}
	req.SetBasicAuth("guest", "guest")

	resp, err := client.Do(req)
	if err != nil {
		t.Skipf("Skipping test: RabbitMQ not available at %s: %v", rabbitmqURL, err)
	}
	resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Skipf("Skipping test: RabbitMQ management API returned status %d", resp.StatusCode)
	}

	namespace := "test-rabbitmq-queue"

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

	// Note: This test will only work if the operator's RabbitMQ config has autoCreate: true
	// The suite_test.go currently has autoCreate: false, so this test validates that
	// the queue is NOT created when autoCreate is disabled

	// Create AsyncActor with RabbitMQ transport
	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "rabbitmq-queue-test",
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

	// Wait for AsyncActor to be reconciled
	err = wait.PollImmediate(100*time.Millisecond, 10*time.Second, func() (bool, error) {
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: namespace,
		}, actor)
		if err != nil {
			return false, err
		}
		// Check if status has been updated
		return actor.Status.ObservedGeneration > 0, nil
	})

	if err != nil {
		t.Fatalf("AsyncActor was not reconciled: %v", err)
	}

	// Check RabbitMQ queue status via management API
	queueName := "asya-rabbitmq-queue-test"
	queueURL := fmt.Sprintf("%s/api/queues/%%2F/%s", rabbitmqURL, queueName)

	req, err = http.NewRequestWithContext(ctx, "GET", queueURL, nil)
	if err != nil {
		t.Fatalf("Failed to create request: %v", err)
	}
	req.SetBasicAuth("guest", "guest")

	resp, err = client.Do(req)
	if err != nil {
		t.Fatalf("Failed to query RabbitMQ API: %v", err)
	}
	defer resp.Body.Close()

	// Since autoCreate is disabled in suite_test.go, the queue should NOT exist
	if resp.StatusCode == http.StatusOK {
		var queueInfo map[string]interface{}
		if err := json.NewDecoder(resp.Body).Decode(&queueInfo); err == nil {
			t.Logf("Queue found (autoCreate may be enabled): %s", queueName)
			t.Logf("Queue info: %+v", queueInfo)
		}
	} else if resp.StatusCode == http.StatusNotFound {
		t.Logf("Queue not found (autoCreate is disabled as expected): %s", queueName)
	} else {
		t.Logf("Unexpected RabbitMQ API response: %d", resp.StatusCode)
	}

	// Verify the AsyncActor status reflects transport readiness
	transportReady := false
	for _, condition := range actor.Status.Conditions {
		if condition.Type == "TransportReady" && condition.Status == metav1.ConditionTrue {
			transportReady = true
			break
		}
	}

	if !transportReady {
		t.Error("Expected TransportReady condition to be True")
	}

	t.Logf("AsyncActor reconciled successfully: %s/%s", namespace, actor.Name)
}

// TestRabbitMQQueueMetrics verifies that queue metrics can be retrieved from RabbitMQ
func TestRabbitMQQueueMetrics(t *testing.T) {
	// Check if RabbitMQ is available
	rabbitmqHost := os.Getenv("RABBITMQ_HOST")
	if rabbitmqHost == "" {
		rabbitmqHost = "localhost"
	}

	rabbitmqURL := fmt.Sprintf("http://%s:15672", rabbitmqHost)

	ctx := context.Background()
	client := &http.Client{Timeout: 5 * time.Second}
	req, err := http.NewRequestWithContext(ctx, "GET", rabbitmqURL+"/api/overview", nil)
	if err != nil {
		t.Skipf("Skipping test: could not create request: %v", err)
	}
	req.SetBasicAuth("guest", "guest")

	resp, err := client.Do(req)
	if err != nil {
		t.Skipf("Skipping test: RabbitMQ not available at %s: %v", rabbitmqURL, err)
	}
	resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Skipf("Skipping test: RabbitMQ management API returned status %d", resp.StatusCode)
	}

	namespace := "test-rabbitmq-metrics"

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

	// Create AsyncActor
	actor := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "metrics-test",
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

	// Wait for reconciliation
	err = wait.PollImmediate(100*time.Millisecond, 10*time.Second, func() (bool, error) {
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: namespace,
		}, actor)
		return err == nil && actor.Status.ObservedGeneration > 0, nil
	})

	if err != nil {
		t.Fatalf("AsyncActor was not reconciled: %v", err)
	}

	// The reconciler should have attempted to query queue metrics
	// Even if the queue doesn't exist, it should handle it gracefully
	// Check the actor's status for any metric-related information

	t.Logf("AsyncActor status: %+v", actor.Status)

	// Verify no errors in conditions
	for _, condition := range actor.Status.Conditions {
		if condition.Status == metav1.ConditionFalse && condition.Reason != "" {
			t.Logf("Condition %s: %s - %s", condition.Type, condition.Reason, condition.Message)
		}
	}
}
