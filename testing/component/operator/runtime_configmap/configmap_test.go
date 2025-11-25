//go:build integration

package controller_test

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
	controller "github.com/asya/operator/internal/controller"
	"github.com/asya/operator/internal/transports"
	kedav1alpha1 "github.com/kedacore/keda/v2/apis/keda/v1alpha1"
)

const (
	testTransportRabbitMQ = "rabbitmq"
	runtimeConfigMap      = "asya-runtime"
)

// setupReconciler creates a reconciler with a temporary runtime script
func setupReconciler(t *testing.T, scheme *runtime.Scheme, objects ...client.Object) *controller.AsyncActorReconciler {
	// Create a temporary runtime script for testing
	tmpDir := t.TempDir()
	runtimePath := filepath.Join(tmpDir, "asya_runtime.py")

	// Write a minimal valid Python script
	runtimeContent := `#!/usr/bin/env python3
import socket
import os

def handle_requests():
    """Main request handler"""
    pass

def _load_function():
    """Load the user function"""
    pass

if __name__ == "__main__":
    handle_requests()
`
	if err := os.WriteFile(runtimePath, []byte(runtimeContent), 0644); err != nil {
		t.Fatalf("Failed to create test runtime script: %v", err)
	}

	// Set environment variable for runtime script path and skip queue operations
	t.Setenv("ASYA_RUNTIME_SCRIPT_PATH", runtimePath)
	t.Setenv("ASYA_SKIP_QUEUE_OPERATIONS", "true")

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(objects...).
		WithStatusSubresource(&asyav1alpha1.AsyncActor{}).
		Build()

	transportRegistry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			testTransportRabbitMQ: {
				Type:    testTransportRabbitMQ,
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

	return &controller.AsyncActorReconciler{
		Client:            fakeClient,
		Scheme:            scheme,
		TransportRegistry: transportRegistry,
		TransportFactory:  transports.NewFactory(fakeClient, transportRegistry),
	}
}

func TestReconcileRuntimeConfigMap_CreatedDuringReconciliation(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	_ = appsv1.AddToScheme(scheme)
	_ = kedav1alpha1.AddToScheme(scheme)

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
			UID:       "test-uid-123",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
			Workload: asyav1alpha1.WorkloadConfig{
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

	r := setupReconciler(t, scheme, asya)

	// Trigger reconciliation
	req := ctrl.Request{
		NamespacedName: types.NamespacedName{
			Name:      asya.Name,
			Namespace: asya.Namespace,
		},
	}

	_, err := r.Reconcile(context.Background(), req)
	if err != nil {
		t.Fatalf("Reconcile failed: %v", err)
	}

	// Verify ConfigMap was created
	cm := &corev1.ConfigMap{}
	err = r.Client.Get(context.Background(), client.ObjectKey{Name: runtimeConfigMap, Namespace: "default"}, cm)
	if err != nil {
		t.Fatalf("Failed to get ConfigMap: %v", err)
	}

	// Verify ConfigMap has no owner references (shared resource)
	if len(cm.OwnerReferences) > 0 {
		t.Errorf("Expected ConfigMap to have no owner references, got %d", len(cm.OwnerReferences))
	}

	// Verify the ConfigMap contains runtime data
	runtimeContent := cm.Data["asya_runtime.py"]
	if runtimeContent == "" {
		t.Fatal("Expected ConfigMap to contain asya_runtime.py data")
	}

	// Validate it contains expected content
	if !strings.Contains(runtimeContent, "def handle_requests():") {
		t.Error("Expected runtime with handle_requests() function")
	}
	if !strings.Contains(runtimeContent, "def _load_function():") {
		t.Error("Expected runtime with _load_function() function")
	}

	// Verify labels
	expectedLabels := map[string]string{
		"app.kubernetes.io/name":      "asya-runtime",
		"app.kubernetes.io/component": "asya-runtime",
		"app.kubernetes.io/part-of":   "asya",
	}
	for k, v := range expectedLabels {
		if cm.Labels[k] != v {
			t.Errorf("Expected label %s=%s, got %s", k, v, cm.Labels[k])
		}
	}
}

func TestReconcileRuntimeConfigMap_SharedBetweenActors(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	_ = appsv1.AddToScheme(scheme)
	_ = kedav1alpha1.AddToScheme(scheme)

	actor1 := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "actor-1",
			Namespace: "default",
			UID:       "uid-1",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
			Workload: asyav1alpha1.WorkloadConfig{
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{{Name: "asya-runtime", Image: "python:3.13-slim"}},
					},
				},
			},
		},
	}

	actor2 := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "actor-2",
			Namespace: "default",
			UID:       "uid-2",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
			Workload: asyav1alpha1.WorkloadConfig{
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{{Name: "asya-runtime", Image: "python:3.13-slim"}},
					},
				},
			},
		},
	}

	r := setupReconciler(t, scheme, actor1, actor2)

	// Reconcile both actors
	for _, actor := range []*asyav1alpha1.AsyncActor{actor1, actor2} {
		req := ctrl.Request{
			NamespacedName: types.NamespacedName{Name: actor.Name, Namespace: actor.Namespace},
		}
		if _, err := r.Reconcile(context.Background(), req); err != nil {
			t.Fatalf("Reconcile failed for %s: %v", actor.Name, err)
		}
	}

	// Verify ConfigMap exists and is shared (no owner references)
	cm := &corev1.ConfigMap{}
	err := r.Client.Get(context.Background(), client.ObjectKey{Name: runtimeConfigMap, Namespace: "default"}, cm)
	if err != nil {
		t.Fatalf("Failed to get ConfigMap: %v", err)
	}

	if len(cm.OwnerReferences) > 0 {
		t.Errorf("Expected ConfigMap to have no owner references when shared, got %d", len(cm.OwnerReferences))
	}
}

func TestReconcileRuntimeConfigMap_UpdatesExistingConfigMap(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	_ = appsv1.AddToScheme(scheme)
	_ = kedav1alpha1.AddToScheme(scheme)

	existingCM := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      runtimeConfigMap,
			Namespace: "default",
			Labels: map[string]string{
				"old-label": "old-value",
			},
		},
		Data: map[string]string{
			"old-key": "old-value",
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
			UID:       "test-uid-123",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
			Workload: asyav1alpha1.WorkloadConfig{
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{{Name: "asya-runtime", Image: "python:3.13-slim"}},
					},
				},
			},
		},
	}

	r := setupReconciler(t, scheme, existingCM, asya)

	req := ctrl.Request{
		NamespacedName: types.NamespacedName{Name: asya.Name, Namespace: asya.Namespace},
	}
	if _, err := r.Reconcile(context.Background(), req); err != nil {
		t.Fatalf("Reconcile failed: %v", err)
	}

	cm := &corev1.ConfigMap{}
	err := r.Client.Get(context.Background(), client.ObjectKey{Name: runtimeConfigMap, Namespace: "default"}, cm)
	if err != nil {
		t.Fatalf("Failed to get ConfigMap: %v", err)
	}

	// Verify the ConfigMap was updated with runtime data
	runtimeContent := cm.Data["asya_runtime.py"]
	if runtimeContent == "" {
		t.Fatal("Expected ConfigMap to be updated with asya_runtime.py data")
	}

	// Verify labels were updated
	if cm.Labels["app.kubernetes.io/name"] != "asya-runtime" {
		t.Error("Expected ConfigMap labels to be updated")
	}

	if len(cm.OwnerReferences) > 0 {
		t.Error("Expected ConfigMap to have no owner references after update")
	}
}
