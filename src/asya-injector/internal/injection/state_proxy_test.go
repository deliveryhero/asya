package injection

import (
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/deliveryhero/asya/asya-injector/internal/config"
)

// makeBasicPod returns a pod with just a runtime container for state proxy tests.
func makeBasicPod() *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{
					Name:  runtimeContainerName,
					Image: "my-app:v1",
				},
			},
		},
	}
}

// makeInjector returns a basic injector for state proxy tests.
func makeInjector() *Injector {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}
	return NewInjector(cfg)
}

// getRuntimeContainer finds the runtime container in a pod, returns nil if not found.
func getRuntimeContainer(pod *corev1.Pod) *corev1.Container {
	for i := range pod.Spec.Containers {
		if pod.Spec.Containers[i].Name == runtimeContainerName {
			return &pod.Spec.Containers[i]
		}
	}
	return nil
}

// getContainer finds a container by name, returns nil if not found.
func getContainer(pod *corev1.Pod, name string) *corev1.Container {
	for i := range pod.Spec.Containers {
		if pod.Spec.Containers[i].Name == name {
			return &pod.Spec.Containers[i]
		}
	}
	return nil
}

// getEnvMap builds a name->value map from a container's Env slice.
func getEnvMap(c *corev1.Container) map[string]string {
	m := make(map[string]string)
	for _, e := range c.Env {
		m[e.Name] = e.Value
	}
	return m
}

// hasVolumeMount returns true if a container has a volume mount with the given name.
func hasVolumeMount(c *corev1.Container, name string) bool {
	for _, vm := range c.VolumeMounts {
		if vm.Name == name {
			return true
		}
	}
	return false
}

// hasVolume returns true if the pod has a volume with the given name.
func hasVolume(pod *corev1.Pod, name string) bool {
	for _, v := range pod.Spec.Volumes {
		if v.Name == name {
			return true
		}
	}
	return false
}

func TestInjectStateProxy_NoStateProxy(t *testing.T) {
	injector := makeInjector()
	pod := makeBasicPod()

	originalContainerCount := len(pod.Spec.Containers)
	originalVolumeCount := len(pod.Spec.Volumes)

	injector.injectStateProxy(pod, nil)

	if len(pod.Spec.Containers) != originalContainerCount {
		t.Errorf("expected %d containers, got %d", originalContainerCount, len(pod.Spec.Containers))
	}
	if len(pod.Spec.Volumes) != originalVolumeCount {
		t.Errorf("expected %d volumes, got %d", originalVolumeCount, len(pod.Spec.Volumes))
	}

	runtime := getRuntimeContainer(pod)
	if runtime == nil {
		t.Fatal("runtime container not found")
	}
	for _, e := range runtime.Env {
		if e.Name == "ASYA_STATE_PROXY_MOUNTS" {
			t.Error("ASYA_STATE_PROXY_MOUNTS should not be set when stateProxy is empty")
		}
	}
}

func TestInjectStateProxy_SingleMount(t *testing.T) {
	injector := makeInjector()
	pod := makeBasicPod()

	stateProxy := []StateProxyMount{
		{
			Name:           "cache",
			MountPath:      "/mnt/state/cache",
			ConnectorImage: "my-registry/redis-connector:v1",
			ConnectorEnv: []corev1.EnvVar{
				{Name: "REDIS_URL", Value: "redis://redis:6379"},
			},
		},
	}

	injector.injectStateProxy(pod, stateProxy)

	// State-sockets volume must be present
	if !hasVolume(pod, stateSocketsVolumeName) {
		t.Errorf("expected volume %q to be added", stateSocketsVolumeName)
	}

	// Connector container must be added
	connectorName := stateProxyPrefix + "cache"
	connector := getContainer(pod, connectorName)
	if connector == nil {
		t.Fatalf("expected connector container %q to be added", connectorName)
	}

	// Connector image must be set
	if connector.Image != "my-registry/redis-connector:v1" {
		t.Errorf("expected connector image %q, got %q", "my-registry/redis-connector:v1", connector.Image)
	}

	// Connector must have state-sockets volume mount
	if !hasVolumeMount(connector, stateSocketsVolumeName) {
		t.Errorf("connector container missing volume mount %q", stateSocketsVolumeName)
	}

	// Connector must have CONNECTOR_SOCKET env var
	connectorEnvMap := getEnvMap(connector)
	expectedSocket := stateSocketsDir + "/cache.sock"
	if connectorEnvMap["CONNECTOR_SOCKET"] != expectedSocket {
		t.Errorf("expected CONNECTOR_SOCKET=%q, got %q", expectedSocket, connectorEnvMap["CONNECTOR_SOCKET"])
	}

	// Connector must have the user-supplied env var
	if connectorEnvMap["REDIS_URL"] != "redis://redis:6379" {
		t.Errorf("expected REDIS_URL=redis://redis:6379, got %q", connectorEnvMap["REDIS_URL"])
	}

	// Runtime container must have state-sockets volume mount
	runtime := getRuntimeContainer(pod)
	if runtime == nil {
		t.Fatal("runtime container not found")
	}
	if !hasVolumeMount(runtime, stateSocketsVolumeName) {
		t.Errorf("runtime container missing volume mount %q", stateSocketsVolumeName)
	}

	// Runtime must have ASYA_STATE_PROXY_MOUNTS env var
	runtimeEnvMap := getEnvMap(runtime)
	mountsVal, ok := runtimeEnvMap["ASYA_STATE_PROXY_MOUNTS"]
	if !ok {
		t.Fatal("ASYA_STATE_PROXY_MOUNTS not set on runtime container")
	}
	// Format: name:path:write=mode
	expectedMounts := "cache:/mnt/state/cache:write=buffered"
	if mountsVal != expectedMounts {
		t.Errorf("expected ASYA_STATE_PROXY_MOUNTS=%q, got %q", expectedMounts, mountsVal)
	}
}

