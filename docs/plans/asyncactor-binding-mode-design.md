# AsyncActor Binding Mode: Design Document

**Status:** Draft
**Date:** 2025-11-09
**Related ADR:** docs/adr/001-asyncactor-binding-mode.md

## Overview

This document provides detailed design and implementation guidance for adding binding mode to AsyncActor CRD. Binding mode allows AsyncActor to add async capabilities to existing workloads created by third-party controllers (KAITO, KServe, KubeRay, etc.) by injecting sidecar and runtime containers.

**Key principle:** AsyncActor operates in two mutually exclusive modes:
- **Standalone mode**: Creates and owns workload with `asya-runtime` container (`spec.workload` is set)
- **Binding mode**: Injects `asya-runtime` container into existing workload (`spec.workloadRef` is set)

**Runtime container serves dual purpose:**
- Standalone: Runs user handler directly (processes envelopes)
- Binding: Runs user handler as proxy to inference server (envelope → REST API)

**Architecture in binding mode:**
```
┌─────────────────────────────────────────────────────────────┐
│ Pod (managed by KAITO/KServe/etc.)                          │
│                                                             │
│  ┌──────────────┐  Unix    ┌──────────────┐  HTTP  ┌──────┐ │
│  │ asya-sidecar │  Socket  │ asya-runtime │  REST  │ KAITO│ │
│  │              │◄────────►│   (adapter)  │◄──────►│ vLLM │ │
│  │ (RabbitMQ/   │          │              │        │      │ │
│  │  SQS)        │          │ Proxy to     │        │      │ │
│  └──────────────┘          │ inference    │        │      │ │
│                            │ server       │        │      │ │
│                            └──────────────┘        └──────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Flow:**
1. Sidecar receives envelope from queue
2. Sidecar forwards to `asya-runtime` via Unix socket
3. `asya-runtime` handler converts envelope → HTTP REST request
4. Handler calls inference server (KAITO vLLM, KServe, Triton, etc.)
5. Response flows back: inference → runtime → sidecar → queue

## API Design

### Extended AsyncActorSpec

```go
type AsyncActorSpec struct {
    // Transport name (required in both modes)
    // +kubebuilder:validation:Required
    Transport string `json:"transport"`

    // STANDALONE MODE: Create workload
    // Mutually exclusive with workloadRef
    // +optional
    Workload *WorkloadConfig `json:"workload,omitempty"`

    // BINDING MODE: Reference existing workload
    // Mutually exclusive with workload
    // +optional
    WorkloadRef *WorkloadReference `json:"workloadRef,omitempty"`

    // BINDING MODE: Runtime configuration
    // Required when workloadRef is set
    // Configures asya-runtime container to proxy to inference server
    // +optional
    Runtime *RuntimeConfig `json:"runtime,omitempty"`

    // Common configuration (both modes)
    Sidecar SidecarConfig `json:"sidecar,omitempty"`
    Socket  SocketConfig  `json:"socket,omitempty"`
    Timeout TimeoutConfig `json:"timeout,omitempty"`
    Scaling ScalingConfig `json:"scaling,omitempty"`
}
```

### WorkloadReference

```go
// WorkloadReference references existing K8s resources
type WorkloadReference struct {
    // API version of the target resource
    // Examples: "apps/v1", "kaito.sh/v1alpha1", "serving.kserve.io/v1beta1"
    // +kubebuilder:validation:Required
    APIVersion string `json:"apiVersion"`

    // Kind of the target resource
    // Examples: "Deployment", "StatefulSet", "Workspace", "InferenceService"
    // +kubebuilder:validation:Required
    Kind string `json:"kind"`

    // Name of the target resource
    // +kubebuilder:validation:Required
    Name string `json:"name"`

    // Namespace of the target resource
    // Defaults to AsyncActor's namespace if not specified
    // +optional
    Namespace string `json:"namespace,omitempty"`
}
```

### RuntimeConfig

```go
// RuntimeConfig defines runtime container configuration for binding mode
// The runtime container is always named "asya-runtime" (consistent with standalone mode)
// User configures handler to act as proxy between sidecar and inference server
type RuntimeConfig struct {
    // Target service to forward requests to
    // +kubebuilder:validation:Required
    TargetService ServiceReference `json:"targetService"`

    // Runtime container image
    // Should contain asya_runtime.py + HTTP client libraries for proxying
    // Defaults to "asya-rest-adapter:latest"
    // +optional
    Image string `json:"image,omitempty"`

    // Handler function for proxying requests to inference server
    // Format: "module.function"
    // Example: "adapters.kaito_openai.forward" - proxies to OpenAI-compatible API
    // Example: "adapters.kserve_v2.forward" - proxies to KServe v2 protocol
    // +kubebuilder:validation:Required
    Handler string `json:"handler"`

    // Additional environment variables for runtime container
    // +optional
    Env []corev1.EnvVar `json:"env,omitempty"`

    // Resource requirements for runtime container
    // +optional
    Resources corev1.ResourceRequirements `json:"resources,omitempty"`

    // Python executable path (optional override)
    // Defaults to "python3"
    // +optional
    PythonExecutable string `json:"pythonExecutable,omitempty"`
}

