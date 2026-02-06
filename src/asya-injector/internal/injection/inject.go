package injection

import (
	"fmt"

	corev1 "k8s.io/api/core/v1"

	"github.com/deliveryhero/asya/asya-injector/internal/config"
)

const (
	sidecarContainerName = "asya-sidecar"
	runtimeContainerName = "asya-runtime"

	socketVolumeName  = "socket-dir"
	tmpVolumeName     = "tmp"
	runtimeVolumeName = "asya-runtime"

	actorNameHappyEnd = "happy-end"
	actorNameErrorEnd = "error-end"
)

// Injector handles sidecar injection into pods
type Injector struct {
	config *config.Config
}

// NewInjector creates a new Injector
func NewInjector(cfg *config.Config) *Injector {
	return &Injector{config: cfg}
}

// Inject injects the asya-sidecar and related configuration into a pod
func (i *Injector) Inject(pod *corev1.Pod, actorConfig *ActorConfig) (*corev1.Pod, error) {
	// Deep copy to avoid modifying the original
	mutated := pod.DeepCopy()

	// Determine sidecar image
	sidecarImage := i.config.SidecarImage
	if actorConfig.SidecarImage != "" {
		sidecarImage = actorConfig.SidecarImage
	}

	// Socket path for sidecar-runtime communication
	socketPath := i.config.SocketDir + "/asya-runtime.sock"

	// Build sidecar environment variables
	sidecarEnv := i.buildSidecarEnv(actorConfig)

	// Create sidecar container
	sidecar := corev1.Container{
		Name:            sidecarContainerName,
		Image:           sidecarImage,
		ImagePullPolicy: corev1.PullPolicy(i.config.SidecarImagePullPolicy),
		Env:             sidecarEnv,
		VolumeMounts: []corev1.VolumeMount{
			{
				Name:      socketVolumeName,
				MountPath: i.config.SocketDir,
			},
			{
				Name:      tmpVolumeName,
				MountPath: "/tmp",
			},
		},
	}

	// Inject AWS credentials from secret if configured
	if i.config.AWSCredsSecret != "" {
		sidecar.EnvFrom = append(sidecar.EnvFrom, corev1.EnvFromSource{
			SecretRef: &corev1.SecretEnvSource{
				LocalObjectReference: corev1.LocalObjectReference{
					Name: i.config.AWSCredsSecret,
				},
			},
		})
	}

	sidecarExists := false
	for i, c := range mutated.Spec.Containers {
		if c.Name == sidecarContainerName {
			mutated.Spec.Containers[i] = sidecar
			sidecarExists = true
			break
		}
	}
	if !sidecarExists {
		mutated.Spec.Containers = append(mutated.Spec.Containers, sidecar)
	}

	// Modify runtime container
	if err := i.modifyRuntimeContainer(mutated, actorConfig, socketPath); err != nil {
		return nil, err
	}

	// Add volumes
	i.addVolumes(mutated)

	// Set termination grace period
	gracePeriod := int64(30)
	mutated.Spec.TerminationGracePeriodSeconds = &gracePeriod

	return mutated, nil
}

// buildSidecarEnv builds environment variables for the sidecar container
func (i *Injector) buildSidecarEnv(actorConfig *ActorConfig) []corev1.EnvVar {
	env := []corev1.EnvVar{
		{Name: "ASYA_LOG_LEVEL", Value: "info"},
		{Name: "ASYA_SOCKET_DIR", Value: i.config.SocketDir},
		{Name: "ASYA_ACTOR_NAME", Value: actorConfig.ActorName},
		{Name: "ASYA_NAMESPACE", Value: actorConfig.Namespace},
		{Name: "ASYA_ACTOR_HAPPY_END", Value: actorNameHappyEnd},
		{Name: "ASYA_ACTOR_ERROR_END", Value: actorNameErrorEnd},
		{Name: "ASYA_TRANSPORT", Value: actorConfig.Transport},
	}

	// Add gateway URL if configured
	if i.config.GatewayURL != "" {
		env = append(env, corev1.EnvVar{
			Name:  "ASYA_GATEWAY_URL",
			Value: i.config.GatewayURL,
		})
	}

	// Add transport-specific configuration
	if actorConfig.Transport == "sqs" {
		env = append(env, corev1.EnvVar{
			Name:  "ASYA_AWS_REGION",
			Value: actorConfig.Region,
		})
		if i.config.SQSEndpoint != "" {
			env = append(env, corev1.EnvVar{
				Name:  "ASYA_SQS_ENDPOINT",
				Value: i.config.SQSEndpoint,
			})
		}
		if actorConfig.QueueURL != "" {
			env = append(env, corev1.EnvVar{
				Name:  "ASYA_QUEUE_URL",
				Value: actorConfig.QueueURL,
			})
		}
	}

	// Set ASYA_IS_END_ACTOR for end actors
	if actorConfig.ActorName == actorNameHappyEnd || actorConfig.ActorName == actorNameErrorEnd {
		env = append(env, corev1.EnvVar{
			Name:  "ASYA_IS_END_ACTOR",
			Value: "true",
		})
	}

	return env
}

