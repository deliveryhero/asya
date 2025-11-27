package transports

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
	corev1 "k8s.io/api/core/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
)

// SQSTransport implements queue reconciliation for AWS SQS
type SQSTransport struct {
	k8sClient         client.Client
	transportRegistry *asyaconfig.TransportRegistry
}

// NewSQSTransport creates a new SQS transport reconciler
func NewSQSTransport(k8sClient client.Client, registry *asyaconfig.TransportRegistry) *SQSTransport {
	return &SQSTransport{
		k8sClient:         k8sClient,
		transportRegistry: registry,
	}
}

// ReconcileQueue creates or updates the SQS queue for an actor
func (t *SQSTransport) ReconcileQueue(ctx context.Context, actor *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	transport, err := t.transportRegistry.GetTransport("sqs")
	if err != nil {
		return err
	}

	sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		return fmt.Errorf("invalid SQS config type")
	}

	logger.V(1).Info("SQS config loaded", "configuredTags", sqsConfig.Tags, "autoCreate", sqsConfig.Queues.AutoCreate)

	queueName := fmt.Sprintf("asya-%s", actor.Name)

	sqsClient, err := t.createSQSClient(ctx, sqsConfig, actor.Namespace)
	if err != nil {
		return fmt.Errorf("failed to create SQS client: %w", err)
	}

	// Check if queue already exists
	urlResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(queueName),
	})

	visibilityTimeout := strconv.Itoa(sqsConfig.VisibilityTimeout)

	if err == nil {
		// Queue exists - check if attributes match
		attrsResult, err := sqsClient.GetQueueAttributes(ctx, &sqs.GetQueueAttributesInput{
			QueueUrl: urlResult.QueueUrl,
			AttributeNames: []types.QueueAttributeName{
				types.QueueAttributeNameVisibilityTimeout,
			},
		})

		if err == nil {
			existingTimeout := attrsResult.Attributes[string(types.QueueAttributeNameVisibilityTimeout)]
			if existingTimeout == visibilityTimeout {
				logger.Info("SQS queue already exists with matching configuration", "queue", queueName)
				return nil
			}

			// Configuration mismatch
			if !sqsConfig.Queues.AutoCreate {
				return fmt.Errorf("queue %s exists but configuration mismatch (autoCreate disabled): expected visibilityTimeout=%s, got %s", queueName, visibilityTimeout, existingTimeout)
			}

			// Auto mode: delete and recreate queue
			logger.Info("Queue exists with different configuration - deleting and recreating", "queue", queueName, "existing", existingTimeout, "desired", visibilityTimeout)
			if err := t.forceDeleteQueue(ctx, sqsClient, queueName); err != nil {
				return fmt.Errorf("failed to delete queue for recreation: %w", err)
			}

			logger.Info("Waiting for AWS SQS cooldown period after queue deletion", "queue", queueName, "duration", "60s")
			time.Sleep(60 * time.Second)
		}
	} else {
		// Queue doesn't exist
		var qne *types.QueueDoesNotExist
		if errors.As(err, &qne) {
			if !sqsConfig.Queues.AutoCreate {
				return fmt.Errorf("queue %s does not exist (autoCreate disabled): queues must be created externally in manual mode", queueName)
			}
			logger.Info("Queue does not exist, will create", "queue", queueName)
		} else {
			return fmt.Errorf("failed to get SQS queue URL: %w", err)
		}
	}

	// Skip queue creation in manual mode if queue exists
	if !sqsConfig.Queues.AutoCreate {
		logger.Info("Queue exists with matching configuration (autoCreate disabled)", "queue", queueName)
		return nil
	}

	// Create shared DLQ first if enabled
	var dlqArn string
	if sqsConfig.Queues.DLQ.Enabled {
		var err error
		dlqArn, err = t.ensureDLQ(ctx, sqsClient, queueName, sqsConfig, actor)
		if err != nil {
			return fmt.Errorf("failed to ensure shared DLQ: %w", err)
		}
		logger.Info("Shared DLQ ensured", "dlq", "asya-dlq", "arn", dlqArn)
	}

	// Merge configured tags with default tags
	// CRITICAL: This tag merging logic is tested in TestSQSConfig_TagsMerging
	// If you modify this code, you MUST update that test to match.
	tags := map[string]string{
		"asya.sh/actor":     actor.Name,
		"asya.sh/namespace": actor.Namespace,
	}
	logger.V(1).Info("Default tags set", "queue", queueName, "defaultTags", tags)

	for k, v := range sqsConfig.Tags {
		tags[k] = v
	}

	logger.Info("Creating SQS queue with merged tags", "queue", queueName, "totalTags", tags, "configuredTagCount", len(sqsConfig.Tags))

	// Prepare queue attributes
	queueAttributes := map[string]string{
		"VisibilityTimeout":      visibilityTimeout,
		"MessageRetentionPeriod": "345600",
	}

	// Add RedrivePolicy if DLQ is enabled
	if sqsConfig.Queues.DLQ.Enabled && dlqArn != "" {
		redrivePolicy := fmt.Sprintf(`{"deadLetterTargetArn":"%s","maxReceiveCount":%d}`,
			dlqArn, sqsConfig.Queues.DLQ.MaxRetryCount)
		queueAttributes["RedrivePolicy"] = redrivePolicy
		logger.Info("Configuring queue with DLQ", "queue", queueName, "redrivePolicy", redrivePolicy)
	}

	// Create queue (either doesn't exist, or was deleted for recreation)
	_, err = sqsClient.CreateQueue(ctx, &sqs.CreateQueueInput{
		QueueName:  aws.String(queueName),
		Attributes: queueAttributes,
		Tags:       tags,
	})

	if err != nil {
		if strings.Contains(err.Error(), "QueueDeletedRecently") {
			logger.Info("Queue was recently deleted, will retry after AWS cooldown period", "queue", queueName, "retryAfter", "65s")
			return fmt.Errorf("queue %s was recently deleted, waiting for AWS cooldown period (60s): %w", queueName, err)
		}
		logger.Error(err, "CreateQueue API call failed", "queue", queueName, "tags", tags)
		return fmt.Errorf("failed to create SQS queue %s: %w", queueName, err)
	}

	logger.Info("SQS queue created successfully", "queue", queueName, "appliedTags", tags)
	return nil
}

