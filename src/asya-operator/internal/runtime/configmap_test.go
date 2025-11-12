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

func TestConfigMapReconciler_Reconcile(t *testing.T) {
	tests := []struct {
		name          string
		loaderContent string
		loaderErr     error
		existingCM    *corev1.ConfigMap
		wantErr       bool
		errContains   string
		verifyFn      func(t *testing.T, cm *corev1.ConfigMap)
	}{
		{
			name:          "create new ConfigMap",
			loaderContent: "#!/usr/bin/env python3\nprint('test')\n",
			verifyFn: func(t *testing.T, cm *corev1.ConfigMap) {
				if cm.Data[RuntimeScriptKey] != "#!/usr/bin/env python3\nprint('test')\n" {
					t.Errorf("ConfigMap content mismatch")
				}
				if cm.Labels["app.kubernetes.io/name"] != "asya-runtime" {
					t.Errorf("Missing or incorrect label app.kubernetes.io/name")
				}
			},
		},
		{
			name:          "update existing ConfigMap",
			loaderContent: "#!/usr/bin/env python3\nprint('updated')\n",
			existingCM: &corev1.ConfigMap{
				ObjectMeta: metav1.ObjectMeta{
					Name:      ConfigMapName,
					Namespace: "test-ns",
				},
				Data: map[string]string{
					RuntimeScriptKey: "old content",
				},
			},
			verifyFn: func(t *testing.T, cm *corev1.ConfigMap) {
				if cm.Data[RuntimeScriptKey] != "#!/usr/bin/env python3\nprint('updated')\n" {
					t.Errorf("ConfigMap not updated")
				}
			},
		},
		{
			name:          "no update needed",
			loaderContent: "#!/usr/bin/env python3\nprint('test')\n",
			existingCM: &corev1.ConfigMap{
				ObjectMeta: metav1.ObjectMeta{
					Name:      ConfigMapName,
					Namespace: "test-ns",
				},
				Data: map[string]string{
					RuntimeScriptKey: "#!/usr/bin/env python3\nprint('test')\n",
				},
			},
			verifyFn: func(t *testing.T, cm *corev1.ConfigMap) {
				if cm.Data[RuntimeScriptKey] != "#!/usr/bin/env python3\nprint('test')\n" {
					t.Errorf("ConfigMap content changed unexpectedly")
				}
			},
		},
		{
			name:        "loader error",
			loaderErr:   fmt.Errorf("failed to load"),
			wantErr:     true,
			errContains: "failed to load runtime script",
		},
		{
			name:          "empty content error",
			loaderContent: "",
			wantErr:       true,
			errContains:   "runtime script content is empty",
		},
		{
			name:          "adds missing labels",
			loaderContent: "new",
			existingCM: &corev1.ConfigMap{
				ObjectMeta: metav1.ObjectMeta{
					Name:      ConfigMapName,
					Namespace: "test-ns",
					Labels:    map[string]string{},
				},
				Data: map[string]string{
					RuntimeScriptKey: "old",
				},
			},
			verifyFn: func(t *testing.T, cm *corev1.ConfigMap) {
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
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = corev1.AddToScheme(scheme)

			builder := fake.NewClientBuilder().WithScheme(scheme)
			if tt.existingCM != nil {
				builder = builder.WithObjects(tt.existingCM)
			}
			fakeClient := builder.Build()

			loader := &mockLoader{content: tt.loaderContent, err: tt.loaderErr}
			reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", nil)

			err := reconciler.Reconcile(context.Background())

			if tt.wantErr {
				if err == nil {
					t.Fatal("Reconcile() expected error, got nil")
				}
				if tt.errContains != "" && !contains(err.Error(), tt.errContains) {
					t.Errorf("Reconcile() error = %v, want error containing %q", err, tt.errContains)
				}
				return
			}

			if err != nil {
				t.Fatalf("Reconcile() unexpected error: %v", err)
			}

			if tt.verifyFn != nil {
				cm := &corev1.ConfigMap{}
				err = fakeClient.Get(context.Background(), client.ObjectKey{
					Name:      ConfigMapName,
					Namespace: "test-ns",
				}, cm)
				if err != nil {
					t.Fatalf("Failed to get ConfigMap: %v", err)
				}
				tt.verifyFn(t, cm)
			}
		})
	}
}

