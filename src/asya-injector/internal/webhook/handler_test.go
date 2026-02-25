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

func TestHandler_mutateAsyncActor_NilRequest(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	resp := handler.mutateAsyncActor(context.Background(), nil)

	if resp.Allowed {
		t.Error("expected nil request to be rejected")
	}
	if resp.Result == nil || resp.Result.Code != http.StatusBadRequest {
		t.Error("expected BadRequest status")
	}
}

func TestHandler_mutateAsyncActor_SetsLabelAndCompositionSelector(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	obj := map[string]any{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "AsyncActor",
		"metadata": map[string]any{
			"name":      "test-actor",
			"namespace": "default",
			"labels":    map[string]any{},
		},
		"spec": map[string]any{
			"actor":     "text-analyzer",
			"transport": "sqs",
		},
	}
	objBytes, _ := json.Marshal(obj)

	req := &admissionv1.AdmissionRequest{
		Name:      "test-actor",
		Namespace: "default",
		Operation: admissionv1.Create,
		Object:    runtime.RawExtension{Raw: objBytes},
	}

	resp := handler.mutateAsyncActor(context.Background(), req)

	if !resp.Allowed {
		t.Errorf("expected request to be allowed, got rejected: %v", resp.Result)
	}
	if resp.Patch == nil {
		t.Fatal("expected patch to be set")
	}
	if resp.PatchType == nil || *resp.PatchType != admissionv1.PatchTypeJSONPatch {
		t.Error("expected JSON patch type")
	}

	var patches []map[string]any
	if err := json.Unmarshal(resp.Patch, &patches); err != nil {
		t.Fatalf("failed to unmarshal patch: %v", err)
	}
	if len(patches) != 2 {
		t.Fatalf("expected 2 patch operations (label + compositionSelector), got %d: %v", len(patches), patches)
	}

	// First op: actor label
	if patches[0]["op"] != "add" {
		t.Errorf("expected op 'add' for label, got %v", patches[0]["op"])
	}
	if patches[0]["value"] != "text-analyzer" {
		t.Errorf("expected label value 'text-analyzer', got %v", patches[0]["value"])
	}

	// Second op: compositionSelector
	if patches[1]["op"] != "add" {
		t.Errorf("expected op 'add' for compositionSelector, got %v", patches[1]["op"])
	}
	if patches[1]["path"] != "/spec/compositionSelector" {
		t.Errorf("expected path '/spec/compositionSelector', got %v", patches[1]["path"])
	}
	selectorVal, ok := patches[1]["value"].(map[string]any)
	if !ok {
		t.Fatalf("expected compositionSelector value to be a map, got %T", patches[1]["value"])
	}
	matchLabels, ok := selectorVal["matchLabels"].(map[string]any)
	if !ok {
		t.Fatalf("expected matchLabels to be a map, got %T", selectorVal["matchLabels"])
	}
	if matchLabels["asya.sh/transport"] != "sqs" {
		t.Errorf("expected transport label 'sqs', got %v", matchLabels["asya.sh/transport"])
	}
}

func TestHandler_mutateAsyncActor_ReplacesExistingLabel(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	obj := map[string]any{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "AsyncActor",
		"metadata": map[string]any{
			"name":      "test-actor",
			"namespace": "default",
			"labels": map[string]any{
				"asya.sh/actor": "old-name",
			},
		},
		"spec": map[string]any{
			"actor":     "new-name",
			"transport": "sqs",
		},
	}
	objBytes, _ := json.Marshal(obj)

	req := &admissionv1.AdmissionRequest{
		Name:      "test-actor",
		Namespace: "default",
		Operation: admissionv1.Update,
		Object:    runtime.RawExtension{Raw: objBytes},
	}

	resp := handler.mutateAsyncActor(context.Background(), req)

	if !resp.Allowed {
		t.Errorf("expected request to be allowed, got rejected: %v", resp.Result)
	}

	var patches []map[string]any
	if err := json.Unmarshal(resp.Patch, &patches); err != nil {
		t.Fatalf("failed to unmarshal patch: %v", err)
	}
	if patches[0]["op"] != "replace" {
		t.Errorf("expected op 'replace', got %v", patches[0]["op"])
	}
	if patches[0]["value"] != "new-name" {
		t.Errorf("expected value 'new-name', got %v", patches[0]["value"])
	}
}

