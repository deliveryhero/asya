package controller

import (
	"context"
	"fmt"
	"strings"

	autoscalingv2 "k8s.io/api/autoscaling/v2"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
	kedav1alpha1 "github.com/kedacore/keda/v2/apis/keda/v1alpha1"
)

// deleteScaledObject deletes the KEDA ScaledObject and TriggerAuthentication if they exist
func (r *AsyncActorReconciler) deleteScaledObject(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	// Delete ScaledObject by name without GET (avoids cache staleness issues)
	scaledObject := &kedav1alpha1.ScaledObject{
		ObjectMeta: metav1.ObjectMeta{
			Name:      asya.Name,
			Namespace: asya.Namespace,
		},
	}

	logger.Info("Deleting ScaledObject")
	err := r.Delete(ctx, scaledObject)
	if err != nil {
		if strings.Contains(err.Error(), "no matches for kind") {
			logger.V(1).Info("KEDA CRDs not installed, nothing to delete")
			return nil
		}
		if client.IgnoreNotFound(err) == nil {
			logger.V(1).Info("ScaledObject not found or already deleted")
			return nil
		}
		return fmt.Errorf("failed to delete ScaledObject: %w", err)
	}
	logger.Info("ScaledObject deleted successfully")

	// Delete TriggerAuthentication by name without GET (avoids garbage collection race)
	triggerAuth := &kedav1alpha1.TriggerAuthentication{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("%s-trigger-auth", asya.Name),
			Namespace: asya.Namespace,
		},
	}

	logger.Info("Deleting TriggerAuthentication")
	if err := r.Delete(ctx, triggerAuth); err != nil {
		if client.IgnoreNotFound(err) == nil {
			logger.V(1).Info("TriggerAuthentication not found or already deleted")
			return nil
		}
		return fmt.Errorf("failed to delete TriggerAuthentication: %w", err)
	}
	logger.Info("TriggerAuthentication deleted successfully")

	return nil
}

