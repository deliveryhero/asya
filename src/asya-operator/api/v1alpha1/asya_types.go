package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// AsyncActorSpec defines the desired state of AsyncActor
type AsyncActorSpec struct {
	// Transport name referencing operator-configured transport
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	Transport string `json:"transport"`

	// Sidecar container configuration
	// +optional
	Sidecar SidecarConfig `json:"sidecar,omitempty"`

	// Timeout configuration
	// +optional
	Timeout TimeoutConfig `json:"timeout,omitempty"`

	// KEDA autoscaling configuration
	// +optional
	Scaling ScalingConfig `json:"scaling,omitempty"`

	// Workload template for the actor runtime
	// +kubebuilder:validation:Required
	Workload WorkloadConfig `json:"workload"`
}

// SidecarConfig defines sidecar container configuration
type SidecarConfig struct {
	// Sidecar image (defaults to asya-sidecar:latest)
	// +optional
	Image string `json:"image,omitempty"`

	// Image pull policy
	// +kubebuilder:validation:Enum=Always;IfNotPresent;Never
	// +kubebuilder:default=IfNotPresent
	// +optional
	ImagePullPolicy corev1.PullPolicy `json:"imagePullPolicy,omitempty"`

	// Resource requirements
	// +optional
	Resources corev1.ResourceRequirements `json:"resources,omitempty"`

	// Additional environment variables
	// +optional
	Env []corev1.EnvVar `json:"env,omitempty"`
}

// TimeoutConfig defines timeout configuration
type TimeoutConfig struct {
	// Processing timeout in seconds
	// +kubebuilder:default=300
	// +optional
	Processing int `json:"processing,omitempty"`

	// Graceful shutdown timeout in seconds
	// +kubebuilder:default=30
	// +optional
	GracefulShutdown int `json:"gracefulShutdown,omitempty"`
}

// ScalingConfig defines KEDA autoscaling configuration
type ScalingConfig struct {
	// Enable KEDA autoscaling
	// +kubebuilder:default=false
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// Minimum replicas
	// +kubebuilder:default=0
	// +kubebuilder:validation:Minimum=0
	// +optional
	MinReplicas *int32 `json:"minReplicas,omitempty"`

	// Maximum replicas
	// +kubebuilder:default=50
	// +kubebuilder:validation:Minimum=1
	// +optional
	MaxReplicas *int32 `json:"maxReplicas,omitempty"`

	// Polling interval in seconds
	// +kubebuilder:default=10
	// +optional
	PollingInterval int `json:"pollingInterval,omitempty"`

	// Cooldown period in seconds
	// +kubebuilder:default=60
	// +optional
	CooldownPeriod int `json:"cooldownPeriod,omitempty"`

	// Queue length threshold (messages per replica)
	// +kubebuilder:default=5
	// +kubebuilder:validation:Minimum=1
	// +optional
	QueueLength int `json:"queueLength,omitempty"`

	// Advanced scaling modifiers for KEDA
	// +optional
	Advanced *AdvancedScalingConfig `json:"advanced,omitempty"`
}

// AdvancedScalingConfig defines advanced KEDA scaling options
type AdvancedScalingConfig struct {
	// Scaling formula (e.g., "ceil(queueLength / maxMessagesPerWorker)")
	// +optional
	Formula string `json:"formula,omitempty"`

	// Target value for the metric
	// +optional
	Target string `json:"target,omitempty"`

	// Activation threshold to scale from 0 to 1 replica
	// +optional
	ActivationTarget string `json:"activationTarget,omitempty"`

	// Metric type (AverageValue, Value, or Utilization)
	// +kubebuilder:validation:Enum=AverageValue;Value;Utilization
	// +optional
	MetricType string `json:"metricType,omitempty"`

	// Restore to original replica count when scaled object is deleted
	// +optional
	RestoreToOriginalReplicaCount bool `json:"restoreToOriginalReplicaCount,omitempty"`
}

// WorkloadConfig defines the workload template
type WorkloadConfig struct {
	// Kind of workload
	// +kubebuilder:validation:Enum=Deployment;StatefulSet
	// +kubebuilder:default=Deployment
	// +optional
	Kind string `json:"kind,omitempty"`

	// Number of replicas (ignored if KEDA scaling enabled)
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=0
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// Python executable path for runtime containers
	// +kubebuilder:default=python3
	// +optional
	PythonExecutable string `json:"pythonExecutable,omitempty"`

	// Pod template
	// +kubebuilder:validation:Required
	Template PodTemplateSpec `json:"template"`
}