// ServiceReference points to a Kubernetes Service
type ServiceReference struct {
    // Service name
    // +kubebuilder:validation:Required
    Name string `json:"name"`

    // Service port (number or name)
    // +kubebuilder:validation:Required
    Port intstr.IntOrString `json:"port"`

    // Service namespace (defaults to AsyncActor namespace)
    // +optional
    Namespace string `json:"namespace,omitempty"`

    // Protocol (http or https)
    // +kubebuilder:default=http
    // +optional
    Protocol string `json:"protocol,omitempty"`

    // Request path prefix (e.g., "/v1/chat/completions")
    // +optional
    Path string `json:"path,omitempty"`
}
```

### Extended AsyncActorStatus

```go
type AsyncActorStatus struct {
    // Existing fields (unchanged)
    Conditions   []metav1.Condition `json:"conditions,omitempty"`
    Status       string             `json:"status,omitempty"`
    Replicas     *int32             `json:"replicas,omitempty"`
    // ... other existing fields

    // NEW: Mode indicator
    // Values: "Standalone" (workload created), "Binding" (runtime injected)
    // +optional
    Mode string `json:"mode,omitempty"`

    // NEW: Resolved workload reference (binding mode only)
    // Shows the actual Deployment/StatefulSet resolved from workloadRef
    // Example: workloadRef points to KAITO Workspace → resolvedTarget points to Deployment
    // +optional
    ResolvedTarget *WorkloadReference `json:"resolvedTarget,omitempty"`

    // NEW: Runtime injection status (binding mode only)
    // Tracks whether runtime container is currently injected
    // +optional
    RuntimeInjected bool `json:"runtimeInjected,omitempty"`

    // NEW: Conflict tracking (binding mode only)
    // Increments when external controller removes runtime/sidecar
    // +optional
    ConflictCount int `json:"conflictCount,omitempty"`

    // NEW: Last conflict timestamp (binding mode only)
    // +optional
    LastConflictTime *metav1.Time `json:"lastConflictTime,omitempty"`
}
```

### CEL Validation Rules

```go
// Mutual exclusion: workload XOR workloadRef
// +kubebuilder:validation:XValidation:rule="(has(self.workload) && !has(self.workloadRef)) || (!has(self.workload) && has(self.workloadRef))", message="Exactly one of 'workload' or 'workloadRef' must be set. Use 'workload' to create new workload, or 'workloadRef' to bind to existing workload."

// Runtime required in binding mode
// +kubebuilder:validation:XValidation:rule="!has(self.workloadRef) || has(self.runtime)", message="When using 'workloadRef', 'runtime' configuration is required to specify how to proxy requests to the inference server."

// Runtime not allowed in standalone mode (use workload.template instead)
// +kubebuilder:validation:XValidation:rule="!has(self.workload) || !has(self.runtime)", message="'runtime' field is only valid when 'workloadRef' is set. In standalone mode, use 'workload.template' to configure the asya-runtime container."

// Runtime handler required
// +kubebuilder:validation:XValidation:rule="!has(self.runtime) || has(self.runtime.handler)", message="'runtime.handler' is required to specify the proxy function."

// Runtime targetService required
// +kubebuilder:validation:XValidation:rule="!has(self.runtime) || has(self.runtime.targetService)", message="'runtime.targetService' is required to specify the inference server endpoint."
```

## Runtime Container Pattern

### Container Architecture

In binding mode, we inject **two containers** into the existing pod:

1. **`asya-sidecar`**: Message queue consumer (same as standalone mode)
2. **`asya-runtime`**: Proxy container (new in binding mode, runs user handler)

**Key insight:** The `asya-runtime` container name is **consistent across both modes**:
- **Standalone mode**: `asya-runtime` runs user's Python handler directly
- **Binding mode**: `asya-runtime` runs user's Python handler configured as proxy to inference server

This consistency simplifies reconciliation logic and sidecar communication.

### Runtime Handler Interface

Runtime handlers follow a standard interface:

```python
# adapters/base.py
from typing import Dict, Any
import httpx

