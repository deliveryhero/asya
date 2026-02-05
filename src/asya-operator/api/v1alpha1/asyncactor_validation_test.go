package v1alpha1

import (
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/validation/field"
)

// TestAsyncActorValidation_RequiredFields tests that required fields are validated
func TestAsyncActorValidation_RequiredFields(t *testing.T) {
	tests := []struct {
		name        string
		actor       *AsyncActor
		expectValid bool
		errorField  string
	}{
		{
			name: "valid minimal actor",
			actor: &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{
										Name:  "asya-runtime",
										Image: "python:3.13-slim",
									},
								},
							},
						},
					},
				},
			},
			expectValid: true,
		},
		{
			name: "missing transport",
			actor: &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "",
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{
										Name:  "asya-runtime",
										Image: "python:3.13-slim",
									},
								},
							},
						},
					},
				},
			},
			expectValid: false,
			errorField:  "spec.transport",
		},
		{
			name: "missing workload",
			actor: &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
				},
			},
			expectValid: false,
			errorField:  "spec.workload",
		},
		{
			name: "empty containers in workload",
			actor: &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{},
							},
						},
					},
				},
			},
			expectValid: false,
			errorField:  "spec.workload.template.spec.containers",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateAsyncActor(tt.actor)
			if tt.expectValid && err != nil {
				t.Errorf("Expected valid actor, got error: %v", err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("Expected validation error for field %s, got none", tt.errorField)
			}
		})
	}
}