// PodTemplateSpec is a simplified pod template
type PodTemplateSpec struct {
	// Metadata
	// +optional
	// +kubebuilder:pruning:PreserveUnknownFields
	// +kubebuilder:validation:Schemaless
	Metadata metav1.ObjectMeta `json:"metadata,omitempty"`

	// Spec
	// +optional
	// +kubebuilder:pruning:PreserveUnknownFields
	// +kubebuilder:validation:Schemaless
	Spec corev1.PodSpec `json:"spec,omitempty"`
}

// AsyncActorStatus defines the observed state of AsyncActor
type AsyncActorStatus struct {
	// Conditions represent the latest available observations of the AsyncActor's state.
	// Standard condition types: TransportReady, WorkloadReady, ScalingReady
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// ReadySummary is a formatted summary of ready conditions for kubectl output.
	// Format: "ready/total" (e.g., "3/3", "2/3", "2/2")
	// Deprecated: Use ReadyReplicasSummary instead (shows pod readiness, not conditions).
	// +optional
	ReadySummary string `json:"readySummary,omitempty"`

	// Status is the overall status of the AsyncActor.
	// Operational: Running, Napping, Degraded
	// Transitional: Creating, ScalingUp, ScalingDown, Updating, Terminating
	// Errors: TransportError, ScalingError, WorkloadError, PendingResources, ImagePullError, RuntimeError, SidecarError, VolumeError, ConfigError
	// Future: WaitingDeps
	// Displayed in kubectl output as STATUS column.
	// +optional
	Status string `json:"status,omitempty"`

	// ReadyReplicas is the number of ready pods from the workload status.
	// Used to calculate ReadyReplicasSummary.
	// +optional
	ReadyReplicas *int32 `json:"readyReplicas,omitempty"`

	// TotalReplicas is the total number of non-terminated pods from the workload status.
	// Used to calculate ReadyReplicasSummary.
	// +optional
	TotalReplicas *int32 `json:"totalReplicas,omitempty"`

	// PendingReplicas is the number of pods created but not yet ready.
	// Includes pods in Pending phase or Running but not ready.
	// Displayed in kubectl output as PENDING column.
	// +optional
	PendingReplicas *int32 `json:"pendingReplicas,omitempty"`

	// FailingPods is the number of pods in failing states (CrashLoopBackOff, ImagePullBackOff, etc).
	// Includes pods actively retrying with backoff, not permanently failed pods.
	// Displayed in kubectl output as FAILING column.
	// +optional
	FailingPods *int32 `json:"failingPods,omitempty"`

	// ReadyReplicasSummary shows pod readiness in ready/total format.
	// Format: "ready/total" (e.g., "3/5", "10/10", "0/3")
	// Displayed in kubectl output as REPLICAS column.
	// +optional
	ReadyReplicasSummary string `json:"readyReplicasSummary,omitempty"`

	// TransportStatus indicates whether transport infrastructure is ready.
	// Values: "Ready", "NotReady"
	// Displayed in kubectl -o wide output as TRANSPORT column.
	// +optional
	TransportStatus string `json:"transportStatus,omitempty"`

	// WorkloadRef is a reference to the created workload (Deployment or StatefulSet)
	// +optional
	WorkloadRef *WorkloadReference `json:"workloadRef,omitempty"`

	// ScaledObjectRef is a reference to the KEDA ScaledObject (when scaling is enabled)
	// +optional
	ScaledObjectRef *NamespacedName `json:"scaledObjectRef,omitempty"`

	// Replicas is the current number of ready (running) replicas.
	// Counts only pods that are fully ready and available.
	// Displayed in kubectl output as RUNNING column.
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// DesiredReplicas is the target number of replicas.
	// When scaling is enabled, this comes from KEDA's HPA.
	// When scaling is disabled, this comes from spec.workload.replicas.
	// Displayed in kubectl output as DESIRED column.
	// +optional
	DesiredReplicas *int32 `json:"desiredReplicas,omitempty"`

	// ReplicasSummary is a formatted summary showing current/desired replicas.
	// Format: "current/desired" (e.g., "5/5", "3/10", "0/0")
	// Deprecated: Use separate Replicas and DesiredReplicas fields instead.
	// +optional
	ReplicasSummary string `json:"replicasSummary,omitempty"`

	// LastScaleTime is the timestamp when replicas last changed (up or down).
	// Used to calculate time since last scaling event.
	// +optional
	LastScaleTime *metav1.Time `json:"lastScaleTime,omitempty"`

	// LastScaleDirection indicates the direction of the last scaling event.
	// Possible values: "up" (scaled up), "down" (scaled down), "" (no scaling yet)
	// +optional
	LastScaleDirection string `json:"lastScaleDirection,omitempty"`

	// ScalingMode indicates the scaling mode for kubectl output.
	// Values: "KEDA" (autoscaling enabled), "Manual" (fixed replicas)
	// Displayed in kubectl -o wide output as SCALING column.
	// +optional
	ScalingMode string `json:"scalingMode,omitempty"`

	// LastScaleFormatted is a human-readable representation of last scaling event.
	// Format: "<time> ago (<direction>)" (e.g., "5m ago (up)", "2h ago (down)", "-")
	// Displayed in kubectl output as LAST-SCALE column.
	// +optional
	LastScaleFormatted string `json:"lastScaleFormatted,omitempty"`

	// QueuedMessages is the number of messages waiting in the queue (ready to process).
	// Only available for transports that support queue metrics (RabbitMQ, SQS).
	// Displayed in kubectl -o wide output as QUEUED column.
	// +optional
	QueuedMessages *int32 `json:"queuedMessages,omitempty"`

	// ProcessingMessages is the number of messages currently being processed (in-flight).
	// Only available for transports that track in-flight messages (RabbitMQ, SQS).
	// Nil if transport doesn't support this metric.
	// Displayed in kubectl -o wide output as PROCESSING column.
	// +optional
	ProcessingMessages *int32 `json:"processingMessages,omitempty"`

	// ObservedGeneration reflects the generation of the most recently observed AsyncActor spec.
	// Used to track if status is up-to-date with latest spec changes.
	// +optional
	// +kubebuilder:validation:Format=""
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
}