class InferenceAdapter:
    """Base class for inference server adapters"""

    def __init__(self, target_url: str, **kwargs):
        """
        Args:
            target_url: Full URL to inference server (e.g., "http://phi-3-inference:8080")
            **kwargs: Additional adapter-specific configuration
        """
        self.target_url = target_url
        self.client = httpx.AsyncClient(timeout=300.0)

    async def forward(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Forward envelope payload to inference server.

        Args:
            payload: Envelope payload (arbitrary JSON)

        Returns:
            Inference server response (arbitrary JSON)

        Raises:
            AdapterError: If inference request fails
        """
        raise NotImplementedError


# adapters/kaito_openai.py
class KAITOOpenAIAdapter(InferenceAdapter):
    """Runtime for KAITO models with OpenAI-compatible API"""

    async def forward(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Envelope payload → OpenAI chat completion format
        request = {
            "model": payload.get("model", "default"),
            "messages": payload["messages"],
            "temperature": payload.get("temperature", 0.7),
        }

        # Call KAITO inference endpoint
        response = await self.client.post(
            f"{self.target_url}/v1/chat/completions",
            json=request,
        )
        response.raise_for_status()

        result = response.json()

        # Extract response
        return {
            "response": result["choices"][0]["message"]["content"],
            "model": result["model"],
            "usage": result["usage"],
        }


# Handler entry point (called by asya_runtime.py)
async def forward(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for ASYA_HANDLER=adapters.kaito_openai.forward"""
    import os

    target_url = os.environ["ASYA_TARGET_URL"]
    runtime = KAITOOpenAIAdapter(target_url)
    return await adapter.forward(payload)
```

### Runtime Image Structure

```dockerfile
# asya-rest-runtime Dockerfile
FROM python:3.13-slim

# Install HTTP client libraries
RUN pip install httpx aiohttp

# Copy asya_runtime.py (same as standalone mode)
COPY asya_runtime.py /opt/asya/asya_runtime.py

# Copy runtime modules
COPY adapters/ /opt/asya/adapters/

# Set PYTHONPATH
ENV PYTHONPATH=/opt/asya

# Runtime will be started by command: python3 /opt/asya/asya_runtime.py
# Handler will be set via ASYA_HANDLER env var
```

**Pre-built adapters:**
- `adapters.kaito_openai` - KAITO models with OpenAI API
- `adapters.kserve_v2` - KServe v2 inference protocol
- `adapters.triton_grpc` - NVIDIA Triton gRPC
- `adapters.ray_serve` - Ray Serve HTTP
- `adapters.generic_rest` - Generic REST JSON API

Users can also provide custom runtime images.

## Reconciliation Logic

### Mode Detection

```go
func (r *AsyncActorReconciler) detectMode(asya *asyav1alpha1.AsyncActor) string {
    if asya.Spec.WorkloadRef != nil {
        return "Binding"
    }
    return "Standalone"
}

func (r *AsyncActorReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    logger := log.FromContext(ctx)

    asya := &asyav1alpha1.AsyncActor{}
    if err := r.Get(ctx, req.NamespacedName, asya); err != nil {
        return ctrl.Result{}, client.IgnoreNotFound(err)
    }

    // Handle deletion (both modes)
    if !asya.DeletionTimestamp.IsZero() {
        return r.reconcileDelete(ctx, asya)
    }

    // Add finalizer (both modes)
    if !controllerutil.ContainsFinalizer(asya, actorFinalizer) {
        controllerutil.AddFinalizer(asya, actorFinalizer)
        return ctrl.Result{}, r.Update(ctx, asya)
    }

    // Mode detection
    mode := r.detectMode(asya)
    asya.Status.Mode = mode

    logger.Info("Reconciling AsyncActor", "mode", mode, "name", asya.Name)

    // Branch based on mode
    var deployment *appsv1.Deployment
    var err error

    if mode == "Binding" {
        deployment, err = r.reconcileBindingMode(ctx, asya)
    } else {
        deployment, err = r.reconcileStandaloneMode(ctx, asya)
    }

    if err != nil {
        return ctrl.Result{}, err
    }

    // Common reconciliation (both modes)
    if err := r.reconcileKEDA(ctx, asya, deployment); err != nil {
        return ctrl.Result{}, err
    }

    if err := r.reconcileTransport(ctx, asya); err != nil {
        return ctrl.Result{}, err
    }

    return r.updateStatus(ctx, asya, deployment)
}
```

### Standalone Mode Reconciliation

```go
func (r *AsyncActorReconciler) reconcileStandaloneMode(ctx context.Context, asya *asyav1alpha1.AsyncActor) (*appsv1.Deployment, error) {
    // EXISTING LOGIC - no changes
    // 1. Create/update ConfigMap (asya_runtime.py)
    // 2. Inject sidecar + runtime containers into pod template
    // 3. Create/update Deployment/StatefulSet (controller-owned)
    // 4. Return created workload

    return r.reconcileWorkload(ctx, asya)  // Existing function
}
```

### Binding Mode Reconciliation

```go
func (r *AsyncActorReconciler) reconcileBindingMode(ctx context.Context, asya *asyav1alpha1.AsyncActor) (*appsv1.Deployment, error) {
    logger := log.FromContext(ctx)

    // Step 1: Resolve workloadRef to Deployment/StatefulSet
    deployment, err := r.resolveWorkloadRef(ctx, asya)
    if err != nil {
        meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
            Type:    "TargetResolved",
            Status:  metav1.ConditionFalse,
            Reason:  "ResolutionFailed",
            Message: fmt.Sprintf("Failed to resolve workloadRef: %v", err),
        })
        return nil, err
    }

    // Update status with resolved target
    asya.Status.ResolvedTarget = &asyav1alpha1.WorkloadReference{
        APIVersion: deployment.APIVersion,
        Kind:       deployment.Kind,
        Name:       deployment.Name,
        Namespace:  deployment.Namespace,
    }

    meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
        Type:    "TargetResolved",
        Status:  metav1.ConditionTrue,
        Reason:  "Resolved",
        Message: fmt.Sprintf("Resolved %s/%s to Deployment %s", asya.Spec.WorkloadRef.Kind, asya.Spec.WorkloadRef.Name, deployment.Name),
    })

    // Step 2: Check if runtime and sidecar are already injected
    runtimePresent := r.hasRuntimeInjected(deployment)
    wasInjected := asya.Status.RuntimeInjected

    // Step 3: Detect conflicts (external controller removed containers)
    if wasInjected && !runtimePresent {
        logger.Info("Conflict detected: runtime/sidecar removed by external controller", "deployment", deployment.Name)

        asya.Status.ConflictCount++
        now := metav1.Now()
        asya.Status.LastConflictTime = &now

        // Check conflict threshold
        if asya.Status.ConflictCount > 5 {
            meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
                Type:    "RuntimeInjected",
                Status:  metav1.ConditionFalse,
                Reason:  "ConflictLoopDetected",
                Message: fmt.Sprintf("External controller repeatedly removing runtime/sidecar (conflicts: %d). Manual intervention required.", asya.Status.ConflictCount),
            })
            logger.Error(nil, "Conflict loop detected, giving up", "conflictCount", asya.Status.ConflictCount)
            return deployment, nil  // Stop reconciling
        }

        // Re-inject with backoff
        backoff := time.Duration(asya.Status.ConflictCount*5) * time.Second
        logger.Info("Re-injecting runtime after conflict", "backoff", backoff, "conflictCount", asya.Status.ConflictCount)

        if err := r.injectRuntimeToExistingWorkload(ctx, asya, deployment); err != nil {
            return nil, err
        }

        asya.Status.RuntimeInjected = true
        return deployment, nil
    }

    // Step 4: First injection or normal reconciliation
    if !runtimePresent {
        logger.Info("Injecting runtime and sidecar into existing workload", "deployment", deployment.Name)

        if err := r.injectRuntimeToExistingWorkload(ctx, asya, deployment); err != nil {
            meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
                Type:    "RuntimeInjected",
                Status:  metav1.ConditionFalse,
                Reason:  "InjectionFailed",
                Message: fmt.Sprintf("Failed to inject runtime and sidecar: %v", err),
            })
            return nil, err
        }

        asya.Status.RuntimeInjected = true
        meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
            Type:    "RuntimeInjected",
            Status:  metav1.ConditionTrue,
            Reason:  "Injected",
            Message: "Runtime and sidecar successfully injected",
        })
    }

    // Step 5: Add non-controller owner reference for garbage collection tracking
    if err := r.addOwnerReference(ctx, asya, deployment); err != nil {
        logger.Error(err, "Failed to add owner reference", "deployment", deployment.Name)
        // Non-fatal - continue reconciliation
    }

    return deployment, nil
}
```

### Workload Resolution

```go
func (r *AsyncActorReconciler) resolveWorkloadRef(ctx context.Context, asya *asyav1alpha1.AsyncActor) (*appsv1.Deployment, error) {
    ref := asya.Spec.WorkloadRef

    // Determine namespace
    namespace := ref.Namespace
    if namespace == "" {
        namespace = asya.Namespace
    }

    // Direct Deployment/StatefulSet reference
    if ref.Kind == "Deployment" || ref.Kind == "StatefulSet" {
        return r.getWorkloadDirectly(ctx, ref.Kind, namespace, ref.Name)
    }

    // CRD reference - resolve to Deployment
    return r.resolveWorkloadFromCRD(ctx, ref, namespace)
}