// TestAsyncActorValidation_ScalingConfig tests scaling configuration validation
func TestAsyncActorValidation_ScalingConfig(t *testing.T) {
	tests := []struct {
		name        string
		scaling     ScalingConfig
		expectValid bool
		description string
	}{
		{
			name: "valid scaling config",
			scaling: ScalingConfig{
				Enabled:     true,
				MinReplicas: ptr(int32(0)),
				MaxReplicas: ptr(int32(10)),
				QueueLength: 5,
			},
			expectValid: true,
			description: "standard scaling configuration",
		},
		{
			name: "minReplicas greater than maxReplicas",
			scaling: ScalingConfig{
				Enabled:     true,
				MinReplicas: ptr(int32(10)),
				MaxReplicas: ptr(int32(5)),
				QueueLength: 5,
			},
			expectValid: false,
			description: "minReplicas > maxReplicas should be invalid",
		},
		{
			name: "negative minReplicas",
			scaling: ScalingConfig{
				Enabled:     true,
				MinReplicas: ptr(int32(-1)),
				MaxReplicas: ptr(int32(10)),
				QueueLength: 5,
			},
			expectValid: false,
			description: "negative minReplicas should be rejected",
		},
		{
			name: "zero maxReplicas",
			scaling: ScalingConfig{
				Enabled:     true,
				MinReplicas: ptr(int32(0)),
				MaxReplicas: ptr(int32(0)),
				QueueLength: 5,
			},
			expectValid: false,
			description: "maxReplicas must be at least 1",
		},
		{
			name: "zero queueLength",
			scaling: ScalingConfig{
				Enabled:     true,
				MinReplicas: ptr(int32(0)),
				MaxReplicas: ptr(int32(10)),
				QueueLength: 0,
			},
			expectValid: false,
			description: "queueLength must be at least 1",
		},
		{
			name: "negative queueLength",
			scaling: ScalingConfig{
				Enabled:     true,
				MinReplicas: ptr(int32(0)),
				MaxReplicas: ptr(int32(10)),
				QueueLength: -5,
			},
			expectValid: false,
			description: "negative queueLength should be rejected",
		},
		{
			name: "valid advanced scaling",
			scaling: ScalingConfig{
				Enabled:     true,
				MinReplicas: ptr(int32(0)),
				MaxReplicas: ptr(int32(50)),
				QueueLength: 10,
				Advanced: &AdvancedScalingConfig{
					Formula:          "ceil(queueLength / 10)",
					Target:           "10",
					ActivationTarget: "5",
					MetricType:       "AverageValue",
				},
			},
			expectValid: true,
			description: "advanced scaling with valid parameters",
		},
		{
			name: "invalid metricType",
			scaling: ScalingConfig{
				Enabled:     true,
				MinReplicas: ptr(int32(0)),
				MaxReplicas: ptr(int32(50)),
				QueueLength: 10,
				Advanced: &AdvancedScalingConfig{
					MetricType: "InvalidType",
				},
			},
			expectValid: false,
			description: "metricType must be AverageValue, Value, or Utilization",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Scaling:   tt.scaling,
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{
										Name:  "asya-runtime",
										Image: "python:3.13-slim",
									},
								},
							},
						},
					},
				},
			}

			err := validateAsyncActor(actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// TestAsyncActorValidation_WorkloadConfig tests workload configuration validation
func TestAsyncActorValidation_WorkloadConfig(t *testing.T) {
	tests := []struct {
		name        string
		workload    WorkloadConfig
		expectValid bool
		description string
	}{
		{
			name: "valid Deployment workload",
			workload: WorkloadConfig{
				Kind:     "Deployment",
				Replicas: ptr(int32(3)),
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
			expectValid: true,
			description: "Deployment is a valid workload kind",
		},
		{
			name: "valid StatefulSet workload",
			workload: WorkloadConfig{
				Kind:     "StatefulSet",
				Replicas: ptr(int32(3)),
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
			expectValid: true,
			description: "StatefulSet is a valid workload kind",
		},
		{
			name: "invalid workload kind - Pod",
			workload: WorkloadConfig{
				Kind:     "Pod",
				Replicas: ptr(int32(1)),
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
			expectValid: false,
			description: "Pod is not a valid workload kind",
		},
		{
			name: "invalid workload kind - DaemonSet",
			workload: WorkloadConfig{
				Kind:     "DaemonSet",
				Replicas: ptr(int32(1)),
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
			expectValid: false,
			description: "DaemonSet is not a valid workload kind",
		},
		{
			name: "negative replicas",
			workload: WorkloadConfig{
				Kind:     "Deployment",
				Replicas: ptr(int32(-1)),
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
			expectValid: false,
			description: "replicas cannot be negative",
		},
		{
			name: "container named asya-sidecar conflicts",
			workload: WorkloadConfig{
				Kind: "Deployment",
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-sidecar",
								Image: "malicious:latest",
							},
						},
					},
				},
			},
			expectValid: false,
			description: "user containers cannot be named asya-sidecar",
		},
		{
			name: "container not named asya-runtime",
			workload: WorkloadConfig{
				Kind: "Deployment",
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
			expectValid: false,
			description: "runtime container must be named asya-runtime",
		},
		{
			name: "asya-runtime container with command override",
			workload: WorkloadConfig{
				Kind: "Deployment",
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:    "asya-runtime",
								Image:   "python:3.13-slim",
								Command: []string{"python", "malicious.py"},
							},
						},
					},
				},
			},
			expectValid: false,
			description: "asya-runtime container cannot override command",
		},
		{
			name: "valid asya-runtime container without command",
			workload: WorkloadConfig{
				Kind: "Deployment",
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
			expectValid: true,
			description: "asya-runtime container without command is valid",
		},
		{
			name: "missing container name",
			workload: WorkloadConfig{
				Kind: "Deployment",
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "",
								Image: "python:3.13-slim",
							},
						},
					},
				},
			},
			expectValid: false,
			description: "container name is required",
		},
		{
			name: "missing container image",
			workload: WorkloadConfig{
				Kind: "Deployment",
				Template: PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "",
							},
						},
					},
				},
			},
			expectValid: false,
			description: "container image is required",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Workload:  tt.workload,
				},
			}

			err := validateAsyncActor(actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// TestAsyncActorValidation_SidecarConfig tests sidecar configuration validation
func TestAsyncActorValidation_SidecarConfig(t *testing.T) {
	tests := []struct {
		name        string
		sidecar     SidecarConfig
		expectValid bool
		description string
	}{
		{
			name: "valid sidecar config",
			sidecar: SidecarConfig{
				Image:           "asya-sidecar:v1.0.0",
				ImagePullPolicy: corev1.PullIfNotPresent,
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("500m"),
						corev1.ResourceMemory: resource.MustParse("256Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("128Mi"),
					},
				},
			},
			expectValid: true,
			description: "valid sidecar configuration",
		},
		{
			name: "invalid imagePullPolicy",
			sidecar: SidecarConfig{
				Image:           "asya-sidecar:v1.0.0",
				ImagePullPolicy: "InvalidPolicy",
			},
			expectValid: false,
			description: "imagePullPolicy must be Always, IfNotPresent, or Never",
		},
		{
			name: "resource limits less than requests - validated by Kubernetes",
			sidecar: SidecarConfig{
				Image: "asya-sidecar:v1.0.0",
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU: resource.MustParse("100m"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU: resource.MustParse("500m"),
					},
				},
			},
			expectValid: true,
			description: "resource limits validation is handled by Kubernetes API, not CRD validation",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Sidecar:   tt.sidecar,
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{
										Name:  "asya-runtime",
										Image: "python:3.13-slim",
									},
								},
							},
						},
					},
				},
			}

			err := validateAsyncActor(actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// TestAsyncActorValidation_TimeoutConfig tests timeout configuration validation
func TestAsyncActorValidation_TimeoutConfig(t *testing.T) {
	tests := []struct {
		name        string
		timeout     TimeoutConfig
		expectValid bool
		description string
	}{
		{
			name: "valid timeout config",
			timeout: TimeoutConfig{
				Processing:       300,
				GracefulShutdown: 30,
			},
			expectValid: true,
			description: "standard timeout configuration",
		},
		{
			name: "negative processing timeout",
			timeout: TimeoutConfig{
				Processing:       -1,
				GracefulShutdown: 30,
			},
			expectValid: false,
			description: "processing timeout cannot be negative",
		},
		{
			name: "negative graceful shutdown timeout",
			timeout: TimeoutConfig{
				Processing:       300,
				GracefulShutdown: -10,
			},
			expectValid: false,
			description: "graceful shutdown timeout cannot be negative",
		},
		{
			name: "zero processing timeout is valid",
			timeout: TimeoutConfig{
				Processing:       0,
				GracefulShutdown: 30,
			},
			expectValid: true,
			description: "zero processing timeout means no timeout",
		},
		{
			name: "very large timeout",
			timeout: TimeoutConfig{
				Processing:       86400,
				GracefulShutdown: 300,
			},
			expectValid: true,
			description: "large timeouts are valid for long-running tasks",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Timeout:   tt.timeout,
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{
										Name:  "asya-runtime",
										Image: "python:3.13-slim",
									},
								},
							},
						},
					},
				},
			}

			err := validateAsyncActor(actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// Socket configuration is no longer user-configurable - hardcoded to /var/run/asya/asya-runtime.sock
// Tests removed as socket config validation is no longer needed

// Helper function to validate AsyncActor
// This demonstrates the validation logic that should be implemented in a webhook or admission controller
func validateAsyncActor(actor *AsyncActor) error {
	allErrs := field.ErrorList{}

	allErrs = append(allErrs, validateTransportAndWorkload(actor)...)
	allErrs = append(allErrs, validateContainers(actor)...)
	allErrs = append(allErrs, validateScaling(actor)...)
	allErrs = append(allErrs, validateSidecarAndTimeouts(actor)...)

	if len(allErrs) > 0 {
		return allErrs.ToAggregate()
	}

	return nil
}

func validateTransportAndWorkload(actor *AsyncActor) field.ErrorList {
	allErrs := field.ErrorList{}

	if actor.Spec.Transport == "" {
		allErrs = append(allErrs, field.Required(field.NewPath("spec", "transport"), "transport is required"))
	}

	if len(actor.Spec.Workload.Template.Spec.Containers) == 0 {
		allErrs = append(allErrs, field.Required(field.NewPath("spec", "workload", "template", "spec", "containers"), "at least one container is required"))
	}

	if actor.Spec.Workload.Kind != "" && actor.Spec.Workload.Kind != "Deployment" && actor.Spec.Workload.Kind != "StatefulSet" {
		allErrs = append(allErrs, field.NotSupported(field.NewPath("spec", "workload", "kind"), actor.Spec.Workload.Kind, []string{"Deployment", "StatefulSet"}))
	}

	if actor.Spec.Workload.Replicas != nil && *actor.Spec.Workload.Replicas < 0 {
		allErrs = append(allErrs, field.Invalid(field.NewPath("spec", "workload", "replicas"), *actor.Spec.Workload.Replicas, "replicas cannot be negative"))
	}

	return allErrs
}

func validateContainers(actor *AsyncActor) field.ErrorList {
	allErrs := field.ErrorList{}

	hasRuntimeContainer := false
	for i, container := range actor.Spec.Workload.Template.Spec.Containers {
		containerPath := field.NewPath("spec", "workload", "template", "spec", "containers").Index(i)
		if container.Name == "" {
			allErrs = append(allErrs, field.Required(containerPath.Child("name"), "container name is required"))
		}
		if container.Name == "asya-sidecar" {
			allErrs = append(allErrs, field.Invalid(containerPath.Child("name"), container.Name, "container name 'asya-sidecar' is reserved for the injected sidecar"))
		}
		if container.Name == "asya-runtime" {
			hasRuntimeContainer = true
			if len(container.Command) > 0 {
				allErrs = append(allErrs, field.Invalid(containerPath.Child("command"), container.Command, "container 'asya-runtime' cannot override command (command is managed by operator)"))
			}
		}
		if container.Image == "" {
			allErrs = append(allErrs, field.Required(containerPath.Child("image"), "container image is required"))
		}
	}

	if !hasRuntimeContainer {
		allErrs = append(allErrs, field.Required(field.NewPath("spec", "workload", "template", "spec", "containers"), "workload must contain exactly one container named 'asya-runtime'"))
	}

	return allErrs
}

func validateScaling(actor *AsyncActor) field.ErrorList {
	allErrs := field.ErrorList{}

	if actor.Spec.Scaling.MinReplicas != nil && *actor.Spec.Scaling.MinReplicas < 0 {
		allErrs = append(allErrs, field.Invalid(field.NewPath("spec", "scaling", "minReplicas"), *actor.Spec.Scaling.MinReplicas, "minReplicas cannot be negative"))
	}

	if actor.Spec.Scaling.MaxReplicas != nil && *actor.Spec.Scaling.MaxReplicas < 1 {
		allErrs = append(allErrs, field.Invalid(field.NewPath("spec", "scaling", "maxReplicas"), *actor.Spec.Scaling.MaxReplicas, "maxReplicas must be at least 1"))
	}

	if actor.Spec.Scaling.MinReplicas != nil && actor.Spec.Scaling.MaxReplicas != nil && *actor.Spec.Scaling.MinReplicas > *actor.Spec.Scaling.MaxReplicas {
		allErrs = append(allErrs, field.Invalid(field.NewPath("spec", "scaling", "minReplicas"), *actor.Spec.Scaling.MinReplicas, "minReplicas cannot be greater than maxReplicas"))
	}

	if actor.Spec.Scaling.QueueLength < 0 {
		allErrs = append(allErrs, field.Invalid(field.NewPath("spec", "scaling", "queueLength"), actor.Spec.Scaling.QueueLength, "queueLength cannot be negative"))
	}

	if actor.Spec.Scaling.QueueLength == 0 && actor.Spec.Scaling.Enabled {
		allErrs = append(allErrs, field.Invalid(field.NewPath("spec", "scaling", "queueLength"), actor.Spec.Scaling.QueueLength, "queueLength must be at least 1 when scaling is enabled"))
	}

	if actor.Spec.Scaling.Advanced != nil && actor.Spec.Scaling.Advanced.MetricType != "" {
		validMetricTypes := []string{"AverageValue", "Value", "Utilization"}
		valid := false
		for _, mt := range validMetricTypes {
			if actor.Spec.Scaling.Advanced.MetricType == mt {
				valid = true
				break
			}
		}
		if !valid {
			allErrs = append(allErrs, field.NotSupported(field.NewPath("spec", "scaling", "advanced", "metricType"), actor.Spec.Scaling.Advanced.MetricType, validMetricTypes))
		}
	}

	return allErrs
}

func validateSidecarAndTimeouts(actor *AsyncActor) field.ErrorList {
	allErrs := field.ErrorList{}

	if actor.Spec.Sidecar.ImagePullPolicy != "" && actor.Spec.Sidecar.ImagePullPolicy != corev1.PullAlways && actor.Spec.Sidecar.ImagePullPolicy != corev1.PullIfNotPresent && actor.Spec.Sidecar.ImagePullPolicy != corev1.PullNever {
		allErrs = append(allErrs, field.NotSupported(field.NewPath("spec", "sidecar", "imagePullPolicy"), actor.Spec.Sidecar.ImagePullPolicy, []string{string(corev1.PullAlways), string(corev1.PullIfNotPresent), string(corev1.PullNever)}))
	}

	if actor.Spec.Timeout.Processing < 0 {
		allErrs = append(allErrs, field.Invalid(field.NewPath("spec", "timeout", "processing"), actor.Spec.Timeout.Processing, "processing timeout cannot be negative"))
	}

	if actor.Spec.Timeout.GracefulShutdown < 0 {
		allErrs = append(allErrs, field.Invalid(field.NewPath("spec", "timeout", "gracefulShutdown"), actor.Spec.Timeout.GracefulShutdown, "graceful shutdown timeout cannot be negative"))
	}

	return allErrs
}

// TestAsyncActorValidation_VolumeMountConflicts tests volume mount conflicts
func TestAsyncActorValidation_VolumeMountConflicts(t *testing.T) {
	tests := []struct {
		name        string
		volumes     []corev1.Volume
		mounts      []corev1.VolumeMount
		expectValid bool
		description string
	}{
		{
			name: "volume named socket-dir conflicts with injected volume",
			volumes: []corev1.Volume{
				{
					Name: "socket-dir",
					VolumeSource: corev1.VolumeSource{
						EmptyDir: &corev1.EmptyDirVolumeSource{},
					},
				},
			},
			expectValid: false,
			description: "socket-dir is reserved for sidecar communication",
		},
		{
			name: "volume named tmp conflicts with injected volume",
			volumes: []corev1.Volume{
				{
					Name: "tmp",
					VolumeSource: corev1.VolumeSource{
						EmptyDir: &corev1.EmptyDirVolumeSource{},
					},
				},
			},
			expectValid: false,
			description: "tmp is reserved for runtime tmp directory",
		},
		{
			name: "volume named asya-runtime conflicts with injected volume",
			volumes: []corev1.Volume{
				{
					Name: "asya-runtime",
					VolumeSource: corev1.VolumeSource{
						EmptyDir: &corev1.EmptyDirVolumeSource{},
					},
				},
			},
			expectValid: false,
			description: "asya-runtime is reserved for runtime script injection",
		},
		{
			name: "mount to /var/run/asya conflicts with sidecar socket path",
			mounts: []corev1.VolumeMount{
				{
					Name:      "my-volume",
					MountPath: "/var/run/asya",
				},
			},
			expectValid: false,
			description: "/var/run/asya is reserved for Unix socket communication",
		},
		{
			name: "mount to /opt/asya/asya_runtime.py conflicts with runtime script",
			mounts: []corev1.VolumeMount{
				{
					Name:      "my-volume",
					MountPath: "/opt/asya/asya_runtime.py",
				},
			},
			expectValid: false,
			description: "/opt/asya/asya_runtime.py is reserved for runtime script",
		},
		{
			name: "valid user volumes and mounts",
			volumes: []corev1.Volume{
				{
					Name: "data",
					VolumeSource: corev1.VolumeSource{
						EmptyDir: &corev1.EmptyDirVolumeSource{},
					},
				},
			},
			mounts: []corev1.VolumeMount{
				{
					Name:      "data",
					MountPath: "/data",
				},
			},
			expectValid: true,
			description: "user-defined volumes should be allowed",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Volumes: tt.volumes,
								Containers: []corev1.Container{
									{
										Name:         "asya-runtime",
										Image:        "python:3.13-slim",
										VolumeMounts: tt.mounts,
									},
								},
							},
						},
					},
				},
			}

			err := validateAsyncActorAdvanced(actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// TestAsyncActorValidation_NamingConflicts tests naming conflicts and restrictions
func TestAsyncActorValidation_NamingConflicts(t *testing.T) {
	tests := []struct {
		name        string
		actorName   string
		expectValid bool
		description string
	}{
		{
			name:        "reserved name happy-end",
			actorName:   "happy-end",
			expectValid: true,
			description: "happy-end is a valid reserved actor name",
		},
		{
			name:        "reserved name error-end",
			actorName:   "error-end",
			expectValid: true,
			description: "error-end is a valid reserved actor name",
		},
		{
			name:        "name with uppercase letters",
			actorName:   "MyActor",
			expectValid: false,
			description: "Kubernetes resource names must be lowercase",
		},
		{
			name:        "name with underscores",
			actorName:   "my_actor",
			expectValid: false,
			description: "Kubernetes resource names cannot contain underscores",
		},
		{
			name:        "name starting with number",
			actorName:   "1-actor",
			expectValid: false,
			description: "Kubernetes resource names cannot start with numbers",
		},
		{
			name:        "name with special characters",
			actorName:   "actor@test",
			expectValid: false,
			description: "Kubernetes resource names can only contain lowercase alphanumeric and hyphens",
		},
		{
			name:        "valid name with hyphens",
			actorName:   "my-cool-actor",
			expectValid: true,
			description: "lowercase alphanumeric with hyphens is valid",
		},
		{
			name:        "very long name",
			actorName:   "this-is-a-very-long-actor-name-that-exceeds-the-kubernetes-resource-name-limit-of-253-characters-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			expectValid: false,
			description: "names longer than 253 characters are invalid",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      tt.actorName,
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{
										Name:  "asya-runtime",
										Image: "python:3.13-slim",
									},
								},
							},
						},
					},
				},
			}

			err := validateAsyncActorAdvanced(actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// TestAsyncActorValidation_EnvironmentVariableConflicts tests env var conflicts
func TestAsyncActorValidation_EnvironmentVariableConflicts(t *testing.T) {
	tests := []struct {
		name        string
		env         []corev1.EnvVar
		expectValid bool
		description string
	}{
		{
			name: "ASYA_SOCKET_DIR reserved env var",
			env: []corev1.EnvVar{
				{Name: "ASYA_SOCKET_DIR", Value: "/custom/path"},
			},
			expectValid: false,
			description: "ASYA_SOCKET_DIR is injected by operator",
		},
		{
			name: "ASYA_HANDLER user-defined is allowed",
			env: []corev1.EnvVar{
				{Name: "ASYA_HANDLER", Value: "my_module.handler"},
			},
			expectValid: true,
			description: "ASYA_HANDLER is user-configurable",
		},
		{
			name: "ASYA_ENABLE_VALIDATION reserved env var",
			env: []corev1.EnvVar{
				{Name: "ASYA_ENABLE_VALIDATION", Value: "false"},
			},
			expectValid: false,
			description: "ASYA_ENABLE_VALIDATION is managed by operator for end actors",
		},
		{
			name: "custom env vars are allowed",
			env: []corev1.EnvVar{
				{Name: "MY_VAR", Value: "value"},
				{Name: "DATABASE_URL", Value: "postgres://localhost"},
			},
			expectValid: true,
			description: "user-defined env vars should be allowed",
		},
		{
			name: "ASYA_HANDLER_MODE user-defined is allowed",
			env: []corev1.EnvVar{
				{Name: "ASYA_HANDLER_MODE", Value: "envelope"},
			},
			expectValid: true,
			description: "ASYA_HANDLER_MODE is user-configurable",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{
										Name:  "asya-runtime",
										Image: "python:3.13-slim",
										Env:   tt.env,
									},
								},
							},
						},
					},
				},
			}

			err := validateAsyncActorAdvanced(actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// TestAsyncActorValidation_MultipleContainers tests multi-container scenarios
func TestAsyncActorValidation_MultipleContainers(t *testing.T) {
	tests := []struct {
		name        string
		containers  []corev1.Container
		expectValid bool
		description string
	}{
		{
			name: "multiple containers with asya-runtime is valid",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{Name: "helper", Image: "helper:latest"},
			},
			expectValid: true,
			description: "multiple containers for sidecars/helpers is allowed",
		},
		{
			name: "one container named asya-sidecar conflicts",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{Name: "asya-sidecar", Image: "malicious:latest"},
			},
			expectValid: false,
			description: "asya-sidecar name is reserved",
		},
		{
			name: "duplicate container names",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{Name: "asya-runtime", Image: "python:3.11-slim"},
			},
			expectValid: false,
			description: "duplicate container names are invalid",
		},
		{
			name: "valid multi-container with unique names",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{Name: "redis", Image: "redis:7-alpine"},
				{Name: "nginx", Image: "nginx:alpine"},
			},
			expectValid: true,
			description: "multiple containers with unique names is valid",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actor := &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: tt.containers,
							},
						},
					},
				},
			}

			err := validateAsyncActorAdvanced(actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// TestAsyncActorValidation_EdgeCases tests various edge cases
func TestAsyncActorValidation_EdgeCases(t *testing.T) {
	tests := []struct {
		name        string
		actor       *AsyncActor
		expectValid bool
		description string
	}{
		{
			name: "scaling enabled with zero minReplicas and maxReplicas is valid",
			actor: &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Scaling: ScalingConfig{
						Enabled:     true,
						MinReplicas: ptr(int32(0)),
						MaxReplicas: ptr(int32(1)),
						QueueLength: 1,
					},
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{Name: "asya-runtime", Image: "python:3.13-slim"},
								},
							},
						},
					},
				},
			},
			expectValid: true,
			description: "scale-to-zero is valid with maxReplicas >= 1",
		},
		{
			name: "workload replicas ignored when scaling enabled",
			actor: &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Scaling: ScalingConfig{
						Enabled:     true,
						MinReplicas: ptr(int32(0)),
						MaxReplicas: ptr(int32(10)),
						QueueLength: 5,
					},
					Workload: WorkloadConfig{
						Replicas: ptr(int32(3)),
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{Name: "asya-runtime", Image: "python:3.13-slim"},
								},
							},
						},
					},
				},
			},
			expectValid: true,
			description: "workload replicas is ignored when KEDA scaling is enabled",
		},
		{
			name: "very large polling interval",
			actor: &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Scaling: ScalingConfig{
						Enabled:         true,
						PollingInterval: 3600,
						MinReplicas:     ptr(int32(0)),
						MaxReplicas:     ptr(int32(10)),
						QueueLength:     5,
					},
					Workload: WorkloadConfig{
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{Name: "asya-runtime", Image: "python:3.13-slim"},
								},
							},
						},
					},
				},
			},
			expectValid: true,
			description: "large polling intervals are valid for low-priority actors",
		},
		{
			name: "empty python executable uses default",
			actor: &AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: AsyncActorSpec{
					Transport: "rabbitmq",
					Workload: WorkloadConfig{
						PythonExecutable: "",
						Template: PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: []corev1.Container{
									{Name: "asya-runtime", Image: "python:3.13-slim"},
								},
							},
						},
					},
				},
			},
			expectValid: true,
			description: "empty pythonExecutable defaults to python3",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateAsyncActor(tt.actor)
			if tt.expectValid && err != nil {
				t.Errorf("%s: expected valid, got error: %v", tt.description, err)
			}
			if !tt.expectValid && err == nil {
				t.Errorf("%s: expected validation error, got none", tt.description)
			}
		})
	}
}

