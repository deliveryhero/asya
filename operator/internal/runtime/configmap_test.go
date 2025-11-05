package runtime

import (
	"context"
	"fmt"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

// mockLoader implements the Loader interface for testing.
type mockLoader struct {
	content string
	err     error
}

func (m *mockLoader) Load(ctx context.Context, version string) (string, error) {
	if m.err != nil {
		return "", m.err
	}
	return m.content, nil
}

func TestConfigMapReconciler_Reconcile_CreateNew(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	content := "#!/usr/bin/env python3\nprint('test')\n"
	loader := &mockLoader{content: content}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "")

	err := reconciler.Reconcile(context.Background())
	if err != nil {
		t.Fatalf("Reconcile() unexpected error: %v", err)
	}

	// Verify ConfigMap was created
	cm := &corev1.ConfigMap{}
	err = fakeClient.Get(context.Background(), client.ObjectKey{
		Name:      ConfigMapName,
		Namespace: "test-ns",
	}, cm)

	if err != nil {
		t.Fatalf("Failed to get created ConfigMap: %v", err)
	}

	if cm.Data[RuntimeScriptKey] != content {
		t.Errorf("ConfigMap content = %q, want %q", cm.Data[RuntimeScriptKey], content)
	}

	// Verify labels
	if cm.Labels["app.kubernetes.io/name"] != "asya-runtime" {
		t.Errorf("Missing or incorrect label app.kubernetes.io/name")
	}
}

func TestConfigMapReconciler_Reconcile_UpdateExisting(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	oldContent := "old content"
	existing := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      ConfigMapName,
			Namespace: "test-ns",
		},
		Data: map[string]string{
			RuntimeScriptKey: oldContent,
		},
	}

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(existing).
		Build()

	newContent := "#!/usr/bin/env python3\nprint('updated')\n"
	loader := &mockLoader{content: newContent}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "")

	err := reconciler.Reconcile(context.Background())
	if err != nil {
		t.Fatalf("Reconcile() unexpected error: %v", err)
	}

	// Verify ConfigMap was updated
	cm := &corev1.ConfigMap{}
	err = fakeClient.Get(context.Background(), client.ObjectKey{
		Name:      ConfigMapName,
		Namespace: "test-ns",
	}, cm)

	if err != nil {
		t.Fatalf("Failed to get updated ConfigMap: %v", err)
	}

	if cm.Data[RuntimeScriptKey] != newContent {
		t.Errorf("ConfigMap content = %q, want %q", cm.Data[RuntimeScriptKey], newContent)
	}
}

func TestConfigMapReconciler_Reconcile_NoUpdateNeeded(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	content := "#!/usr/bin/env python3\nprint('test')\n"
	existing := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      ConfigMapName,
			Namespace: "test-ns",
		},
		Data: map[string]string{
			RuntimeScriptKey: content,
		},
	}

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(existing).
		Build()

	loader := &mockLoader{content: content}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "")

	err := reconciler.Reconcile(context.Background())
	if err != nil {
		t.Fatalf("Reconcile() unexpected error: %v", err)
	}

	// Verify ConfigMap still has same content
	cm := &corev1.ConfigMap{}
	err = fakeClient.Get(context.Background(), client.ObjectKey{
		Name:      ConfigMapName,
		Namespace: "test-ns",
	}, cm)

	if err != nil {
		t.Fatalf("Failed to get ConfigMap: %v", err)
	}

	if cm.Data[RuntimeScriptKey] != content {
		t.Errorf("ConfigMap content = %q, want %q", cm.Data[RuntimeScriptKey], content)
	}
}

func TestConfigMapReconciler_Reconcile_LoaderError(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	loader := &mockLoader{err: fmt.Errorf("failed to load")}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "")

	err := reconciler.Reconcile(context.Background())
	if err == nil {
		t.Fatal("Reconcile() expected error, got nil")
	}

	if !contains(err.Error(), "failed to load runtime script") {
		t.Errorf("Reconcile() error = %v, want error containing 'failed to load runtime script'", err)
	}
}

func TestConfigMapReconciler_Reconcile_EmptyContent(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	loader := &mockLoader{content: ""}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "")

	err := reconciler.Reconcile(context.Background())
	if err == nil {
		t.Fatal("Reconcile() expected error, got nil")
	}

	if !contains(err.Error(), "runtime script content is empty") {
		t.Errorf("Reconcile() error = %v, want error containing 'runtime script content is empty'", err)
	}
}

func TestConfigMapReconciler_Reconcile_AddsMissingLabels(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	oldContent := "old"
	existing := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      ConfigMapName,
			Namespace: "test-ns",
			Labels:    map[string]string{}, // No labels initially
		},
		Data: map[string]string{
			RuntimeScriptKey: oldContent,
		},
	}

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(existing).
		Build()

	newContent := "new"
	loader := &mockLoader{content: newContent}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "")

	err := reconciler.Reconcile(context.Background())
	if err != nil {
		t.Fatalf("Reconcile() unexpected error: %v", err)
	}

	// Verify labels were added
	cm := &corev1.ConfigMap{}
	err = fakeClient.Get(context.Background(), client.ObjectKey{
		Name:      ConfigMapName,
		Namespace: "test-ns",
	}, cm)

	if err != nil {
		t.Fatalf("Failed to get ConfigMap: %v", err)
	}

	expectedLabels := map[string]string{
		"app.kubernetes.io/name":      "asya-runtime",
		"app.kubernetes.io/component": "runtime",
		"app.kubernetes.io/part-of":   "asya",
	}

	for key, expectedValue := range expectedLabels {
		if cm.Labels[key] != expectedValue {
			t.Errorf("Label %s = %q, want %q", key, cm.Labels[key], expectedValue)
		}
	}
}

func TestConfigMapReconciler_Delete(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	existing := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      ConfigMapName,
			Namespace: "test-ns",
		},
		Data: map[string]string{
			RuntimeScriptKey: "content",
		},
	}

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(existing).
		Build()

	loader := &mockLoader{content: "test"}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "")

	err := reconciler.Delete(context.Background())
	if err != nil {
		t.Fatalf("Delete() unexpected error: %v", err)
	}

	// Verify ConfigMap was deleted
	cm := &corev1.ConfigMap{}
	err = fakeClient.Get(context.Background(), client.ObjectKey{
		Name:      ConfigMapName,
		Namespace: "test-ns",
	}, cm)

	if err == nil {
		t.Fatal("Expected ConfigMap to be deleted, but it still exists")
	}
}

func TestConfigMapReconciler_Delete_NotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()

	loader := &mockLoader{content: "test"}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "")

	err := reconciler.Delete(context.Background())
	if err != nil {
		t.Fatalf("Delete() unexpected error when ConfigMap doesn't exist: %v", err)
	}
}

func TestNewConfigMapReconciler(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()
	loader := &mockLoader{content: "test"}

	reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", "v1.0.0")

	if reconciler == nil {
		t.Fatal("NewConfigMapReconciler() returned nil")
	}

	if reconciler.Client != fakeClient {
		t.Error("NewConfigMapReconciler() client not set correctly")
	}

	if reconciler.Loader != loader {
		t.Error("NewConfigMapReconciler() loader not set correctly")
	}

	if reconciler.Namespace != "test-ns" {
		t.Errorf("NewConfigMapReconciler() namespace = %q, want 'test-ns'", reconciler.Namespace)
	}

	if reconciler.Version != "v1.0.0" {
		t.Errorf("NewConfigMapReconciler() version = %q, want 'v1.0.0'", reconciler.Version)
	}
}