func (r *AsyncActorReconciler) getWorkloadDirectly(ctx context.Context, kind, namespace, name string) (*appsv1.Deployment, error) {
    if kind == "Deployment" {
        deployment := &appsv1.Deployment{}
        err := r.Get(ctx, client.ObjectKey{Namespace: namespace, Name: name}, deployment)
        return deployment, err
    }

    // StatefulSet - convert to Deployment-like structure for common handling
    return nil, fmt.Errorf("StatefulSet support in binding mode not yet implemented")
}

func (r *AsyncActorReconciler) resolveWorkloadFromCRD(ctx context.Context, ref *asyav1alpha1.WorkloadReference, namespace string) (*appsv1.Deployment, error) {
    // Use dynamic client to fetch CRD
    gvr, err := r.parseGVR(ref)
    if err != nil {
        return nil, err
    }

    dynamicClient := r.DynamicClient  // Injected in reconciler
    obj, err := dynamicClient.Resource(gvr).Namespace(namespace).Get(ctx, ref.Name, metav1.GetOptions{})
    if err != nil {
        return nil, fmt.Errorf("failed to fetch %s/%s: %w", ref.Kind, ref.Name, err)
    }

    // Extract deployment name from CRD
    deploymentName, err := r.extractDeploymentName(ref.Kind, obj)
    if err != nil {
        return nil, err
    }

    // Fetch actual Deployment
    deployment := &appsv1.Deployment{}
    err = r.Get(ctx, client.ObjectKey{Namespace: namespace, Name: deploymentName}, deployment)
    if err != nil {
        return nil, fmt.Errorf("resolved deployment %s not found: %w", deploymentName, err)
    }

    return deployment, nil
}

func (r *AsyncActorReconciler) extractDeploymentName(kind string, obj *unstructured.Unstructured) (string, error) {
    switch kind {
    case "Workspace":  // KAITO
        // KAITO stores deployment name in status.resources[0].name
        resources, found, err := unstructured.NestedSlice(obj.Object, "status", "resources")
        if err != nil || !found || len(resources) == 0 {
            return "", fmt.Errorf("KAITO Workspace status.resources not ready")
        }

        resource := resources[0].(map[string]interface{})
        name, found, err := unstructured.NestedString(resource, "name")
        if err != nil || !found {
            return "", fmt.Errorf("KAITO resource name not found")
        }
        return name, nil

    case "InferenceService":  // KServe
        // KServe stores predictor deployment in status.components.predictor.latestCreatedRevision
        revision, found, err := unstructured.NestedString(obj.Object, "status", "components", "predictor", "latestCreatedRevision")
        if err != nil || !found {
            return "", fmt.Errorf("KServe InferenceService status not ready")
        }
        return revision, nil

    case "RayService":  // KubeRay
        // Ray deployment name format: <rayservice-name>-raycluster-<hash>-head
        serviceName := obj.GetName()
        return fmt.Sprintf("%s-raycluster-head", serviceName), nil

    default:
        return "", fmt.Errorf("unsupported CRD kind: %s", kind)
    }
}
```

### Runtime Injection

```go
func (r *AsyncActorReconciler) injectRuntime containersToExistingWorkload(ctx context.Context, asya *asyav1alpha1.AsyncActor, deployment *appsv1.Deployment) error {
    logger := log.FromContext(ctx)

    // Create patch base
    original := deployment.DeepCopy()

    // Get runtime config
    runtimeConfig := asya.Spec.Runtime
    if runtimeConfig == nil {
        return fmt.Errorf("runtime config is nil (should be validated by CEL)")
    }

    template := &deployment.Spec.Template

    // Check if runtime containers already exist (idempotency)
    if r.hasRuntime containersInjected(deployment) {
        logger.Info("Runtime containers already present, skipping injection")
        return nil
    }

    // Build target URL from service reference
    targetURL := r.buildTargetURL(asya, runtimeConfig.TargetService)

    // Socket configuration
    socketsDir := "/tmp/sockets"
    if asya.Spec.Socket.Dir != "" {
        socketsDir = asya.Spec.Socket.Dir
    }

    // Build runtime container (asya-runtime)
    runtimeContainer := r.buildRuntimeContainer(asya, runtimeConfig, targetURL, socketsDir)

    // Build sidecar container
    sidecarContainer := r.buildSidecarContainer(asya, socketsDir)

    // Add containers to pod template
    template.Spec.Containers = append(template.Spec.Containers, runtimeContainer, sidecarContainer)

    // Add volumes
    template.Spec.Volumes = append(template.Spec.Volumes,
        corev1.Volume{
            Name: socketVolume,
            VolumeSource: corev1.VolumeSource{
                EmptyDir: &corev1.EmptyDirVolumeSource{},
            },
        },
        corev1.Volume{
            Name: tmpVolume,
            VolumeSource: corev1.VolumeSource{
                EmptyDir: &corev1.EmptyDirVolumeSource{},
            },
        },
        corev1.Volume{
            Name: runtimeVolume,
            VolumeSource: corev1.VolumeSource{
                ConfigMap: &corev1.ConfigMapVolumeSource{
                    LocalObjectReference: corev1.LocalObjectReference{
                        Name: runtimeConfigMap,
                    },
                },
            },
        },
    )

    // Add annotations to track Asya🎭 management
    if deployment.Annotations == nil {
        deployment.Annotations = make(map[string]string)
    }
    deployment.Annotations["asya.sh/managed-by"] = asya.Name
    deployment.Annotations["asya.sh/injected-at"] = time.Now().Format(time.RFC3339)
    deployment.Annotations["asya.sh/mode"] = "binding"

    // Apply patch
    patch := client.MergeFrom(original)
    if err := r.Patch(ctx, deployment, patch); err != nil {
        return fmt.Errorf("failed to patch deployment: %w", err)
    }

    logger.Info("Successfully injected runtime and sidecar", "deployment", deployment.Name)
    return nil
}