// DeleteQueue deletes the SQS queue for an actor
func (t *SQSTransport) DeleteQueue(ctx context.Context, actor *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	transport, err := t.transportRegistry.GetTransport("sqs")
	if err != nil {
		return err
	}

	sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		return fmt.Errorf("invalid SQS config type")
	}

	queueName := fmt.Sprintf("asya-%s", actor.Name)

	sqsClient, err := t.createSQSClient(ctx, sqsConfig, actor.Namespace)
	if err != nil {
		return fmt.Errorf("failed to create SQS client: %w", err)
	}

	// Delete main queue
	if err := t.forceDeleteQueue(ctx, sqsClient, queueName); err != nil {
		return err
	}

	// Shared DLQ is not deleted when actors are removed
	logger.V(1).Info("Shared DLQ preserved (not deleted with actor)", "queue", queueName)

	return nil
}

// ReconcileServiceAccount creates or updates ServiceAccount with IRSA annotation
func (t *SQSTransport) ReconcileServiceAccount(ctx context.Context, actor *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	transport, err := t.transportRegistry.GetTransport("sqs")
	if err != nil {
		return err
	}

	sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		return fmt.Errorf("invalid SQS config type")
	}

	// Only create ServiceAccount if actorRoleArn is configured (for EKS IRSA)
	// Skip for LocalStack or environments using static credentials
	if sqsConfig.ActorRoleArn == "" {
		logger.Info("Skipping ServiceAccount creation (no actorRoleArn configured)", "actor", actor.Name)
		return nil
	}

	// TODO: Implement ServiceAccount creation with IRSA annotation
	// This would create a ServiceAccount with eks.amazonaws.com/role-arn annotation
	logger.Info("ServiceAccount reconciliation not yet implemented", "actor", actor.Name)
	return nil
}

// createSQSClient creates an SQS client with proper credentials
func (t *SQSTransport) createSQSClient(ctx context.Context, sqsConfig *asyaconfig.SQSConfig, namespace string) (*sqs.Client, error) {
	configOpts := []func(*config.LoadOptions) error{
		config.WithRegion(sqsConfig.Region),
	}

	// If custom endpoint is configured (e.g., LocalStack), use it
	if sqsConfig.Endpoint != "" {
		configOpts = append(configOpts, config.WithEndpointResolverWithOptions(
			aws.EndpointResolverWithOptionsFunc(func(service, region string, options ...interface{}) (aws.Endpoint, error) {
				return aws.Endpoint{
					URL:               sqsConfig.Endpoint,
					HostnameImmutable: true,
				}, nil
			}),
		))
	}

	// Load credentials from secret if configured
	if sqsConfig.Credentials != nil {
		accessKeyID, secretAccessKey, err := t.loadSQSCredentials(ctx, sqsConfig, namespace)
		if err != nil {
			return nil, fmt.Errorf("failed to load SQS credentials: %w", err)
		}

		configOpts = append(configOpts, config.WithCredentialsProvider(
			credentials.NewStaticCredentialsProvider(accessKeyID, secretAccessKey, ""),
		))
	}

	cfg, err := config.LoadDefaultConfig(ctx, configOpts...)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	return sqs.NewFromConfig(cfg), nil
}

