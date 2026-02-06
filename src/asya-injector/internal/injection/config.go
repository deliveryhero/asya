package injection

import corev1 "k8s.io/api/core/v1"

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

	// HandlerMode is the handler mode (payload, envelope)
	HandlerMode string

	// SidecarImage is the sidecar container image (optional override)
	SidecarImage string

	// SidecarImagePullPolicy is the image pull policy for the sidecar (optional override)
	SidecarImagePullPolicy string

	// SidecarEnv is additional environment variables for the sidecar container
	SidecarEnv []corev1.EnvVar

	// Region is the AWS region for SQS
	Region string
}
