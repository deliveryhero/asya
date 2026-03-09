package injection

import corev1 "k8s.io/api/core/v1"

// RetryConfig holds retry policy configuration
type RetryConfig struct {
	Policy             string
	MaxAttempts        string
	InitialInterval    string
	MaxInterval        string
	BackoffCoefficient string
	Jitter             string
}

// ResiliencyConfig holds resiliency configuration extracted from AsyncActor spec
type ResiliencyConfig struct {
	Retry              *RetryConfig
	NonRetryableErrors string
	ActorTimeout       string
}

// StateProxyMount holds a single state proxy mount configuration
type StateProxyMount struct {
	Name           string
	MountPath      string
	ConnectorImage string
	ConnectorEnv   []corev1.EnvVar
	Resources      *corev1.ResourceRequirements
	WriteMode      string
}

// SecretRefKey maps a key in a Kubernetes Secret to an environment variable name
type SecretRefKey struct {
	Key    string // key in the Secret
	EnvVar string // env var name in the container
}

// SecretRef holds a reference to a Kubernetes Secret and the keys to inject
type SecretRef struct {
	SecretName string
	Keys       []SecretRefKey
}

// ActorConfig holds the configuration extracted from an AsyncActor resource
type ActorConfig struct {
	// ActorName is the name of the actor
	ActorName string

	// Namespace is the namespace where the actor is deployed
	Namespace string

	// Transport is the transport type (sqs, rabbitmq)
	Transport string

	// QueueURL is the URL of the queue for this actor
	QueueURL string

	// Handler is the Python handler path (e.g., my_module.process)
	Handler string

	// SidecarImage is the sidecar container image (optional override)
	SidecarImage string

	// SidecarImagePullPolicy is the image pull policy for the sidecar (optional override)
	SidecarImagePullPolicy string

	// SidecarEnv is additional environment variables for the sidecar container
	SidecarEnv []corev1.EnvVar

	// Resiliency is the resiliency configuration (nil means no resiliency config)
	Resiliency *ResiliencyConfig

	// StateProxy is the list of state proxy mount configurations
	StateProxy []StateProxyMount

	// SecretRefs is the list of Secret references to inject into the runtime container
	SecretRefs []SecretRef
}