// WorkloadReference references a created workload
type WorkloadReference struct {
	APIVersion string `json:"apiVersion"`
	Kind       string `json:"kind"`
	Name       string `json:"name"`
	Namespace  string `json:"namespace"`
}

// NamespacedName is a simple namespace/name tuple
type NamespacedName struct {
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=asyncactor;asya;asyas
// +kubebuilder:printcolumn:name="Status",type=string,JSONPath=`.status.status`
// +kubebuilder:printcolumn:name="Running",type=integer,JSONPath=`.status.replicas`
// +kubebuilder:printcolumn:name="Failing",type=integer,JSONPath=`.status.failingPods`
// +kubebuilder:printcolumn:name="Total",type=integer,JSONPath=`.status.totalReplicas`
// +kubebuilder:printcolumn:name="Desired",type=integer,JSONPath=`.status.desiredReplicas`
// +kubebuilder:printcolumn:name="Min",type=integer,JSONPath=`.spec.scaling.minReplicas`
// +kubebuilder:printcolumn:name="Max",type=integer,JSONPath=`.spec.scaling.maxReplicas`
// +kubebuilder:printcolumn:name="Last-Scale",type=string,JSONPath=`.status.lastScaleFormatted`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`
// +kubebuilder:printcolumn:name="Workload",type=string,JSONPath=`.spec.workload.kind`,priority=1
// +kubebuilder:printcolumn:name="Transport",type=string,JSONPath=`.status.transportStatus`,priority=1
// +kubebuilder:printcolumn:name="Scaling",type=string,JSONPath=`.status.scalingMode`,priority=1
// +kubebuilder:printcolumn:name="Queued",type=integer,JSONPath=`.status.queuedMessages`,priority=1
// +kubebuilder:printcolumn:name="Processing",type=integer,JSONPath=`.status.processingMessages`,priority=1

// AsyncActor is the Schema for the asyncactors API
type AsyncActor struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   AsyncActorSpec   `json:"spec,omitempty"`
	Status AsyncActorStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// AsyncActorList contains a list of AsyncActor
type AsyncActorList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []AsyncActor `json:"items"`
}

func init() {
	SchemeBuilder.Register(&AsyncActor{}, &AsyncActorList{})
}
