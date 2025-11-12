package config

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
	corev1 "k8s.io/api/core/v1"
)

// QueueMetrics contains queue-level metrics from a transport
type QueueMetrics struct {
	Queued     int32  // Messages waiting in queue (always available)
	Processing *int32 // Messages being processed (optional - nil if unavailable)
}

// PasswordResolver is a function that resolves a password from secrets
type PasswordResolver func(ctx context.Context, secretRef *corev1.SecretKeySelector, namespace string) (string, error)

// TransportSpecificConfig is an interface for transport-specific configurations
type TransportSpecificConfig interface {
	isTransportConfig()

	// GetQueueMetrics returns queue metrics if supported by the transport
	// Returns QueueMetrics with Queued=0 and Processing=nil if not supported
	// passwordResolver is called to resolve passwords from secret references
	GetQueueMetrics(ctx context.Context, queueName string, namespace string, passwordResolver PasswordResolver) (*QueueMetrics, error)
}

// TransportRegistry holds all configured transports
type TransportRegistry struct {
	Transports map[string]*TransportConfig
}

// TransportConfig defines a configured transport
type TransportConfig struct {
	Type    string
	Enabled bool
	Config  TransportSpecificConfig
}

// rawTransportConfig is used for JSON unmarshaling
type rawTransportConfig struct {
	Type    string                 `json:"type"`
	Enabled bool                   `json:"enabled"`
	Config  map[string]interface{} `json:"config"`
}

// hasQueuesConfig checks if queues config is present in raw config
func (r *rawTransportConfig) hasQueuesConfig() bool {
	_, ok := r.Config["queues"]
	return ok
}

// rawTransportRegistry is used for JSON unmarshaling
type rawTransportRegistry struct {
	Transports map[string]*rawTransportConfig `json:"transports"`
}

// QueueManagementConfig defines queue creation and lifecycle options
type QueueManagementConfig struct {
	AutoCreate    bool      `json:"autoCreate"`
	ForceRecreate bool      `json:"forceRecreate"`
	DLQ           DLQConfig `json:"dlq"`
}

// DLQConfig defines Dead Letter Queue configuration
type DLQConfig struct {
	Enabled       bool `json:"enabled"`
	MaxRetryCount int  `json:"maxRetryCount"`
	RetentionDays int  `json:"retentionDays,omitempty"`
}

// RabbitMQConfig defines RabbitMQ-specific configuration
type RabbitMQConfig struct {
	Host              string                    `json:"host"`
	Port              int                       `json:"port"`
	Username          string                    `json:"username"`
	PasswordSecretRef *corev1.SecretKeySelector `json:"passwordSecretRef,omitempty"`
	Password          string                    `json:"-"` // For testing only, not marshaled
	Exchange          string                    `json:"exchange,omitempty"`
	Queues            QueueManagementConfig     `json:"queues"`
}

func (r *RabbitMQConfig) isTransportConfig() {}

// SQSConfig defines SQS-specific configuration
type SQSConfig struct {
	Region            string                `json:"region"`
	ActorRoleArn      string                `json:"actorRoleArn"`
	AccountID         string                `json:"accountId,omitempty"`
	Endpoint          string                `json:"endpoint,omitempty"`
	VisibilityTimeout int                   `json:"visibilityTimeout"`
	WaitTimeSeconds   int                   `json:"waitTimeSeconds"`
	Credentials       *SQSCredentialsConfig `json:"credentials,omitempty"`
	Queues            QueueManagementConfig `json:"queues"`
	Tags              map[string]string     `json:"tags,omitempty"`
}

// SQSCredentialsConfig defines AWS credentials for SQS
type SQSCredentialsConfig struct {
	AccessKeyIdSecretRef     *corev1.SecretKeySelector `json:"accessKeyIdSecretRef,omitempty"`
	SecretAccessKeySecretRef *corev1.SecretKeySelector `json:"secretAccessKeySecretRef,omitempty"`
}

func (s *SQSConfig) isTransportConfig() {}