// reconcileScaledObject creates or updates a KEDA ScaledObject
func (r *AsyncActorReconciler) reconcileScaledObject(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	// Check if ScaledObject already exists and is up-to-date with current AsyncActor generation
	existingScaledObject := &kedav1alpha1.ScaledObject{}
	err := r.Get(ctx, client.ObjectKey{Name: asya.Name, Namespace: asya.Namespace}, existingScaledObject)
	if err != nil {
		if strings.Contains(err.Error(), "no matches for kind") {
			return fmt.Errorf("KEDA CRDs not installed: %w", err)
		}
		if client.IgnoreNotFound(err) != nil {
			return err
		}
	}
	if err == nil {
		// ScaledObject exists - check ownership before proceeding
		hasCorrectOwner := false
		for _, ownerRef := range existingScaledObject.OwnerReferences {
			if ownerRef.Controller != nil && *ownerRef.Controller &&
				ownerRef.UID == asya.UID {
				hasCorrectOwner = true
				break
			}
		}

		if !hasCorrectOwner {
			logger.Info("Found existing ScaledObject with incorrect ownership, deleting to recreate", "name", existingScaledObject.Name)
			if err := r.Delete(ctx, existingScaledObject); err != nil {
				return fmt.Errorf("failed to delete ScaledObject with incorrect ownership: %w", err)
			}
			logger.Info("Deleted ScaledObject with incorrect ownership, will recreate")
		} else {
			// Has correct owner, check if it matches current AsyncActor generation
			if existingScaledObject.Annotations != nil {
				if sourceGen, ok := existingScaledObject.Annotations["asya.sh/source-generation"]; ok {
					if sourceGen == fmt.Sprintf("%d", asya.Generation) {
						logger.V(1).Info("ScaledObject already up-to-date, skipping reconciliation", "generation", asya.Generation)
						return nil
					}
				}
			}
		}
	}

	// Build triggers only when needed (ScaledObject doesn't exist or AsyncActor generation changed)
	logger.V(1).Info("Building KEDA triggers", "generation", asya.Generation)
	triggers, err := r.buildKEDATriggers(ctx, asya)
	if err != nil {
		return fmt.Errorf("failed to build KEDA triggers: %w", err)
	}

	// Build advanced scaling config with HPA behavior to prevent thrashing
	stabilizationWindowSeconds := int32(300)
	selectPolicy := autoscalingv2.MaxChangePolicySelect
	advanced := &kedav1alpha1.AdvancedConfig{
		HorizontalPodAutoscalerConfig: &kedav1alpha1.HorizontalPodAutoscalerConfig{
			Behavior: &autoscalingv2.HorizontalPodAutoscalerBehavior{
				ScaleDown: &autoscalingv2.HPAScalingRules{
					StabilizationWindowSeconds: &stabilizationWindowSeconds,
					SelectPolicy:               &selectPolicy,
					Policies: []autoscalingv2.HPAScalingPolicy{
						{
							Type:          autoscalingv2.PodsScalingPolicy,
							Value:         1,
							PeriodSeconds: 60,
						},
					},
				},
				ScaleUp: &autoscalingv2.HPAScalingRules{
					StabilizationWindowSeconds: func() *int32 { v := int32(0); return &v }(),
					SelectPolicy:               &selectPolicy,
					Policies: []autoscalingv2.HPAScalingPolicy{
						{
							Type:          autoscalingv2.PodsScalingPolicy,
							Value:         10,
							PeriodSeconds: 60,
						},
						{
							Type:          autoscalingv2.PercentScalingPolicy,
							Value:         100,
							PeriodSeconds: 60,
						},
					},
				},
			},
		},
	}

	if asya.Spec.Scaling.Advanced != nil {
		advanced.RestoreToOriginalReplicaCount = asya.Spec.Scaling.Advanced.RestoreToOriginalReplicaCount

		// Build scaling modifiers
		scalingModifiers := kedav1alpha1.ScalingModifiers{}
		if asya.Spec.Scaling.Advanced.Formula != "" {
			scalingModifiers.Formula = asya.Spec.Scaling.Advanced.Formula
		}
		if asya.Spec.Scaling.Advanced.Target != "" {
			scalingModifiers.Target = asya.Spec.Scaling.Advanced.Target
		}
		if asya.Spec.Scaling.Advanced.ActivationTarget != "" {
			scalingModifiers.ActivationTarget = asya.Spec.Scaling.Advanced.ActivationTarget
		}
		if asya.Spec.Scaling.Advanced.MetricType != "" {
			scalingModifiers.MetricType = r.parseMetricType(asya.Spec.Scaling.Advanced.MetricType)
		}

		advanced.ScalingModifiers = scalingModifiers
	}

	scaledObject := &kedav1alpha1.ScaledObject{
		ObjectMeta: metav1.ObjectMeta{
			Name:      asya.Name,
			Namespace: asya.Namespace,
		},
	}

	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, scaledObject, func() error {
		// Set owner reference
		if err := controllerutil.SetControllerReference(asya, scaledObject, r.Scheme); err != nil {
			return err
		}

		// Track AsyncActor generation to avoid unnecessary trigger rebuilds
		if scaledObject.Annotations == nil {
			scaledObject.Annotations = make(map[string]string)
		}
		scaledObject.Annotations["asya.sh/source-generation"] = fmt.Sprintf("%d", asya.Generation)

		// Set scaling target
		scaledObject.Spec.ScaleTargetRef = &kedav1alpha1.ScaleTarget{
			Name: asya.Name,
		}

		// Set min/max replicas
		minReplicas := int32(0)
		if asya.Spec.Scaling.MinReplicas != nil {
			minReplicas = *asya.Spec.Scaling.MinReplicas
		}
		scaledObject.Spec.MinReplicaCount = &minReplicas

		maxReplicas := int32(50)
		if asya.Spec.Scaling.MaxReplicas != nil {
			maxReplicas = *asya.Spec.Scaling.MaxReplicas
		}
		scaledObject.Spec.MaxReplicaCount = &maxReplicas

		// Set polling and cooldown
		pollingInterval := int32(10)
		if asya.Spec.Scaling.PollingInterval > 0 {
			pollingInterval = int32(asya.Spec.Scaling.PollingInterval)
		}
		scaledObject.Spec.PollingInterval = &pollingInterval

		cooldownPeriod := int32(300) // default 5 min
		if asya.Spec.Scaling.CooldownPeriod > 0 {
			cooldownPeriod = int32(asya.Spec.Scaling.CooldownPeriod)
		}
		scaledObject.Spec.CooldownPeriod = &cooldownPeriod

		// Set triggers (built outside this function)
		scaledObject.Spec.Triggers = triggers

		// Set advanced scaling config (built outside this function)
		if advanced != nil {
			scaledObject.Spec.Advanced = advanced
		}

		return nil
	})

	if err != nil {
		return err
	}

	logger.Info("ScaledObject reconciled", "result", result)

	// Update status
	asya.Status.ScaledObjectRef = &asyav1alpha1.NamespacedName{
		Name:      scaledObject.Name,
		Namespace: scaledObject.Namespace,
	}

	return nil
}