func TestHandler_mutateAsyncActor_DoesNotOverwriteCompositionSelector(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	obj := map[string]any{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "AsyncActor",
		"metadata": map[string]any{
			"name":      "test-actor",
			"namespace": "default",
		},
		"spec": map[string]any{
			"actor":     "my-actor",
			"transport": "sqs",
			"compositionSelector": map[string]any{
				"matchLabels": map[string]any{
					"asya.sh/transport": "rabbitmq", // deliberately different
				},
			},
		},
	}
	objBytes, _ := json.Marshal(obj)

	req := &admissionv1.AdmissionRequest{
		Name:      "test-actor",
		Namespace: "default",
		Operation: admissionv1.Create,
		Object:    runtime.RawExtension{Raw: objBytes},
	}

	resp := handler.mutateAsyncActor(context.Background(), req)

	if !resp.Allowed {
		t.Errorf("expected request to be allowed, got rejected: %v", resp.Result)
	}

	var patches []map[string]any
	if err := json.Unmarshal(resp.Patch, &patches); err != nil {
		t.Fatalf("failed to unmarshal patch: %v", err)
	}
	// Should only have the actor label patch, NOT a compositionSelector patch
	if len(patches) != 1 {
		t.Fatalf("expected 1 patch (label only), got %d: %v", len(patches), patches)
	}
	for _, p := range patches {
		if p["path"] == "/spec/compositionSelector" {
			t.Error("should not overwrite existing compositionSelector")
		}
	}
}

func TestHandler_mutateAsyncActor_NoTransportSkipsCompositionSelector(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	obj := map[string]any{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "AsyncActor",
		"metadata": map[string]any{
			"name":      "test-actor",
			"namespace": "default",
		},
		"spec": map[string]any{
			"actor": "my-actor",
			// no transport field
		},
	}
	objBytes, _ := json.Marshal(obj)

	req := &admissionv1.AdmissionRequest{
		Name:      "test-actor",
		Namespace: "default",
		Operation: admissionv1.Create,
		Object:    runtime.RawExtension{Raw: objBytes},
	}

	resp := handler.mutateAsyncActor(context.Background(), req)

	if !resp.Allowed {
		t.Errorf("expected request to be allowed, got rejected: %v", resp.Result)
	}

	var patches []map[string]any
	if err := json.Unmarshal(resp.Patch, &patches); err != nil {
		t.Fatalf("failed to unmarshal patch: %v", err)
	}
	// Only actor label patch, no compositionSelector
	if len(patches) != 1 {
		t.Fatalf("expected 1 patch (label only), got %d: %v", len(patches), patches)
	}
}

func TestHandler_mutateAsyncActor_MissingSpecActor(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	obj := map[string]any{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "AsyncActor",
		"metadata": map[string]any{
			"name":      "test-actor",
			"namespace": "default",
		},
		"spec": map[string]any{
			"transport": "sqs",
		},
	}
	objBytes, _ := json.Marshal(obj)

	req := &admissionv1.AdmissionRequest{
		Name:      "test-actor",
		Namespace: "default",
		Operation: admissionv1.Create,
		Object:    runtime.RawExtension{Raw: objBytes},
	}

	resp := handler.mutateAsyncActor(context.Background(), req)

	if resp.Allowed {
		t.Error("expected request without spec.actor to be rejected")
	}
	if resp.Result == nil || resp.Result.Code != http.StatusBadRequest {
		t.Error("expected BadRequest status")
	}
}

func TestHandler_mutateAsyncActor_NoLabelsMap(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "test:latest",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}
	handler := NewHandler(nil, nil, cfg)

	obj := map[string]any{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "AsyncActor",
		"metadata": map[string]any{
			"name":      "test-actor",
			"namespace": "default",
		},
		"spec": map[string]any{
			"actor":     "my-actor",
			"transport": "sqs",
		},
	}
	objBytes, _ := json.Marshal(obj)

	req := &admissionv1.AdmissionRequest{
		Name:      "test-actor",
		Namespace: "default",
		Operation: admissionv1.Create,
		Object:    runtime.RawExtension{Raw: objBytes},
	}

	resp := handler.mutateAsyncActor(context.Background(), req)

	if !resp.Allowed {
		t.Errorf("expected request to be allowed, got rejected: %v", resp.Result)
	}

	var patches []map[string]any
	if err := json.Unmarshal(resp.Patch, &patches); err != nil {
		t.Fatalf("failed to unmarshal patch: %v", err)
	}
	// 2 ops: create labels map + add compositionSelector
	if len(patches) != 2 {
		t.Fatalf("expected 2 patch operations, got %d: %v", len(patches), patches)
	}
	// First op: creates entire labels object
	if patches[0]["op"] != "add" {
		t.Errorf("expected op 'add', got %v", patches[0]["op"])
	}
	if patches[0]["path"] != "/metadata/labels" {
		t.Errorf("expected path '/metadata/labels', got %v", patches[0]["path"])
	}
	valueMap, ok := patches[0]["value"].(map[string]any)
	if !ok {
		t.Fatalf("expected value to be a map, got %T", patches[0]["value"])
	}
	if valueMap["asya.sh/actor"] != "my-actor" {
		t.Errorf("expected actor label 'my-actor', got %v", valueMap["asya.sh/actor"])
	}
}

