package controller

import (
	"context"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/equality"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/event"
	"sigs.k8s.io/controller-runtime/pkg/predicate"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
)

func TestUpdateStatusWithRetry_SuccessFirstAttempt(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:       "test-actor",
			Namespace:  "default",
			Generation: 1,
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Scaling: asyav1alpha1.ScalingConfig{
				Enabled: false,
			},
		},
		Status: asyav1alpha1.AsyncActorStatus{
			Conditions: []metav1.Condition{
				{Type: "TransportReady", Status: metav1.ConditionTrue},
				{Type: "WorkloadReady", Status: metav1.ConditionTrue},
			},
		},
	}

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(asya).WithStatusSubresource(asya).Build()

	r := &AsyncActorReconciler{
		Client: fakeClient,
		Scheme: scheme,
	}

	err := r.updateStatusWithRetry(context.Background(), asya)
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if asya.Status.ObservedGeneration != 1 {
		t.Errorf("Expected ObservedGeneration=1, got %d", asya.Status.ObservedGeneration)
	}
}

func TestUpdateStatusWithRetry_ConflictRetry(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:            "test-actor",
			Namespace:       "default",
			Generation:      1,
			ResourceVersion: "1",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Scaling: asyav1alpha1.ScalingConfig{
				Enabled: false,
			},
		},
		Status: asyav1alpha1.AsyncActorStatus{
			Conditions: []metav1.Condition{
				{Type: "TransportReady", Status: metav1.ConditionTrue},
				{Type: "WorkloadReady", Status: metav1.ConditionTrue},
			},
		},
	}

	conflictClient := &conflictingClient{
		Client:          fake.NewClientBuilder().WithScheme(scheme).WithObjects(asya).WithStatusSubresource(asya).Build(),
		conflictOnFirst: true,
	}

	r := &AsyncActorReconciler{
		Client: conflictClient,
		Scheme: scheme,
	}

	err := r.updateStatusWithRetry(context.Background(), asya)
	if err != nil {
		t.Fatalf("Expected retry to succeed, got %v", err)
	}
}

func TestIgnoreReplicaOnlyChanges_IgnoresReplicaChanges(t *testing.T) {
	pred := predicate.Funcs{
		UpdateFunc: func(e event.UpdateEvent) bool {
			oldDep, oldOk := e.ObjectOld.(*appsv1.Deployment)
			newDep, newOk := e.ObjectNew.(*appsv1.Deployment)

			if !oldOk || !newOk {
				return true
			}

			oldSpec := oldDep.Spec.DeepCopy()
			newSpec := newDep.Spec.DeepCopy()

			oldSpec.Replicas = nil
			newSpec.Replicas = nil

			if equality.Semantic.DeepEqual(oldSpec, newSpec) {
				oldReplicas := int32(0)
				newReplicas := int32(0)
				if oldDep.Spec.Replicas != nil {
					oldReplicas = *oldDep.Spec.Replicas
				}
				if newDep.Spec.Replicas != nil {
					newReplicas = *newDep.Spec.Replicas
				}

				if oldReplicas != newReplicas {
					return false
				}
			}

			return true
		},
	}

	oldDep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-deployment",
			Namespace: "default",
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: ptr(int32(1)),
			Template: corev1.PodTemplateSpec{
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{Name: "test", Image: "test:latest"},
					},
				},
			},
		},
	}

	newDep := oldDep.DeepCopy()
	newDep.Spec.Replicas = ptr(int32(3))

	updateEvent := event.UpdateEvent{
		ObjectOld: oldDep,
		ObjectNew: newDep,
	}

	shouldReconcile := pred.Update(updateEvent)
	if shouldReconcile {
		t.Error("Expected predicate to return false (ignore) for replica-only changes")
	}
}