func (r *AsyncActorReconciler) buildRuntimeContainer(asya *asyav1alpha1.AsyncActor, config *asyav1alpha1.RuntimeConfig, targetURL, socketsDir string) corev1.Container {
    // Default image
    image := "asya-rest-adapter:latest"
    if config.Image != "" {
        image = config.Image
    }

    // Python executable
    pythonExec := "python3"
    if config.PythonExecutable != "" {
        pythonExec = config.PythonExecutable
    }

    // Build environment variables
    env := []corev1.EnvVar{
        {Name: "ASYA_HANDLER", Value: config.Handler},
        {Name: "ASYA_TARGET_URL", Value: targetURL},
        {Name: "ASYA_SOCKET_DIR", Value: socketsDir},
    }

    // Add custom env vars
    env = append(env, config.Env...)

    // Disable validation for runtime containers (they don't follow standard envelope routing)
    env = append(env, corev1.EnvVar{
        Name:  "ASYA_ENABLE_VALIDATION",
        Value: "false",
    })

    return corev1.Container{
        Name:            runtimeContainerName,  // Always "asya-runtime"
        Image:           image,
        ImagePullPolicy: corev1.PullIfNotPresent,
        Command:         []string{pythonExec, runtimeMountPath},
        Env:             env,
        Resources:       config.Resources,
        VolumeMounts: []corev1.VolumeMount{
            {
                Name:      socketVolume,
                MountPath: socketsDir,
            },
            {
                Name:      tmpVolume,
                MountPath: "/tmp",
            },
            {
                Name:      runtimeVolume,
                MountPath: runtimeMountPath,
                SubPath:   "asya_runtime.py",
                ReadOnly:  true,
            },
        },
    }
}

func (r *AsyncActorReconciler) buildTargetURL(asya *asyav1alpha1.AsyncActor, svc asyav1alpha1.ServiceReference) string {
    namespace := svc.Namespace
    if namespace == "" {
        namespace = asya.Namespace
    }

    protocol := svc.Protocol
    if protocol == "" {
        protocol = "http"
    }

    // Kubernetes Service DNS: <service>.<namespace>.svc.cluster.local:<port>
    host := fmt.Sprintf("%s.%s.svc.cluster.local", svc.Name, namespace)

    port := svc.Port.String()

    path := svc.Path
    if path == "" {
        path = ""
    }

    return fmt.Sprintf("%s://%s:%s%s", protocol, host, port, path)
}

func (r *AsyncActorReconciler) hasRuntime containersInjected(deployment *appsv1.Deployment) bool {
    hasSidecar := false
    hasRuntime := false

    for _, c := range deployment.Spec.Template.Spec.Containers {
        if c.Name == sidecarName {
            hasSidecar = true
        }
        if c.Name == runtimeContainerName {
            hasRuntime = true
        }
    }

    return hasSidecar && hasAdapter
}
```

## Watch Configuration

```go
func (r *AsyncActorReconciler) SetupWithManager(mgr ctrl.Manager) error {
    // Create dynamic client for CRD resolution
    r.DynamicClient = dynamic.NewForConfigOrDie(mgr.GetConfig())

    return ctrl.NewControllerManagedBy(mgr).
        For(&asyav1alpha1.AsyncActor{}).

        // Watch owned resources (standalone mode)
        Owns(&appsv1.Deployment{}).
        Owns(&appsv1.StatefulSet{}).
        Owns(&kedav1alpha1.ScaledObject{}).
        Owns(&corev1.ConfigMap{}).

        // Watch ALL Deployments for binding mode
        // CRITICAL: Use predicate to filter only Asya🎭-managed Deployments
        Watches(
            &appsv1.Deployment{},
            handler.EnqueueRequestsFromMapFunc(r.findAsyncActorsForDeployment),
            builder.WithPredicates(predicate.NewPredicateFuncs(func(obj client.Object) bool {
                // Only watch Deployments with Asya🎭 annotation
                annotations := obj.GetAnnotations()
                if annotations == nil {
                    return false
                }
                _, managed := annotations["asya.sh/managed-by"]
                return managed
            })),
        ).

        // Set max concurrent reconciles
        WithOptions(controller.Options{
            MaxConcurrentReconciles: r.MaxConcurrentReconciles,
        }).

        Complete(r)
}

func (r *AsyncActorReconciler) findAsyncActorsForDeployment(ctx context.Context, obj client.Object) []reconcile.Request {
    deployment := obj.(*appsv1.Deployment)

    // Check annotation for AsyncActor name
    annotations := deployment.GetAnnotations()
    if annotations == nil {
        return nil
    }

    asyaName, ok := annotations["asya.sh/managed-by"]
    if !ok {
        return nil
    }

    // Enqueue AsyncActor
    return []reconcile.Request{
        {
            NamespacedName: types.NamespacedName{
                Name:      asyaName,
                Namespace: deployment.Namespace,
            },
        },
    }
}
```

## Corner Cases and Mitigations

### Corner Case 1: Conflict Loop with Third-Party Controller

**Scenario:**
1. AsyncActor injects runtime + sidecar into KAITO-managed Deployment
2. KAITO updates Deployment (model version change)
3. KAITO's reconciliation overwrites pod template → runtime containers removed
4. AsyncActor detects change, re-injects runtime and sidecar
5. Repeat steps 2-4 indefinitely

**Detection:**
```go
if wasInjected && !runtimePresent {
    asya.Status.ConflictCount++
}
```

**Mitigation:**
```go
if asya.Status.ConflictCount > 5 {
    // Stop fighting, report error in status
    meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
        Type:    "RuntimeInjected",
        Status:  metav1.ConditionFalse,
        Reason:  "ConflictLoopDetected",
        Message: "External controller repeatedly removing runtime and sidecar. Manual intervention required.",
    })
    return ctrl.Result{}, nil  // Stop reconciling
}