// LoadTransportRegistry loads transport configurations from environment
func LoadTransportRegistry() (*TransportRegistry, error) {
	configJSON := os.Getenv("ASYA_TRANSPORT_CONFIG")
	if configJSON == "" {
		return &TransportRegistry{Transports: make(map[string]*TransportConfig)}, nil
	}

	rawRegistry := &rawTransportRegistry{}
	decoder := json.NewDecoder(bytes.NewReader([]byte(configJSON)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(rawRegistry); err != nil {
		return nil, fmt.Errorf("failed to parse transport config: %w", err)
	}

	registry := &TransportRegistry{
		Transports: make(map[string]*TransportConfig),
	}

	for name, rawConfig := range rawRegistry.Transports {
		typedConfig, err := parseTransportConfig(rawConfig)
		if err != nil {
			return nil, fmt.Errorf("failed to parse config for transport '%s': %w", name, err)
		}
		registry.Transports[name] = typedConfig
	}

	return registry, nil
}

// parseTransportConfig parses raw config into typed transport config
func parseTransportConfig(raw *rawTransportConfig) (*TransportConfig, error) {
	var typedConfig TransportSpecificConfig

	configBytes, err := json.Marshal(raw.Config)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal config: %w", err)
	}

	switch raw.Type {
	case "rabbitmq":
		config := &RabbitMQConfig{}
		decoder := json.NewDecoder(bytes.NewReader(configBytes))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(config); err != nil {
			return nil, fmt.Errorf("failed to parse RabbitMQ config: %w", err)
		}
		// Set defaults for queue management if not specified
		if !raw.hasQueuesConfig() {
			config.Queues.AutoCreate = true
			config.Queues.ForceRecreate = false
		}
		// Set DLQ defaults
		if config.Queues.DLQ.MaxRetryCount == 0 {
			config.Queues.DLQ.MaxRetryCount = 3
		}
		typedConfig = config

	case "sqs":
		config := &SQSConfig{}
		decoder := json.NewDecoder(bytes.NewReader(configBytes))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(config); err != nil {
			return nil, fmt.Errorf("failed to parse SQS config: %w", err)
		}
		// Set defaults for queue management if not specified
		if !raw.hasQueuesConfig() {
			config.Queues.AutoCreate = true
			config.Queues.ForceRecreate = false
		}
		// Set DLQ defaults
		if config.Queues.DLQ.MaxRetryCount == 0 {
			config.Queues.DLQ.MaxRetryCount = 3
		}
		if config.Queues.DLQ.RetentionDays == 0 {
			config.Queues.DLQ.RetentionDays = 14
		}
		typedConfig = config

	default:
		return nil, fmt.Errorf("unsupported transport type: %s", raw.Type)
	}

	return &TransportConfig{
		Type:    raw.Type,
		Enabled: raw.Enabled,
		Config:  typedConfig,
	}, nil
}

// GetTransport retrieves a transport config by name
func (r *TransportRegistry) GetTransport(name string) (*TransportConfig, error) {
	transport, ok := r.Transports[name]
	if !ok {
		return nil, fmt.Errorf("transport '%s' not found in operator configuration", name)
	}

	if !transport.Enabled {
		return nil, fmt.Errorf("transport '%s' is disabled in operator configuration", name)
	}

	return transport, nil
}

// BuildEnvVars builds environment variables for a transport
func (t *TransportConfig) BuildEnvVars() ([]corev1.EnvVar, error) {
	env := []corev1.EnvVar{
		{Name: "ASYA_TRANSPORT", Value: t.Type},
	}

	switch t.Type {
	case "rabbitmq":
		config, ok := t.Config.(*RabbitMQConfig)
		if !ok {
			return nil, fmt.Errorf("invalid config type for RabbitMQ transport")
		}

		port := config.Port
		if port == 0 {
			port = 5672
		}
		username := config.Username
		if username == "" {
			username = "guest"
		}

		env = append(env, corev1.EnvVar{Name: "ASYA_RABBITMQ_HOST", Value: config.Host})
		env = append(env, corev1.EnvVar{Name: "ASYA_RABBITMQ_PORT", Value: fmt.Sprintf("%d", port)})
		env = append(env, corev1.EnvVar{Name: "ASYA_RABBITMQ_USERNAME", Value: username})

		if config.PasswordSecretRef != nil {
			env = append(env, corev1.EnvVar{
				Name: "ASYA_RABBITMQ_PASSWORD",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: config.PasswordSecretRef,
				},
			})
		} else if config.Password != "" {
			env = append(env, corev1.EnvVar{
				Name:  "ASYA_RABBITMQ_PASSWORD",
				Value: config.Password,
			})
		}

		if config.Exchange != "" {
			env = append(env, corev1.EnvVar{Name: "ASYA_RABBITMQ_EXCHANGE", Value: config.Exchange})
		}

		env = append(env, corev1.EnvVar{Name: "ASYA_QUEUE_AUTO_CREATE", Value: fmt.Sprintf("%t", config.Queues.AutoCreate)})

	case "sqs":
		config, ok := t.Config.(*SQSConfig)
		if !ok {
			return nil, fmt.Errorf("invalid config type for SQS transport")
		}

		if config.Region != "" {
			env = append(env, corev1.EnvVar{Name: "ASYA_AWS_REGION", Value: config.Region})
		}
		if config.Endpoint != "" {
			env = append(env, corev1.EnvVar{Name: "ASYA_SQS_ENDPOINT", Value: config.Endpoint})
		}
		if config.VisibilityTimeout > 0 {
			env = append(env, corev1.EnvVar{Name: "ASYA_SQS_VISIBILITY_TIMEOUT", Value: fmt.Sprintf("%d", config.VisibilityTimeout)})
		}
		if config.WaitTimeSeconds > 0 {
			env = append(env, corev1.EnvVar{Name: "ASYA_SQS_WAIT_TIME_SECONDS", Value: fmt.Sprintf("%d", config.WaitTimeSeconds)})
		}

		if config.Credentials != nil {
			if config.Credentials.AccessKeyIdSecretRef != nil {
				env = append(env, corev1.EnvVar{
					Name: "AWS_ACCESS_KEY_ID",
					ValueFrom: &corev1.EnvVarSource{
						SecretKeyRef: config.Credentials.AccessKeyIdSecretRef,
					},
				})
			}
			if config.Credentials.SecretAccessKeySecretRef != nil {
				env = append(env, corev1.EnvVar{
					Name: "AWS_SECRET_ACCESS_KEY",
					ValueFrom: &corev1.EnvVarSource{
						SecretKeyRef: config.Credentials.SecretAccessKeySecretRef,
					},
				})
			}
		}
	}

	return env, nil
}