// modifyRuntimeContainer modifies the runtime container to work with the sidecar
func (i *Injector) modifyRuntimeContainer(pod *corev1.Pod, actorConfig *ActorConfig, socketPath string) error {
	runtimeIdx := -1
	for idx, c := range pod.Spec.Containers {
		if c.Name == runtimeContainerName {
			runtimeIdx = idx
			break
		}
	}

	if runtimeIdx == -1 {
		return fmt.Errorf("runtime container '%s' not found in pod", runtimeContainerName)
	}

	runtime := &pod.Spec.Containers[runtimeIdx]

	// Set runtime command if not already set
	if len(runtime.Command) == 0 {
		pythonExec := actorConfig.PythonExecutable
		if pythonExec == "" {
			pythonExec = "python3"
		}
		runtime.Command = []string{pythonExec, i.config.RuntimeMountPath}
	}

	// Add ASYA_SOCKET_DIR environment variable
	runtime.Env = appendEnvIfNotExists(runtime.Env, corev1.EnvVar{
		Name:  "ASYA_SOCKET_DIR",
		Value: i.config.SocketDir,
	})

	// Disable validation for end actors
	if actorConfig.ActorName == actorNameHappyEnd || actorConfig.ActorName == actorNameErrorEnd {
		runtime.Env = appendEnvIfNotExists(runtime.Env, corev1.EnvVar{
			Name:  "ASYA_ENABLE_VALIDATION",
			Value: "false",
		})
	}

	// Add volume mounts
	runtime.VolumeMounts = appendVolumeMountIfNotExists(runtime.VolumeMounts, corev1.VolumeMount{
		Name:      socketVolumeName,
		MountPath: i.config.SocketDir,
	})
	runtime.VolumeMounts = appendVolumeMountIfNotExists(runtime.VolumeMounts, corev1.VolumeMount{
		Name:      tmpVolumeName,
		MountPath: "/tmp",
	})
	runtime.VolumeMounts = appendVolumeMountIfNotExists(runtime.VolumeMounts, corev1.VolumeMount{
		Name:      runtimeVolumeName,
		MountPath: i.config.RuntimeMountPath,
		SubPath:   "asya_runtime.py",
		ReadOnly:  true,
	})

	// Add probes
	i.addRuntimeProbes(runtime, socketPath)

	return nil
}

// addRuntimeProbes adds startup, liveness, and readiness probes to the runtime container
func (i *Injector) addRuntimeProbes(runtime *corev1.Container, socketPath string) {
	probeCommand := []string{
		"sh", "-c",
		fmt.Sprintf("test -S %s && test -f %s/runtime-ready", socketPath, i.config.SocketDir),
	}

	// Add startup probe if not set
	if runtime.StartupProbe == nil {
		runtime.StartupProbe = &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				Exec: &corev1.ExecAction{
					Command: probeCommand,
				},
			},
			InitialDelaySeconds: 3,
			PeriodSeconds:       2,
			TimeoutSeconds:      3,
			FailureThreshold:    150,
		}
	}

	// Add liveness probe if not set
	if runtime.LivenessProbe == nil {
		runtime.LivenessProbe = &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				Exec: &corev1.ExecAction{
					Command: probeCommand,
				},
			},
			InitialDelaySeconds: 0,
			PeriodSeconds:       30,
			TimeoutSeconds:      5,
			FailureThreshold:    3,
		}
	}

	// Add readiness probe if not set
	if runtime.ReadinessProbe == nil {
		runtime.ReadinessProbe = &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				Exec: &corev1.ExecAction{
					Command: probeCommand,
				},
			},
			InitialDelaySeconds: 0,
			PeriodSeconds:       10,
			TimeoutSeconds:      3,
			FailureThreshold:    3,
		}
	}
}

// addVolumes adds required volumes to the pod
func (i *Injector) addVolumes(pod *corev1.Pod) {
	// Socket directory volume
	pod.Spec.Volumes = appendVolumeIfNotExists(pod.Spec.Volumes, corev1.Volume{
		Name: socketVolumeName,
		VolumeSource: corev1.VolumeSource{
			EmptyDir: &corev1.EmptyDirVolumeSource{},
		},
	})

	// Tmp volume
	pod.Spec.Volumes = appendVolumeIfNotExists(pod.Spec.Volumes, corev1.Volume{
		Name: tmpVolumeName,
		VolumeSource: corev1.VolumeSource{
			EmptyDir: &corev1.EmptyDirVolumeSource{},
		},
	})

	// Runtime ConfigMap volume
	defaultMode := int32(0755)
	pod.Spec.Volumes = appendVolumeIfNotExists(pod.Spec.Volumes, corev1.Volume{
		Name: runtimeVolumeName,
		VolumeSource: corev1.VolumeSource{
			ConfigMap: &corev1.ConfigMapVolumeSource{
				LocalObjectReference: corev1.LocalObjectReference{
					Name: i.config.RuntimeConfigMap,
				},
				DefaultMode: &defaultMode,
			},
		},
	})
}

// appendEnvIfNotExists adds an env var if it doesn't already exist
func appendEnvIfNotExists(envs []corev1.EnvVar, newEnv corev1.EnvVar) []corev1.EnvVar {
	for _, e := range envs {
		if e.Name == newEnv.Name {
			return envs
		}
	}
	return append(envs, newEnv)
}

// appendVolumeMountIfNotExists adds a volume mount if it doesn't already exist
func appendVolumeMountIfNotExists(mounts []corev1.VolumeMount, newMount corev1.VolumeMount) []corev1.VolumeMount {
	for _, m := range mounts {
		if m.Name == newMount.Name && m.MountPath == newMount.MountPath {
			return mounts
		}
	}
	return append(mounts, newMount)
}

// appendVolumeIfNotExists adds a volume if it doesn't already exist
func appendVolumeIfNotExists(volumes []corev1.Volume, newVolume corev1.Volume) []corev1.Volume {
	for _, v := range volumes {
		if v.Name == newVolume.Name {
			return volumes
		}
	}
	return append(volumes, newVolume)
}
