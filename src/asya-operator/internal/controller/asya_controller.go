package controller

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
	appsv1 "k8s.io/api/apps/v1"
	autoscalingv2 "k8s.io/api/autoscaling/v2"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
	"github.com/asya/operator/internal/transports"
)

const (
	actorFinalizer        = "asya.sh/finalizer"
	sidecarName           = "asya-sidecar"
	runtimeContainerName  = "asya-runtime"
	socketVolume          = "socket-dir"
	tmpVolume             = "tmp"
	runtimeVolume         = "asya-runtime"
	runtimeConfigMap      = "asya-runtime"
	runtimeMountPath      = "/opt/asya/asya_runtime.py"
	transportTypeRabbitMQ = "rabbitmq"
	transportTypeSQS      = "sqs"

	actorNameHappyEnd = "happy-end"
	actorNameErrorEnd = "error-end"

	podReasonCrashLoopBackOff           = "CrashLoopBackOff"
	podReasonImagePullBackOff           = "ImagePullBackOff"
	podReasonErrImagePull               = "ErrImagePull"
	podReasonCreateContainerError       = "CreateContainerError"
	podReasonCreateContainerConfigError = "CreateContainerConfigError"
	podReasonInvalidImageName           = "InvalidImageName"
	podReasonRunContainerError          = "RunContainerError"
)

// QueueDeletedRecentlyError is returned when attempting to create an SQS queue
// that was recently deleted (AWS requires 60-second cooldown)
type QueueDeletedRecentlyError struct {
	QueueName string
}

func (e *QueueDeletedRecentlyError) Error() string {
	return fmt.Sprintf("queue %s was recently deleted, waiting for AWS cooldown period (60s)", e.QueueName)
}

func getRuntimeScriptPath() string {
	if path := os.Getenv("ASYA_RUNTIME_SCRIPT_PATH"); path != "" {
		return path
	}
	return "/runtime/asya_runtime.py"
}

func getSidecarImage() string {
	if image := os.Getenv("ASYA_SIDECAR_IMAGE"); image != "" {
		return image
	}
	return "asya-sidecar:latest"
}

func isFailingContainerReason(reason string) bool {
	return reason == podReasonCrashLoopBackOff ||
		reason == podReasonImagePullBackOff ||
		reason == podReasonErrImagePull ||
		reason == podReasonCreateContainerError ||
		reason == podReasonCreateContainerConfigError ||
		reason == podReasonInvalidImageName ||
		reason == podReasonRunContainerError
}

// isPodFailing checks if a pod is in a permanent failure state
// Detects both container-level failures and pod-level failures (volume mounts, scheduling)
func isPodFailing(pod *corev1.Pod) bool {
	// Check init container states
	for _, initStatus := range pod.Status.InitContainerStatuses {
		if initStatus.State.Waiting != nil {
			if isFailingContainerReason(initStatus.State.Waiting.Reason) {
				return true
			}
		}
	}

	// Check regular container states
	for _, containerStatus := range pod.Status.ContainerStatuses {
		if containerStatus.State.Waiting != nil {
			if isFailingContainerReason(containerStatus.State.Waiting.Reason) {
				return true
			}
		}
	}

	// Check pod conditions for persistent failures
	for _, condition := range pod.Status.Conditions {
		// PodScheduled=False indicates scheduling issues
		if condition.Type == corev1.PodScheduled &&
			condition.Status == corev1.ConditionFalse &&
			condition.Reason == "Unschedulable" {
			return true
		}

		// ContainersReady=False may indicate volume mount failures
		if condition.Type == corev1.ContainersReady &&
			condition.Status == corev1.ConditionFalse {
			msg := condition.Message
			// Volume mount failures
			if strings.Contains(msg, "MountVolume.SetUp failed") {
				return true
			}
			// ConfigMap/Secret not found
			if (strings.Contains(msg, "configmap") || strings.Contains(msg, "secret")) &&
				strings.Contains(msg, "not found") {
				return true
			}
		}

		// PodReadyToStartContainers=False indicates volume/mount issues
		// This condition is set when volumes cannot be mounted (ConfigMap/Secret missing, etc.)
		if condition.Type == corev1.PodReadyToStartContainers &&
			condition.Status == corev1.ConditionFalse {
			return true
		}
	}

	return false
}

// AsyncActorReconciler reconciles an AsyncActor object
type AsyncActorReconciler struct {
	client.Client
	Scheme                  *runtime.Scheme
	TransportRegistry       *asyaconfig.TransportRegistry
	TransportFactory        *transports.Factory
	MaxConcurrentReconciles int
	GatewayURL              string
}

// +kubebuilder:rbac:groups=asya.sh,resources=asyncactors,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=asya.sh,resources=asyncactors/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=asya.sh,resources=asyncactors/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=apps,resources=statefulsets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=keda.sh,resources=scaledobjects,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=keda.sh,resources=triggerauthentications,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=serviceaccounts,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=pods,verbs=get;list;watch
// +kubebuilder:rbac:groups=autoscaling,resources=horizontalpodautoscalers,verbs=get;list;watch