func TestInjectStateProxy_MultipleMounts(t *testing.T) {
	injector := makeInjector()
	pod := makeBasicPod()

	stateProxy := []StateProxyMount{
		{
			Name:           "cache",
			MountPath:      "/mnt/state/cache",
			ConnectorImage: "my-registry/redis-connector:v1",
		},
		{
			Name:           "store",
			MountPath:      "/mnt/state/store",
			ConnectorImage: "my-registry/s3-connector:v1",
			WriteMode:      "passthrough",
		},
	}

	injector.injectStateProxy(pod, stateProxy)

	// State-sockets volume must appear exactly once
	stateSocketsCount := 0
	for _, v := range pod.Spec.Volumes {
		if v.Name == stateSocketsVolumeName {
			stateSocketsCount++
		}
	}
	if stateSocketsCount != 1 {
		t.Errorf("expected exactly 1 %q volume, got %d", stateSocketsVolumeName, stateSocketsCount)
	}

	// Both connector containers must be added
	cacheConnector := getContainer(pod, stateProxyPrefix+"cache")
	if cacheConnector == nil {
		t.Fatal("expected cache connector container to be added")
	}
	storeConnector := getContainer(pod, stateProxyPrefix+"store")
	if storeConnector == nil {
		t.Fatal("expected store connector container to be added")
	}

	// ASYA_STATE_PROXY_MOUNTS must contain both mounts separated by semicolon
	runtime := getRuntimeContainer(pod)
	if runtime == nil {
		t.Fatal("runtime container not found")
	}
	runtimeEnvMap := getEnvMap(runtime)
	mountsVal, ok := runtimeEnvMap["ASYA_STATE_PROXY_MOUNTS"]
	if !ok {
		t.Fatal("ASYA_STATE_PROXY_MOUNTS not set on runtime container")
	}

	parts := strings.Split(mountsVal, ";")
	if len(parts) != 2 {
		t.Fatalf("expected 2 mount parts in ASYA_STATE_PROXY_MOUNTS, got %d: %q", len(parts), mountsVal)
	}

	if parts[0] != "cache:/mnt/state/cache:write=buffered" {
		t.Errorf("unexpected first mount part: %q", parts[0])
	}
	if parts[1] != "store:/mnt/state/store:write=passthrough" {
		t.Errorf("unexpected second mount part: %q", parts[1])
	}
}

func TestInferWriteMode(t *testing.T) {
	tests := []struct {
		image    string
		expected string
	}{
		{"my-registry/redis-connector:v1", "buffered"},
		{"my-registry/s3-passthrough-connector:v1", "passthrough"},
		{"passthrough:latest", "passthrough"},
		{"ghcr.io/org/my-passthrough-store:v2", "passthrough"},
		{"ghcr.io/org/buffered-store:v2", "buffered"},
		{"", "buffered"},
		{"redis:7", "buffered"},
	}

	for _, tt := range tests {
		t.Run(tt.image, func(t *testing.T) {
			got := inferWriteMode(tt.image)
			if got != tt.expected {
				t.Errorf("inferWriteMode(%q) = %q, want %q", tt.image, got, tt.expected)
			}
		})
	}
}

func TestInjectStateProxy_ConnectorSocketEnvVar(t *testing.T) {
	injector := makeInjector()
	pod := makeBasicPod()

	stateProxy := []StateProxyMount{
		{
			Name:           "my-db",
			MountPath:      "/mnt/state/db",
			ConnectorImage: "my-registry/db-connector:v1",
		},
	}

	injector.injectStateProxy(pod, stateProxy)

	connector := getContainer(pod, stateProxyPrefix+"my-db")
	if connector == nil {
		t.Fatal("connector container not found")
	}

	envMap := getEnvMap(connector)
	expectedSocket := stateSocketsDir + "/my-db.sock"
	if envMap["CONNECTOR_SOCKET"] != expectedSocket {
		t.Errorf("CONNECTOR_SOCKET: expected %q, got %q", expectedSocket, envMap["CONNECTOR_SOCKET"])
	}
}

func TestInjectStateProxy_ViaInject(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}
	injector := NewInjector(cfg)

	pod := makeBasicPod()
	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
		Region:    "us-east-1",
		StateProxy: []StateProxyMount{
			{
				Name:           "session",
				MountPath:      "/mnt/state/session",
				ConnectorImage: "my-registry/session-connector:v1",
				ConnectorEnv: []corev1.EnvVar{
					{Name: "SESSION_TTL", Value: "3600"},
				},
			},
		},
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	// Verify connector container was added via full Inject path
	connector := getContainer(mutated, stateProxyPrefix+"session")
	if connector == nil {
		t.Fatal("connector container not found after full Inject")
	}

	runtime := getRuntimeContainer(mutated)
	if runtime == nil {
		t.Fatal("runtime container not found after full Inject")
	}

	runtimeEnvMap := getEnvMap(runtime)
	if _, ok := runtimeEnvMap["ASYA_STATE_PROXY_MOUNTS"]; !ok {
		t.Error("ASYA_STATE_PROXY_MOUNTS not set on runtime after full Inject")
	}
}
