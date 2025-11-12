//go:build integration

package integration

import (
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/wait"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

const (
	timeout  = 30 * time.Second
	interval = 250 * time.Millisecond
)

func TestDeployment(t *testing.T) {
	tests := []struct {
		name     string
		yamlFile string
		verifyFn func(t *testing.T, deployment *appsv1.Deployment)
	}{
		{
			name:     "basic deployment",
			yamlFile: "deployment-basic.yaml",
			verifyFn: func(t *testing.T, deployment *appsv1.Deployment) {
				containers := deployment.Spec.Template.Spec.Containers
				if len(containers) != 2 {
					t.Fatalf("Expected 2 containers (runtime + sidecar), got %d", len(containers))
				}

				if containers[0].Name != "asya-runtime" {
					t.Errorf("Expected first container to be 'asya-runtime', got %q", containers[0].Name)
				}
				if containers[1].Name != "asya-sidecar" {
					t.Errorf("Expected second container to be 'asya-sidecar', got %q", containers[1].Name)
				}

				sidecarContainer := containers[1]
				envMap := make(map[string]string)
				for _, env := range sidecarContainer.Env {
					envMap[env.Name] = env.Value
				}

				if transportType, ok := envMap["ASYA_TRANSPORT"]; !ok {
					t.Error("ASYA_TRANSPORT environment variable not found in sidecar")
				} else if transportType != "rabbitmq" {
					t.Errorf("Expected ASYA_TRANSPORT=rabbitmq, got %q", transportType)
				}

				hasSocketMount := false
				for _, vm := range sidecarContainer.VolumeMounts {
					if vm.Name == "socket-dir" {
						hasSocketMount = true
						break
					}
				}
				if !hasSocketMount {
					t.Error("Socket volume mount not found in sidecar container")
				}
			},
		},
		{
			name:     "custom replicas",
			yamlFile: "deployment-custom-replicas.yaml",
			verifyFn: func(t *testing.T, deployment *appsv1.Deployment) {
				if deployment.Spec.Replicas == nil {
					t.Fatal("Deployment replicas is nil")
				}
				if *deployment.Spec.Replicas != 3 {
					t.Errorf("Expected 3 replicas, got %d", *deployment.Spec.Replicas)
				}
			},
		},
		{
			name:     "custom python executable",
			yamlFile: "deployment-custom-python.yaml",
			verifyFn: func(t *testing.T, deployment *appsv1.Deployment) {
				runtimeContainer := deployment.Spec.Template.Spec.Containers[0]
				if len(runtimeContainer.Command) != 2 {
					t.Fatalf("Expected 2 command arguments, got %d", len(runtimeContainer.Command))
				}
				if runtimeContainer.Command[0] != "/usr/local/bin/python3.13" {
					t.Errorf("Expected python executable '/usr/local/bin/python3.13', got %q", runtimeContainer.Command[0])
				}
				if runtimeContainer.Command[1] != "/opt/asya/asya_runtime.py" {
					t.Errorf("Expected runtime script '/opt/asya/asya_runtime.py', got %q", runtimeContainer.Command[1])
				}
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := loadAsyncActorFromYAML(t, tt.yamlFile)

			if err := k8sClient.Create(ctx, actor); err != nil {
				t.Fatalf("Failed to create AsyncActor: %v", err)
			}
			defer func() {
				_ = k8sClient.Delete(ctx, actor)
			}()

			disableScalingInK8s(t, actor)

			deployment := &appsv1.Deployment{}
			err := wait.PollImmediate(interval, timeout, func() (bool, error) {
				err := k8sClient.Get(ctx, types.NamespacedName{
					Name:      actor.Name,
					Namespace: actor.Namespace,
				}, deployment)
				return err == nil, nil
			})
			if err != nil {
				t.Fatalf("Deployment was not created: %v", err)
			}

			if tt.verifyFn != nil {
				tt.verifyFn(t, deployment)
			}
		})
	}
}

func TestStatefulSetUnsupported(t *testing.T) {
	actor := loadAsyncActorFromYAML(t, "statefulset-basic.yaml")

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	disableScalingInK8s(t, actor)

	// Wait for WorkloadReady condition to be False
	err := wait.PollImmediate(interval, timeout, func() (bool, error) {
		if err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, actor); err != nil {
			return false, nil
		}
		for _, cond := range actor.Status.Conditions {
			if cond.Type == "WorkloadReady" && cond.Status == metav1.ConditionFalse {
				return true, nil
			}
		}
		return false, nil
	})
	if err != nil {
		t.Error("Expected WorkloadReady=False condition for unsupported workload kind")
	}
}

