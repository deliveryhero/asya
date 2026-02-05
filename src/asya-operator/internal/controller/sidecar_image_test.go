package controller

import (
	"os"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
)

func TestGetSidecarImage(t *testing.T) {
	tests := []struct {
		name     string
		envValue string
		want     string
	}{
		{
			name:     "default image when env not set",
			envValue: "",
			want:     "asya-sidecar:latest",
		},
		{
			name:     "custom image from environment",
			envValue: "custom-registry/asya-sidecar:v1.2.3",
			want:     "custom-registry/asya-sidecar:v1.2.3",
		},
		{
			name:     "different tag",
			envValue: "asya-sidecar:dev",
			want:     "asya-sidecar:dev",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.envValue != "" {
				if err := os.Setenv("ASYA_SIDECAR_IMAGE", tt.envValue); err != nil {
					t.Fatalf("Failed to set env var: %v", err)
				}
				defer func() {
					if err := os.Unsetenv("ASYA_SIDECAR_IMAGE"); err != nil {
						t.Logf("Failed to unset env var: %v", err)
					}
				}()
			} else {
				if err := os.Unsetenv("ASYA_SIDECAR_IMAGE"); err != nil {
					t.Fatalf("Failed to unset env var: %v", err)
				}
			}

			got := getSidecarImage()
			if got != tt.want {
				t.Errorf("getSidecarImage() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestInjectSidecar_SidecarImage(t *testing.T) {
	tests := []struct {
		name          string
		envImage      string
		specImage     string
		expectedImage string
	}{
		{
			name:          "default image from environment",
			envImage:      "asya-sidecar:latest",
			specImage:     "",
			expectedImage: "asya-sidecar:latest",
		},
		{
			name:          "custom image from environment",
			envImage:      "custom-registry/asya-sidecar:v1.0.0",
			specImage:     "",
			expectedImage: "custom-registry/asya-sidecar:v1.0.0",
		},
		{
			name:          "spec image overrides environment",
			envImage:      "asya-sidecar:latest",
			specImage:     "override-registry/asya-sidecar:v2.0.0",
			expectedImage: "override-registry/asya-sidecar:v2.0.0",
		},
		{
			name:          "spec image overrides custom environment",
			envImage:      "custom-registry/asya-sidecar:v1.0.0",
			specImage:     "user-registry/asya-sidecar:dev",
			expectedImage: "user-registry/asya-sidecar:dev",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := os.Setenv("ASYA_SIDECAR_IMAGE", tt.envImage); err != nil {
				t.Fatalf("Failed to set env var: %v", err)
			}
			defer func() {
				if err := os.Unsetenv("ASYA_SIDECAR_IMAGE"); err != nil {
					t.Logf("Failed to unset env var: %v", err)
				}
			}()

			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)
			_ = corev1.AddToScheme(scheme)

			r := &AsyncActorReconciler{
				Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme: scheme,
				TransportRegistry: &asyaconfig.TransportRegistry{
					Transports: make(map[string]*asyaconfig.TransportConfig),
				},
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Sidecar: asyav1alpha1.SidecarConfig{
						Image: tt.specImage,
					},
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

			result := r.injectSidecar(asya)

			var sidecarContainer *corev1.Container
			for i := range result.Spec.Containers {
				if result.Spec.Containers[i].Name == sidecarName {
					sidecarContainer = &result.Spec.Containers[i]
					break
				}
			}

			if sidecarContainer == nil {
				t.Fatal("Sidecar container not found")
			}

			if sidecarContainer.Image != tt.expectedImage {
				t.Errorf("Expected sidecar image %s, got %s", tt.expectedImage, sidecarContainer.Image)
			}
		})
	}
}