// Re-inject with exponential backoff
backoff := time.Duration(asya.Status.ConflictCount * 5) * time.Second
return ctrl.Result{RequeueAfter: backoff}, nil
```

**User resolution:**
1. Check third-party controller configuration (KAITO Workspace, etc.)
2. Ensure controller preserves existing containers
3. Delete AsyncActor and recreate, or
4. Manually patch Deployment

---

### Corner Case 2: Target Service Not Ready

**Scenario:**
1. AsyncActor references KAITO Workspace
2. KAITO creates Deployment and Service
3. Service exists but endpoints not ready (pods starting)
4. Runtime container tries to connect → connection refused

**Detection:**
Runtime container will log connection errors but continue running (retry on each request).

**Mitigation:**
```go
// Runtime health check
func (a *InferenceAdapter) healthCheck(ctx context.Context) error {
    resp, err := a.client.Get(ctx, a.target_url + "/health")
    if err != nil {
        return err
    }
    if resp.StatusCode != 200:
        return fmt.Errorf("target unhealthy: %d", resp.StatusCode)
    }
    return nil
}
```

Add readiness probe to runtime container:
```go
container.ReadinessProbe = &corev1.Probe{
    ProbeHandler: corev1.ProbeHandler{
        HTTPGet: &corev1.HTTPGetAction{
            Path: "/health",  // Runtime exposes health endpoint
            Port: intstr.FromInt(8081),
        },
    },
    InitialDelaySeconds: 5,
    PeriodSeconds:       10,
}
```

**User impact:**
Pod stays in "Not Ready" state until target service is healthy. KEDA won't scale up until pods are ready.

---

### Corner Case 3: Wrong Handler Configuration

**Scenario:**
User specifies handler that doesn't exist:
```yaml
runtime:
  handler: "adapters.wrong_module.forward"
```

**Detection:**
Runtime container crashes with ImportError:
```
ModuleNotFoundError: No module named 'adapters.wrong_module'
```

**Mitigation:**
Container enters CrashLoopBackOff. AsyncActor status shows:
```go
asya.Status.Status = "RuntimeError"
asya.Status.FailingPods = 1

meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
    Type:    "WorkloadReady",
    Status:  metav1.ConditionFalse,
    Reason:  "PodFailing",
    Message: "Runtime container failing (check logs): CrashLoopBackOff",
})
```

**User resolution:**
1. Check logs: `kubectl logs <pod> -c asya-runtime`
2. Verify handler exists in runtime image
3. Update AsyncActor with correct handler

---

### Corner Case 4: Service Name Typo

**Scenario:**
```yaml
runtime:
  targetService:
    name: "phi-3-inferenc"  # Typo: missing 'e'
    port: 8080
```

**Detection:**
Runtime container starts successfully but fails on first request:
```
failed to connect to http://phi-3-inferenc.default.svc.cluster.local:8080: no such host
```

**Mitigation:**
Add startup probe to runtime that validates service resolution:
```python
# In runtime startup
import socket

def validate_service(host: str):
    try:
        socket.gethostbyname(host)
    except socket.gaierror:
        raise RuntimeError(f"Cannot resolve service: {host}")

# Called during runtime initialization
validate_service("phi-3-inferenc.default.svc.cluster.local")
```

Container fails startup probe → CrashLoopBackOff → visible in status.

**User resolution:**
1. Check service exists: `kubectl get svc phi-3-inference`
2. Fix AsyncActor service name

---

### Corner Case 5: Port Mismatch

**Scenario:**
```yaml
runtime:
  targetService:
    name: "triton-server"
    port: 8000  # Wrong: Triton uses 8001 for HTTP
```

**Detection:**
Connection established but wrong protocol:
```
HTTP 404 Not Found (Triton expects gRPC on 8000)
```

**Mitigation:**
Add protocol validation in adapter:
```python
class TritonAdapter(InferenceAdapter):
    def __init__(self, target_url: str):
        super().__init__(target_url)

        # Validate port matches protocol
        if "triton" in target_url and ":8000" in target_url:
            raise ValueError("Triton HTTP requires port 8001, gRPC uses 8000")
```

**User resolution:**
Update port in AsyncActor spec.

---

### Corner Case 6: Multiple AsyncActors Targeting Same Workload

**Scenario:**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: actor-1
spec:
  workloadRef:
    kind: Deployment
    name: shared-deployment
  runtime:
    targetService:
      name: svc-1
      port: 8080

---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: actor-2
spec:
  workloadRef:
    kind: Deployment
    name: shared-deployment  # Same!
  runtime:
    targetService:
      name: svc-2  # Different service
      port: 8081
```

**Problem:**
Second AsyncActor tries to inject runtime but first AsyncActor already did.

**Detection:**
```go
if existingOwner := deployment.Annotations["asya.sh/managed-by"]; existingOwner != "" && existingOwner != asya.Name {
    return fmt.Errorf("deployment already managed by AsyncActor %s", existingOwner)
}
```

**Mitigation:**
```go
meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
    Type:    "RuntimeInjected",
    Status:  metav1.ConditionFalse,
    Reason:  "AlreadyManaged",
    Message: fmt.Sprintf("Deployment already managed by AsyncActor %s. Multiple AsyncActors cannot manage same deployment.", existingOwner),
})
```

**User resolution:**
Delete conflicting AsyncActor. Only one AsyncActor per Deployment.

---

### Corner Case 7: Runtime Container Name Conflict

**Scenario:**
Target Deployment already has container named `asya-runtime`:
```yaml
spec:
  template:
    spec:
      containers:
      - name: asya-runtime  # Conflict!
        image: custom-app:latest
```

**Detection:**
```go
// Check for existing asya-runtime container before injection
for _, c := range template.Spec.Containers {
    if c.Name == runtimeContainerName && !r.isAsyaContainer(c) {
        return fmt.Errorf("container named %q already exists (not injected by Asya🎭)", runtimeContainerName)
    }
}

func (r *AsyncActorReconciler) isAsyaContainer(c corev1.Container) bool {
    // Check if container was injected by Asya🎭 (has asya_runtime.py mount)
    for _, vm := range c.VolumeMounts {
        if vm.MountPath == runtimeMountPath {
            return true
        }
    }
    return false
}
```

