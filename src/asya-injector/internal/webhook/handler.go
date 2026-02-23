package webhook

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"

	admissionv1 "k8s.io/api/admission/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/serializer"
	"k8s.io/client-go/dynamic"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/deliveryhero/asya/asya-injector/internal/config"
	"github.com/deliveryhero/asya/asya-injector/internal/injection"
)

const (
	// LabelInject is the label that triggers sidecar injection
	LabelInject = "asya.sh/inject"

	// LabelActor is the label that identifies the actor name
	LabelActor = "asya.sh/actor"
)

var (
	runtimeScheme = runtime.NewScheme()
	codecs        = serializer.NewCodecFactory(runtimeScheme)
	deserializer  = codecs.UniversalDeserializer()
)

func init() {
	_ = admissionv1.AddToScheme(runtimeScheme)
	_ = corev1.AddToScheme(runtimeScheme)
}

// Handler handles mutating webhook requests
type Handler struct {
	k8sClient     client.Client
	dynamicClient dynamic.Interface
	config        *config.Config
	injector      *injection.Injector
}

// NewHandler creates a new webhook handler
func NewHandler(k8sClient client.Client, dynamicClient dynamic.Interface, cfg *config.Config) *Handler {
	return &Handler{
		k8sClient:     k8sClient,
		dynamicClient: dynamicClient,
		config:        cfg,
		injector:      injection.NewInjector(cfg),
	}
}

// HandleMutate handles the mutating admission webhook request
func (h *Handler) HandleMutate(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		slog.Error("Failed to read request body", "error", err)
		http.Error(w, "failed to read request body", http.StatusBadRequest)
		return
	}

	if len(body) == 0 {
		slog.Error("Empty request body")
		http.Error(w, "empty request body", http.StatusBadRequest)
		return
	}

	// Decode the admission review
	var admissionReview admissionv1.AdmissionReview
	if _, _, err := deserializer.Decode(body, nil, &admissionReview); err != nil {
		slog.Error("Failed to decode admission review", "error", err)
		http.Error(w, "failed to decode admission review", http.StatusBadRequest)
		return
	}

	// Process the admission request
	response := h.mutate(r.Context(), admissionReview.Request)

	// Build the response
	admissionReview.Response = response
	admissionReview.Response.UID = admissionReview.Request.UID

	respBytes, err := json.Marshal(admissionReview)
	if err != nil {
		slog.Error("Failed to marshal response", "error", err)
		http.Error(w, "failed to marshal response", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(respBytes)
}

// mutate processes the admission request and returns an admission response
func (h *Handler) mutate(ctx context.Context, req *admissionv1.AdmissionRequest) *admissionv1.AdmissionResponse {
	if req == nil {
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusBadRequest,
				Message: "empty admission request",
			},
		}
	}

	slog.Debug("Processing admission request",
		"name", req.Name,
		"namespace", req.Namespace,
		"kind", req.Kind.Kind,
		"operation", req.Operation,
	)

	// Only handle Pod CREATE operations
	if req.Kind.Kind != "Pod" || req.Operation != admissionv1.Create {
		slog.Debug("Skipping non-Pod or non-Create request")
		return &admissionv1.AdmissionResponse{Allowed: true}
	}

	// Decode the pod
	var pod corev1.Pod
	if err := json.Unmarshal(req.Object.Raw, &pod); err != nil {
		slog.Error("Failed to decode pod", "error", err)
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusBadRequest,
				Message: fmt.Sprintf("failed to decode pod: %v", err),
			},
		}
	}

	// Check if injection is requested
	if !shouldInject(&pod) {
		slog.Debug("Pod does not have injection label", "pod", pod.Name)
		return &admissionv1.AdmissionResponse{Allowed: true}
	}

	// Get actor name from label
	actorName := pod.Labels[LabelActor]
	if actorName == "" {
		slog.Error("Pod has inject label but missing actor label", "pod", pod.Name)
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusBadRequest,
				Message: fmt.Sprintf("pod has %s=true but missing %s label", LabelInject, LabelActor),
			},
		}
	}

	slog.Info("Injecting sidecar",
		"pod", pod.Name,
		"namespace", req.Namespace,
		"actor", actorName,
	)

	// Query AsyncActor XR for configuration
	actorConfig, err := h.getAsyncActorConfig(ctx, req.Namespace, actorName)
	if err != nil {
		slog.Error("Failed to get AsyncActor config", "error", err, "actor", actorName)
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusServiceUnavailable,
				Message: fmt.Sprintf("failed to get AsyncActor %s: %v (infrastructure may not be ready)", actorName, err),
			},
		}
	}

	// Perform the injection
	mutatedPod, err := h.injector.Inject(&pod, actorConfig)
	if err != nil {
		slog.Error("Failed to inject sidecar", "error", err)
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusInternalServerError,
				Message: fmt.Sprintf("failed to inject sidecar: %v", err),
			},
		}
	}

	// Create JSON patch
	patch, err := createPatch(&pod, mutatedPod)
	if err != nil {
		slog.Error("Failed to create patch", "error", err)
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusInternalServerError,
				Message: fmt.Sprintf("failed to create patch: %v", err),
			},
		}
	}

	slog.Info("Sidecar injected successfully",
		"pod", pod.Name,
		"actor", actorName,
		"patchLength", len(patch),
	)

	patchType := admissionv1.PatchTypeJSONPatch
	return &admissionv1.AdmissionResponse{
		Allowed: true,
		Patch:   patch,
		PatchType: &patchType,
	}
}

