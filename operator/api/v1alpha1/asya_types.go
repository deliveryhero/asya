package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// AsyncActorSpec defines the desired state of AsyncActor
type AsyncActorSpec struct {
	// QueueName is the name of the queue this actor consumes from
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	QueueName string `json:"queueName"`

	// Transport configuration for message queue
	// +kubebuilder:validation:Required
	Transport TransportConfig `json:"transport"`

	// Sidecar container configuration
	// +optional
	Sidecar SidecarConfig `json:"sidecar,omitempty"`

	// Socket configuration
	// +optional
	Socket SocketConfig `json:"socket,omitempty"`

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

// TransportConfig defines the message transport configuration
type TransportConfig struct {
	// Type of transport (sqs or rabbitmq)
	// +kubebuilder:validation:Enum=sqs;rabbitmq
	// +kubebuilder:validation:Required
	Type string `json:"type"`

	// SQS-specific configuration
	// +optional
	SQS *SQSConfig `json:"sqs,omitempty"`

	// RabbitMQ-specific configuration
	// +optional
	RabbitMQ *RabbitMQConfig `json:"rabbitmq,omitempty"`
}

// SQSConfig defines SQS-specific configuration
type SQSConfig struct {
	// AWS Region
	// +kubebuilder:default=us-east-1
	// +optional
	Region string `json:"region,omitempty"`

	// Queue base URL
	// +optional
	QueueBaseURL string `json:"queueBaseUrl,omitempty"`

	// Visibility timeout in seconds
	// +kubebuilder:default=300
	// +optional
	VisibilityTimeout int `json:"visibilityTimeout,omitempty"`

	// Wait time for long polling in seconds
	// +kubebuilder:default=20
	// +optional
	WaitTimeSeconds int `json:"waitTimeSeconds,omitempty"`
}

// RabbitMQConfig defines RabbitMQ-specific configuration
type RabbitMQConfig struct {
	// RabbitMQ host
	// +optional
	Host string `json:"host,omitempty"`

	// RabbitMQ port
	// +kubebuilder:default=5672
	// +optional
	Port int `json:"port,omitempty"`

	// Username
	// +optional
	Username string `json:"username,omitempty"`

	// Password secret reference
	// +optional
	PasswordSecretRef *corev1.SecretKeySelector `json:"passwordSecretRef,omitempty"`
}

// SidecarConfig defines sidecar container configuration
type SidecarConfig struct {
	// Sidecar image
	// +kubebuilder:default=asya-sidecar:latest
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

// SocketConfig defines Unix socket configuration
type SocketConfig struct {
	// Socket path
	// +kubebuilder:default=/tmp/sockets/app.sock
	// +optional
	Path string `json:"path,omitempty"`

	// Maximum message size
	// +kubebuilder:default=10485760
	// +optional
	MaxSize string `json:"maxSize,omitempty"`
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
	// +kubebuilder:default=true
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
}

// WorkloadConfig defines the workload template
type WorkloadConfig struct {
	// Type of workload
	// +kubebuilder:validation:Enum=Deployment;StatefulSet;Job
	// +kubebuilder:default=Deployment
	// +optional
	Type string `json:"type,omitempty"`

	// Number of replicas (ignored if KEDA scaling enabled)
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=0
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// Pod template
	// +kubebuilder:validation:Required
	Template PodTemplateSpec `json:"template"`
}

// PodTemplateSpec is a simplified pod template
type PodTemplateSpec struct {
	// Metadata
	// +optional
	Metadata metav1.ObjectMeta `json:"metadata,omitempty"`

	// Spec
	// +optional
	Spec corev1.PodSpec `json:"spec,omitempty"`
}

// AsyncActorStatus defines the observed state of AsyncActor
type AsyncActorStatus struct {
	// Conditions represent the latest available observations
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// Reference to created workload
	// +optional
	WorkloadRef *WorkloadReference `json:"workloadRef,omitempty"`

	// Reference to created KEDA ScaledObject
	// +optional
	ScaledObjectRef *NamespacedName `json:"scaledObjectRef,omitempty"`

	// ObservedGeneration reflects the generation observed
	// +optional
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
// +kubebuilder:resource:shortName=asyncactor
// +kubebuilder:printcolumn:name="Queue",type=string,JSONPath=`.spec.queueName`
// +kubebuilder:printcolumn:name="Transport",type=string,JSONPath=`.spec.transport.type`
// +kubebuilder:printcolumn:name="Workload",type=string,JSONPath=`.spec.workload.type`
// +kubebuilder:printcolumn:name="Min",type=integer,JSONPath=`.spec.scaling.minReplicas`
// +kubebuilder:printcolumn:name="Max",type=integer,JSONPath=`.spec.scaling.maxReplicas`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

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
