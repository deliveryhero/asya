package controller

import (
	"context"
	"fmt"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	kedav1alpha1 "github.com/kedacore/keda/v2/apis/keda/v1alpha1"
)

// reconcileScaledObject creates or updates a KEDA ScaledObject
func (r *AsyncActorReconciler) reconcileScaledObject(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

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

		cooldownPeriod := int32(60)
		if asya.Spec.Scaling.CooldownPeriod > 0 {
			cooldownPeriod = int32(asya.Spec.Scaling.CooldownPeriod)
		}
		scaledObject.Spec.CooldownPeriod = &cooldownPeriod

		// Build triggers based on transport type
		triggers, err := r.buildKEDATriggers(asya)
		if err != nil {
			return err
		}
		scaledObject.Spec.Triggers = triggers

		// Set advanced HPA config
		// Note: Advanced HPA behavior config not available in this KEDA version
		// scaledObject.Spec.Advanced = &kedav1alpha1.AdvancedConfig{...}

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

// buildKEDATriggers builds KEDA triggers based on transport type
func (r *AsyncActorReconciler) buildKEDATriggers(asya *asyav1alpha1.AsyncActor) ([]kedav1alpha1.ScaleTriggers, error) {
	queueLength := "5"
	if asya.Spec.Scaling.QueueLength > 0 {
		queueLength = fmt.Sprintf("%d", asya.Spec.Scaling.QueueLength)
	}

	switch asya.Spec.Transport.Type {
	case "sqs":
		return r.buildSQSTrigger(asya, queueLength)
	case "rabbitmq":
		return r.buildRabbitMQTrigger(asya, queueLength)
	default:
		return nil, fmt.Errorf("unsupported transport type: %s", asya.Spec.Transport.Type)
	}
}

// buildSQSTrigger builds an SQS KEDA trigger
func (r *AsyncActorReconciler) buildSQSTrigger(asya *asyav1alpha1.AsyncActor, queueLength string) ([]kedav1alpha1.ScaleTriggers, error) {
	if asya.Spec.Transport.SQS == nil {
		return nil, fmt.Errorf("SQS config is required for SQS transport")
	}

	region := "us-east-1"
	if asya.Spec.Transport.SQS.Region != "" {
		region = asya.Spec.Transport.SQS.Region
	}

	// Build queue URL
	queueURL := ""
	if asya.Spec.Transport.SQS.QueueBaseURL != "" {
		queueURL = fmt.Sprintf("%s/%s", asya.Spec.Transport.SQS.QueueBaseURL, asya.Spec.QueueName)
	}

	trigger := kedav1alpha1.ScaleTriggers{
		Type: "aws-sqs-queue",
		Metadata: map[string]string{
			"queueURL":      queueURL,
			"queueLength":   queueLength,
			"awsRegion":     region,
			"identityOwner": "pod",
		},
	}

	return []kedav1alpha1.ScaleTriggers{trigger}, nil
}

// buildRabbitMQTrigger builds a RabbitMQ KEDA trigger
func (r *AsyncActorReconciler) buildRabbitMQTrigger(asya *asyav1alpha1.AsyncActor, queueLength string) ([]kedav1alpha1.ScaleTriggers, error) {
	if asya.Spec.Transport.RabbitMQ == nil {
		return nil, fmt.Errorf("RabbitMQ config is required for RabbitMQ transport")
	}

	host := asya.Spec.Transport.RabbitMQ.Host
	if host == "" {
		host = "rabbitmq.rabbitmq.svc.cluster.local"
	}

	port := 5672
	if asya.Spec.Transport.RabbitMQ.Port > 0 {
		port = asya.Spec.Transport.RabbitMQ.Port
	}

	// Build host connection string
	username := asya.Spec.Transport.RabbitMQ.Username
	if username == "" {
		username = "guest"
	}

	hostStr := fmt.Sprintf("amqp://%s@%s:%d", username, host, port)

	trigger := kedav1alpha1.ScaleTriggers{
		Type: "rabbitmq",
		Metadata: map[string]string{
			"queueName": asya.Spec.QueueName,
			"mode":      "QueueLength",
			"value":     queueLength,
			"protocol":  "amqp",
			"host":      hostStr,
		},
	}

	// Add authentication if password secret is provided
	if asya.Spec.Transport.RabbitMQ.PasswordSecretRef != nil {
		trigger.AuthenticationRef = &kedav1alpha1.AuthenticationRef{
			Name: fmt.Sprintf("%s-trigger-auth", asya.Name),
		}

		// Create TriggerAuthentication
		if err := r.reconcileTriggerAuthentication(context.Background(), asya); err != nil {
			return nil, err
		}
	}

	return []kedav1alpha1.ScaleTriggers{trigger}, nil
}

// reconcileTriggerAuthentication creates or updates a KEDA TriggerAuthentication
func (r *AsyncActorReconciler) reconcileTriggerAuthentication(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	triggerAuth := &kedav1alpha1.TriggerAuthentication{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("%s-trigger-auth", asya.Name),
			Namespace: asya.Namespace,
		},
	}

	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, triggerAuth, func() error {
		// Set owner reference
		if err := controllerutil.SetControllerReference(asya, triggerAuth, r.Scheme); err != nil {
			return err
		}

		switch asya.Spec.Transport.Type {
		case "sqs":
			// AWS credentials from environment or IAM role
			// For simplicity, using pod identity
			triggerAuth.Spec.PodIdentity = &kedav1alpha1.AuthPodIdentity{
				Provider: "aws",
			}

		case "rabbitmq":
			if asya.Spec.Transport.RabbitMQ != nil && asya.Spec.Transport.RabbitMQ.PasswordSecretRef != nil {
				triggerAuth.Spec.SecretTargetRef = []kedav1alpha1.AuthSecretTargetRef{
					{
						Parameter: "host",
						Name:      asya.Spec.Transport.RabbitMQ.PasswordSecretRef.Name,
						Key:       "host",
					},
				}
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

// Helper functions

func int32Ptr(i int32) *int32 {
	return &i
}

func stringPtr(s string) *string {
	return &s
}