// rabbitmqQueueResponse represents the response from RabbitMQ Management API
type rabbitmqQueueResponse struct {
	MessagesReady          int32 `json:"messages_ready"`
	MessagesUnacknowledged int32 `json:"messages_unacknowledged"`
}

// GetQueueMetrics for RabbitMQ queries the Management API
func (r *RabbitMQConfig) GetQueueMetrics(ctx context.Context, queueName string, namespace string, passwordResolver PasswordResolver) (*QueueMetrics, error) {
	vhost := "%2F" // URL-encoded "/"

	// Determine host:port for Management API
	host := r.Host
	if !strings.Contains(host, ":") {
		// No port specified, use default Management API port
		host = fmt.Sprintf("%s:15672", host)
	}

	url := fmt.Sprintf("http://%s/api/queues/%s/%s", host, vhost, queueName)

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	// Resolve password from secret or use plain password field
	password := r.Password
	if r.PasswordSecretRef != nil && passwordResolver != nil {
		resolvedPassword, err := passwordResolver(ctx, r.PasswordSecretRef, namespace)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve password: %w", err)
		}
		password = resolvedPassword
	}

	// Add basic auth
	req.SetBasicAuth(r.Username, password)

	client := &http.Client{
		Timeout: 5 * time.Second,
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to query RabbitMQ API: %w", err)
	}
	defer func() {
		_ = resp.Body.Close()
	}()

	if resp.StatusCode == http.StatusNotFound {
		// Queue doesn't exist yet - return zeros
		processing := int32(0)
		return &QueueMetrics{
			Queued:     0,
			Processing: &processing,
		}, nil
	}

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("RabbitMQ API returned %d: %s", resp.StatusCode, string(body))
	}

	var queueData rabbitmqQueueResponse
	if err := json.NewDecoder(resp.Body).Decode(&queueData); err != nil {
		return nil, fmt.Errorf("failed to parse queue data: %w", err)
	}

	return &QueueMetrics{
		Queued:     queueData.MessagesReady,
		Processing: &queueData.MessagesUnacknowledged,
	}, nil
}

// GetQueueMetrics for SQS queries AWS SQS GetQueueAttributes
func (s *SQSConfig) GetQueueMetrics(ctx context.Context, queueName string, namespace string, passwordResolver PasswordResolver) (*QueueMetrics, error) {
	// Create AWS config
	configOpts := []func(*config.LoadOptions) error{
		config.WithRegion(s.Region),
	}

	// If custom endpoint is configured (e.g., LocalStack), use it
	if s.Endpoint != "" {
		configOpts = append(configOpts, config.WithEndpointResolverWithOptions(
			aws.EndpointResolverWithOptionsFunc(func(service, region string, options ...interface{}) (aws.Endpoint, error) {
				return aws.Endpoint{
					URL:               s.Endpoint,
					HostnameImmutable: true,
				}, nil
			}),
		))
	}

	awsConfig, err := config.LoadDefaultConfig(ctx, configOpts...)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	sqsClient := sqs.NewFromConfig(awsConfig)

	// Get queue URL
	urlResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(queueName),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to get queue URL: %w", err)
	}

	// Get queue attributes
	attrsResult, err := sqsClient.GetQueueAttributes(ctx, &sqs.GetQueueAttributesInput{
		QueueUrl: urlResult.QueueUrl,
		AttributeNames: []types.QueueAttributeName{
			types.QueueAttributeNameApproximateNumberOfMessages,
			types.QueueAttributeNameApproximateNumberOfMessagesNotVisible,
		},
	})
	if err != nil {
		return nil, fmt.Errorf("failed to get queue attributes: %w", err)
	}

	// Parse metrics
	queued := int32(0)
	processing := int32(0)

	if val, ok := attrsResult.Attributes[string(types.QueueAttributeNameApproximateNumberOfMessages)]; ok {
		if parsed, err := strconv.ParseInt(val, 10, 32); err == nil {
			queued = int32(parsed)
		}
	}

	if val, ok := attrsResult.Attributes[string(types.QueueAttributeNameApproximateNumberOfMessagesNotVisible)]; ok {
		if parsed, err := strconv.ParseInt(val, 10, 32); err == nil {
			processing = int32(parsed)
		}
	}

	return &QueueMetrics{
		Queued:     queued,
		Processing: &processing,
	}, nil
}
