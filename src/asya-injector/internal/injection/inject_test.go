package injection

import (
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/deliveryhero/asya/asya-injector/internal/config"
)

func TestInjector_Inject(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
		GatewayURL:             "http://gateway.default.svc:8080",
		SQSEndpoint:            "http://localstack:4566",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{
					Name:  "asya-runtime",
					Image: "my-app:v1",
				},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName:   "my-actor",
		Namespace:   "default",
		Transport:   "sqs",
		QueueURL:    "http://sqs.localhost:4566/000000000000/asya-default-my-actor",
		Handler:     "my_module.process",
		HandlerMode: "payload",
		Region:      "us-east-1",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	// Verify sidecar was added
	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}
	if sidecar == nil {
		t.Fatal("sidecar container was not added")
	}

	// Verify sidecar image
	if sidecar.Image != "ghcr.io/deliveryhero/asya-sidecar:test" {
		t.Errorf("expected sidecar image %q, got %q", "ghcr.io/deliveryhero/asya-sidecar:test", sidecar.Image)
	}

	// Verify sidecar environment variables
	sidecarEnv := make(map[string]string)
	for _, e := range sidecar.Env {
		sidecarEnv[e.Name] = e.Value
	}

	expectedEnv := map[string]string{
		"ASYA_SOCKET_DIR":      "/var/run/asya",
		"ASYA_ACTOR_NAME":      "my-actor",
		"ASYA_NAMESPACE":       "default",
		"ASYA_TRANSPORT":       "sqs",
		"ASYA_GATEWAY_URL":     "http://gateway.default.svc:8080",
		"ASYA_AWS_REGION":      "us-east-1",
		"ASYA_SQS_ENDPOINT":    "http://localstack:4566",
		"ASYA_QUEUE_URL":       "http://sqs.localhost:4566/000000000000/asya-default-my-actor",
		"ASYA_ACTOR_SINK":      "x-sink",
		"ASYA_ACTOR_HAPPY_END": "happy-end",
		"ASYA_ACTOR_ERROR_END": "error-end",
	}

	for key, expected := range expectedEnv {
		if actual, ok := sidecarEnv[key]; !ok {
			t.Errorf("missing env var %s", key)
		} else if actual != expected {
			t.Errorf("env var %s: expected %q, got %q", key, expected, actual)
		}
	}

	// Verify no resiliency env vars when not configured
	resiliencyVars := []string{
		"ASYA_RESILIENCY_RETRY_POLICY",
		"ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS",
		"ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL",
		"ASYA_RESILIENCY_NON_RETRYABLE_ERRORS",
		"ASYA_RESILIENCY_ACTOR_TIMEOUT",
	}
	for _, key := range resiliencyVars {
		if _, ok := sidecarEnv[key]; ok {
			t.Errorf("resiliency env var %s should not be present when not configured", key)
		}
	}

	// Verify volumes were added
	volumeNames := make(map[string]bool)
	for _, v := range mutated.Spec.Volumes {
		volumeNames[v.Name] = true
	}

	requiredVolumes := []string{"socket-dir", "tmp", "asya-runtime"}
	for _, name := range requiredVolumes {
		if !volumeNames[name] {
			t.Errorf("missing volume %s", name)
		}
	}

	// Verify runtime container was modified
	var runtime *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-runtime" {
			runtime = &mutated.Spec.Containers[i]
			break
		}
	}
	if runtime == nil {
		t.Fatal("runtime container not found")
	}

	// Verify runtime command was set
	if len(runtime.Command) != 2 || runtime.Command[0] != "python3" || runtime.Command[1] != "/opt/asya/asya_runtime.py" {
		t.Errorf("unexpected runtime command: %v", runtime.Command)
	}

	// Verify probes were added
	if runtime.StartupProbe == nil {
		t.Error("startup probe not added")
	}
	if runtime.LivenessProbe == nil {
		t.Error("liveness probe not added")
	}
	if runtime.ReadinessProbe == nil {
		t.Error("readiness probe not added")
	}
}

