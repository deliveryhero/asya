package controller

import (
	"context"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
)

const (
	actorFinalizer    = "asya.io/finalizer"
	sidecarName       = "sidecar"
	socketVolume      = "socket-dir"
	tmpVolume         = "tmp"
	runtimeVolume     = "asya-runtime"
	runtimeConfigMap  = "asya-runtime"
	runtimeMountPath  = "/opt/asya"
	runtimeScriptPath = "/opt/asya/asya_runtime.py"
)

// AsyncActorReconciler reconciles an AsyncActor object
type AsyncActorReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=asya.io,resources=asyncactors,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=asya.io,resources=asyncactors/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=asya.io,resources=asyncactors/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=apps,resources=statefulsets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=batch,resources=jobs,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=keda.sh,resources=scaledobjects,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=keda.sh,resources=triggerauthentications,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete

// Reconcile is the main reconciliation loop
func (r *AsyncActorReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	// Fetch the AsyncActor instance
	asya := &asyav1alpha1.AsyncActor{}
	if err := r.Get(ctx, req.NamespacedName, asya); err != nil {
		if errors.IsNotFound(err) {
			logger.Info("AsyncActor resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		logger.Error(err, "Failed to get AsyncActor")
		return ctrl.Result{}, err
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(asya, actorFinalizer) {
		controllerutil.AddFinalizer(asya, actorFinalizer)
		if err := r.Update(ctx, asya); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Check if the Asya is being deleted
	if !asya.DeletionTimestamp.IsZero() {
		return r.reconcileDelete(ctx, asya)
	}

	// Reconcile the workload
	if err := r.reconcileWorkload(ctx, asya); err != nil {
		logger.Error(err, "Failed to reconcile workload")
		r.setCondition(asya, "WorkloadReady", metav1.ConditionFalse, "ReconcileError", err.Error())
		if updateErr := r.Status().Update(ctx, asya); updateErr != nil {
			logger.Error(updateErr, "Failed to update status")
		}
		return ctrl.Result{}, err
	}

	r.setCondition(asya, "WorkloadReady", metav1.ConditionTrue, "WorkloadCreated", "Workload successfully created")

	// Reconcile KEDA ScaledObject if enabled
	if asya.Spec.Scaling.Enabled {
		if err := r.reconcileScaledObject(ctx, asya); err != nil {
			logger.Error(err, "Failed to reconcile ScaledObject")
			r.setCondition(asya, "ScalingReady", metav1.ConditionFalse, "ReconcileError", err.Error())
			if updateErr := r.Status().Update(ctx, asya); updateErr != nil {
				logger.Error(updateErr, "Failed to update status")
			}
			return ctrl.Result{}, err
		}
		r.setCondition(asya, "ScalingReady", metav1.ConditionTrue, "ScaledObjectCreated", "KEDA ScaledObject successfully created")
	}

	// Update status
	asya.Status.ObservedGeneration = asya.Generation
	if err := r.Status().Update(ctx, asya); err != nil {
		logger.Error(err, "Failed to update AsyncActor status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// reconcileDelete handles AsyncActor deletion
func (r *AsyncActorReconciler) reconcileDelete(ctx context.Context, asya *asyav1alpha1.AsyncActor) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("Deleting AsyncActor", "name", asya.Name)

	// Remove finalizer
	controllerutil.RemoveFinalizer(asya, actorFinalizer)
	if err := r.Update(ctx, asya); err != nil {
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// reconcileWorkload creates or updates the workload (Deployment/StatefulSet/Job)
func (r *AsyncActorReconciler) reconcileWorkload(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	_ = log.FromContext(ctx)

	// Inject sidecar into pod template
	podTemplate := r.injectSidecar(asya)

	switch asya.Spec.Workload.Type {
	case "Deployment", "":
		return r.reconcileDeployment(ctx, asya, podTemplate)
	case "StatefulSet":
		return r.reconcileStatefulSet(ctx, asya, podTemplate)
	case "Job":
		return r.reconcileJob(ctx, asya, podTemplate)
	default:
		return fmt.Errorf("unsupported workload type: %s", asya.Spec.Workload.Type)
	}
}

// injectSidecar injects the sidecar container into the pod template
func (r *AsyncActorReconciler) injectSidecar(asya *asyav1alpha1.AsyncActor) corev1.PodTemplateSpec {
	template := corev1.PodTemplateSpec{
		ObjectMeta: asya.Spec.Workload.Template.Metadata,
		Spec:       asya.Spec.Workload.Template.Spec,
	}

	// Set defaults
	socketPath := "/tmp/sockets/app.sock"
	if asya.Spec.Socket.Path != "" {
		socketPath = asya.Spec.Socket.Path
	}

	sidecarImage := "asya-sidecar:latest"
	if asya.Spec.Sidecar.Image != "" {
		sidecarImage = asya.Spec.Sidecar.Image
	}

	imagePullPolicy := corev1.PullIfNotPresent
	if asya.Spec.Sidecar.ImagePullPolicy != "" {
		imagePullPolicy = asya.Spec.Sidecar.ImagePullPolicy
	}

	// Build sidecar environment variables
	env := r.buildSidecarEnv(asya, socketPath)
	env = append(env, asya.Spec.Sidecar.Env...)

	// Create sidecar container
	sidecarContainer := corev1.Container{
		Name:            sidecarName,
		Image:           sidecarImage,
		ImagePullPolicy: imagePullPolicy,
		Env:             env,
		Resources:       asya.Spec.Sidecar.Resources,
		VolumeMounts: []corev1.VolumeMount{
			{
				Name:      socketVolume,
				MountPath: "/tmp/sockets",
			},
			{
				Name:      tmpVolume,
				MountPath: "/tmp",
			},
		},
	}

	// Add sidecar to containers
	template.Spec.Containers = append([]corev1.Container{sidecarContainer}, template.Spec.Containers...)

	// Add socket path to all runtime containers and inject asya_runtime.py
	for i := range template.Spec.Containers {
		if template.Spec.Containers[i].Name != sidecarName {
			// Set default command if not specified
			if len(template.Spec.Containers[i].Command) == 0 {
				template.Spec.Containers[i].Command = []string{"python", runtimeScriptPath}
			}

			// Add socket path env var
			template.Spec.Containers[i].Env = append(template.Spec.Containers[i].Env,
				corev1.EnvVar{
					Name:  "ASYA_SOCKET_PATH",
					Value: socketPath,
				},
			)

			// Add volume mounts
			template.Spec.Containers[i].VolumeMounts = append(template.Spec.Containers[i].VolumeMounts,
				corev1.VolumeMount{
					Name:      socketVolume,
					MountPath: "/tmp/sockets",
				},
				corev1.VolumeMount{
					Name:      tmpVolume,
					MountPath: "/tmp",
				},
				corev1.VolumeMount{
					Name:      runtimeVolume,
					MountPath: runtimeMountPath,
					ReadOnly:  true,
				},
			)
		}
	}

	// Add volumes
	template.Spec.Volumes = append(template.Spec.Volumes,
		corev1.Volume{
			Name: socketVolume,
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{},
			},
		},
		corev1.Volume{
			Name: tmpVolume,
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{},
			},
		},
		corev1.Volume{
			Name: runtimeVolume,
			VolumeSource: corev1.VolumeSource{
				ConfigMap: &corev1.ConfigMapVolumeSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: runtimeConfigMap,
					},
					DefaultMode: func() *int32 { mode := int32(0755); return &mode }(),
				},
			},
		},
	)

	// Set termination grace period
	gracePeriod := int64(30)
	if asya.Spec.Timeout.GracefulShutdown > 0 {
		gracePeriod = int64(asya.Spec.Timeout.GracefulShutdown)
	}
	template.Spec.TerminationGracePeriodSeconds = &gracePeriod

	return template
}

// buildSidecarEnv builds environment variables for the sidecar
func (r *AsyncActorReconciler) buildSidecarEnv(asya *asyav1alpha1.AsyncActor, socketPath string) []corev1.EnvVar {
	env := []corev1.EnvVar{
		{Name: "TRANSPORT_TYPE", Value: asya.Spec.Transport.Type},
		{Name: "ASYA_QUEUE_NAME", Value: asya.Spec.QueueName},
		{Name: "ASYA_SOCKET_PATH", Value: socketPath},
		{Name: "ASYA_LOG_LEVEL", Value: "info"},
		// Progress reporting to Gateway
		{Name: "ASYA_GATEWAY_URL", Value: "http://asya-gateway.asya.svc.cluster.local:8080"},
		{
			Name: "ASYA_ACTOR_NAME",
			ValueFrom: &corev1.EnvVarSource{
				FieldRef: &corev1.ObjectFieldSelector{
					FieldPath: "metadata.name",
				},
			},
		},
	}

	// Add processing timeout
	if asya.Spec.Timeout.Processing > 0 {
		env = append(env, corev1.EnvVar{
			Name:  "PROCESSING_TIMEOUT",
			Value: fmt.Sprintf("%d", asya.Spec.Timeout.Processing),
		})
	}

	// Add transport-specific config
	switch asya.Spec.Transport.Type {
	case "sqs":
		if asya.Spec.Transport.SQS != nil {
			if asya.Spec.Transport.SQS.Region != "" {
				env = append(env, corev1.EnvVar{Name: "AWS_REGION", Value: asya.Spec.Transport.SQS.Region})
			}
			if asya.Spec.Transport.SQS.QueueBaseURL != "" {
				env = append(env, corev1.EnvVar{Name: "QUEUE_BASE_URL", Value: asya.Spec.Transport.SQS.QueueBaseURL})
			}
		}

	case "rabbitmq":
		if asya.Spec.Transport.RabbitMQ != nil {
			if asya.Spec.Transport.RabbitMQ.Host != "" {
				env = append(env, corev1.EnvVar{Name: "RABBITMQ_HOST", Value: asya.Spec.Transport.RabbitMQ.Host})
			}
			if asya.Spec.Transport.RabbitMQ.Port > 0 {
				env = append(env, corev1.EnvVar{Name: "RABBITMQ_PORT", Value: fmt.Sprintf("%d", asya.Spec.Transport.RabbitMQ.Port)})
			}
			if asya.Spec.Transport.RabbitMQ.Username != "" {
				env = append(env, corev1.EnvVar{Name: "RABBITMQ_USERNAME", Value: asya.Spec.Transport.RabbitMQ.Username})
			}
			if asya.Spec.Transport.RabbitMQ.PasswordSecretRef != nil {
				env = append(env, corev1.EnvVar{
					Name: "RABBITMQ_PASSWORD",
					ValueFrom: &corev1.EnvVarSource{
						SecretKeyRef: asya.Spec.Transport.RabbitMQ.PasswordSecretRef,
					},
				})
			}
		}
	}

	return env
}

// reconcileDeployment creates or updates a Deployment
func (r *AsyncActorReconciler) reconcileDeployment(ctx context.Context, asya *asyav1alpha1.AsyncActor, podTemplate corev1.PodTemplateSpec) error {
	logger := log.FromContext(ctx)

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      asya.Name,
			Namespace: asya.Namespace,
		},
	}

	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, deployment, func() error {
		// Set owner reference
		if err := controllerutil.SetControllerReference(asya, deployment, r.Scheme); err != nil {
			return err
		}

		// Set replicas (will be overridden by KEDA if enabled)
		replicas := int32(1)
		if asya.Spec.Workload.Replicas != nil {
			replicas = *asya.Spec.Workload.Replicas
		}
		deployment.Spec.Replicas = &replicas

		// Set selector
		if deployment.Spec.Selector == nil {
			deployment.Spec.Selector = &metav1.LabelSelector{
				MatchLabels: map[string]string{
					"app":              asya.Name,
					"asya.io/asya":     asya.Name,
					"asya.io/workload": "deployment",
				},
			}
		}

		// Merge labels
		if podTemplate.ObjectMeta.Labels == nil {
			podTemplate.ObjectMeta.Labels = make(map[string]string)
		}
		for k, v := range deployment.Spec.Selector.MatchLabels {
			podTemplate.ObjectMeta.Labels[k] = v
		}

		deployment.Spec.Template = podTemplate

		return nil
	})

	if err != nil {
		return err
	}

	logger.Info("Deployment reconciled", "result", result)

	// Update status
	asya.Status.WorkloadRef = &asyav1alpha1.WorkloadReference{
		APIVersion: "apps/v1",
		Kind:       "Deployment",
		Name:       deployment.Name,
		Namespace:  deployment.Namespace,
	}

	return nil
}

// reconcileStatefulSet creates or updates a StatefulSet
func (r *AsyncActorReconciler) reconcileStatefulSet(ctx context.Context, asya *asyav1alpha1.AsyncActor, podTemplate corev1.PodTemplateSpec) error {
	// Similar to reconcileDeployment but for StatefulSet
	// Implementation omitted for brevity
	return fmt.Errorf("StatefulSet support not yet implemented")
}

// reconcileJob creates or updates a Job
func (r *AsyncActorReconciler) reconcileJob(ctx context.Context, asya *asyav1alpha1.AsyncActor, podTemplate corev1.PodTemplateSpec) error {
	// Implementation for Job workload
	// Implementation omitted for brevity
	return fmt.Errorf("Job support not yet implemented")
}

// setCondition sets a condition on the AsyncActor status
func (r *AsyncActorReconciler) setCondition(asya *asyav1alpha1.AsyncActor, condType string, status metav1.ConditionStatus, reason, message string) {
	condition := metav1.Condition{
		Type:               condType,
		Status:             status,
		ObservedGeneration: asya.Generation,
		LastTransitionTime: metav1.Now(),
		Reason:             reason,
		Message:            message,
	}

	// Find and update existing condition or append new one
	found := false
	for i, c := range asya.Status.Conditions {
		if c.Type == condType {
			if c.Status != status {
				asya.Status.Conditions[i] = condition
			}
			found = true
			break
		}
	}

	if !found {
		asya.Status.Conditions = append(asya.Status.Conditions, condition)
	}
}

// SetupWithManager sets up the controller with the Manager
func (r *AsyncActorReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&asyav1alpha1.AsyncActor{}).
		Owns(&appsv1.Deployment{}).
		Owns(&appsv1.StatefulSet{}).
		Owns(&batchv1.Job{}).
		Complete(r)
}
