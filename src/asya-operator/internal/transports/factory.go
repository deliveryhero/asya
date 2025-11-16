package transports

import (
	"fmt"

	"sigs.k8s.io/controller-runtime/pkg/client"

	asyaconfig "github.com/asya/operator/internal/config"
)

const (
	transportTypeSQS      = "sqs"
	transportTypeRabbitMQ = "rabbitmq"
)

// Factory creates transport-specific reconcilers
type Factory struct {
	k8sClient         client.Client
	transportRegistry *asyaconfig.TransportRegistry
}

// NewFactory creates a new transport factory
func NewFactory(k8sClient client.Client, registry *asyaconfig.TransportRegistry) *Factory {
	return &Factory{
		k8sClient:         k8sClient,
		transportRegistry: registry,
	}
}

// GetQueueReconciler returns a queue reconciler for the given transport type
func (f *Factory) GetQueueReconciler(transportType string) (QueueReconciler, error) {
	switch transportType {
	case transportTypeSQS:
		return NewSQSTransport(f.k8sClient, f.transportRegistry), nil
	case transportTypeRabbitMQ:
		return NewRabbitMQTransport(f.k8sClient, f.transportRegistry), nil
	default:
		return nil, fmt.Errorf("unsupported transport type: %s", transportType)
	}
}

// GetServiceAccountReconciler returns a ServiceAccount reconciler if the transport supports it
func (f *Factory) GetServiceAccountReconciler(transportType string) (ServiceAccountReconciler, error) {
	switch transportType {
	case transportTypeSQS:
		return NewSQSTransport(f.k8sClient, f.transportRegistry), nil
	case transportTypeRabbitMQ:
		return nil, nil
	default:
		return nil, fmt.Errorf("unsupported transport type: %s", transportType)
	}
}