func TestInjector_InjectPythonExecutable(t *testing.T) {
	tests := []struct {
		name           string
		envVars        []corev1.EnvVar
		expectedPython string
	}{
		{
			name: "custom python executable from env",
			envVars: []corev1.EnvVar{
				{Name: "ASYA_PYTHONEXECUTABLE", Value: "/usr/bin/python3.11"},
			},
			expectedPython: "/usr/bin/python3.11",
		},
		{
			name:           "default python3 when env not set",
			envVars:        nil,
			expectedPython: "python3",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &config.Config{
				SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
				RuntimeConfigMap:       "asya-runtime",
				SidecarImagePullPolicy: "IfNotPresent",
				SocketDir:              "/var/run/asya",
				RuntimeMountPath:       "/opt/asya/asya_runtime.py",
			}

			injector := NewInjector(cfg)

			pod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-pod",
					Namespace: "default",
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:  "asya-runtime",
							Image: "my-app:v1",
							Env:   tt.envVars,
						},
					},
				},
			}

			actorConfig := &ActorConfig{
				ActorName: "my-actor",
				Namespace: "default",
				Transport: "sqs",
				Region:    "us-east-1",
			}

			mutated, err := injector.Inject(pod, actorConfig)
			if err != nil {
				t.Fatalf("Inject failed: %v", err)
			}

			var runtime *corev1.Container
			for i := range mutated.Spec.Containers {
				if mutated.Spec.Containers[i].Name == "asya-runtime" {
					runtime = &mutated.Spec.Containers[i]
					break
				}
			}
			if runtime == nil {
				t.Fatal("runtime container not found")
			}

			expectedCommand := []string{tt.expectedPython, "/opt/asya/asya_runtime.py"}
			if len(runtime.Command) != 2 || runtime.Command[0] != expectedCommand[0] || runtime.Command[1] != expectedCommand[1] {
				t.Errorf("expected runtime command %v, got %v", expectedCommand, runtime.Command)
			}
		})
	}
}

func TestInjector_InjectEndActor(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{
					Name:  "asya-runtime",
					Image: "my-app:v1",
				},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "happy-end",
		Namespace: "default",
		Transport: "sqs",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	// Verify ASYA_IS_END_ACTOR is set on sidecar
	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}

	found := false
	for _, e := range sidecar.Env {
		if e.Name == "ASYA_IS_END_ACTOR" && e.Value == "true" {
			found = true
			break
		}
	}
	if !found {
		t.Error("ASYA_IS_END_ACTOR not set on sidecar for happy-end actor")
	}

	// Verify ASYA_ENABLE_VALIDATION is false on runtime
	var runtime *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-runtime" {
			runtime = &mutated.Spec.Containers[i]
			break
		}
	}

	found = false
	for _, e := range runtime.Env {
		if e.Name == "ASYA_ENABLE_VALIDATION" && e.Value == "false" {
			found = true
			break
		}
	}
	if !found {
		t.Error("ASYA_ENABLE_VALIDATION not set to false on runtime for end actor")
	}
}

func TestInjector_InjectMissingRuntimeContainer(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{
					Name:  "other-container",
					Image: "my-app:v1",
				},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
	}

	_, err := injector.Inject(pod, actorConfig)
	if err == nil {
		t.Fatal("expected error for missing runtime container, got nil")
	}
}

func TestInjector_InjectAWSCredentials(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
		AWSCredsSecret:         "aws-creds",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
		Region:    "us-east-1",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}
	if sidecar == nil {
		t.Fatal("sidecar container was not added")
	}

	// Verify envFrom contains AWS credentials secret
	if len(sidecar.EnvFrom) == 0 {
		t.Fatal("expected envFrom with AWS credentials secret, got none")
	}

	found := false
	for _, ef := range sidecar.EnvFrom {
		if ef.SecretRef != nil && ef.SecretRef.Name == "aws-creds" {
			found = true
			break
		}
	}
	if !found {
		t.Error("expected envFrom with secretRef 'aws-creds', not found")
	}
}

func TestInjector_InjectNoAWSCredentials(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
		AWSCredsSecret:         "",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
		Region:    "us-east-1",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}
	if sidecar == nil {
		t.Fatal("sidecar container was not added")
	}

	// Verify no envFrom when AWSCredsSecret is empty
	if len(sidecar.EnvFrom) != 0 {
		t.Errorf("expected no envFrom when AWSCredsSecret is empty, got %d", len(sidecar.EnvFrom))
	}
}

func TestInjector_SidecarImagePullPolicyOverride(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "test-pod",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName:              "my-actor",
		Namespace:              "default",
		Transport:              "sqs",
		SidecarImagePullPolicy: "Always",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}

	if sidecar.ImagePullPolicy != corev1.PullAlways {
		t.Errorf("expected imagePullPolicy Always, got %q", sidecar.ImagePullPolicy)
	}
}

func TestInjector_SidecarImagePullPolicyDefault(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "test-pod",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}

	if sidecar.ImagePullPolicy != corev1.PullIfNotPresent {
		t.Errorf("expected imagePullPolicy IfNotPresent (from global config), got %q", sidecar.ImagePullPolicy)
	}
}