**Mitigation:**
```go
meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
    Type:    "RuntimeInjected",
    Status:  metav1.ConditionFalse,
    Reason:  "ContainerNameConflict",
    Message: "Deployment already has container named 'asya-runtime'. Rename existing container to avoid conflict.",
})
```

**User resolution:**
Rename existing container in Deployment to something else.

---

### Corner Case 8: CRD Not Ready

**Scenario:**
1. User creates AsyncActor with `workloadRef` pointing to KAITO Workspace
2. KAITO Workspace exists but hasn't created Deployment yet (status.resources empty)
3. AsyncActor reconciliation fails: "Deployment not found"

**Detection:**
```go
deploymentName, err := r.extractDeploymentName(ref.Kind, obj)
if err != nil {
    if errors.Is(err, ErrCRDNotReady) {
        // CRD exists but workload not created yet
    }
}
```

**Mitigation:**
```go
if errors.Is(err, ErrCRDNotReady) {
    meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
        Type:    "TargetResolved",
        Status:  metav1.ConditionFalse,
        Reason:  "TargetNotReady",
        Message: fmt.Sprintf("%s/%s exists but underlying workload not ready. Waiting...", ref.Kind, ref.Name),
    })

    // Requeue with backoff
    return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
}
```

**User resolution:**
Wait for KAITO to create Deployment. Check: `kubectl describe workspace <name>`

---

### Corner Case 9: Runtime Image Pull Error

**Scenario:**
```yaml
runtime:
  image: "private-registry.com/asya-adapter:v2"  # Requires pull secret
```

**Detection:**
Pod stuck in ImagePullBackOff:
```
Failed to pull image "private-registry.com/asya-adapter:v2": authentication required
```

**Mitigation:**
AsyncActor status shows:
```go
asya.Status.Status = "ImagePullError"
asya.Status.FailingPods = 1

meta.SetStatusCondition(&asya.Status.Conditions, metav1.Condition{
    Type:    "WorkloadReady",
    Status:  metav1.ConditionFalse,
    Reason:  "ImagePullError",
    Message: "Runtime container image pull failed (check imagePullSecrets)",
})
```

**User resolution:**
1. Add imagePullSecrets to target Deployment
2. Or use public runtime image
3. Or build custom image with embedded handler modules

---

### Corner Case 10: Runtime Handler Returns Wrong Format

**Scenario:**
Runtime handler returns malformed response:
```python
async def forward(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Wrong: Returns string instead of dict
    return "result"
```

**Detection:**
Runtime validation fails:
```python
# In asya_runtime.py
result = await handler(payload)
if not isinstance(result, dict):
    raise ValueError(f"Handler must return dict, got {type(result)}")
```

**Mitigation:**
Envelope marked as processing_error, sent to error-end queue.

**User resolution:**
Fix runtime handler to return dict.

---

## Testing Strategy

### Unit Tests

**Test: Runtime injection**
```go
func TestInjectRuntime containers(t *testing.T) {
    deployment := &appsv1.Deployment{
        Spec: appsv1.DeploymentSpec{
            Template: corev1.PodTemplateSpec{
                Spec: corev1.PodSpec{
                    Containers: []corev1.Container{
                        {Name: "inference", Image: "kaito-llm:latest"},
                    },
                },
            },
        },
    }

    asya := &asyav1alpha1.AsyncActor{
        Spec: asyav1alpha1.AsyncActorSpec{
            WorkloadRef: &asyav1alpha1.WorkloadReference{
                Kind: "Deployment",
                Name: "test",
            },
            Runtime: &asyav1alpha1.RuntimeConfig{
                TargetService: asyav1alpha1.ServiceReference{
                    Name: "kaito-svc",
                    Port: intstr.FromInt(8080),
                },
                Handler: "adapters.kaito_openai.forward",
            },
        },
    }

    r := &AsyncActorReconciler{}
    err := r.injectRuntime containersToExistingWorkload(context.TODO(), asya, deployment)

    assert.NoError(t, err)
    assert.Len(t, deployment.Spec.Template.Spec.Containers, 3)  // inference + runtime + sidecar
    assert.Equal(t, "asya-runtime", deployment.Spec.Template.Spec.Containers[1].Name)
    assert.Equal(t, "asya-sidecar", deployment.Spec.Template.Spec.Containers[2].Name)
}
```

**Test: Target URL construction**
```go
func TestBuildTargetURL(t *testing.T) {
    tests := []struct {
        name     string
        svc      asyav1alpha1.ServiceReference
        expected string
    }{
        {
            name: "http with port number",
            svc: asyav1alpha1.ServiceReference{
                Name:     "kaito-svc",
                Port:     intstr.FromInt(8080),
                Protocol: "http",
            },
            expected: "http://kaito-svc.default.svc.cluster.local:8080",
        },
        {
            name: "https with path",
            svc: asyav1alpha1.ServiceReference{
                Name:     "triton",
                Port:     intstr.FromInt(8001),
                Protocol: "https",
                Path:     "/v2/models/bert/infer",
            },
            expected: "https://triton.default.svc.cluster.local:8001/v2/models/bert/infer",
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            asya := &asyav1alpha1.AsyncActor{
                ObjectMeta: metav1.ObjectMeta{Namespace: "default"},
            }
            r := &AsyncActorReconciler{}
            url := r.buildTargetURL(asya, tt.svc)
            assert.Equal(t, tt.expected, url)
        })
    }
}
```

### Integration Tests