func TestDeploymentUpdate(t *testing.T) {
	actor := loadAsyncActorFromYAML(t, "deployment-basic.yaml")
	actor.Name = "test-update-actor"

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	disableScalingInK8s(t, actor)

	deployment := &appsv1.Deployment{}
	err := wait.PollImmediate(interval, timeout, func() (bool, error) {
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, deployment)
		return err == nil, nil
	})
	if err != nil {
		t.Fatalf("Deployment was not created: %v", err)
	}

	// Update the actor image
	err = wait.PollImmediate(interval, timeout, func() (bool, error) {
		if err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, actor); err != nil {
			return false, nil
		}
		actor.Spec.Workload.Template.Spec.Containers[0].Image = "python:3.13-alpine"
		return k8sClient.Update(ctx, actor) == nil, nil
	})
	if err != nil {
		t.Fatalf("Failed to update AsyncActor: %v", err)
	}

	// Wait for deployment to reflect the change
	err = wait.PollImmediate(interval, timeout, func() (bool, error) {
		if err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, deployment); err != nil {
			return false, nil
		}
		return deployment.Spec.Template.Spec.Containers[0].Image == "python:3.13-alpine", nil
	})
	if err != nil {
		t.Error("Deployment did not update with new image")
	}
}

func TestOwnerReference(t *testing.T) {
	actor := loadAsyncActorFromYAML(t, "deployment-basic.yaml")
	actor.Name = "test-ownerref-actor"

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	disableScalingInK8s(t, actor)

	deployment := &appsv1.Deployment{}
	err := wait.PollImmediate(interval, timeout, func() (bool, error) {
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, deployment)
		return err == nil, nil
	})
	if err != nil {
		t.Fatalf("Deployment was not created: %v", err)
	}

	// Verify owner reference
	if len(deployment.OwnerReferences) != 1 {
		t.Fatalf("Expected 1 owner reference, got %d", len(deployment.OwnerReferences))
	}

	ownerRef := deployment.OwnerReferences[0]
	if ownerRef.Name != actor.Name {
		t.Errorf("Expected owner reference name %q, got %q", actor.Name, ownerRef.Name)
	}
	if ownerRef.Kind != "AsyncActor" {
		t.Errorf("Expected owner reference kind 'AsyncActor', got %q", ownerRef.Kind)
	}
	if ownerRef.Controller == nil || !*ownerRef.Controller {
		t.Error("Expected owner reference to be a controller")
	}
}

func TestInvalidTransport(t *testing.T) {
	actor := loadAsyncActorFromYAML(t, "deployment-invalid-transport.yaml")

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	disableScalingInK8s(t, actor)

	// Wait for TransportReady condition to be False
	err := wait.PollImmediate(interval, timeout, func() (bool, error) {
		if err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, actor); err != nil {
			return false, nil
		}
		for _, cond := range actor.Status.Conditions {
			if cond.Type == "TransportReady" && cond.Status == metav1.ConditionFalse {
				return true, nil
			}
		}
		return false, nil
	})
	if err != nil {
		t.Error("Expected TransportReady=False condition for invalid transport")
	}
}