// loadSQSCredentials loads AWS credentials from Kubernetes secrets
func (t *SQSTransport) loadSQSCredentials(ctx context.Context, sqsConfig *asyaconfig.SQSConfig, namespace string) (string, string, error) {
	var accessKeyID, secretAccessKey string

	if sqsConfig.Credentials.AccessKeyIdSecretRef != nil {
		secret := &corev1.Secret{}
		key := client.ObjectKey{
			Name:      sqsConfig.Credentials.AccessKeyIdSecretRef.Name,
			Namespace: namespace,
		}
		if err := t.k8sClient.Get(ctx, key, secret); err != nil {
			return "", "", fmt.Errorf("failed to get access key secret: %w", err)
		}
		accessKeyID = string(secret.Data[sqsConfig.Credentials.AccessKeyIdSecretRef.Key])
	}

	if sqsConfig.Credentials.SecretAccessKeySecretRef != nil {
		secret := &corev1.Secret{}
		key := client.ObjectKey{
			Name:      sqsConfig.Credentials.SecretAccessKeySecretRef.Name,
			Namespace: namespace,
		}
		if err := t.k8sClient.Get(ctx, key, secret); err != nil {
			return "", "", fmt.Errorf("failed to get secret access key secret: %w", err)
		}
		secretAccessKey = string(secret.Data[sqsConfig.Credentials.SecretAccessKeySecretRef.Key])
	}

	return accessKeyID, secretAccessKey, nil
}

// forceDeleteQueue deletes an SQS queue by name
func (t *SQSTransport) forceDeleteQueue(ctx context.Context, sqsClient *sqs.Client, queueName string) error {
	logger := log.FromContext(ctx)

	urlResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(queueName),
	})
	if err != nil {
		logger.Info("Queue does not exist, skipping deletion", "queue", queueName)
		return nil
	}

	_, err = sqsClient.DeleteQueue(ctx, &sqs.DeleteQueueInput{
		QueueUrl: urlResult.QueueUrl,
	})
	if err != nil {
		return fmt.Errorf("failed to delete queue: %w", err)
	}

	logger.Info("SQS queue deleted", "queue", queueName)
	return nil
}

// ensureDLQ creates or retrieves the shared DLQ and returns its ARN
func (t *SQSTransport) ensureDLQ(ctx context.Context, sqsClient *sqs.Client, mainQueueName string, sqsConfig *asyaconfig.SQSConfig, actor *asyav1alpha1.AsyncActor) (string, error) {
	logger := log.FromContext(ctx)
	dlqName := "asya-dlq"

	// Check if DLQ already exists
	urlResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(dlqName),
	})

	if err == nil {
		// DLQ exists, get its ARN
		attrsResult, err := sqsClient.GetQueueAttributes(ctx, &sqs.GetQueueAttributesInput{
			QueueUrl: urlResult.QueueUrl,
			AttributeNames: []types.QueueAttributeName{
				types.QueueAttributeNameQueueArn,
			},
		})
		if err != nil {
			return "", fmt.Errorf("failed to get DLQ attributes: %w", err)
		}

		arn := attrsResult.Attributes[string(types.QueueAttributeNameQueueArn)]
		logger.V(1).Info("Shared DLQ already exists", "dlq", dlqName, "arn", arn)
		return arn, nil
	}

	var qne *types.QueueDoesNotExist
	if !errors.As(err, &qne) {
		return "", fmt.Errorf("failed to check for DLQ existence: %w", err)
	}

	// DLQ doesn't exist, create it
	retentionPeriod := strconv.Itoa(sqsConfig.Queues.DLQ.RetentionDays * 86400)

	// Shared DLQ tags
	tags := map[string]string{
		"asya.sh/type": "dlq",
	}
	for k, v := range sqsConfig.Tags {
		tags[k] = v
	}

	createResult, err := sqsClient.CreateQueue(ctx, &sqs.CreateQueueInput{
		QueueName: aws.String(dlqName),
		Attributes: map[string]string{
			"MessageRetentionPeriod": retentionPeriod,
		},
		Tags: tags,
	})
	if err != nil {
		return "", fmt.Errorf("failed to create DLQ: %w", err)
	}

	// Get ARN of the newly created DLQ
	attrsResult, err := sqsClient.GetQueueAttributes(ctx, &sqs.GetQueueAttributesInput{
		QueueUrl: createResult.QueueUrl,
		AttributeNames: []types.QueueAttributeName{
			types.QueueAttributeNameQueueArn,
		},
	})
	if err != nil {
		return "", fmt.Errorf("failed to get DLQ ARN: %w", err)
	}

	arn := attrsResult.Attributes[string(types.QueueAttributeNameQueueArn)]
	logger.Info("Shared DLQ created", "dlq", dlqName, "arn", arn)
	return arn, nil
}

// QueueExists checks if an SQS queue exists
func (t *SQSTransport) QueueExists(ctx context.Context, queueName, namespace string) (bool, error) {
	transport, err := t.transportRegistry.GetTransport("sqs")
	if err != nil {
		return false, err
	}

	sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		return false, fmt.Errorf("invalid SQS config type")
	}

	sqsClient, err := t.createSQSClient(ctx, sqsConfig, namespace)
	if err != nil {
		return false, fmt.Errorf("failed to create SQS client: %w", err)
	}

	// Try to get queue URL
	_, err = sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(queueName),
	})

	if err != nil {
		var qne *types.QueueDoesNotExist
		if errors.As(err, &qne) {
			return false, nil
		}
		return false, fmt.Errorf("failed to check queue existence: %w", err)
	}

	return true, nil
}
