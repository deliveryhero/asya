package transports

import (
	"context"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
)

// QueueReconciler handles queue creation and lifecycle for a specific transport
type QueueReconciler interface {
	// ReconcileQueue creates or updates the queue for an actor
	ReconcileQueue(ctx context.Context, actor *asyav1alpha1.AsyncActor) error

	// DeleteQueue deletes the queue for an actor
	DeleteQueue(ctx context.Context, actor *asyav1alpha1.AsyncActor) error

	// QueueExists checks if a queue exists
	// namespace parameter is used to look up transport credential secrets)
	QueueExists(ctx context.Context, queueName, namespace string) (bool, error)
}

// ServiceAccountReconciler handles ServiceAccount creation for transports that need it (e.g., SQS with IRSA)
type ServiceAccountReconciler interface {
	// ReconcileServiceAccount creates or updates ServiceAccount if needed
	ReconcileServiceAccount(ctx context.Context, actor *asyav1alpha1.AsyncActor) error
}