// resolveQueueIdentifier resolves actor name to queue identifier based on transport
func (r *AsyncActorReconciler) resolveQueueIdentifier(asya *asyav1alpha1.AsyncActor, transport *asyaconfig.TransportConfig) (string, error) {
	switch transport.Type {
	case transportTypeRabbitMQ:
		return fmt.Sprintf("asya-%s", asya.Name), nil
	case transportTypeSQS:
		return fmt.Sprintf("asya-%s", asya.Name), nil
	default:
		return asya.Name, nil
	}
}

// buildKEDATriggers builds KEDA triggers based on transport type
func (r *AsyncActorReconciler) buildKEDATriggers(ctx context.Context, asya *asyav1alpha1.AsyncActor) ([]kedav1alpha1.ScaleTriggers, error) {
	queueLength := "5"
	if asya.Spec.Scaling.QueueLength > 0 {
		queueLength = fmt.Sprintf("%d", asya.Spec.Scaling.QueueLength)
	}

	// Get transport config from registry
	transport, err := r.TransportRegistry.GetTransport(asya.Spec.Transport)
	if err != nil {
		return nil, fmt.Errorf("failed to get transport config: %w", err)
	}

	switch transport.Type {
	case transportTypeSQS:
		return r.buildSQSTrigger(asya, transport, queueLength)
	case transportTypeRabbitMQ:
		return r.buildRabbitMQTrigger(ctx, asya, transport, queueLength)
	default:
		return nil, fmt.Errorf("unsupported transport type: %s", transport.Type)
	}
}

