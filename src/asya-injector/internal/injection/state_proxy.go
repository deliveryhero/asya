package injection

import (
	"fmt"
	"strings"

	corev1 "k8s.io/api/core/v1"
)

const (
	stateSocketsVolumeName = "state-sockets"
	stateSocketsDir        = "/var/run/asya/state"
	stateProxyPrefix       = "asya-state-proxy-"
)

// injectStateProxy adds state proxy sidecar containers, volumes, and env vars to a pod.
// For each StateProxyMount, it:
// 1. Adds a sidecar container with the connector image
// 2. Adds the state-sockets volume
// 3. Generates ASYA_STATE_PROXY_MOUNTS env var for the runtime container
func (i *Injector) injectStateProxy(pod *corev1.Pod, stateProxy []StateProxyMount) {
	if len(stateProxy) == 0 {
		return
	}

	// Add state-sockets emptyDir volume
	pod.Spec.Volumes = appendVolumeIfNotExists(pod.Spec.Volumes, corev1.Volume{
		Name: stateSocketsVolumeName,
		VolumeSource: corev1.VolumeSource{
			EmptyDir: &corev1.EmptyDirVolumeSource{},
		},
	})

	// Build ASYA_STATE_PROXY_MOUNTS and inject connector containers
	var mountParts []string
	for _, sp := range stateProxy {
		writeMode := sp.WriteMode
		if writeMode == "" {
			writeMode = "buffered"
		}
		mountParts = append(mountParts, fmt.Sprintf("%s:%s:write=%s", sp.Name, sp.MountPath, writeMode))

		env := []corev1.EnvVar{
			{Name: "CONNECTOR_SOCKET", Value: fmt.Sprintf("%s/%s.sock", stateSocketsDir, sp.Name)},
		}
		env = append(env, sp.ConnectorEnv...)

		container := corev1.Container{
			Name:  stateProxyPrefix + sp.Name,
			Image: sp.ConnectorImage,
			Env:   env,
			VolumeMounts: []corev1.VolumeMount{
				{Name: stateSocketsVolumeName, MountPath: stateSocketsDir},
			},
		}
		if sp.Resources != nil {
			container.Resources = *sp.Resources
		}
		pod.Spec.Containers = append(pod.Spec.Containers, container)
	}

	// Add state-sockets volume mount and ASYA_STATE_PROXY_MOUNTS to runtime container
	for idx, c := range pod.Spec.Containers {
		if c.Name == runtimeContainerName {
			pod.Spec.Containers[idx].VolumeMounts = appendVolumeMountIfNotExists(
				pod.Spec.Containers[idx].VolumeMounts,
				corev1.VolumeMount{Name: stateSocketsVolumeName, MountPath: stateSocketsDir},
			)
			pod.Spec.Containers[idx].Env = appendEnvIfNotExists(
				pod.Spec.Containers[idx].Env,
				corev1.EnvVar{
					Name:  "ASYA_STATE_PROXY_MOUNTS",
					Value: strings.Join(mountParts, ";"),
				},
			)
			break
		}
	}
}

// inferWriteMode determines write mode from connector image name convention.
// Images containing "passthrough" use passthrough mode; everything else defaults to buffered.
func inferWriteMode(image string) string {
	if strings.Contains(image, "passthrough") {
		return "passthrough"
	}
	return "buffered"
}