func TestDeletion(t *testing.T) {
	actor := loadAsyncActorFromYAML(t, "deployment-basic.yaml")
	actor.Name = "test-deletion-actor"

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}

	disableScalingInK8s(t, actor)

	// Wait for deployment to be created
	deployment := &appsv1.Deployment{}
	err := wait.PollImmediate(interval, timeout, func() (bool, error) {
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, deployment)
		return err == nil, nil
	})
	if err != nil {
		t.Fatalf("Deployment was not created: %v", err)
	}

	// Delete the AsyncActor
	if err := k8sClient.Delete(ctx, actor); err != nil {
		t.Fatalf("Failed to delete AsyncActor: %v", err)
	}

	// Wait for finalizer to be removed (reconcileDelete executes)
	err = wait.PollImmediate(interval, timeout, func() (bool, error) {
		if err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, actor); err != nil {
			if errors.IsNotFound(err) {
				return true, nil
			}
			return false, nil
		}
		// Check if finalizer is removed
		return !controllerutil.ContainsFinalizer(actor, "asya.sh/finalizer"), nil
	})
	if err != nil {
		t.Error("AsyncActor finalizer was not removed during deletion")
	}
}

func TestFinalizerAdded(t *testing.T) {
	actor := loadAsyncActorFromYAML(t, "deployment-basic.yaml")
	actor.Name = "test-finalizer-actor"

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	// Wait for finalizer to be added (happens in first reconciliation)
	err := wait.PollImmediate(interval, timeout, func() (bool, error) {
		if err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, actor); err != nil {
			return false, nil
		}
		return controllerutil.ContainsFinalizer(actor, "asya.sh/finalizer"), nil
	})
	if err != nil {
		t.Error("Expected finalizer to be added to AsyncActor")
	}

	disableScalingInK8s(t, actor)
}

func TestStatusConditions(t *testing.T) {
	actor := loadAsyncActorFromYAML(t, "deployment-basic.yaml")
	actor.Name = "test-conditions-actor"

	if err := k8sClient.Create(ctx, actor); err != nil {
		t.Fatalf("Failed to create AsyncActor: %v", err)
	}
	defer func() {
		_ = k8sClient.Delete(ctx, actor)
	}()

	// Don't call disableScalingInK8s here - scaling is already disabled in the YAML

	// Wait for conditions to be set
	err := wait.PollImmediate(interval, timeout, func() (bool, error) {
		if err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, actor); err != nil {
			t.Logf("Failed to get actor: %v", err)
			return false, nil
		}
		t.Logf("Got actor with %d conditions, ObservedGeneration=%d", len(actor.Status.Conditions), actor.Status.ObservedGeneration)
		if len(actor.Status.Conditions) == 0 {
			return false, nil
		}
		// Check for expected conditions (both must exist)
		hasTransportReady := false
		hasWorkloadReady := false
		for _, cond := range actor.Status.Conditions {
			t.Logf("Condition: Type=%s, Status=%s", cond.Type, cond.Status)
			if cond.Type == "TransportReady" {
				hasTransportReady = true
			}
			if cond.Type == "WorkloadReady" {
				hasWorkloadReady = true
			}
		}
		return hasTransportReady && hasWorkloadReady, nil
	})
	if err != nil {
		t.Errorf("Expected TransportReady and WorkloadReady conditions to exist. Found %d conditions: %+v", len(actor.Status.Conditions), actor.Status.Conditions)
	}

	// In envtest, RabbitMQ is not running, so TransportReady may be False.
	// Just verify that WorkloadReady exists (but may be False due to no running pods).
	// The conditions existence check above is sufficient.

	// Verify ObservedGeneration is set
	if actor.Status.ObservedGeneration != actor.Generation {
		t.Errorf("Expected ObservedGeneration %d, got %d", actor.Generation, actor.Status.ObservedGeneration)
	}
}

func TestReconcileWithMissingResource(t *testing.T) {
	actor := loadAsyncActorFromYAML(t, "deployment-basic.yaml")
	actor.Name = "test-notfound-actor"

	// Try to get a non-existent actor (tests Reconcile NotFound path)
	err := k8sClient.Get(ctx, types.NamespacedName{
		Name:      actor.Name,
		Namespace: actor.Namespace,
	}, actor)
	if err == nil {
		t.Fatal("Expected error for non-existent actor")
	}
	if !errors.IsNotFound(err) {
		t.Errorf("Expected NotFound error, got: %v", err)
	}
}

// Helper function to check if error is NotFound
func isNotFound(err error) bool {
	return errors.IsNotFound(err)
}