// validateAsyncActorAdvanced performs advanced validation including conflict detection
func validateAsyncActorAdvanced(actor *AsyncActor) error {
	allErrs := field.ErrorList{}

	// First run basic validation
	if err := validateAsyncActor(actor); err != nil {
		return err
	}

	// Check for reserved volume names
	reservedVolumeNames := map[string]bool{
		"socket-dir":   true,
		"tmp":          true,
		"asya-runtime": true,
	}

	for i, volume := range actor.Spec.Workload.Template.Spec.Volumes {
		volumePath := field.NewPath("spec", "workload", "template", "spec", "volumes").Index(i)
		if reservedVolumeNames[volume.Name] {
			allErrs = append(allErrs, field.Invalid(volumePath.Child("name"), volume.Name, "volume name is reserved for operator injection"))
		}
	}

	// Check for reserved volume mount paths
	reservedMountPaths := map[string]bool{
		"/var/run/asya":             true,
		"/opt/asya/asya_runtime.py": true,
	}

	for i, container := range actor.Spec.Workload.Template.Spec.Containers {
		containerPath := field.NewPath("spec", "workload", "template", "spec", "containers").Index(i)

		for j, mount := range container.VolumeMounts {
			mountPath := containerPath.Child("volumeMounts").Index(j)
			if reservedMountPaths[mount.MountPath] {
				allErrs = append(allErrs, field.Invalid(mountPath.Child("mountPath"), mount.MountPath, "mount path is reserved for operator injection"))
			}
		}

		// Check for reserved environment variables
		reservedEnvVars := map[string]bool{
			"ASYA_SOCKET_DIR":        true,
			"ASYA_ENABLE_VALIDATION": true,
		}

		for j, env := range container.Env {
			envPath := containerPath.Child("env").Index(j)
			if reservedEnvVars[env.Name] {
				allErrs = append(allErrs, field.Invalid(envPath.Child("name"), env.Name, "environment variable is reserved for operator injection"))
			}
		}
	}

	// Check for duplicate container names
	containerNames := make(map[string]bool)
	for i, container := range actor.Spec.Workload.Template.Spec.Containers {
		containerPath := field.NewPath("spec", "workload", "template", "spec", "containers").Index(i)
		if containerNames[container.Name] {
			allErrs = append(allErrs, field.Duplicate(containerPath.Child("name"), container.Name))
		}
		containerNames[container.Name] = true
	}

	// Validate Kubernetes resource name format
	if !isValidK8sName(actor.Name) {
		allErrs = append(allErrs, field.Invalid(field.NewPath("metadata", "name"), actor.Name, "must be a valid Kubernetes resource name (lowercase alphanumeric or '-', max 253 chars)"))
	}

	if len(allErrs) > 0 {
		return allErrs.ToAggregate()
	}

	return nil
}

// isValidK8sName validates Kubernetes resource name format
func isValidK8sName(name string) bool {
	if len(name) == 0 || len(name) > 253 {
		return false
	}

	// Must start with alphanumeric
	if name[0] < 'a' || name[0] > 'z' {
		if name[0] < '0' || name[0] > '9' {
			return false
		}
		// Cannot start with number
		return false
	}

	// Check all characters
	for _, c := range name {
		if (c < 'a' || c > 'z') && (c < '0' || c > '9') && c != '-' {
			return false
		}
	}

	return true
}

// ptr is a helper to create pointers to primitives
func ptr[T any](v T) *T {
	return &v
}