**Test: Runtime proxying to mock service**
```bash
# Start mock inference server
docker run -d --name mock-inference -p 8080:8080 \
  mock-server --endpoint /v1/chat/completions

# Create Deployment
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-deployment
spec:
  template:
    spec:
      containers:
      - name: mock-inference
        image: mock-server:latest
---
apiVersion: v1
kind: Service
metadata:
  name: mock-inference-svc
spec:
  selector:
    app: test-deployment
  ports:
  - port: 8080
EOF

# Create AsyncActor with adapter
kubectl apply -f - <<EOF
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-adapter
spec:
  transport: rabbitmq
  workloadRef:
    kind: Deployment
    name: test-deployment
  runtime:
    targetService:
      name: mock-inference-svc
      port: 8080
    handler: "adapters.generic_rest.forward"
EOF

# Verify runtime containers injected
kubectl get deployment test-deployment -o yaml | grep asya-runtime
kubectl get deployment test-deployment -o yaml | grep asya-sidecar

# Send test envelope
python3 -c "
import pika
connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()
channel.basic_publish(
    exchange='',
    routing_key='asya-test-adapter',
    body=json.dumps({
        'id': 'test-1',
        'route': {'actors': ['test-adapter'], 'current': 0},
        'payload': {'messages': [{'role': 'user', 'content': 'hello'}]}
    })
)
"

# Verify response in happy-end queue
kubectl logs -l app=happy-end | grep test-1
```

### E2E Tests

**Test: Real KAITO integration**
```bash
# Install KAITO operator
kubectl apply -f https://raw.githubusercontent.com/Azure/kaito/main/manifests/install.yaml

# Create KAITO Workspace
kubectl apply -f - <<EOF
apiVersion: kaito.sh/v1alpha1
kind: Workspace
metadata:
  name: phi-3-mini
spec:
  resource:
    instanceType: Standard_NC6s_v3
  inference:
    preset:
      name: phi-3-mini-4k-instruct
EOF

# Wait for KAITO to create Deployment
kubectl wait --for=condition=WorkspaceReady workspace/phi-3-mini --timeout=10m

# Create AsyncActor binding
kubectl apply -f - <<EOF
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: phi-3-async
spec:
  transport: rabbitmq
  workloadRef:
    apiVersion: kaito.sh/v1alpha1
    kind: Workspace
    name: phi-3-mini
  runtime:
    targetService:
      name: phi-3-mini-inference
      port: 80
    handler: "adapters.kaito_openai.forward"
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
EOF

# Verify injection
kubectl describe asyncactor phi-3-async | grep "RuntimeInjected.*True"

# Test scale-to-zero
kubectl get asyncactor phi-3-async -w
# Should show: 1 → 0 replicas after cooldown

# Send message
# Should scale up: 0 → 1 replicas

# Verify response
```

---

## Migration Guide

### For Existing AsyncActor Users

No changes required. Existing AsyncActors continue working unchanged.

### For New Bindings

**Example 1: KAITO Workspace**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: kaito-phi3
spec:
  transport: rabbitmq

  workloadRef:
    apiVersion: kaito.sh/v1alpha1
    kind: Workspace
    name: phi-3-embeddings

  runtime:
    targetService:
      name: phi-3-inference  # Created by KAITO
      port: 80
    handler: "adapters.kaito_openai.forward"

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 100
```

**Example 2: KServe InferenceService**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: kserve-bert
spec:
  transport: sqs

  workloadRef:
    apiVersion: serving.kserve.io/v1beta1
    kind: InferenceService
    name: bert-classifier

  runtime:
    targetService:
      name: bert-classifier-predictor
      port: 8080
    handler: "adapters.kserve_v2.forward"

  scaling:
    enabled: true
```

**Example 3: NVIDIA Triton**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: triton-gpu
spec:
  transport: rabbitmq

  workloadRef:
    kind: Deployment
    name: triton-server

  runtime:
    targetService:
      name: triton-http
      port: 8001
    handler: "adapters.triton_http.forward"
    image: asya-triton-adapter:latest
    env:
    - name: TRITON_MODEL_NAME
      value: "resnet50"

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 20
```

**Example 4: Custom adapter**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: custom-model
spec:
  transport: rabbitmq

  workloadRef:
    kind: Deployment
    name: my-model-server

  runtime:
    targetService:
      name: my-model-svc
      port: 5000
      protocol: https
      path: /predict
    handler: "custom_adapters.my_model.forward"
    image: my-custom-adapter:v1
    resources:
      limits:
        cpu: 500m
        memory: 512Mi
```

---

## Implementation Checklist

- [ ] Extend AsyncActorSpec with WorkloadRef and RuntimeConfig
- [ ] Add CEL validation rules
- [ ] Update AsyncActorStatus with binding-specific fields
- [ ] Implement mode detection logic
- [ ] Implement workload resolution (direct + CRD)
- [ ] Implement runtime injection with patching
- [ ] Implement conflict detection and backoff
- [ ] Add predicate filtering to watch configuration
- [ ] Update status calculation for binding mode
- [ ] Add kubectl output columns for mode
- [ ] Create asya-rest-adapter base image
- [ ] Implement pre-built handler modules (KAITO, KServe, Triton, Ray)
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Write E2E tests with real KAITO
- [ ] Update API documentation
- [ ] Write runtime development guide
- [ ] Create integration examples
- [ ] Add troubleshooting guide

---

## Open Questions

1. **Runtime health checks:**
   - Should runtime container expose /health endpoint?
   - How to validate target service connectivity during startup?

2. **Runtime authentication:**
   - How to pass credentials to runtime handler for authenticated inference servers?
   - Support for API keys, mTLS certificates?

3. **Runtime retry logic:**
   - Should runtime handler implement retry on target service failures?
   - Or let sidecar handle retries (re-queue envelope)?

4. **Runtime metrics:**
   - Should runtime container expose Prometheus metrics?
   - What metrics: request latency, error rate, target service health?

5. **Multi-target support:**
   - Support for load balancing across multiple inference servers?
   - Use case: A/B testing, canary deployments

---

## Next Steps

1. Review and approve design document
2. Create GitHub issue for implementation tracking
3. Implement Phase 1: API extensions
4. Implement Phase 2: Runtime injection logic
5. Implement Phase 3: Base runtime image + pre-built handler modules
6. Implement Phase 4: Tests
7. Implement Phase 5: Documentation
8. Release as alpha feature in v1alpha2