// buildSQSTrigger builds an SQS KEDA trigger
func (r *AsyncActorReconciler) buildSQSTrigger(asya *asyav1alpha1.AsyncActor, transport *asyaconfig.TransportConfig, queueLength string) ([]kedav1alpha1.ScaleTriggers, error) {
	config, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		return nil, fmt.Errorf("invalid config type for SQS transport")
	}

	if config.Region == "" {
		return nil, fmt.Errorf("SQS region is required in operator transport config")
	}

	if config.AccountID == "" {
		return nil, fmt.Errorf("SQS accountId is required in operator transport config")
	}

	queueName := fmt.Sprintf("asya-%s", asya.Name)

	metadata := map[string]string{
		"queueLength": queueLength,
		"awsRegion":   config.Region,
	}

	var queueURL string
	if config.Endpoint != "" {
		queueURL = fmt.Sprintf("%s/%s/%s", config.Endpoint, config.AccountID, queueName)
		metadata["awsEndpoint"] = config.Endpoint
	} else {
		queueURL = fmt.Sprintf("https://sqs.%s.amazonaws.com/%s/%s", config.Region, config.AccountID, queueName)
	}
	metadata["queueURL"] = queueURL

	trigger := kedav1alpha1.ScaleTriggers{
		Type:     "aws-sqs-queue",
		Metadata: metadata,
	}

	if config.Credentials != nil && (config.Credentials.AccessKeyIdSecretRef != nil || config.Credentials.SecretAccessKeySecretRef != nil) {
		trigger.AuthenticationRef = &kedav1alpha1.AuthenticationRef{
			Name: fmt.Sprintf("%s-trigger-auth", asya.Name),
		}

		if err := r.reconcileTriggerAuthentication(context.Background(), asya, transport); err != nil {
			return nil, err
		}
	} else {
		metadata["identityOwner"] = "pod"
	}

	return []kedav1alpha1.ScaleTriggers{trigger}, nil
}

// buildRabbitMQTrigger builds a RabbitMQ KEDA trigger
func (r *AsyncActorReconciler) buildRabbitMQTrigger(ctx context.Context, asya *asyav1alpha1.AsyncActor, transport *asyaconfig.TransportConfig, queueLength string) ([]kedav1alpha1.ScaleTriggers, error) {
	logger := log.FromContext(ctx)

	config, ok := transport.Config.(*asyaconfig.RabbitMQConfig)
	if !ok {
		return nil, fmt.Errorf("invalid config type for RabbitMQ transport")
	}

	if config.Host == "" {
		return nil, fmt.Errorf("RabbitMQ host is required in operator transport config")
	}

	port := config.Port
	if port == 0 {
		return nil, fmt.Errorf("RabbitMQ port is required in operator transport config")
	}

	username := config.Username
	if username == "" {
		return nil, fmt.Errorf("RabbitMQ username is required in operator transport config")
	}

	queueName, err := r.resolveQueueIdentifier(asya, transport)
	if err != nil {
		return nil, err
	}

	var hostStr string
	triggerMetadata := map[string]string{
		"queueName": queueName,
		"mode":      "QueueLength",
		"value":     queueLength,
		"protocol":  "amqp",
	}

	if config.PasswordSecretRef != nil {
		hostStr = fmt.Sprintf("amqp://%s:%d", config.Host, port)
		triggerMetadata["host"] = hostStr
		logger.V(1).Info("Using TriggerAuthentication for RabbitMQ credentials", "host", hostStr, "actor", asya.Name)
	} else {
		hostStr = fmt.Sprintf("amqp://%s@%s:%d", username, config.Host, port)
		triggerMetadata["host"] = hostStr
		logger.V(1).Info("Using inline credentials in host URL", "host", hostStr, "actor", asya.Name)
	}

	trigger := kedav1alpha1.ScaleTriggers{
		Type:     "rabbitmq",
		Metadata: triggerMetadata,
	}

	if config.PasswordSecretRef != nil {
		trigger.AuthenticationRef = &kedav1alpha1.AuthenticationRef{
			Name: fmt.Sprintf("%s-trigger-auth", asya.Name),
		}

		if err := r.reconcileTriggerAuthentication(context.Background(), asya, transport); err != nil {
			return nil, err
		}
	}

	return []kedav1alpha1.ScaleTriggers{trigger}, nil
}

