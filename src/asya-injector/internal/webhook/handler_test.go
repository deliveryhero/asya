package webhook

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	admissionv1 "k8s.io/api/admission/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"

	"github.com/deliveryhero/asya/asya-injector/internal/config"
)

func TestHandler_HandleMutate_MethodNotAllowed(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	req := httptest.NewRequest(http.MethodGet, "/mutate", nil)
	w := httptest.NewRecorder()

	handler.HandleMutate(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected status %d, got %d", http.StatusMethodNotAllowed, w.Code)
	}
}

func TestHandler_HandleMutate_EmptyBody(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	req := httptest.NewRequest(http.MethodPost, "/mutate", nil)
	w := httptest.NewRecorder()

	handler.HandleMutate(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected status %d, got %d", http.StatusBadRequest, w.Code)
	}
}

func TestHandler_mutate_AllowsNonPodRequests(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	req := &admissionv1.AdmissionRequest{
		Kind: metav1.GroupVersionKind{
			Kind: "Deployment",
		},
		Operation: admissionv1.Create,
	}

	resp := handler.mutate(context.Background(), req)

	if !resp.Allowed {
		t.Error("expected non-Pod request to be allowed")
	}
}

func TestHandler_mutate_AllowsNonCreateOperations(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	req := &admissionv1.AdmissionRequest{
		Kind: metav1.GroupVersionKind{
			Kind: "Pod",
		},
		Operation: admissionv1.Update,
	}

	resp := handler.mutate(context.Background(), req)

	if !resp.Allowed {
		t.Error("expected non-Create operation to be allowed")
	}
}

func TestHandler_mutate_AllowsPodWithoutInjectLabel(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
			Labels: map[string]string{
				"app": "test",
			},
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "app", Image: "app:v1"},
			},
		},
	}

	podBytes, _ := json.Marshal(pod)

	req := &admissionv1.AdmissionRequest{
		Kind: metav1.GroupVersionKind{
			Kind: "Pod",
		},
		Operation: admissionv1.Create,
		Object: runtime.RawExtension{
			Raw: podBytes,
		},
	}

	resp := handler.mutate(context.Background(), req)

	if !resp.Allowed {
		t.Error("expected pod without inject label to be allowed")
	}
	if resp.Patch != nil {
		t.Error("expected no patch for pod without inject label")
	}
}

func TestHandler_mutate_RejectsPodWithoutActorLabel(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
			Labels: map[string]string{
				"asya.sh/inject": "true",
			},
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "app", Image: "app:v1"},
			},
		},
	}

	podBytes, _ := json.Marshal(pod)

	req := &admissionv1.AdmissionRequest{
		Kind: metav1.GroupVersionKind{
			Kind: "Pod",
		},
		Namespace: "default",
		Operation: admissionv1.Create,
		Object: runtime.RawExtension{
			Raw: podBytes,
		},
	}

	resp := handler.mutate(context.Background(), req)

	if resp.Allowed {
		t.Error("expected pod without actor label to be rejected")
	}
	if resp.Result == nil || resp.Result.Code != http.StatusBadRequest {
		t.Error("expected BadRequest status")
	}
}

func TestShouldInject(t *testing.T) {
	tests := []struct {
		name     string
		labels   map[string]string
		expected bool
	}{
		{
			name:     "nil labels",
			labels:   nil,
			expected: false,
		},
		{
			name:     "empty labels",
			labels:   map[string]string{},
			expected: false,
		},
		{
			name: "inject=true",
			labels: map[string]string{
				"asya.sh/inject": "true",
			},
			expected: true,
		},
		{
			name: "inject=false",
			labels: map[string]string{
				"asya.sh/inject": "false",
			},
			expected: false,
		},
		{
			name: "other labels only",
			labels: map[string]string{
				"app": "test",
			},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			pod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					Labels: tt.labels,
				},
			}

			result := shouldInject(pod)
			if result != tt.expected {
				t.Errorf("shouldInject() = %v, expected %v", result, tt.expected)
			}
		})
	}
}

func TestHandler_HandleMutate_FullFlow(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
			Labels: map[string]string{
				"app": "test",
			},
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "app", Image: "app:v1"},
			},
		},
	}

	podBytes, _ := json.Marshal(pod)

	admissionReview := admissionv1.AdmissionReview{
		TypeMeta: metav1.TypeMeta{
			APIVersion: "admission.k8s.io/v1",
			Kind:       "AdmissionReview",
		},
		Request: &admissionv1.AdmissionRequest{
			UID: "test-uid",
			Kind: metav1.GroupVersionKind{
				Kind: "Pod",
			},
			Namespace: "default",
			Operation: admissionv1.Create,
			Object: runtime.RawExtension{
				Raw: podBytes,
			},
		},
	}

	body, _ := json.Marshal(admissionReview)

	req := httptest.NewRequest(http.MethodPost, "/mutate", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.HandleMutate(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status %d, got %d", http.StatusOK, w.Code)
	}

	var response admissionv1.AdmissionReview
	if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}

	if response.Response == nil {
		t.Fatal("response.Response is nil")
	}

	if response.Response.UID != "test-uid" {
		t.Errorf("expected UID 'test-uid', got '%s'", response.Response.UID)
	}

	if !response.Response.Allowed {
		t.Error("expected request to be allowed")
	}
}