func TestConfigMapReconciler_Delete(t *testing.T) {
	tests := []struct {
		name       string
		existingCM *corev1.ConfigMap
		wantErr    bool
	}{
		{
			name: "delete existing ConfigMap",
			existingCM: &corev1.ConfigMap{
				ObjectMeta: metav1.ObjectMeta{
					Name:      ConfigMapName,
					Namespace: "test-ns",
				},
				Data: map[string]string{
					RuntimeScriptKey: "content",
				},
			},
		},
		{
			name:       "delete non-existent ConfigMap",
			existingCM: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = corev1.AddToScheme(scheme)

			builder := fake.NewClientBuilder().WithScheme(scheme)
			if tt.existingCM != nil {
				builder = builder.WithObjects(tt.existingCM)
			}
			fakeClient := builder.Build()

			loader := &mockLoader{content: "test"}
			reconciler := NewConfigMapReconciler(fakeClient, loader, "test-ns", nil)

			err := reconciler.Delete(context.Background())
			if tt.wantErr && err == nil {
				t.Fatal("Delete() expected error, got nil")
			}
			if !tt.wantErr && err != nil {
				t.Fatalf("Delete() unexpected error: %v", err)
			}

			if tt.existingCM != nil && !tt.wantErr {
				cm := &corev1.ConfigMap{}
				err = fakeClient.Get(context.Background(), client.ObjectKey{
					Name:      ConfigMapName,
					Namespace: "test-ns",
				}, cm)
				if err == nil {
					t.Fatal("Expected ConfigMap to be deleted, but it still exists")
				}
			}
		})
	}
}

func TestNewConfigMapReconciler(t *testing.T) {
	tests := []struct {
		name           string
		namespace      string
		customLabels   map[string]string
		expectedLabels map[string]string
	}{
		{
			name:      "default labels",
			namespace: "test-ns",
			expectedLabels: map[string]string{
				"app.kubernetes.io/name":      "asya-runtime",
				"app.kubernetes.io/component": "runtime",
				"app.kubernetes.io/part-of":   "asya",
			},
		},
		{
			name:      "custom labels",
			namespace: "test-ns",
			customLabels: map[string]string{
				"custom-label": "custom-value",
				"env":          "test",
			},
			expectedLabels: map[string]string{
				"custom-label": "custom-value",
				"env":          "test",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = corev1.AddToScheme(scheme)

			fakeClient := fake.NewClientBuilder().WithScheme(scheme).Build()
			loader := &mockLoader{content: "test"}

			reconciler := NewConfigMapReconciler(fakeClient, loader, tt.namespace, tt.customLabels)

			if reconciler == nil {
				t.Fatal("NewConfigMapReconciler() returned nil")
			}

			if reconciler.Client != fakeClient {
				t.Error("NewConfigMapReconciler() client not set correctly")
			}

			if reconciler.Loader != loader {
				t.Error("NewConfigMapReconciler() loader not set correctly")
			}

			if reconciler.Namespace != tt.namespace {
				t.Errorf("NewConfigMapReconciler() namespace = %q, want %q", reconciler.Namespace, tt.namespace)
			}

			if len(reconciler.Labels) != len(tt.expectedLabels) {
				t.Errorf("NewConfigMapReconciler() labels count = %d, want %d", len(reconciler.Labels), len(tt.expectedLabels))
			}
			for key, expectedValue := range tt.expectedLabels {
				if reconciler.Labels[key] != expectedValue {
					t.Errorf("NewConfigMapReconciler() label %s = %q, want %q", key, reconciler.Labels[key], expectedValue)
				}
			}

			if tt.customLabels != nil {
				err := reconciler.Reconcile(context.Background())
				if err != nil {
					t.Fatalf("Reconcile() unexpected error: %v", err)
				}

				cm := &corev1.ConfigMap{}
				err = fakeClient.Get(context.Background(), client.ObjectKey{
					Name:      ConfigMapName,
					Namespace: tt.namespace,
				}, cm)

				if err != nil {
					t.Fatalf("Failed to get created ConfigMap: %v", err)
				}

				for key, expectedValue := range tt.customLabels {
					if cm.Labels[key] != expectedValue {
						t.Errorf("ConfigMap label %s = %q, want %q", key, cm.Labels[key], expectedValue)
					}
				}
			}
		})
	}
}