// reconcileTriggerAuthentication creates or updates a KEDA TriggerAuthentication
func (r *AsyncActorReconciler) reconcileTriggerAuthentication(ctx context.Context, asya *asyav1alpha1.AsyncActor, transport *asyaconfig.TransportConfig) error {
	logger := log.FromContext(ctx)

	triggerAuth := &kedav1alpha1.TriggerAuthentication{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("%s-trigger-auth", asya.Name),
			Namespace: asya.Namespace,
		},
	}

	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, triggerAuth, func() error {
		if err := controllerutil.SetControllerReference(asya, triggerAuth, r.Scheme); err != nil {
			return err
		}

		switch transport.Type {
		case transportTypeSQS:
			sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
			if !ok {
				return fmt.Errorf("invalid config type for SQS transport")
			}

			if sqsConfig.Credentials != nil {
				var secretTargetRef []kedav1alpha1.AuthSecretTargetRef

				if sqsConfig.Credentials.AccessKeyIdSecretRef != nil {
					secretTargetRef = append(secretTargetRef, kedav1alpha1.AuthSecretTargetRef{
						Parameter: "awsAccessKeyID",
						Name:      sqsConfig.Credentials.AccessKeyIdSecretRef.Name,
						Key:       sqsConfig.Credentials.AccessKeyIdSecretRef.Key,
					})
					logger.V(1).Info("Configuring SQS TriggerAuthentication with AWS Access Key ID from secret",
						"secret", sqsConfig.Credentials.AccessKeyIdSecretRef.Name,
						"key", sqsConfig.Credentials.AccessKeyIdSecretRef.Key,
						"actor", asya.Name)
				}

				if sqsConfig.Credentials.SecretAccessKeySecretRef != nil {
					secretTargetRef = append(secretTargetRef, kedav1alpha1.AuthSecretTargetRef{
						Parameter: "awsSecretAccessKey",
						Name:      sqsConfig.Credentials.SecretAccessKeySecretRef.Name,
						Key:       sqsConfig.Credentials.SecretAccessKeySecretRef.Key,
					})
					logger.V(1).Info("Configuring SQS TriggerAuthentication with AWS Secret Access Key from secret",
						"secret", sqsConfig.Credentials.SecretAccessKeySecretRef.Name,
						"key", sqsConfig.Credentials.SecretAccessKeySecretRef.Key,
						"actor", asya.Name)
				}

				triggerAuth.Spec.SecretTargetRef = secretTargetRef
			} else {
				triggerAuth.Spec.PodIdentity = &kedav1alpha1.AuthPodIdentity{
					Provider: "aws",
				}
			}

		case transportTypeRabbitMQ:
			config, ok := transport.Config.(*asyaconfig.RabbitMQConfig)
			if !ok {
				return fmt.Errorf("invalid config type for RabbitMQ transport")
			}

			if config.PasswordSecretRef != nil {
				logger.V(1).Info("Configuring RabbitMQ TriggerAuthentication with username and password",
					"secret", config.PasswordSecretRef.Name,
					"passwordKey", config.PasswordSecretRef.Key,
					"username", config.Username,
					"actor", asya.Name)

				var secretTargetRef []kedav1alpha1.AuthSecretTargetRef

				secretTargetRef = append(secretTargetRef, kedav1alpha1.AuthSecretTargetRef{
					Parameter: "username",
					Name:      config.PasswordSecretRef.Name,
					Key:       "username",
				})

				secretTargetRef = append(secretTargetRef, kedav1alpha1.AuthSecretTargetRef{
					Parameter: "password",
					Name:      config.PasswordSecretRef.Name,
					Key:       config.PasswordSecretRef.Key,
				})

				triggerAuth.Spec.SecretTargetRef = secretTargetRef
			}
		}

		return nil
	})

	if err != nil {
		return err
	}

	logger.Info("TriggerAuthentication reconciled", "result", result)

	return nil
}

// parseMetricType converts a string to autoscaling MetricTargetType
func (r *AsyncActorReconciler) parseMetricType(metricType string) autoscalingv2.MetricTargetType {
	switch metricType {
	case "AverageValue":
		return autoscalingv2.AverageValueMetricType
	case "Value":
		return autoscalingv2.ValueMetricType
	case "Utilization":
		return autoscalingv2.UtilizationMetricType
	default:
		return autoscalingv2.AverageValueMetricType
	}
}