func TestInjector_SidecarEnvMerge(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "test-pod",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
		SidecarEnv: []corev1.EnvVar{
			{Name: "ASYA_LOG_LEVEL", Value: "debug"},
			{Name: "MY_CUSTOM_VAR", Value: "custom-value"},
		},
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}

	envMap := make(map[string]string)
	for _, e := range sidecar.Env {
		envMap[e.Name] = e.Value
	}

	// ASYA_LOG_LEVEL should be overridden from "info" to "debug"
	if envMap["ASYA_LOG_LEVEL"] != "debug" {
		t.Errorf("expected ASYA_LOG_LEVEL=debug, got %q", envMap["ASYA_LOG_LEVEL"])
	}

	// Custom var should be added
	if envMap["MY_CUSTOM_VAR"] != "custom-value" {
		t.Errorf("expected MY_CUSTOM_VAR=custom-value, got %q", envMap["MY_CUSTOM_VAR"])
	}

	// Default vars should still be present
	if envMap["ASYA_TRANSPORT"] != "sqs" {
		t.Errorf("expected ASYA_TRANSPORT=sqs, got %q", envMap["ASYA_TRANSPORT"])
	}
}

func TestInjector_InjectRabbitMQ(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
		GatewayURL:             "http://gateway.default.svc:8080",
		RabbitMQURL:            "amqp://guest:guest@rabbitmq.default.svc:5672/",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{
					Name:  "asya-runtime",
					Image: "my-app:v1",
				},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName:   "my-actor",
		Namespace:   "default",
		Transport:   "rabbitmq",
		Handler:     "my_module.process",
		HandlerMode: "payload",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}
	if sidecar == nil {
		t.Fatal("sidecar container was not added")
	}

	sidecarEnv := make(map[string]string)
	for _, e := range sidecar.Env {
		sidecarEnv[e.Name] = e.Value
	}

	expectedEnv := map[string]string{
		"ASYA_SOCKET_DIR":      "/var/run/asya",
		"ASYA_ACTOR_NAME":      "my-actor",
		"ASYA_NAMESPACE":       "default",
		"ASYA_TRANSPORT":       "rabbitmq",
		"ASYA_GATEWAY_URL":     "http://gateway.default.svc:8080",
		"ASYA_RABBITMQ_URL":    "amqp://guest:guest@rabbitmq.default.svc:5672/",
		"ASYA_ACTOR_SINK":      "x-sink",
		"ASYA_ACTOR_HAPPY_END": "happy-end",
		"ASYA_ACTOR_ERROR_END": "error-end",
	}

	for key, expected := range expectedEnv {
		if actual, ok := sidecarEnv[key]; !ok {
			t.Errorf("missing env var %s", key)
		} else if actual != expected {
			t.Errorf("env var %s: expected %q, got %q", key, expected, actual)
		}
	}

	// SQS-specific env vars should NOT be present
	sqsVars := []string{"ASYA_AWS_REGION", "ASYA_SQS_ENDPOINT", "ASYA_QUEUE_URL"}
	for _, key := range sqsVars {
		if _, ok := sidecarEnv[key]; ok {
			t.Errorf("SQS env var %s should not be present for rabbitmq transport", key)
		}
	}
}

func TestInjector_InjectRabbitMQCredentials(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
		RabbitMQURL:            "amqp://guest:guest@rabbitmq.default.svc:5672/",
		RabbitMQCredsSecret:    "rabbitmq-creds",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "rabbitmq",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}
	if sidecar == nil {
		t.Fatal("sidecar container was not added")
	}

	found := false
	for _, ef := range sidecar.EnvFrom {
		if ef.SecretRef != nil && ef.SecretRef.Name == "rabbitmq-creds" {
			found = true
			break
		}
	}
	if !found {
		t.Error("expected envFrom with secretRef 'rabbitmq-creds', not found")
	}
}

func TestInjector_InjectRabbitMQNoCredsForSQS(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
		RabbitMQCredsSecret:    "rabbitmq-creds",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
		Region:    "us-east-1",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}
	if sidecar == nil {
		t.Fatal("sidecar container was not added")
	}

	// RabbitMQ creds should NOT be injected for SQS transport
	for _, ef := range sidecar.EnvFrom {
		if ef.SecretRef != nil && ef.SecretRef.Name == "rabbitmq-creds" {
			t.Error("rabbitmq-creds secret should not be injected for SQS transport")
		}
	}
}

func TestInjector_SidecarImageOverride(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:     "ghcr.io/deliveryhero/asya-sidecar:default",
		RuntimeConfigMap: "asya-runtime",
		SocketDir:        "/var/run/asya",
		RuntimeMountPath: "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "test-pod",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName:    "my-actor",
		Namespace:    "default",
		Transport:    "sqs",
		SidecarImage: "custom-sidecar:v2",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}

	if sidecar.Image != "custom-sidecar:v2" {
		t.Errorf("expected custom sidecar image, got %q", sidecar.Image)
	}
}

