package injection

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

	// PythonExecutable is the Python executable to use
	PythonExecutable string

	// SidecarImage is the sidecar container image (optional override)
	SidecarImage string

	// Region is the AWS region for SQS
	Region string
}