func TestBuildActorLabelPatch(t *testing.T) {
	tests := []struct {
		name           string
		existingLabels map[string]string
		actorName      string
		wantOp         string
		wantPath       string
	}{
		{
			name:           "nil labels - creates labels map",
			existingLabels: nil,
			actorName:      "my-actor",
			wantOp:         "add",
			wantPath:       "/metadata/labels",
		},
		{
			name:           "empty labels - adds label",
			existingLabels: map[string]string{},
			actorName:      "my-actor",
			wantOp:         "add",
			wantPath:       "/metadata/labels/asya.sh~1actor",
		},
		{
			name:           "existing other labels - adds label",
			existingLabels: map[string]string{"app": "test"},
			actorName:      "my-actor",
			wantOp:         "add",
			wantPath:       "/metadata/labels/asya.sh~1actor",
		},
		{
			name:           "existing actor label - replaces",
			existingLabels: map[string]string{"asya.sh/actor": "old-name"},
			actorName:      "new-name",
			wantOp:         "replace",
			wantPath:       "/metadata/labels/asya.sh~1actor",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ops, err := buildActorLabelPatch(tt.existingLabels, tt.actorName)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			if len(ops) != 1 {
				t.Fatalf("expected 1 operation, got %d", len(ops))
			}
			if ops[0].Op != tt.wantOp {
				t.Errorf("expected op %q, got %v", tt.wantOp, ops[0].Op)
			}
			if ops[0].Path != tt.wantPath {
				t.Errorf("expected path %q, got %v", tt.wantPath, ops[0].Path)
			}
		})
	}
}

func TestBuildCompositionSelectorOps(t *testing.T) {
	tests := []struct {
		name          string
		obj           map[string]interface{}
		transport     string
		wantOps       int
		wantTransport string
	}{
		{
			name: "injects selector when absent",
			obj: map[string]interface{}{
				"spec": map[string]interface{}{
					"actor":     "my-actor",
					"transport": "rabbitmq",
				},
			},
			transport:     "rabbitmq",
			wantOps:       1,
			wantTransport: "rabbitmq",
		},
		{
			name: "does not overwrite existing selector",
			obj: map[string]interface{}{
				"spec": map[string]interface{}{
					"actor":     "my-actor",
					"transport": "sqs",
					"compositionSelector": map[string]interface{}{
						"matchLabels": map[string]interface{}{
							"asya.sh/transport": "rabbitmq",
						},
					},
				},
			},
			transport: "sqs",
			wantOps:   0,
		},
		{
			name: "empty transport produces no ops",
			obj: map[string]interface{}{
				"spec": map[string]interface{}{
					"actor": "my-actor",
				},
			},
			transport: "",
			wantOps:   0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ops := buildCompositionSelectorOps(tt.obj, tt.transport)
			if len(ops) != tt.wantOps {
				t.Fatalf("expected %d ops, got %d: %v", tt.wantOps, len(ops), ops)
			}
			if tt.wantOps == 0 {
				return
			}
			if ops[0].Op != "add" {
				t.Errorf("expected op 'add', got %v", ops[0].Op)
			}
			if ops[0].Path != "/spec/compositionSelector" {
				t.Errorf("expected path '/spec/compositionSelector', got %v", ops[0].Path)
			}
			val, ok := ops[0].Value.(map[string]interface{})
			if !ok {
				t.Fatalf("expected value map, got %T", ops[0].Value)
			}
			ml, ok := val["matchLabels"].(map[string]string)
			if !ok {
				t.Fatalf("expected matchLabels map[string]string, got %T", val["matchLabels"])
			}
			if ml["asya.sh/transport"] != tt.wantTransport {
				t.Errorf("expected transport %q, got %v", tt.wantTransport, ml["asya.sh/transport"])
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