func TestInjector_InjectResiliencyEnvVars(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "test-pod",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
		Region:    "us-east-1",
		Resiliency: &ResiliencyConfig{
			Retry: &RetryConfig{
				Policy:             "exponential",
				MaxAttempts:        "5",
				InitialInterval:    "1s",
				MaxInterval:        "300s",
				BackoffCoefficient: "2",
				Jitter:             "true",
			},
			NonRetryableErrors: "ValueError,KeyError",
			ActorTimeout:       "30s",
		},
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}
	if sidecar == nil {
		t.Fatal("sidecar container was not added")
	}

	envMap := make(map[string]string)
	for _, e := range sidecar.Env {
		envMap[e.Name] = e.Value
	}

	expectedResiliency := map[string]string{
		"ASYA_RESILIENCY_RETRY_POLICY":             "exponential",
		"ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS":        "5",
		"ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL":    "1s",
		"ASYA_RESILIENCY_RETRY_MAX_INTERVAL":        "300s",
		"ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT": "2",
		"ASYA_RESILIENCY_RETRY_JITTER":              "true",
		"ASYA_RESILIENCY_NON_RETRYABLE_ERRORS":      "ValueError,KeyError",
		"ASYA_RESILIENCY_ACTOR_TIMEOUT":             "30s",
	}

	for key, expected := range expectedResiliency {
		if actual, ok := envMap[key]; !ok {
			t.Errorf("missing resiliency env var %s", key)
		} else if actual != expected {
			t.Errorf("resiliency env var %s: expected %q, got %q", key, expected, actual)
		}
	}
}

func TestInjector_InjectResiliencyPartial(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "test-pod",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
		Region:    "us-east-1",
		Resiliency: &ResiliencyConfig{
			Retry: &RetryConfig{
				MaxAttempts: "3",
			},
			ActorTimeout: "60s",
		},
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}

	envMap := make(map[string]string)
	for _, e := range sidecar.Env {
		envMap[e.Name] = e.Value
	}

	// Only maxAttempts and actorTimeout should be set
	if envMap["ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS"] != "3" {
		t.Errorf("expected ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS=3, got %q", envMap["ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS"])
	}
	if envMap["ASYA_RESILIENCY_ACTOR_TIMEOUT"] != "60s" {
		t.Errorf("expected ASYA_RESILIENCY_ACTOR_TIMEOUT=60s, got %q", envMap["ASYA_RESILIENCY_ACTOR_TIMEOUT"])
	}

	// Empty fields should not produce env vars
	if _, ok := envMap["ASYA_RESILIENCY_RETRY_POLICY"]; ok {
		t.Error("ASYA_RESILIENCY_RETRY_POLICY should not be set when empty")
	}
	if _, ok := envMap["ASYA_RESILIENCY_NON_RETRYABLE_ERRORS"]; ok {
		t.Error("ASYA_RESILIENCY_NON_RETRYABLE_ERRORS should not be set when empty")
	}
}

func TestInjector_InjectSystemActors(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	systemActors := []string{"happy-end", "error-end", "x-sink", "x-sump"}

	for _, actorName := range systemActors {
		t.Run(actorName, func(t *testing.T) {
			pod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-pod",
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{Name: "asya-runtime", Image: "my-app:v1"},
					},
				},
			}

			actorConfig := &ActorConfig{
				ActorName: actorName,
				Namespace: "default",
				Transport: "sqs",
			}

			mutated, err := injector.Inject(pod, actorConfig)
			if err != nil {
				t.Fatalf("Inject failed: %v", err)
			}

			// Verify ASYA_IS_END_ACTOR is set on sidecar
			var sidecar *corev1.Container
			for i := range mutated.Spec.Containers {
				if mutated.Spec.Containers[i].Name == "asya-sidecar" {
					sidecar = &mutated.Spec.Containers[i]
					break
				}
			}

			sidecarEnv := make(map[string]string)
			for _, e := range sidecar.Env {
				sidecarEnv[e.Name] = e.Value
			}

			if sidecarEnv["ASYA_IS_END_ACTOR"] != "true" {
				t.Errorf("ASYA_IS_END_ACTOR not set for system actor %s", actorName)
			}

			// Verify ASYA_ENABLE_VALIDATION=false on runtime
			var runtime *corev1.Container
			for i := range mutated.Spec.Containers {
				if mutated.Spec.Containers[i].Name == "asya-runtime" {
					runtime = &mutated.Spec.Containers[i]
					break
				}
			}

			runtimeEnv := make(map[string]string)
			for _, e := range runtime.Env {
				runtimeEnv[e.Name] = e.Value
			}

			if runtimeEnv["ASYA_ENABLE_VALIDATION"] != "false" {
				t.Errorf("ASYA_ENABLE_VALIDATION not set to false for system actor %s", actorName)
			}
		})
	}
}

func TestInjector_RegularActorNotSystemActor(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}

	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "test-pod",
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}

	for _, e := range sidecar.Env {
		if e.Name == "ASYA_IS_END_ACTOR" {
			t.Error("ASYA_IS_END_ACTOR should not be set for regular actors")
		}
	}
}