// shouldInject checks if a pod should have the sidecar injected
func shouldInject(pod *corev1.Pod) bool {
	if pod.Labels == nil {
		return false
	}
	return pod.Labels[LabelInject] == "true"
}

// createPatch creates a JSON patch to transform the original pod into the mutated pod
func createPatch(original, mutated *corev1.Pod) ([]byte, error) {
	origBytes, err := json.Marshal(original)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal original pod: %w", err)
	}

	mutatedBytes, err := json.Marshal(mutated)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal mutated pod: %w", err)
	}

	// Use strategic merge patch to create JSON patch
	return createJSONPatch(origBytes, mutatedBytes)
}

// HandleMutateAsyncActor handles the mutating admission webhook request for AsyncActor resources.
// It copies spec.actor to metadata.labels["asya.sh/actor"] on CREATE and UPDATE operations.
func (h *Handler) HandleMutateAsyncActor(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		slog.Error("Failed to read request body", "error", err)
		http.Error(w, "failed to read request body", http.StatusBadRequest)
		return
	}

	if len(body) == 0 {
		slog.Error("Empty request body")
		http.Error(w, "empty request body", http.StatusBadRequest)
		return
	}

	var admissionReview admissionv1.AdmissionReview
	if _, _, err := deserializer.Decode(body, nil, &admissionReview); err != nil {
		slog.Error("Failed to decode admission review", "error", err)
		http.Error(w, "failed to decode admission review", http.StatusBadRequest)
		return
	}

	response := h.mutateAsyncActor(r.Context(), admissionReview.Request)

	admissionReview.Response = response
	admissionReview.Response.UID = admissionReview.Request.UID

	respBytes, err := json.Marshal(admissionReview)
	if err != nil {
		slog.Error("Failed to marshal response", "error", err)
		http.Error(w, "failed to marshal response", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(respBytes)
}

// mutateAsyncActor copies spec.actor to metadata.labels["asya.sh/actor"]
func (h *Handler) mutateAsyncActor(_ context.Context, req *admissionv1.AdmissionRequest) *admissionv1.AdmissionResponse {
	if req == nil {
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusBadRequest,
				Message: "empty admission request",
			},
		}
	}

	slog.Debug("Processing AsyncActor admission request",
		"name", req.Name,
		"namespace", req.Namespace,
		"operation", req.Operation,
	)

	// Decode the object as unstructured
	var obj unstructured.Unstructured
	if err := json.Unmarshal(req.Object.Raw, &obj.Object); err != nil {
		slog.Error("Failed to decode AsyncActor", "error", err)
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusBadRequest,
				Message: fmt.Sprintf("failed to decode object: %v", err),
			},
		}
	}

	// Extract spec.actor
	actorName, found, err := unstructured.NestedString(obj.Object, "spec", "actor")
	if err != nil || !found || actorName == "" {
		slog.Error("spec.actor is required", "name", req.Name)
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusBadRequest,
				Message: "spec.actor is required",
			},
		}
	}

	// Build JSON patch to set metadata.labels["asya.sh/actor"]
	patch, err := buildActorLabelPatch(obj.GetLabels(), actorName)
	if err != nil {
		slog.Error("Failed to build patch", "error", err)
		return &admissionv1.AdmissionResponse{
			Allowed: false,
			Result: &metav1.Status{
				Code:    http.StatusInternalServerError,
				Message: fmt.Sprintf("failed to build patch: %v", err),
			},
		}
	}

	slog.Info("Setting actor label on AsyncActor",
		"name", req.Name,
		"namespace", req.Namespace,
		"actor", actorName,
	)

	patchType := admissionv1.PatchTypeJSONPatch
	return &admissionv1.AdmissionResponse{
		Allowed:   true,
		Patch:     patch,
		PatchType: &patchType,
	}
}

// jsonPatchOp represents a single RFC 6902 JSON Patch operation.
type jsonPatchOp struct {
	Op    string `json:"op"`
	Path  string `json:"path"`
	Value any    `json:"value"`
}

// buildActorLabelPatch creates an RFC 6902 JSON Patch to set the asya.sh/actor label.
// Handles both cases: labels map missing entirely, or label needs add/replace.
func buildActorLabelPatch(existingLabels map[string]string, actorName string) ([]byte, error) {
	if existingLabels == nil {
		return json.Marshal([]jsonPatchOp{{
			Op:    "add",
			Path:  "/metadata/labels",
			Value: map[string]string{LabelActor: actorName},
		}})
	}

	// RFC 6902: "/" in JSON Pointer path is escaped as "~1"
	op := "add"
	if _, exists := existingLabels[LabelActor]; exists {
		op = "replace"
	}
	return json.Marshal([]jsonPatchOp{{
		Op:    op,
		Path:  "/metadata/labels/asya.sh~1actor",
		Value: actorName,
	}})
}
