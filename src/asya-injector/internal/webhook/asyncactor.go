package webhook

import (
	"context"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"

	"github.com/deliveryhero/asya/asya-injector/internal/injection"
)

var asyncActorGVR = schema.GroupVersionResource{
	Group:    "asya.sh",
	Version:  "v1alpha1",
	Resource: "asyncactors",
}

// getAsyncActorConfig queries the AsyncActor XR and extracts configuration for injection
func (h *Handler) getAsyncActorConfig(ctx context.Context, namespace, actorName string) (*injection.ActorConfig, error) {
	// Query the AsyncActor claim in the namespace
	asyncActor, err := h.dynamicClient.Resource(asyncActorGVR).Namespace(namespace).Get(ctx, actorName, metav1.GetOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to get AsyncActor %s/%s: %w", namespace, actorName, err)
	}

	// Check if the AsyncActor is ready
	ready, err := isAsyncActorReady(asyncActor)
	if err != nil {
		return nil, fmt.Errorf("failed to check AsyncActor status: %w", err)
	}
	if !ready {
		return nil, fmt.Errorf("AsyncActor %s is not ready (infrastructure provisioning may be in progress)", actorName)
	}

	// Extract configuration from AsyncActor spec and status
	config, err := extractActorConfig(asyncActor)
	if err != nil {
		return nil, fmt.Errorf("failed to extract config from AsyncActor: %w", err)
	}

	config.ActorName = actorName
	config.Namespace = namespace

	return config, nil
}

// isAsyncActorReady checks if the AsyncActor's infrastructure is ready
func isAsyncActorReady(asyncActor *unstructured.Unstructured) (bool, error) {
	// Check the status.conditions for Ready=True
	conditions, found, err := unstructured.NestedSlice(asyncActor.Object, "status", "conditions")
	if err != nil {
		return false, fmt.Errorf("failed to get conditions: %w", err)
	}
	if !found || len(conditions) == 0 {
		// If no conditions yet, infrastructure is not ready
		return false, nil
	}

	for _, c := range conditions {
		condition, ok := c.(map[string]interface{})
		if !ok {
			continue
		}

		condType, _, _ := unstructured.NestedString(condition, "type")
		condStatus, _, _ := unstructured.NestedString(condition, "status")

		if condType == "Ready" && condStatus == "True" {
			return true, nil
		}
	}

	// Also check Crossplane's Synced condition
	for _, c := range conditions {
		condition, ok := c.(map[string]interface{})
		if !ok {
			continue
		}

		condType, _, _ := unstructured.NestedString(condition, "type")
		condStatus, _, _ := unstructured.NestedString(condition, "status")

		if condType == "Synced" && condStatus == "True" {
			return true, nil
		}
	}

	return false, nil
}

// extractActorConfig extracts injection configuration from the AsyncActor resource
func extractActorConfig(asyncActor *unstructured.Unstructured) (*injection.ActorConfig, error) {
	spec, found, err := unstructured.NestedMap(asyncActor.Object, "spec")
	if err != nil || !found {
		return nil, fmt.Errorf("spec not found in AsyncActor")
	}

	config := &injection.ActorConfig{}

	// Extract transport type
	config.Transport, _, _ = unstructured.NestedString(spec, "transport")
	if config.Transport == "" {
		config.Transport = "sqs"
	}

	// Extract queue URL from status
	queueURL, _, _ := unstructured.NestedString(asyncActor.Object, "status", "queueUrl")
	config.QueueURL = queueURL

	// Extract workload configuration
	workload, workloadFound, _ := unstructured.NestedMap(spec, "workload")
	if workloadFound {
		config.Handler, _, _ = unstructured.NestedString(workload, "handler")
		config.HandlerMode, _, _ = unstructured.NestedString(workload, "handlerMode")
		config.PythonExecutable, _, _ = unstructured.NestedString(workload, "pythonExecutable")

		if config.HandlerMode == "" {
			config.HandlerMode = "payload"
		}
		if config.PythonExecutable == "" {
			config.PythonExecutable = "python3"
		}
	}

	// Extract sidecar configuration
	sidecar, sidecarFound, _ := unstructured.NestedMap(spec, "sidecar")
	if sidecarFound {
		config.SidecarImage, _, _ = unstructured.NestedString(sidecar, "image")
		config.SidecarImagePullPolicy, _, _ = unstructured.NestedString(sidecar, "imagePullPolicy")

		// Extract sidecar env vars
		envSlice, envFound, _ := unstructured.NestedSlice(sidecar, "env")
		if envFound {
			for _, item := range envSlice {
				envMap, ok := item.(map[string]interface{})
				if !ok {
					continue
				}
				name, _, _ := unstructured.NestedString(envMap, "name")
				value, _, _ := unstructured.NestedString(envMap, "value")
				if name != "" {
					config.SidecarEnv = append(config.SidecarEnv, corev1.EnvVar{
						Name:  name,
						Value: value,
					})
				}
			}
		}
	}

	// Extract region for SQS
	config.Region, _, _ = unstructured.NestedString(spec, "region")
	if config.Region == "" {
		config.Region = "us-east-1"
	}

	return config, nil
}