// Reconcile is the main reconciliation loop
func (r *AsyncActorReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("[DEBUG-VERSION-CHECK] Starting Reconcile with DEBUG logging enabled", "resource", req.NamespacedName)

	// Fetch the AsyncActor instance
	asya := &asyav1alpha1.AsyncActor{}
	if err := r.Get(ctx, req.NamespacedName, asya); err != nil {
		if apierrors.IsNotFound(err) {
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

	// Validate spec before processing
	if err := r.validateAsyncActorSpec(asya); err != nil {
		logger.Error(err, "AsyncActor spec validation failed")
		r.setCondition(asya, "WorkloadReady", metav1.ConditionFalse, "ValidationError", err.Error())
		asya.Status.ObservedGeneration = asya.Generation
		r.updateDisplayFields(asya)
		if updateErr := r.Status().Update(ctx, asya); updateErr != nil {
			logger.Error(updateErr, "Failed to update status")
		}
		return ctrl.Result{}, err
	}

	// Validate transport exists and is enabled
	if _, err := r.TransportRegistry.GetTransport(asya.Spec.Transport); err != nil {
		logger.Error(err, "Invalid transport configuration", "transport", asya.Spec.Transport)
		r.setCondition(asya, "TransportReady", metav1.ConditionFalse, "InvalidTransport", err.Error())
		asya.Status.ObservedGeneration = asya.Generation
		r.updateDisplayFields(asya)
		if updateErr := r.Status().Update(ctx, asya); updateErr != nil {
			logger.Error(updateErr, "Failed to update status")
		}
		return ctrl.Result{}, err
	}
	r.setCondition(asya, "TransportReady", metav1.ConditionTrue, "TransportValidated", "Transport configuration validated")

	// Reconcile transport-specific resources using transport layer
	queueReconciler, err := r.TransportFactory.GetQueueReconciler(asya.Spec.Transport)
	if err != nil {
		logger.Error(err, "Failed to get queue reconciler for transport", "transport", asya.Spec.Transport)
		return ctrl.Result{}, err
	}

	if err := queueReconciler.ReconcileQueue(ctx, asya); err != nil {
		// Handle SQS-specific queue deletion cooldown error
		if strings.Contains(err.Error(), "QueueDeletedRecently") {
			logger.Info("Requeuing after SQS queue deletion cooldown", "retryAfter", "65s")
			return ctrl.Result{RequeueAfter: 65 * time.Second}, nil
		}
		logger.Error(err, "Failed to reconcile queue", "transport", asya.Spec.Transport)
		return ctrl.Result{}, err
	}

	// Only reconcile ServiceAccount if using SQS with IRSA (actorRoleArn configured)
	if asya.Spec.Transport == transportTypeSQS {
		if err := r.reconcileServiceAccountIfNeeded(ctx, asya); err != nil {
			logger.Error(err, "Failed to reconcile ServiceAccount")
			return ctrl.Result{}, err
		}
	}

	// Ensure runtime ConfigMap exists in actor's namespace
	if err := r.reconcileRuntimeConfigMap(ctx, asya); err != nil {
		logger.Error(err, "Failed to reconcile runtime ConfigMap")
		return ctrl.Result{}, err
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

	// Check pod health to verify workload is actually ready
	podHealthy, healthMessage := r.checkPodHealth(ctx, asya)
	if !podHealthy {
		logger.Info("Pods not healthy", "message", healthMessage)
		r.setCondition(asya, "WorkloadReady", metav1.ConditionFalse, "PodsNotHealthy", healthMessage)
	} else {
		r.setCondition(asya, "WorkloadReady", metav1.ConditionTrue, "WorkloadCreated", "Workload successfully created")
	}
	logger.Info("Workload condition set", "healthy", podHealthy)

	// Reconcile KEDA ScaledObject based on latest spec
	if asya.Spec.Scaling.Enabled {
		logger.Info("Reconciling KEDA ScaledObject", "enabled", asya.Spec.Scaling.Enabled)
		if err := r.reconcileScaledObject(ctx, asya); err != nil {
			logger.Error(err, "Failed to reconcile ScaledObject")
			r.setCondition(asya, "ScalingReady", metav1.ConditionFalse, "ReconcileError", err.Error())
			if updateErr := r.Status().Update(ctx, asya); updateErr != nil {
				logger.Error(updateErr, "Failed to update status")
			}
			return ctrl.Result{}, err
		}
		r.setCondition(asya, "ScalingReady", metav1.ConditionTrue, "ScaledObjectCreated", "KEDA ScaledObject successfully created")
		logger.Info("ScaledObject condition set")

		// When KEDA is enabled, fetch desired replicas from the HPA
		hpaDesired, err := r.getHPADesiredReplicas(ctx, asya)
		if err != nil {
			logger.Error(err, "Failed to get HPA desired replicas")
		} else if hpaDesired != nil {
			asya.Status.DesiredReplicas = hpaDesired
			logger.Info("Set desired replicas from HPA", "desiredReplicas", *hpaDesired)
		} else {
			// HPA not found - KEDA may still be creating it
			logger.Info("HPA not found, KEDA may be creating it - will requeue to check again")

			// Update status before requeuing to show current state
			asya.Status.ObservedGeneration = asya.Generation
			r.updateDisplayFields(asya)
			if updateErr := r.Status().Update(ctx, asya); updateErr != nil {
				logger.Error(updateErr, "Failed to update status before requeue")
			}

			// Requeue after 5 seconds to give KEDA time to create the HPA
			return ctrl.Result{RequeueAfter: 5 * time.Second}, nil
		}
	} else {
		logger.Info("KEDA scaling disabled, ensuring ScaledObject is deleted")
		if err := r.deleteScaledObject(ctx, asya); err != nil {
			logger.Error(err, "Failed to delete ScaledObject")
			return ctrl.Result{}, err
		}
	}

	// Update queue metrics (optional - non-critical)
	r.updateQueueMetrics(ctx, asya)

	// Update status
	asya.Status.ObservedGeneration = asya.Generation
	logger.Info("ObservedGeneration set", "generation", asya.Generation)

	// Update display fields (includes status calculation)
	r.updateDisplayFields(asya)
	logger.Info("Display fields updated", "status", asya.Status.Status, "readySummary", asya.Status.ReadySummary, "replicasSummary", asya.Status.ReplicasSummary)

	if err := r.Status().Update(ctx, asya); err != nil {
		logger.Error(err, "Failed to update AsyncActor status")
		return ctrl.Result{}, err
	}
	logger.Info("Status updated successfully")

	return ctrl.Result{}, nil
}

// validateAsyncActorSpec validates the AsyncActor spec for forbidden configurations
func (r *AsyncActorReconciler) validateAsyncActorSpec(asya *asyav1alpha1.AsyncActor) error {
	// Validate: user containers must not be named "asya-sidecar"
	for _, container := range asya.Spec.Workload.Template.Spec.Containers {
		if container.Name == sidecarName {
			return fmt.Errorf("container name '%s' is reserved for the injected sidecar and cannot be defined in the AsyncActor spec", sidecarName)
		}
	}

	// Validate: init containers must not be named "asya-sidecar"
	for _, initContainer := range asya.Spec.Workload.Template.Spec.InitContainers {
		if initContainer.Name == sidecarName {
			return fmt.Errorf("init container name '%s' is reserved for operator use and cannot be defined in the AsyncActor spec", sidecarName)
		}
	}

	// Validate: runtime container must be named "asya-runtime"
	runtimeContainerCount := 0
	for _, container := range asya.Spec.Workload.Template.Spec.Containers {
		if container.Name == runtimeContainerName {
			runtimeContainerCount++
			if len(container.Command) > 0 {
				return fmt.Errorf("container '%s' cannot override command (command is managed by operator)", runtimeContainerName)
			}
		}
	}

	if runtimeContainerCount != 1 {
		return fmt.Errorf("workload must contain exactly one container named '%s', but found %d", runtimeContainerName, runtimeContainerCount)
	}

	return nil
}

// reconcileDelete handles AsyncActor deletion
func (r *AsyncActorReconciler) reconcileDelete(ctx context.Context, asya *asyav1alpha1.AsyncActor) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("Deleting AsyncActor", "name", asya.Name)

	// Delete ScaledObject and TriggerAuthentication if they exist
	if err := r.deleteScaledObject(ctx, asya); err != nil {
		logger.Error(err, "Failed to delete ScaledObject, continuing with deletion")
	}

	// Delete transport queue using transport layer
	queueReconciler, err := r.TransportFactory.GetQueueReconciler(asya.Spec.Transport)
	if err != nil {
		logger.Error(err, "Failed to get queue reconciler for deletion", "transport", asya.Spec.Transport)
	} else {
		if err := queueReconciler.DeleteQueue(ctx, asya); err != nil {
			logger.Error(err, "Failed to delete queue, continuing with deletion", "transport", asya.Spec.Transport)
		}
	}

	// Remove finalizer
	controllerutil.RemoveFinalizer(asya, actorFinalizer)
	if err := r.Update(ctx, asya); err != nil {
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// CreateSQSClient creates an AWS SQS client with configured credentials
func (r *AsyncActorReconciler) CreateSQSClient(ctx context.Context, sqsConfig *asyaconfig.SQSConfig, actorNamespace string) (*sqs.Client, error) {
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

	// If credentials are configured via secrets, read them and use static credentials
	if sqsConfig.Credentials != nil {
		var accessKeyID, secretAccessKey string
		var err error

		// Read access key ID from secret
		if sqsConfig.Credentials.AccessKeyIdSecretRef != nil {
			secret := &corev1.Secret{}
			secretKey := client.ObjectKey{
				Namespace: actorNamespace,
				Name:      sqsConfig.Credentials.AccessKeyIdSecretRef.Name,
			}

			if err = r.Get(ctx, secretKey, secret); err != nil {
				return nil, fmt.Errorf("failed to read access key secret: %w", err)
			}

			accessKeyID = string(secret.Data[sqsConfig.Credentials.AccessKeyIdSecretRef.Key])
			if accessKeyID == "" {
				return nil, fmt.Errorf("access key ID not found in secret %s/%s", secretKey.Namespace, secretKey.Name)
			}
		}

		// Read secret access key from secret
		if sqsConfig.Credentials.SecretAccessKeySecretRef != nil {
			secret := &corev1.Secret{}
			secretKey := client.ObjectKey{
				Namespace: actorNamespace,
				Name:      sqsConfig.Credentials.SecretAccessKeySecretRef.Name,
			}

			if err = r.Get(ctx, secretKey, secret); err != nil {
				return nil, fmt.Errorf("failed to read secret access key secret: %w", err)
			}

			secretAccessKey = string(secret.Data[sqsConfig.Credentials.SecretAccessKeySecretRef.Key])
			if secretAccessKey == "" {
				return nil, fmt.Errorf("secret access key not found in secret %s/%s", secretKey.Namespace, secretKey.Name)
			}
		}

		// Use static credentials provider
		if accessKeyID != "" && secretAccessKey != "" {
			configOpts = append(configOpts, config.WithCredentialsProvider(
				credentials.NewStaticCredentialsProvider(accessKeyID, secretAccessKey, ""),
			))
		}
	}

	cfg, err := config.LoadDefaultConfig(ctx, configOpts...)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	return sqs.NewFromConfig(cfg), nil
}

// reconcileServiceAccountIfNeeded creates or updates the ServiceAccount with IRSA annotation
// Only creates ServiceAccount if actorRoleArn is configured (for EKS IRSA)
// Skips for LocalStack or environments using static credentials
func (r *AsyncActorReconciler) reconcileServiceAccountIfNeeded(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	transport, err := r.TransportRegistry.GetTransport(transportTypeSQS)
	if err != nil {
		return err
	}

	sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		return fmt.Errorf("invalid SQS config type")
	}

	if sqsConfig.ActorRoleArn == "" {
		logger.Info("Skipping ServiceAccount reconciliation (actorRoleArn not configured, using static credentials)")
		return nil
	}

	saName := fmt.Sprintf("asya-%s", asya.Name)

	sa := &corev1.ServiceAccount{
		ObjectMeta: metav1.ObjectMeta{
			Name:      saName,
			Namespace: asya.Namespace,
		},
	}

	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, sa, func() error {
		if err := controllerutil.SetControllerReference(asya, sa, r.Scheme); err != nil {
			return err
		}

		if sa.Annotations == nil {
			sa.Annotations = make(map[string]string)
		}
		sa.Annotations["eks.amazonaws.com/role-arn"] = sqsConfig.ActorRoleArn

		return nil
	})

	if err != nil {
		return fmt.Errorf("failed to reconcile ServiceAccount: %w", err)
	}

	logger.Info("ServiceAccount reconciled", "result", result, "name", saName)
	return nil
}

// reconcileRuntimeConfigMap ensures the runtime ConfigMap exists in the actor's namespace
func (r *AsyncActorReconciler) reconcileRuntimeConfigMap(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	logger := log.FromContext(ctx)

	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      runtimeConfigMap,
			Namespace: asya.Namespace,
		},
	}

	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, configMap, func() error {
		// Do not set controller ownership - this is a shared ConfigMap used by all AsyncActors in the namespace
		// It will persist across actor deletions and be reused by new actors

		// Set labels
		if configMap.Labels == nil {
			configMap.Labels = make(map[string]string)
		}
		configMap.Labels["app.kubernetes.io/name"] = runtimeContainerName
		configMap.Labels["app.kubernetes.io/component"] = runtimeContainerName
		configMap.Labels["app.kubernetes.io/part-of"] = "asya"

		// Set data
		if configMap.Data == nil {
			configMap.Data = make(map[string]string)
		}

		runtimeScriptPath := getRuntimeScriptPath()
		runtimeContent, err := os.ReadFile(runtimeScriptPath) // #nosec G304
		if err != nil {
			return fmt.Errorf("failed to read runtime script from %s: %w", runtimeScriptPath, err)
		}
		configMap.Data["asya_runtime.py"] = string(runtimeContent)

		return nil
	})

	if err != nil {
		// Handle race condition: If another reconciler created the ConfigMap between our GET and CREATE,
		// treat it as success since the ConfigMap now exists with the correct content
		if apierrors.IsAlreadyExists(err) {
			logger.Info("Runtime ConfigMap already exists (concurrent reconciliation)", "namespace", asya.Namespace)
			return nil
		}
		return fmt.Errorf("failed to reconcile runtime ConfigMap: %w", err)
	}

	logger.Info("Runtime ConfigMap reconciled", "result", result, "namespace", asya.Namespace)
	return nil
}