func TestIgnoreReplicaOnlyChanges_AllowsTemplateChanges(t *testing.T) {
	pred := predicate.Funcs{
		UpdateFunc: func(e event.UpdateEvent) bool {
			oldDep, oldOk := e.ObjectOld.(*appsv1.Deployment)
			newDep, newOk := e.ObjectNew.(*appsv1.Deployment)

			if !oldOk || !newOk {
				return true
			}

			oldSpec := oldDep.Spec.DeepCopy()
			newSpec := newDep.Spec.DeepCopy()

			oldSpec.Replicas = nil
			newSpec.Replicas = nil

			if equality.Semantic.DeepEqual(oldSpec, newSpec) {
				oldReplicas := int32(0)
				newReplicas := int32(0)
				if oldDep.Spec.Replicas != nil {
					oldReplicas = *oldDep.Spec.Replicas
				}
				if newDep.Spec.Replicas != nil {
					newReplicas = *newDep.Spec.Replicas
				}

				if oldReplicas != newReplicas {
					return false
				}
			}

			return true
		},
	}

	oldDep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-deployment",
			Namespace: "default",
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: ptr(int32(1)),
			Template: corev1.PodTemplateSpec{
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{Name: "test", Image: "test:v1"},
					},
				},
			},
		},
	}

	newDep := oldDep.DeepCopy()
	newDep.Spec.Template.Spec.Containers[0].Image = "test:v2"

	updateEvent := event.UpdateEvent{
		ObjectOld: oldDep,
		ObjectNew: newDep,
	}

	shouldReconcile := pred.Update(updateEvent)
	if !shouldReconcile {
		t.Error("Expected predicate to return true (reconcile) for template changes")
	}
}

func TestIgnoreReplicaOnlyChanges_AllowsReplicaAndTemplateChanges(t *testing.T) {
	pred := predicate.Funcs{
		UpdateFunc: func(e event.UpdateEvent) bool {
			oldDep, oldOk := e.ObjectOld.(*appsv1.Deployment)
			newDep, newOk := e.ObjectNew.(*appsv1.Deployment)

			if !oldOk || !newOk {
				return true
			}

			oldSpec := oldDep.Spec.DeepCopy()
			newSpec := newDep.Spec.DeepCopy()

			oldSpec.Replicas = nil
			newSpec.Replicas = nil

			if equality.Semantic.DeepEqual(oldSpec, newSpec) {
				oldReplicas := int32(0)
				newReplicas := int32(0)
				if oldDep.Spec.Replicas != nil {
					oldReplicas = *oldDep.Spec.Replicas
				}
				if newDep.Spec.Replicas != nil {
					newReplicas = *newDep.Spec.Replicas
				}

				if oldReplicas != newReplicas {
					return false
				}
			}

			return true
		},
	}

	oldDep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-deployment",
			Namespace: "default",
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: ptr(int32(1)),
			Template: corev1.PodTemplateSpec{
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{Name: "test", Image: "test:v1"},
					},
				},
			},
		},
	}

	newDep := oldDep.DeepCopy()
	newDep.Spec.Replicas = ptr(int32(3))
	newDep.Spec.Template.Spec.Containers[0].Image = "test:v2"

	updateEvent := event.UpdateEvent{
		ObjectOld: oldDep,
		ObjectNew: newDep,
	}

	shouldReconcile := pred.Update(updateEvent)
	if !shouldReconcile {
		t.Error("Expected predicate to return true (reconcile) when both replicas and template change")
	}
}

type conflictingClient struct {
	client.Client
	conflictOnFirst bool
	attemptCount    int
}

func (c *conflictingClient) Status() client.SubResourceWriter {
	return &conflictingStatusWriter{
		SubResourceWriter: c.Client.Status(),
		client:            c,
	}
}

type conflictingStatusWriter struct {
	client.SubResourceWriter
	client *conflictingClient
}

func (w *conflictingStatusWriter) Update(ctx context.Context, obj client.Object, opts ...client.SubResourceUpdateOption) error {
	w.client.attemptCount++

	if w.client.conflictOnFirst && w.client.attemptCount == 1 {
		return apierrors.NewConflict(
			schema.GroupResource{Group: "asya.sh", Resource: "asyncactors"},
			obj.GetName(),
			nil,
		)
	}

	return w.SubResourceWriter.Update(ctx, obj, opts...)
}
