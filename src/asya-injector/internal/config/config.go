package config

import (
	"os"
)

// Config holds the injector configuration
type Config struct {
	// SidecarImage is the image to use for the asya-sidecar container
	SidecarImage string

	// RuntimeConfigMap is the name of the ConfigMap containing asya_runtime.py
	RuntimeConfigMap string

	// SidecarImagePullPolicy is the pull policy for the sidecar image
	SidecarImagePullPolicy string

	// SocketDir is the directory for the Unix socket shared between sidecar and runtime
	SocketDir string

	// RuntimeMountPath is the mount path for the runtime script
	RuntimeMountPath string

	// GatewayURL is the URL of the asya-gateway for progress reporting
	GatewayURL string

	// SQSEndpoint is the custom SQS endpoint URL (for LocalStack or other AWS-compatible services)
	SQSEndpoint string

	// AWSCredsSecret is the name of the secret containing AWS credentials to inject into the sidecar
	AWSCredsSecret string

	// RabbitMQURL is the AMQP connection URL for RabbitMQ transport
	RabbitMQURL string

	// RabbitMQCredsSecret is the name of the secret containing RabbitMQ credentials to inject into the sidecar
	RabbitMQCredsSecret string
}

// LoadFromEnv loads configuration from environment variables
func LoadFromEnv() *Config {
	return &Config{
		SidecarImage:           getEnv("ASYA_SIDECAR_IMAGE", "ghcr.io/deliveryhero/asya-sidecar:latest"),
		RuntimeConfigMap:       getEnv("ASYA_RUNTIME_CONFIGMAP", "asya-runtime"),
		SidecarImagePullPolicy: getEnv("ASYA_SIDECAR_IMAGE_PULL_POLICY", "IfNotPresent"),
		SocketDir:              getEnv("ASYA_SOCKET_DIR", "/var/run/asya"),
		RuntimeMountPath:       getEnv("ASYA_RUNTIME_MOUNT_PATH", "/opt/asya/asya_runtime.py"),
		GatewayURL:             getEnv("ASYA_GATEWAY_URL", ""),
		SQSEndpoint:            getEnv("ASYA_SQS_ENDPOINT", ""),
		AWSCredsSecret:         getEnv("ASYA_AWS_CREDS_SECRET", ""),
		RabbitMQURL:            getEnv("ASYA_RABBITMQ_URL", ""),
		RabbitMQCredsSecret:    getEnv("ASYA_RABBITMQ_CREDS_SECRET", ""),
	}
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
