//go:build integration

package controller

import (
	"context"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
)

// ReconcileRuntimeConfigMap is a test helper that exposes the private reconcileRuntimeConfigMap method
// for integration/component tests.
func (r *AsyncActorReconciler) ReconcileRuntimeConfigMap(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	return r.reconcileRuntimeConfigMap(ctx, asya)
}