// reconcileWorkload creates or updates the workload (Deployment or StatefulSet)
func (r *AsyncActorReconciler) reconcileWorkload(ctx context.Context, asya *asyav1alpha1.AsyncActor) error {
	_ = log.FromContext(ctx)

	// Inject sidecar into pod template
	podTemplate := r.injectSidecar(asya)

	switch asya.Spec.Workload.Kind {
	case "Deployment", "":
		return r.reconcileDeployment(ctx, asya, podTemplate)
	case "StatefulSet":
		return r.reconcileStatefulSet(ctx, asya, podTemplate)
	default:
		return fmt.Errorf("unsupported workload kind: %s (only Deployment and StatefulSet are supported)", asya.Spec.Workload.Kind)
	}
}

// injectSidecar injects the sidecar container into the pod template
func (r *AsyncActorReconciler) injectSidecar(asya *asyav1alpha1.AsyncActor) corev1.PodTemplateSpec {
	template := corev1.PodTemplateSpec{
		ObjectMeta: asya.Spec.Workload.Template.Metadata,
		Spec:       asya.Spec.Workload.Template.Spec,
	}

	// Note: Validation is performed in validateAsyncActorSpec() before reaching this point
	// This function assumes the spec has already been validated

	// Hardcoded socket path (not user-configurable to prevent misconfiguration)
	const socketsDir = "/var/run/asya"
	socketPath := socketsDir + "/asya-runtime.sock"

	sidecarImage := getSidecarImage()
	if asya.Spec.Sidecar.Image != "" {
		sidecarImage = asya.Spec.Sidecar.Image
	}

	imagePullPolicy := corev1.PullIfNotPresent
	if asya.Spec.Sidecar.ImagePullPolicy != "" {
		imagePullPolicy = asya.Spec.Sidecar.ImagePullPolicy
	}

	// Build sidecar environment variables
	env := r.buildSidecarEnv(asya)
	env = append(env, corev1.EnvVar{
		Name:  "ASYA_SOCKET_DIR",
		Value: socketsDir,
	})
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
				MountPath: socketsDir,
			},
			{
				Name:      tmpVolume,
				MountPath: "/tmp",
			},
		},
	}

	// Add sidecar to containers (append at end to preserve container ordering)
	template.Spec.Containers = append(template.Spec.Containers, sidecarContainer)

	// Queue initialization is handled by operator's ReconcileQueue()

	// Add socket path to runtime container and inject asya_runtime.py
	for i := range template.Spec.Containers {
		if template.Spec.Containers[i].Name == runtimeContainerName {
			// Set runtime command (validation ensures it's not already set)
			pythonExec := "python3"
			if asya.Spec.Workload.PythonExecutable != "" {
				pythonExec = asya.Spec.Workload.PythonExecutable
			}
			template.Spec.Containers[i].Command = []string{pythonExec, runtimeMountPath}

			// Add ASYA_SOCKET_DIR environment variable
			template.Spec.Containers[i].Env = append(template.Spec.Containers[i].Env,
				corev1.EnvVar{
					Name:  "ASYA_SOCKET_DIR",
					Value: socketsDir,
				},
			)

			// Disable validation for end actors
			if asya.Name == actorNameHappyEnd || asya.Name == actorNameErrorEnd {
				template.Spec.Containers[i].Env = append(template.Spec.Containers[i].Env,
					corev1.EnvVar{
						Name:  "ASYA_ENABLE_VALIDATION",
						Value: "false",
					},
				)
			}

			// Add volume mounts
			template.Spec.Containers[i].VolumeMounts = append(template.Spec.Containers[i].VolumeMounts,
				corev1.VolumeMount{
					Name:      socketVolume,
					MountPath: socketsDir,
				},
				corev1.VolumeMount{
					Name:      tmpVolume,
					MountPath: "/tmp",
				},
				corev1.VolumeMount{
					Name:      runtimeVolume,
					MountPath: runtimeMountPath,
					SubPath:   "asya_runtime.py",
					ReadOnly:  true,
				},
			)

			// Add startup probe to detect initialization failures
			if template.Spec.Containers[i].StartupProbe == nil {
				template.Spec.Containers[i].StartupProbe = &corev1.Probe{
					ProbeHandler: corev1.ProbeHandler{
						Exec: &corev1.ExecAction{
							Command: []string{"sh", "-c", fmt.Sprintf("test -S %s && test -f %s/runtime-ready", socketPath, socketsDir)},
						},
					},
					InitialDelaySeconds: 3,
					PeriodSeconds:       2,
					TimeoutSeconds:      3,
					FailureThreshold:    150,
				}
			}

			// Add liveness probe to detect hung runtime processes
			if template.Spec.Containers[i].LivenessProbe == nil {
				template.Spec.Containers[i].LivenessProbe = &corev1.Probe{
					ProbeHandler: corev1.ProbeHandler{
						Exec: &corev1.ExecAction{
							Command: []string{"sh", "-c", fmt.Sprintf("test -S %s && test -f %s/runtime-ready", socketPath, socketsDir)},
						},
					},
					InitialDelaySeconds: 0,
					PeriodSeconds:       30,
					TimeoutSeconds:      5,
					FailureThreshold:    3,
				}
			}

			// Add readiness probe for graceful startup
			if template.Spec.Containers[i].ReadinessProbe == nil {
				template.Spec.Containers[i].ReadinessProbe = &corev1.Probe{
					ProbeHandler: corev1.ProbeHandler{
						Exec: &corev1.ExecAction{
							Command: []string{"sh", "-c", fmt.Sprintf("test -S %s && test -f %s/runtime-ready", socketPath, socketsDir)},
						},
					},
					InitialDelaySeconds: 0,
					PeriodSeconds:       10,
					TimeoutSeconds:      3,
					FailureThreshold:    3,
				}
			}
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

// extractGatewayURLFromRuntime extracts ASYA_GATEWAY_URL from runtime container env vars
func (r *AsyncActorReconciler) extractGatewayURLFromRuntime(asya *asyav1alpha1.AsyncActor) string {
	if asya.Spec.Workload.Template.Spec.Containers == nil {
		return ""
	}

	for _, container := range asya.Spec.Workload.Template.Spec.Containers {
		if container.Name != runtimeContainerName {
			continue
		}
		for _, env := range container.Env {
			if env.Name == "ASYA_GATEWAY_URL" {
				return env.Value
			}
		}
	}
	return ""
}

// buildSidecarEnv builds environment variables for the sidecar
func (r *AsyncActorReconciler) buildSidecarEnv(asya *asyav1alpha1.AsyncActor) []corev1.EnvVar {
	// Use operator-level gateway URL if configured, otherwise fall back to extracting from AsyncActor spec
	gatewayURL := r.GatewayURL
	if gatewayURL == "" {
		gatewayURL = r.extractGatewayURLFromRuntime(asya)
	}

	env := []corev1.EnvVar{
		{Name: "ASYA_LOG_LEVEL", Value: "info"},
		{Name: "ASYA_GATEWAY_URL", Value: gatewayURL},
		{Name: "ASYA_ACTOR_NAME", Value: asya.Name},
		{Name: "ASYA_ACTOR_HAPPY_END", Value: actorNameHappyEnd},
		{Name: "ASYA_ACTOR_ERROR_END", Value: actorNameErrorEnd},
	}

	// Set ASYA_IS_END_ACTOR for end actors
	if asya.Name == actorNameHappyEnd || asya.Name == actorNameErrorEnd {
		env = append(env, corev1.EnvVar{
			Name:  "ASYA_IS_END_ACTOR",
			Value: "true",
		})
	}

	// Add processing timeout
	if asya.Spec.Timeout.Processing > 0 {
		env = append(env, corev1.EnvVar{
			Name:  "ASYA_RUNTIME_TIMEOUT",
			Value: fmt.Sprintf("%ds", asya.Spec.Timeout.Processing),
		})
	}

	// Get transport config from registry and build env vars
	transport, err := r.TransportRegistry.GetTransport(asya.Spec.Transport)
	if err != nil {
		return env
	}

	transportEnv, err := transport.BuildEnvVars()
	if err != nil {
		return env
	}

	env = append(env, transportEnv...)

	return env
}

// checkPodHealth checks actual pod health status for the workload
func (r *AsyncActorReconciler) checkPodHealth(ctx context.Context, asya *asyav1alpha1.AsyncActor) (bool, string) {
	logger := log.FromContext(ctx)

	podList := &corev1.PodList{}
	listOpts := []client.ListOption{
		client.InNamespace(asya.Namespace),
		client.MatchingLabels{"asya.sh/asya": asya.Name},
	}

	if err := r.List(ctx, podList, listOpts...); err != nil {
		logger.Error(err, "Failed to list pods for health check")
		return false, fmt.Sprintf("Failed to list pods: %v", err)
	}

	if len(podList.Items) == 0 {
		return false, "No pods found"
	}

	for _, pod := range podList.Items {
		if pod.Status.Phase == corev1.PodFailed {
			return false, fmt.Sprintf("Pod %s in Failed phase", pod.Name)
		}

		for _, initStatus := range pod.Status.InitContainerStatuses {
			if initStatus.RestartCount > 5 {
				return false, fmt.Sprintf("Init container %s has %d restarts (pod: %s)", initStatus.Name, initStatus.RestartCount, pod.Name)
			}

			if initStatus.State.Waiting != nil {
				reason := initStatus.State.Waiting.Reason
				if isFailingContainerReason(reason) {
					return false, fmt.Sprintf("Init container %s in %s (pod: %s)", initStatus.Name, reason, pod.Name)
				}
			}
		}

		for _, containerStatus := range pod.Status.ContainerStatuses {
			if containerStatus.Name == runtimeContainerName || containerStatus.Name == sidecarName {
				if containerStatus.RestartCount > 5 {
					return false, fmt.Sprintf("Container %s has %d restarts (pod: %s)", containerStatus.Name, containerStatus.RestartCount, pod.Name)
				}

				if containerStatus.State.Waiting != nil {
					reason := containerStatus.State.Waiting.Reason
					if isFailingContainerReason(reason) {
						return false, fmt.Sprintf("Container %s in %s (pod: %s)", containerStatus.Name, reason, pod.Name)
					}
				}
			}
		}
	}

	return true, "All pods healthy"
}

// updatePodStateCounts updates granular pod state counts
func (r *AsyncActorReconciler) updatePodStateCounts(ctx context.Context, asya *asyav1alpha1.AsyncActor) {
	logger := log.FromContext(ctx)

	podList := &corev1.PodList{}
	listOpts := []client.ListOption{
		client.InNamespace(asya.Namespace),
		client.MatchingLabels{"asya.sh/asya": asya.Name},
	}

	if err := r.List(ctx, podList, listOpts...); err != nil {
		logger.Error(err, "Failed to list pods for state counts")
		return
	}

	running := int32(0)
	pending := int32(0)
	failed := int32(0)

	for _, pod := range podList.Items {
		if pod.DeletionTimestamp != nil {
			continue
		}

		// Check if pod is ready (all containers ready)
		podReady := false
		for _, condition := range pod.Status.Conditions {
			if condition.Type == corev1.PodReady && condition.Status == corev1.ConditionTrue {
				podReady = true
				break
			}
		}

		switch pod.Status.Phase {
		case corev1.PodRunning:
			if podReady {
				running++
			} else {
				if isPodFailing(&pod) {
					failed++
				} else {
					pending++
				}
			}
		case corev1.PodPending:
			if isPodFailing(&pod) {
				failed++
			} else {
				pending++
			}
		case corev1.PodFailed:
			failed++
		}
	}

	asya.Status.PendingReplicas = &pending
	asya.Status.FailingPods = &failed
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

		// Set replicas only if KEDA scaling is disabled
		// When scaling.enabled=true, HPA owns the replicas field
		if !asya.Spec.Scaling.Enabled {
			replicas := int32(1)
			if asya.Spec.Workload.Replicas != nil {
				replicas = *asya.Spec.Workload.Replicas
			}
			deployment.Spec.Replicas = &replicas
		}

		// Set selector
		if deployment.Spec.Selector == nil {
			deployment.Spec.Selector = &metav1.LabelSelector{
				MatchLabels: map[string]string{
					"app":              asya.Name,
					"asya.sh/asya":     asya.Name,
					"asya.sh/workload": "deployment",
				},
			}
		}

		// Merge labels: add operator-managed labels, preserve user labels
		if podTemplate.Labels == nil {
			podTemplate.Labels = make(map[string]string)
		}
		for k, v := range deployment.Spec.Selector.MatchLabels {
			if _, exists := podTemplate.Labels[k]; !exists {
				podTemplate.Labels[k] = v
			}
		}

		// Set ServiceAccount for SQS transport (only if using IRSA)
		if asya.Spec.Transport == transportTypeSQS {
			transport, err := r.TransportRegistry.GetTransport(transportTypeSQS)
			if err == nil {
				if sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig); ok {
					userProvidedSA := asya.Spec.Workload.Template.Spec.ServiceAccountName

					if sqsConfig.ActorRoleArn != "" {
						// IRSA enabled: require operator-managed ServiceAccount
						if userProvidedSA != "" {
							return fmt.Errorf("cannot use custom serviceAccountName %q when IRSA (actorRoleArn) is configured: remove serviceAccountName from spec or disable IRSA", userProvidedSA)
						}
						podTemplate.Spec.ServiceAccountName = fmt.Sprintf("asya-%s", asya.Name)
					}
					// IRSA disabled: preserve user's ServiceAccount choice (or empty if not provided)
				}
			}
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

	// Read Deployment status to get current replicas
	if err := r.Get(ctx, client.ObjectKey{Name: deployment.Name, Namespace: deployment.Namespace}, deployment); err == nil {
		// Track ready and total replicas
		readyReplicas := deployment.Status.ReadyReplicas
		totalReplicas := deployment.Status.Replicas

		asya.Status.ReadyReplicas = &readyReplicas
		asya.Status.TotalReplicas = &totalReplicas

		// Track pods by state for granular status (sets PendingReplicas and FailingPods)
		r.updatePodStateCounts(ctx, asya)

		// Track replica changes for scaling detection
		oldReplicas := int32(0)
		if asya.Status.Replicas != nil {
			oldReplicas = *asya.Status.Replicas
		}

		// Replicas = ready replicas (RUNNING column)
		newReplicas := readyReplicas

		// Track replica changes
		if newReplicas != oldReplicas {
			now := metav1.Now()
			asya.Status.LastScaleTime = &now

			if newReplicas > oldReplicas {
				asya.Status.LastScaleDirection = "up"
			} else if newReplicas < oldReplicas {
				asya.Status.LastScaleDirection = "down"
			}
		}

		asya.Status.Replicas = &newReplicas

		// Set desired replicas from deployment spec
		if deployment.Spec.Replicas != nil {
			asya.Status.DesiredReplicas = deployment.Spec.Replicas
		}
	}

	return nil
}

// reconcileStatefulSet creates or updates a StatefulSet
func (r *AsyncActorReconciler) reconcileStatefulSet(ctx context.Context, asya *asyav1alpha1.AsyncActor, podTemplate corev1.PodTemplateSpec) error {
	// Similar to reconcileDeployment but for StatefulSet
	// Implementation omitted for brevity
	return fmt.Errorf("StatefulSet support not yet implemented")
}

// getHPADesiredReplicas fetches the desired replica count from KEDA's HPA
// Returns the desired replicas if found, or nil if HPA doesn't exist or has no desired replicas
func (r *AsyncActorReconciler) getHPADesiredReplicas(ctx context.Context, asya *asyav1alpha1.AsyncActor) (*int32, error) {
	logger := log.FromContext(ctx)

	// KEDA creates HPAs with the naming convention: keda-hpa-{scaledobject-name}
	hpaName := fmt.Sprintf("keda-hpa-%s", asya.Name)

	hpa := &autoscalingv2.HorizontalPodAutoscaler{}
	err := r.Get(ctx, client.ObjectKey{
		Name:      hpaName,
		Namespace: asya.Namespace,
	}, hpa)

	if err != nil {
		if apierrors.IsNotFound(err) {
			logger.V(1).Info("HPA not found, KEDA may not have created it yet", "hpaName", hpaName)
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get HPA %s: %w", hpaName, err)
	}

	// HPA status.desiredReplicas is the number of replicas KEDA wants
	if hpa.Status.DesiredReplicas > 0 {
		logger.Info("Fetched desired replicas from HPA", "hpaName", hpaName, "desiredReplicas", hpa.Status.DesiredReplicas)
		return &hpa.Status.DesiredReplicas, nil
	}

	logger.V(1).Info("HPA has no desired replicas set", "hpaName", hpaName)
	return nil, nil
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

// updateQueueMetrics updates queue metrics from the transport
func (r *AsyncActorReconciler) updateQueueMetrics(ctx context.Context, asya *asyav1alpha1.AsyncActor) {
	logger := log.FromContext(ctx)

	transport, err := r.TransportRegistry.GetTransport(asya.Spec.Transport)
	if err != nil {
		logger.V(1).Info("Failed to get transport for queue metrics", "error", err)
		return
	}

	queueName := fmt.Sprintf("asya-%s", asya.Name)

	var metrics *asyaconfig.QueueMetrics

	// Create password resolver function
	passwordResolver := func(ctx context.Context, secretRef *corev1.SecretKeySelector, namespace string) (string, error) {
		secret := &corev1.Secret{}
		secretKey := client.ObjectKey{
			Name:      secretRef.Name,
			Namespace: namespace,
		}
		if err := r.Get(ctx, secretKey, secret); err != nil {
			return "", fmt.Errorf("failed to get secret: %w", err)
		}
		passwordBytes, ok := secret.Data[secretRef.Key]
		if !ok {
			return "", fmt.Errorf("key %s not found in secret %s", secretRef.Key, secretRef.Name)
		}
		return string(passwordBytes), nil
	}

	if asya.Spec.Transport == transportTypeSQS {
		metrics, err = r.GetSQSQueueMetrics(ctx, asya, queueName)
	} else {
		metrics, err = transport.Config.GetQueueMetrics(ctx, queueName, asya.Namespace, passwordResolver)
	}

	if err != nil {
		logger.V(1).Info("Failed to get queue metrics", "error", err, "queue", queueName)
		return
	}

	asya.Status.QueuedMessages = &metrics.Queued
	asya.Status.ProcessingMessages = metrics.Processing

	logger.V(1).Info("Queue metrics updated", "queued", metrics.Queued, "processing", metrics.Processing)
}

// GetSQSQueueMetrics gets queue metrics for SQS using proper credentials
func (r *AsyncActorReconciler) GetSQSQueueMetrics(ctx context.Context, asya *asyav1alpha1.AsyncActor, queueName string) (*asyaconfig.QueueMetrics, error) {
	transport, err := r.TransportRegistry.GetTransport(transportTypeSQS)
	if err != nil {
		return nil, err
	}

	sqsConfig, ok := transport.Config.(*asyaconfig.SQSConfig)
	if !ok {
		return nil, fmt.Errorf("invalid SQS config type")
	}

	sqsClient, err := r.CreateSQSClient(ctx, sqsConfig, asya.Namespace)
	if err != nil {
		return nil, fmt.Errorf("failed to create SQS client: %w", err)
	}

	urlResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(queueName),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to get queue URL: %w", err)
	}

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

	return &asyaconfig.QueueMetrics{
		Queued:     queued,
		Processing: &processing,
	}, nil
}

// SetupWithManager sets up the controller with the Manager
func (r *AsyncActorReconciler) SetupWithManager(mgr ctrl.Manager) error {
	maxConcurrent := r.MaxConcurrentReconciles
	if maxConcurrent <= 0 {
		maxConcurrent = 1
	}

	bldr := ctrl.NewControllerManagedBy(mgr).
		For(&asyav1alpha1.AsyncActor{}, builder.WithPredicates(predicate.GenerationChangedPredicate{})).
		Owns(&appsv1.Deployment{}).
		Owns(&appsv1.StatefulSet{}).
		WithOptions(controller.Options{MaxConcurrentReconciles: maxConcurrent})

	return bldr.Complete(r)
}
