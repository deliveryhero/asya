package controller

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	autoscalingv2 "k8s.io/api/autoscaling/v2"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
	"github.com/asya/operator/internal/transports"
)

const (
	testContainerRuntime  = "asya-runtime"
	testTransportRabbitMQ = "rabbitmq"
	testTransportSQS      = "sqs"
)

func TestInjectSidecar_PythonExecutable(t *testing.T) {
	tests := []struct {
		name             string
		pythonExecutable string
		expectedPython   string
	}{
		{
			name:           "default python executable",
			expectedPython: "python3",
		},
		{
			name:             "custom python executable",
			pythonExecutable: "/opt/conda/bin/python",
			expectedPython:   "/opt/conda/bin/python",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)
			_ = corev1.AddToScheme(scheme)

			r := &AsyncActorReconciler{
				Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme: scheme,
				TransportRegistry: &asyaconfig.TransportRegistry{
					Transports: make(map[string]*asyaconfig.TransportConfig),
				},
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Workload: asyav1alpha1.WorkloadConfig{
						PythonExecutable: tt.pythonExecutable,
						Template: asyav1alpha1.PodTemplateSpec{
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

			result := r.injectSidecar(asya)

			var runtimeContainer *corev1.Container
			for i := range result.Spec.Containers {
				if result.Spec.Containers[i].Name == testContainerRuntime {
					runtimeContainer = &result.Spec.Containers[i]
					break
				}
			}

			if runtimeContainer == nil {
				t.Fatal("Runtime container not found")
			}

			if len(runtimeContainer.Command) != 2 {
				t.Errorf("Expected 2 command args, got %d", len(runtimeContainer.Command))
			}

			if runtimeContainer.Command[0] != tt.expectedPython {
				t.Errorf("Expected python executable %s, got %s", tt.expectedPython, runtimeContainer.Command[0])
			}

			if runtimeContainer.Command[1] != runtimeMountPath {
				t.Errorf("Expected runtime script path %s, got %s", runtimeMountPath, runtimeContainer.Command[1])
			}
		})
	}
}

// Removed: TestInjectSidecar_RejectCommandOverride
// Validation is now performed in validateAsyncActorSpec() before reaching injectSidecar()
// See TestValidateAsyncActorSpec_CommandOverride for the replacement test

func TestInjectSidecar_MultipleContainers(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: make(map[string]*asyaconfig.TransportConfig),
		},
	}

	customPython := "python3.11"
	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
			Workload: asyav1alpha1.WorkloadConfig{
				PythonExecutable: customPython,
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  "asya-runtime",
								Image: "python:3.11-slim",
							},
							{
								Name:  "helper",
								Image: "python:3.11-slim",
							},
						},
					},
				},
			},
		},
	}

	result := r.injectSidecar(asya)

	var runtimeContainer *corev1.Container
	var helperContainer *corev1.Container
	var sidecarContainer *corev1.Container

	for i := range result.Spec.Containers {
		switch result.Spec.Containers[i].Name {
		case "asya-runtime":
			runtimeContainer = &result.Spec.Containers[i]
		case "helper":
			helperContainer = &result.Spec.Containers[i]
		case sidecarName:
			sidecarContainer = &result.Spec.Containers[i]
		}
	}

	if runtimeContainer == nil {
		t.Fatal("Runtime container not found")
	}
	if helperContainer == nil {
		t.Fatal("Helper container not found")
	}
	if sidecarContainer == nil {
		t.Fatal("Sidecar container not found")
	}

	if len(runtimeContainer.Command) != 2 {
		t.Errorf("Runtime container: expected 2 command args, got %d", len(runtimeContainer.Command))
	}
	if runtimeContainer.Command[0] != customPython {
		t.Errorf("Runtime container: expected python executable %s, got %s", customPython, runtimeContainer.Command[0])
	}

	if len(helperContainer.Command) != 0 {
		t.Errorf("Helper container: expected no command override, got %d args", len(helperContainer.Command))
	}
}

func TestInjectSidecar_ProbesAdded(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: make(map[string]*asyaconfig.TransportConfig),
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
			Workload: asyav1alpha1.WorkloadConfig{
				Template: asyav1alpha1.PodTemplateSpec{
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

	result := r.injectSidecar(asya)

	var runtimeContainer *corev1.Container
	for i := range result.Spec.Containers {
		if result.Spec.Containers[i].Name == "asya-runtime" {
			runtimeContainer = &result.Spec.Containers[i]
			break
		}
	}

	if runtimeContainer == nil {
		t.Fatal("Runtime container not found")
	}

	if runtimeContainer.LivenessProbe == nil {
		t.Error("Expected LivenessProbe to be set, got nil")
	} else {
		if runtimeContainer.LivenessProbe.Exec == nil {
			t.Error("Expected LivenessProbe.Exec to be set, got nil")
		} else {
			expectedCmd := []string{"sh", "-c", "test -S /var/run/asya/asya-runtime.sock && test -f /var/run/asya/runtime-ready"}
			if len(runtimeContainer.LivenessProbe.Exec.Command) != len(expectedCmd) {
				t.Errorf("Expected LivenessProbe command length %d, got %d",
					len(expectedCmd), len(runtimeContainer.LivenessProbe.Exec.Command))
			}
		}
		if runtimeContainer.LivenessProbe.InitialDelaySeconds != 0 {
			t.Errorf("Expected LivenessProbe InitialDelaySeconds 0, got %d",
				runtimeContainer.LivenessProbe.InitialDelaySeconds)
		}
		if runtimeContainer.LivenessProbe.PeriodSeconds != 30 {
			t.Errorf("Expected LivenessProbe PeriodSeconds 30, got %d",
				runtimeContainer.LivenessProbe.PeriodSeconds)
		}
	}

	if runtimeContainer.ReadinessProbe == nil {
		t.Error("Expected ReadinessProbe to be set, got nil")
	} else {
		if runtimeContainer.ReadinessProbe.Exec == nil {
			t.Error("Expected ReadinessProbe.Exec to be set, got nil")
		} else {
			expectedCmd := []string{"sh", "-c", "test -S /var/run/asya/asya-runtime.sock && test -f /var/run/asya/runtime-ready"}
			if len(runtimeContainer.ReadinessProbe.Exec.Command) != len(expectedCmd) {
				t.Errorf("Expected ReadinessProbe command length %d, got %d",
					len(expectedCmd), len(runtimeContainer.ReadinessProbe.Exec.Command))
			}
		}
		if runtimeContainer.ReadinessProbe.InitialDelaySeconds != 0 {
			t.Errorf("Expected ReadinessProbe InitialDelaySeconds 0, got %d",
				runtimeContainer.ReadinessProbe.InitialDelaySeconds)
		}
		if runtimeContainer.ReadinessProbe.PeriodSeconds != 10 {
			t.Errorf("Expected ReadinessProbe PeriodSeconds 10, got %d",
				runtimeContainer.ReadinessProbe.PeriodSeconds)
		}
	}
}

func TestReconcileWorkload_UnsupportedType(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: make(map[string]*asyaconfig.TransportConfig),
		},
	}

	testCases := []struct {
		name          string
		workloadType  string
		expectedError string
	}{
		{
			name:          "Pod type not supported",
			workloadType:  "Pod",
			expectedError: "unsupported workload kind: Pod (only Deployment and StatefulSet are supported)",
		},
		{
			name:          "ReplicaSet type not supported",
			workloadType:  "ReplicaSet",
			expectedError: "unsupported workload kind: ReplicaSet (only Deployment and StatefulSet are supported)",
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-unsupported",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Workload: asyav1alpha1.WorkloadConfig{
						Kind: tc.workloadType,
						Template: asyav1alpha1.PodTemplateSpec{
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

			err := r.reconcileWorkload(context.Background(), asya)
			if err == nil {
				t.Fatal("Expected error for unsupported workload kind, got nil")
			}

			if err.Error() != tc.expectedError {
				t.Errorf("Expected error message '%s', got '%s'", tc.expectedError, err.Error())
			}
		})
	}
}
func TestSetCondition(t *testing.T) {
	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:       "test-actor",
			Namespace:  "default",
			Generation: 1,
		},
	}

	r := &AsyncActorReconciler{}

	// Test adding new condition
	r.setCondition(asya, "Ready", metav1.ConditionTrue, "Success", "All good")

	if len(asya.Status.Conditions) != 1 {
		t.Fatalf("Expected 1 condition, got %d", len(asya.Status.Conditions))
	}

	cond := asya.Status.Conditions[0]
	if cond.Type != "Ready" {
		t.Errorf("Expected type 'Ready', got %q", cond.Type)
	}
	if cond.Status != metav1.ConditionTrue {
		t.Errorf("Expected status True, got %v", cond.Status)
	}
	if cond.Reason != "Success" {
		t.Errorf("Expected reason 'Success', got %q", cond.Reason)
	}
	if cond.Message != "All good" {
		t.Errorf("Expected message 'All good', got %q", cond.Message)
	}
	if cond.ObservedGeneration != 1 {
		t.Errorf("Expected observedGeneration 1, got %d", cond.ObservedGeneration)
	}

	// Test updating existing condition with same status (should not update)
	r.setCondition(asya, "Ready", metav1.ConditionTrue, "Success", "Still good")

	if len(asya.Status.Conditions) != 1 {
		t.Fatalf("Expected 1 condition, got %d", len(asya.Status.Conditions))
	}
	// Message should still be old since status didn't change
	if asya.Status.Conditions[0].Message != "All good" {
		t.Errorf("Expected message to stay 'All good', got %q", asya.Status.Conditions[0].Message)
	}

	// Test updating existing condition with different status (should update)
	r.setCondition(asya, "Ready", metav1.ConditionFalse, "Failed", "Something broke")

	if len(asya.Status.Conditions) != 1 {
		t.Fatalf("Expected 1 condition, got %d", len(asya.Status.Conditions))
	}

	cond = asya.Status.Conditions[0]
	if cond.Status != metav1.ConditionFalse {
		t.Errorf("Expected status False, got %v", cond.Status)
	}
	if cond.Message != "Something broke" {
		t.Errorf("Expected updated message, got %q", cond.Message)
	}

	// Test adding second condition
	r.setCondition(asya, "Progressing", metav1.ConditionTrue, "InProgress", "Working on it")

	if len(asya.Status.Conditions) != 2 {
		t.Fatalf("Expected 2 conditions, got %d", len(asya.Status.Conditions))
	}
}

func TestInjectSidecar_EndActorsDisableValidation(t *testing.T) {
	tests := []struct {
		name                     string
		actorName                string
		expectValidationDisabled bool
	}{
		{"happy-end actor disables validation", "happy-end", true},
		{"error-end actor disables validation", "error-end", true},
		{"regular actor enables validation", "regular-actor", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)
			_ = corev1.AddToScheme(scheme)

			r := &AsyncActorReconciler{
				Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme: scheme,
				TransportRegistry: &asyaconfig.TransportRegistry{
					Transports: make(map[string]*asyaconfig.TransportConfig),
				},
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      tt.actorName,
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Workload: asyav1alpha1.WorkloadConfig{
						Template: asyav1alpha1.PodTemplateSpec{
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

			result := r.injectSidecar(asya)

			var runtimeContainer *corev1.Container
			for i := range result.Spec.Containers {
				if result.Spec.Containers[i].Name == testContainerRuntime {
					runtimeContainer = &result.Spec.Containers[i]
					break
				}
			}

			if runtimeContainer == nil {
				t.Fatal("Runtime container not found")
			}

			envMap := make(map[string]string)
			for _, e := range runtimeContainer.Env {
				envMap[e.Name] = e.Value
			}

			if tt.expectValidationDisabled {
				if envMap["ASYA_ENABLE_VALIDATION"] != "false" {
					t.Errorf("Expected ASYA_ENABLE_VALIDATION=false for %s, got %q", tt.actorName, envMap["ASYA_ENABLE_VALIDATION"])
				}
			} else {
				if val, exists := envMap["ASYA_ENABLE_VALIDATION"]; exists {
					t.Errorf("Expected ASYA_ENABLE_VALIDATION to not be set for %s, but it was set to %q", tt.actorName, val)
				}
			}

			// Verify sidecar also has ASYA_IS_END_ACTOR for end actors
			var sidecarContainer *corev1.Container
			for i := range result.Spec.Containers {
				if result.Spec.Containers[i].Name == sidecarName {
					sidecarContainer = &result.Spec.Containers[i]
					break
				}
			}

			if sidecarContainer == nil {
				t.Fatal("Sidecar container not found")
			}

			sidecarEnvMap := make(map[string]string)
			for _, e := range sidecarContainer.Env {
				sidecarEnvMap[e.Name] = e.Value
			}

			if tt.expectValidationDisabled {
				if sidecarEnvMap["ASYA_IS_END_ACTOR"] != "true" {
					t.Errorf("Expected ASYA_IS_END_ACTOR=true in sidecar for %s, got %q", tt.actorName, sidecarEnvMap["ASYA_IS_END_ACTOR"])
				}
			} else {
				if _, exists := sidecarEnvMap["ASYA_IS_END_ACTOR"]; exists {
					t.Errorf("Expected ASYA_IS_END_ACTOR to not be set in sidecar for %s", tt.actorName)
				}
			}
		})
	}
}

func TestBuildSidecarEnv(t *testing.T) {
	r := &AsyncActorReconciler{
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				testTransportRabbitMQ: {
					Type:    testTransportRabbitMQ,
					Enabled: true,
					Config: &asyaconfig.RabbitMQConfig{
						Host:     "localhost",
						Port:     5672,
						Username: "guest",
					},
				},
			},
		},
	}

	t.Run("basic environment variables", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: testTransportRabbitMQ,
			},
		}

		env := r.buildSidecarEnv(asya)

		envMap := make(map[string]string)
		for _, e := range env {
			envMap[e.Name] = e.Value
		}

		if envMap["ASYA_LOG_LEVEL"] != "info" {
			t.Errorf("Expected ASYA_LOG_LEVEL=info, got %q", envMap["ASYA_LOG_LEVEL"])
		}
		if envMap["ASYA_TRANSPORT"] != testTransportRabbitMQ {
			t.Errorf("Expected ASYA_TRANSPORT=%s, got %q", testTransportRabbitMQ, envMap["ASYA_TRANSPORT"])
		}
		if envMap["ASYA_ACTOR_HAPPY_END"] != actorNameHappyEnd {
			t.Errorf("Expected ASYA_ACTOR_HAPPY_END=%s, got %q", actorNameHappyEnd, envMap["ASYA_ACTOR_HAPPY_END"])
		}
		if envMap["ASYA_ACTOR_ERROR_END"] != actorNameErrorEnd {
			t.Errorf("Expected ASYA_ACTOR_ERROR_END=%s, got %q", actorNameErrorEnd, envMap["ASYA_ACTOR_ERROR_END"])
		}
	})

	t.Run("with processing timeout", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: testTransportRabbitMQ,
				Timeout: asyav1alpha1.TimeoutConfig{
					Processing: 300,
				},
			},
		}

		env := r.buildSidecarEnv(asya)

		envMap := make(map[string]string)
		for _, e := range env {
			envMap[e.Name] = e.Value
		}

		if envMap["ASYA_RUNTIME_TIMEOUT"] != "300s" {
			t.Errorf("Expected ASYA_RUNTIME_TIMEOUT=300s, got %q", envMap["ASYA_RUNTIME_TIMEOUT"])
		}
	})

	t.Run("invalid transport returns basic env", func(t *testing.T) {
		asya := &asyav1alpha1.AsyncActor{
			Spec: asyav1alpha1.AsyncActorSpec{
				Transport: "invalid",
			},
		}

		env := r.buildSidecarEnv(asya)

		// Should still return basic env vars even if transport is invalid
		if len(env) < 3 {
			t.Errorf("Expected at least 3 basic env vars, got %d", len(env))
		}
	})

	t.Run("end actors set ASYA_IS_END_ACTOR", func(t *testing.T) {
		tests := []struct {
			name             string
			actorName        string
			expectIsEndActor bool
		}{
			{"happy-end actor", "happy-end", true},
			{"error-end actor", "error-end", true},
			{"regular actor", "regular-actor", false},
		}

		for _, tt := range tests {
			t.Run(tt.name, func(t *testing.T) {
				asya := &asyav1alpha1.AsyncActor{
					ObjectMeta: metav1.ObjectMeta{
						Name: tt.actorName,
					},
					Spec: asyav1alpha1.AsyncActorSpec{
						Transport: testTransportRabbitMQ,
					},
				}

				env := r.buildSidecarEnv(asya)

				envMap := make(map[string]string)
				for _, e := range env {
					envMap[e.Name] = e.Value
				}

				if tt.expectIsEndActor {
					if envMap["ASYA_IS_END_ACTOR"] != "true" {
						t.Errorf("Expected ASYA_IS_END_ACTOR=true for %s, got %q", tt.actorName, envMap["ASYA_IS_END_ACTOR"])
					}
				} else {
					if _, exists := envMap["ASYA_IS_END_ACTOR"]; exists {
						t.Errorf("Expected ASYA_IS_END_ACTOR to not be set for %s, but it was set to %q", tt.actorName, envMap["ASYA_IS_END_ACTOR"])
					}
				}
			})
		}
	})
}

func TestParseMetricType(t *testing.T) {
	r := &AsyncActorReconciler{}

	tests := []struct {
		input    string
		expected string
	}{
		{"AverageValue", "AverageValue"},
		{"Value", "Value"},
		{"Utilization", "Utilization"},
		{"unknown", "AverageValue"}, // default
		{"", "AverageValue"},        // default
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := r.parseMetricType(tt.input)
			if string(result) != tt.expected {
				t.Errorf("parseMetricType(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestUpdateDisplayFields(t *testing.T) {
	r := &AsyncActorReconciler{}

	tests := []struct {
		name                string
		conditions          []metav1.Condition
		scalingEnabled      bool
		replicas            *int32
		readyReplicas       *int32
		totalReplicas       *int32
		desiredReplicas     *int32
		expectedReady       string
		expectedStatus      string
		expectedReplicas    string
		expectedCurrent     int32
		expectedDesired     int32
		expectedScalingMode string
	}{
		{
			name: "all conditions true without scaling",
			conditions: []metav1.Condition{
				{Type: "TransportReady", Status: metav1.ConditionTrue},
				{Type: "WorkloadReady", Status: metav1.ConditionTrue},
			},
			scalingEnabled:      false,
			replicas:            ptr(int32(3)),
			readyReplicas:       ptr(int32(3)),
			totalReplicas:       ptr(int32(3)),
			desiredReplicas:     ptr(int32(3)),
			expectedReady:       "2/2",
			expectedStatus:      "Running",
			expectedReplicas:    "3/3",
			expectedCurrent:     3,
			expectedDesired:     3,
			expectedScalingMode: "Manual",
		},
		{
			name: "all conditions true with scaling enabled",
			conditions: []metav1.Condition{
				{Type: "TransportReady", Status: metav1.ConditionTrue},
				{Type: "WorkloadReady", Status: metav1.ConditionTrue},
				{Type: "ScalingReady", Status: metav1.ConditionTrue},
			},
			scalingEnabled:      true,
			replicas:            ptr(int32(10)),
			readyReplicas:       ptr(int32(10)),
			totalReplicas:       ptr(int32(10)),
			desiredReplicas:     ptr(int32(10)),
			expectedReady:       "3/3",
			expectedStatus:      "Running",
			expectedReplicas:    "10/10",
			expectedCurrent:     10,
			expectedDesired:     10,
			expectedScalingMode: "KEDA",
		},
		{
			name: "transport not ready",
			conditions: []metav1.Condition{
				{Type: "TransportReady", Status: metav1.ConditionFalse},
				{Type: "WorkloadReady", Status: metav1.ConditionTrue},
			},
			scalingEnabled:      false,
			replicas:            ptr(int32(0)),
			readyReplicas:       ptr(int32(0)),
			totalReplicas:       ptr(int32(0)),
			desiredReplicas:     ptr(int32(0)),
			expectedReady:       "1/2",
			expectedStatus:      "TransportError",
			expectedReplicas:    "0/0",
			expectedCurrent:     0,
			expectedDesired:     0,
			expectedScalingMode: "Manual",
		},
		{
			name: "workload not ready",
			conditions: []metav1.Condition{
				{Type: "TransportReady", Status: metav1.ConditionTrue},
				{Type: "WorkloadReady", Status: metav1.ConditionFalse},
			},
			scalingEnabled:      false,
			replicas:            ptr(int32(0)),
			readyReplicas:       ptr(int32(0)),
			totalReplicas:       ptr(int32(0)),
			desiredReplicas:     ptr(int32(0)),
			expectedReady:       "1/2",
			expectedStatus:      "WorkloadError",
			expectedReplicas:    "0/0",
			expectedCurrent:     0,
			expectedDesired:     0,
			expectedScalingMode: "Manual",
		},
		{
			name: "scaling not ready when enabled",
			conditions: []metav1.Condition{
				{Type: "TransportReady", Status: metav1.ConditionTrue},
				{Type: "WorkloadReady", Status: metav1.ConditionTrue},
				{Type: "ScalingReady", Status: metav1.ConditionFalse},
			},
			scalingEnabled:      true,
			replicas:            ptr(int32(3)),
			readyReplicas:       ptr(int32(3)),
			totalReplicas:       ptr(int32(3)),
			desiredReplicas:     ptr(int32(3)),
			expectedReady:       "2/3",
			expectedStatus:      "ScalingError",
			expectedReplicas:    "3/3",
			expectedCurrent:     3,
			expectedDesired:     3,
			expectedScalingMode: "KEDA",
		},
		{
			name:                "no conditions set",
			conditions:          []metav1.Condition{},
			scalingEnabled:      false,
			replicas:            nil,
			readyReplicas:       nil,
			totalReplicas:       nil,
			desiredReplicas:     nil,
			expectedReady:       "0/2",
			expectedStatus:      "TransportError",
			expectedReplicas:    "0/0",
			expectedCurrent:     0,
			expectedDesired:     0,
			expectedScalingMode: "Manual",
		},
		{
			name: "replicas converging (scaling up)",
			conditions: []metav1.Condition{
				{Type: "TransportReady", Status: metav1.ConditionTrue},
				{Type: "WorkloadReady", Status: metav1.ConditionTrue},
				{Type: "ScalingReady", Status: metav1.ConditionTrue},
			},
			scalingEnabled:      true,
			replicas:            ptr(int32(3)),
			readyReplicas:       ptr(int32(3)),
			totalReplicas:       ptr(int32(3)),
			desiredReplicas:     ptr(int32(5)),
			expectedReady:       "3/3",
			expectedStatus:      "ScalingUp",
			expectedReplicas:    "3/5",
			expectedCurrent:     3,
			expectedDesired:     5,
			expectedScalingMode: "KEDA",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			asya := &asyav1alpha1.AsyncActor{
				Spec: asyav1alpha1.AsyncActorSpec{
					Scaling: asyav1alpha1.ScalingConfig{
						Enabled: tt.scalingEnabled,
					},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					Conditions:         tt.conditions,
					Replicas:           tt.replicas,
					ReadyReplicas:      tt.readyReplicas,
					TotalReplicas:      tt.totalReplicas,
					DesiredReplicas:    tt.desiredReplicas,
					ObservedGeneration: 1,
				},
			}

			r.updateDisplayFields(asya)

			if asya.Status.ReadySummary != tt.expectedReady {
				t.Errorf("ReadySummary = %q, want %q", asya.Status.ReadySummary, tt.expectedReady)
			}
			if asya.Status.Status != tt.expectedStatus {
				t.Errorf("Status = %q, want %q", asya.Status.Status, tt.expectedStatus)
			}
			if asya.Status.ReplicasSummary != tt.expectedReplicas {
				t.Errorf("ReplicasSummary = %q, want %q", asya.Status.ReplicasSummary, tt.expectedReplicas)
			}
			if asya.Status.Replicas == nil {
				t.Errorf("Replicas is nil, want %d", tt.expectedCurrent)
			} else if *asya.Status.Replicas != tt.expectedCurrent {
				t.Errorf("Replicas = %d, want %d", *asya.Status.Replicas, tt.expectedCurrent)
			}
			if asya.Status.DesiredReplicas == nil {
				t.Errorf("DesiredReplicas is nil, want %d", tt.expectedDesired)
			} else if *asya.Status.DesiredReplicas != tt.expectedDesired {
				t.Errorf("DesiredReplicas = %d, want %d", *asya.Status.DesiredReplicas, tt.expectedDesired)
			}
			if asya.Status.ScalingMode != tt.expectedScalingMode {
				t.Errorf("ScalingMode = %q, want %q", asya.Status.ScalingMode, tt.expectedScalingMode)
			}
		})
	}
}

// ptr is a helper to create pointers to primitives
func ptr[T any](v T) *T {
	return &v
}

func TestUpdateDisplayFields_LastScaleFormatted(t *testing.T) {
	r := &AsyncActorReconciler{}

	tests := []struct {
		name               string
		lastScaleTime      *metav1.Time
		lastScaleDirection string
		expectedFormatted  string
		secondsAgo         int
	}{
		{
			name:               "no scale time",
			lastScaleTime:      nil,
			lastScaleDirection: "",
			expectedFormatted:  "-",
			secondsAgo:         0,
		},
		{
			name:               "scaled up 30 seconds ago",
			lastScaleDirection: "up",
			expectedFormatted:  "30s ago (up)",
			secondsAgo:         30,
		},
		{
			name:               "scaled down 5 minutes ago",
			lastScaleDirection: "down",
			expectedFormatted:  "5m ago (down)",
			secondsAgo:         300,
		},
		{
			name:               "scaled up 2 hours ago",
			lastScaleDirection: "up",
			expectedFormatted:  "2h ago (up)",
			secondsAgo:         7200,
		},
		{
			name:               "scaled down 3 days ago",
			lastScaleDirection: "down",
			expectedFormatted:  "3d ago (down)",
			secondsAgo:         259200,
		},
		{
			name:               "scaled with no direction",
			lastScaleDirection: "",
			expectedFormatted:  "1m ago",
			secondsAgo:         60,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			asya := &asyav1alpha1.AsyncActor{
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
					LastScaleDirection: tt.lastScaleDirection,
				},
			}

			if tt.secondsAgo > 0 {
				scaleTime := metav1.NewTime(metav1.Now().Add(-time.Duration(tt.secondsAgo) * time.Second))
				asya.Status.LastScaleTime = &scaleTime
			} else {
				asya.Status.LastScaleTime = tt.lastScaleTime
			}

			r.updateDisplayFields(asya)

			if asya.Status.LastScaleFormatted != tt.expectedFormatted {
				t.Errorf("LastScaleFormatted = %q, want %q", asya.Status.LastScaleFormatted, tt.expectedFormatted)
			}
		})
	}
}

func TestReconcileServiceAccountIfNeeded_SkipsWhenNoActorRoleArn(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				testTransportSQS: {
					Type:    testTransportSQS,
					Enabled: true,
					Config: &asyaconfig.SQSConfig{
						Region:       "us-east-1",
						ActorRoleArn: "",
					},
				},
			},
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportSQS,
		},
	}

	err := r.reconcileServiceAccountIfNeeded(context.Background(), asya)
	if err != nil {
		t.Fatalf("Expected no error when actorRoleArn is empty (should skip ServiceAccount creation), got: %v", err)
	}

	// Verify no ServiceAccount was created
	saName := ""
	sa := &corev1.ServiceAccount{}
	err = r.Get(context.Background(), client.ObjectKey{Name: saName, Namespace: "default"}, sa)
	if err == nil {
		t.Error("Expected ServiceAccount to NOT be created when actorRoleArn is empty")
	}
}

func TestReconcileServiceAccount_TransportNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: make(map[string]*asyaconfig.TransportConfig),
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportSQS,
		},
	}

	err := r.reconcileServiceAccountIfNeeded(context.Background(), asya)
	if err == nil {
		t.Fatal("Expected error for missing transport, got nil")
	}

	if err.Error() != "transport 'sqs' not found in operator configuration" {
		t.Errorf("Expected transport not found error, got %q", err.Error())
	}
}

func TestReconcileDeployment_SQSServiceAccount(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	_ = appsv1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				testTransportSQS: {
					Type:    testTransportSQS,
					Enabled: true,
					Config: &asyaconfig.SQSConfig{
						Region:            "us-east-1",
						ActorRoleArn:      "arn:aws:iam::123456789012:role/asya-actor",
						VisibilityTimeout: 300,
						WaitTimeSeconds:   20,
					},
				},
			},
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportSQS,
			Workload: asyav1alpha1.WorkloadConfig{
				Template: asyav1alpha1.PodTemplateSpec{
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

	podTemplate := r.injectSidecar(asya)
	err := r.reconcileDeployment(context.Background(), asya, podTemplate)
	if err != nil {
		t.Fatalf("reconcileDeployment failed: %v", err)
	}

	deployment := &appsv1.Deployment{}
	err = r.Get(context.Background(), client.ObjectKey{Name: asya.Name, Namespace: asya.Namespace}, deployment)
	if err != nil {
		t.Fatalf("Failed to get deployment: %v", err)
	}

	if deployment.Spec.Template.Spec.ServiceAccountName != "asya-test-actor" {
		t.Errorf("Expected ServiceAccountName to be 'asya-test-actor', got %q", deployment.Spec.Template.Spec.ServiceAccountName)
	}
}

func TestReconcileDeployment_RabbitMQNoServiceAccount(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	_ = appsv1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				testTransportRabbitMQ: {
					Type:    testTransportRabbitMQ,
					Enabled: true,
					Config: &asyaconfig.RabbitMQConfig{
						Host:     "localhost",
						Port:     5672,
						Username: "guest",
					},
				},
			},
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
			Workload: asyav1alpha1.WorkloadConfig{
				Template: asyav1alpha1.PodTemplateSpec{
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

	podTemplate := r.injectSidecar(asya)
	err := r.reconcileDeployment(context.Background(), asya, podTemplate)
	if err != nil {
		t.Fatalf("reconcileDeployment failed: %v", err)
	}

	deployment := &appsv1.Deployment{}
	err = r.Get(context.Background(), client.ObjectKey{Name: asya.Name, Namespace: asya.Namespace}, deployment)
	if err != nil {
		t.Fatalf("Failed to get deployment: %v", err)
	}

	if deployment.Spec.Template.Spec.ServiceAccountName != "" {
		t.Errorf("Expected ServiceAccountName to be empty for RabbitMQ, got %q", deployment.Spec.Template.Spec.ServiceAccountName)
	}
}

func TestReconcileDeployment_SQSNoIRSAPreservesUserServiceAccount(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	_ = appsv1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				testTransportSQS: {
					Type:    testTransportSQS,
					Enabled: true,
					Config: &asyaconfig.SQSConfig{
						Region: "us-west-2",
					},
				},
			},
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportSQS,
			Workload: asyav1alpha1.WorkloadConfig{
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						ServiceAccountName: "user-provided-sa",
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

	podTemplate := r.injectSidecar(asya)
	err := r.reconcileDeployment(context.Background(), asya, podTemplate)
	if err != nil {
		t.Fatalf("reconcileDeployment failed: %v", err)
	}

	deployment := &appsv1.Deployment{}
	err = r.Get(context.Background(), client.ObjectKey{Name: asya.Name, Namespace: asya.Namespace}, deployment)
	if err != nil {
		t.Fatalf("Failed to get deployment: %v", err)
	}

	if deployment.Spec.Template.Spec.ServiceAccountName != "user-provided-sa" {
		t.Errorf("Expected ServiceAccountName to be preserved as 'user-provided-sa', got %q", deployment.Spec.Template.Spec.ServiceAccountName)
	}
}

func TestReconcileDeployment_SQSIRSAConflictWithUserServiceAccount(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	_ = appsv1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				testTransportSQS: {
					Type:    testTransportSQS,
					Enabled: true,
					Config: &asyaconfig.SQSConfig{
						Region:       "us-west-2",
						ActorRoleArn: "arn:aws:iam::123456789012:role/asya-actor-role",
					},
				},
			},
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportSQS,
			Workload: asyav1alpha1.WorkloadConfig{
				Template: asyav1alpha1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						ServiceAccountName: "user-provided-sa",
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

	podTemplate := r.injectSidecar(asya)
	err := r.reconcileDeployment(context.Background(), asya, podTemplate)
	if err == nil {
		t.Fatal("Expected reconcileDeployment to fail when user provides ServiceAccount with IRSA enabled")
	}

	expectedError := `cannot use custom serviceAccountName "user-provided-sa" when IRSA (actorRoleArn) is configured`
	if !strings.Contains(err.Error(), expectedError) {
		t.Errorf("Expected error containing %q, got %q", expectedError, err.Error())
	}
}

func TestUpdateQueueMetrics_Success(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)

	// Mock RabbitMQ HTTP API
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		response := rabbitmqQueueResponse{
			MessagesReady:          100,
			MessagesUnacknowledged: 10,
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()

	// Create transport config for testing
	mockTransport := &asyaconfig.TransportConfig{
		Type:    testTransportRabbitMQ,
		Enabled: true,
		Config: &asyaconfig.RabbitMQConfig{
			Host:     server.Listener.Addr().String(),
			Port:     15672,
			Username: "guest",
		},
	}

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				testTransportRabbitMQ: mockTransport,
			},
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
		},
	}

	r.updateQueueMetrics(context.Background(), asya)

	if asya.Status.QueuedMessages == nil {
		t.Fatal("Expected QueuedMessages to be set")
	}
	if *asya.Status.QueuedMessages != 100 {
		t.Errorf("Expected QueuedMessages=100, got %d", *asya.Status.QueuedMessages)
	}

	if asya.Status.ProcessingMessages == nil {
		t.Fatal("Expected ProcessingMessages to be set")
	}
	if *asya.Status.ProcessingMessages != 10 {
		t.Errorf("Expected ProcessingMessages=10, got %d", *asya.Status.ProcessingMessages)
	}
}

func TestUpdateQueueMetrics_TransportNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: make(map[string]*asyaconfig.TransportConfig),
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: "nonexistent",
		},
	}

	r.updateQueueMetrics(context.Background(), asya)

	if asya.Status.QueuedMessages != nil {
		t.Error("Expected QueuedMessages to remain nil for missing transport")
	}
}

func TestGetHPADesiredReplicas_Success(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = autoscalingv2.AddToScheme(scheme)

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
	}

	hpa := &autoscalingv2.HorizontalPodAutoscaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "keda-hpa-test-actor",
			Namespace: "default",
		},
		Status: autoscalingv2.HorizontalPodAutoscalerStatus{
			DesiredReplicas: 5,
		},
	}

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(hpa).Build(),
		Scheme: scheme,
	}

	desired, err := r.getHPADesiredReplicas(context.Background(), asya)
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if desired == nil {
		t.Fatal("Expected desired replicas, got nil")
	}

	if *desired != 5 {
		t.Errorf("Expected desired replicas = 5, got %d", *desired)
	}
}

func TestGetHPADesiredReplicas_NotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = autoscalingv2.AddToScheme(scheme)

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
	}

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
	}

	desired, err := r.getHPADesiredReplicas(context.Background(), asya)
	if err != nil {
		t.Fatalf("Expected no error for not found, got %v", err)
	}

	if desired != nil {
		t.Errorf("Expected nil for not found HPA, got %d", *desired)
	}
}

func TestGetHPADesiredReplicas_ZeroReplicas(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = autoscalingv2.AddToScheme(scheme)

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
	}

	hpa := &autoscalingv2.HorizontalPodAutoscaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "keda-hpa-test-actor",
			Namespace: "default",
		},
		Status: autoscalingv2.HorizontalPodAutoscalerStatus{
			DesiredReplicas: 0,
		},
	}

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(hpa).Build(),
		Scheme: scheme,
	}

	desired, err := r.getHPADesiredReplicas(context.Background(), asya)
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if desired != nil {
		t.Errorf("Expected nil for zero desired replicas, got %d", *desired)
	}
}

func TestReconcileDelete_RemovesFinalizer(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:       "test-actor",
			Namespace:  "default",
			Finalizers: []string{actorFinalizer},
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportSQS,
		},
	}

	transportRegistry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			testTransportSQS: {
				Type:    testTransportSQS,
				Enabled: true,
				Config: &asyaconfig.SQSConfig{
					Region:   "us-east-1",
					Endpoint: "http://localstack:4566",
				},
			},
		},
	}

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(asya).Build()

	r := &AsyncActorReconciler{
		Client:            fakeClient,
		Scheme:            scheme,
		TransportRegistry: transportRegistry,
		TransportFactory:  transports.NewFactory(fakeClient, transportRegistry),
	}

	_, err := r.reconcileDelete(context.Background(), asya)
	if err != nil {
		t.Fatalf("reconcileDelete failed: %v", err)
	}

	var updatedAsya asyav1alpha1.AsyncActor
	err = r.Get(context.Background(), client.ObjectKey{Name: "test-actor", Namespace: "default"}, &updatedAsya)
	if err != nil {
		t.Fatalf("Failed to get updated AsyncActor: %v", err)
	}

	if len(updatedAsya.Finalizers) != 0 {
		t.Errorf("Expected finalizer to be removed, but finalizers still present: %v", updatedAsya.Finalizers)
	}
}

func TestReconcileDelete_HandlesRabbitMQTransport(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:       "test-actor-rabbitmq",
			Namespace:  "default",
			Finalizers: []string{actorFinalizer},
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: testTransportRabbitMQ,
		},
	}

	transportRegistry := &asyaconfig.TransportRegistry{
		Transports: map[string]*asyaconfig.TransportConfig{
			testTransportRabbitMQ: {
				Type:    testTransportRabbitMQ,
				Enabled: true,
				Config: &asyaconfig.RabbitMQConfig{
					Host:     "localhost",
					Port:     5672,
					Username: "guest",
					Password: "guest",
				},
			},
		},
	}

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(asya).Build()

	r := &AsyncActorReconciler{
		Client:            fakeClient,
		Scheme:            scheme,
		TransportRegistry: transportRegistry,
		TransportFactory:  transports.NewFactory(fakeClient, transportRegistry),
	}

	_, err := r.reconcileDelete(context.Background(), asya)
	if err != nil {
		t.Fatalf("reconcileDelete failed: %v", err)
	}

	var updatedAsya asyav1alpha1.AsyncActor
	err = r.Get(context.Background(), client.ObjectKey{Name: "test-actor-rabbitmq", Namespace: "default"}, &updatedAsya)
	if err != nil {
		t.Fatalf("Failed to get updated AsyncActor: %v", err)
	}

	if len(updatedAsya.Finalizers) != 0 {
		t.Errorf("Expected finalizer to be removed, but finalizers still present: %v", updatedAsya.Finalizers)
	}
}

func TestReconcileDeployment_PreservesUserLabels(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = asyav1alpha1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	_ = appsv1.AddToScheme(scheme)

	r := &AsyncActorReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
		Scheme: scheme,
		TransportRegistry: &asyaconfig.TransportRegistry{
			Transports: map[string]*asyaconfig.TransportConfig{
				"rabbitmq": {
					Type:    "rabbitmq",
					Enabled: true,
					Config:  &asyaconfig.RabbitMQConfig{},
				},
			},
		},
	}

	asya := &asyav1alpha1.AsyncActor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-actor",
			Namespace: "default",
		},
		Spec: asyav1alpha1.AsyncActorSpec{
			Transport: "rabbitmq",
			Workload: asyav1alpha1.WorkloadConfig{
				Kind: "Deployment",
				Template: asyav1alpha1.PodTemplateSpec{
					Metadata: metav1.ObjectMeta{
						Labels: map[string]string{
							"app":                  "custom-app-value",
							"user-label":           "user-value",
							"asya.sh/custom-label": "custom-value",
						},
						Annotations: map[string]string{
							"user-annotation": "annotation-value",
						},
					},
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

	podTemplate := r.injectSidecar(asya)
	err := r.reconcileDeployment(context.Background(), asya, podTemplate)
	if err != nil {
		t.Fatalf("reconcileDeployment failed: %v", err)
	}

	deployment := &appsv1.Deployment{}
	err = r.Get(context.Background(), client.ObjectKey{Name: asya.Name, Namespace: asya.Namespace}, deployment)
	if err != nil {
		t.Fatalf("Failed to get deployment: %v", err)
	}

	labels := deployment.Spec.Template.Labels

	if labels["app"] != "custom-app-value" {
		t.Errorf("Expected user-provided 'app' label to be preserved, got %q", labels["app"])
	}

	if labels["user-label"] != "user-value" {
		t.Errorf("Expected 'user-label' to be preserved, got %q", labels["user-label"])
	}

	if labels["asya.sh/custom-label"] != "custom-value" {
		t.Errorf("Expected 'asya.sh/custom-label' to be preserved, got %q", labels["asya.sh/custom-label"])
	}

	if labels["asya.sh/asya"] != "test-actor" {
		t.Errorf("Expected operator-managed 'asya.sh/asya' label to be added, got %q", labels["asya.sh/asya"])
	}

	if labels["asya.sh/workload"] != "deployment" {
		t.Errorf("Expected operator-managed 'asya.sh/workload' label to be added, got %q", labels["asya.sh/workload"])
	}

	annotations := deployment.Spec.Template.Annotations
	if annotations["user-annotation"] != "annotation-value" {
		t.Errorf("Expected 'user-annotation' to be preserved, got %q", annotations["user-annotation"])
	}
}

func TestUpdatePodStateCounts(t *testing.T) {
	tests := []struct {
		name            string
		pods            []corev1.Pod
		expectedPending int32
		expectedFailing int32
		description     string
	}{
		{
			name: "Running pod with ready containers",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-1",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						Conditions: []corev1.PodCondition{
							{Type: corev1.PodReady, Status: corev1.ConditionTrue},
						},
						ContainerStatuses: []corev1.ContainerStatus{
							{Name: runtimeContainerName, Ready: true, State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}}},
							{Name: sidecarName, Ready: true, State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}}},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 0,
			description:     "Running pod should not count as pending or failing",
		},
		{
			name: "Pending pod with init container in CrashLoopBackOff",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-backoff",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name: "migrations-waiting-init",
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"},
								},
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Init container in CrashLoopBackOff should count as failing, not pending",
		},
		{
			name: "Pending pod with init container in ImagePullBackOff",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-imagepull",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name: "init-container",
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "ImagePullBackOff"},
								},
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Init container in ImagePullBackOff should count as failing",
		},
		{
			name: "Running pod with container in CrashLoopBackOff",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-runtime-crash",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						Conditions: []corev1.PodCondition{
							{Type: corev1.PodReady, Status: corev1.ConditionFalse},
						},
						ContainerStatuses: []corev1.ContainerStatus{
							{
								Name: runtimeContainerName,
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"},
								},
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Runtime container in CrashLoopBackOff should count as failing",
		},
		{
			name: "Pending pod without BackOff errors",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-pending",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name: "init-container",
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "PodInitializing"},
								},
							},
						},
					},
				},
			},
			expectedPending: 1,
			expectedFailing: 0,
			description:     "Pending pod without BackOff should count as pending",
		},
		{
			name: "Multiple pods with mixed states",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-ready",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						Conditions: []corev1.PodCondition{
							{Type: corev1.PodReady, Status: corev1.ConditionTrue},
						},
					},
				},
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-backoff",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name:  "init",
								State: corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"}},
							},
						},
					},
				},
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-pending",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
					},
				},
			},
			expectedPending: 1,
			expectedFailing: 1,
			description:     "Multiple pods should be counted correctly",
		},
		{
			name: "Pod in Failed phase",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-failed",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodFailed,
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Failed pod should count as failing",
		},
		{
			name: "Init container in ErrImagePull",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-errimagepull",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name:  "init",
								State: corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "ErrImagePull"}},
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Init container in ErrImagePull should count as failing",
		},
		{
			name: "Init container in CreateContainerConfigError",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-config-error",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name:  "init",
								State: corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "CreateContainerConfigError"}},
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Init container in CreateContainerConfigError should count as failing",
		},
		{
			name: "Runtime container in RunContainerError",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-run-error",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						Conditions: []corev1.PodCondition{
							{Type: corev1.PodReady, Status: corev1.ConditionFalse},
						},
						ContainerStatuses: []corev1.ContainerStatus{
							{
								Name:  runtimeContainerName,
								State: corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "RunContainerError"}},
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Runtime container in RunContainerError should count as failing",
		},
		{
			name: "Pending pod with volume mount failure (ConfigMap not found)",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-volume-mount-fail",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						Conditions: []corev1.PodCondition{
							{
								Type:    corev1.ContainersReady,
								Status:  corev1.ConditionFalse,
								Message: "MountVolume.SetUp failed for volume \"app-config-volume\" : configmap \"scorer-gemini-captioning-eu-app-config\" not found",
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Pod with volume mount failure should count as failing",
		},
		{
			name: "Pending pod with secret not found",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-secret-not-found",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						Conditions: []corev1.PodCondition{
							{
								Type:    corev1.ContainersReady,
								Status:  corev1.ConditionFalse,
								Message: "MountVolume.SetUp failed for volume \"credentials\" : secret \"api-credentials\" not found",
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Pod with secret not found should count as failing",
		},
		{
			name: "Pending pod with unschedulable condition",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-unschedulable",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						Conditions: []corev1.PodCondition{
							{
								Type:   corev1.PodScheduled,
								Status: corev1.ConditionFalse,
								Reason: "Unschedulable",
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Unschedulable pod should count as failing",
		},
		{
			name: "Pending pod waiting for scheduling (not failing)",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-waiting-schedule",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						Conditions: []corev1.PodCondition{
							{
								Type:   corev1.PodScheduled,
								Status: corev1.ConditionTrue,
							},
						},
					},
				},
			},
			expectedPending: 1,
			expectedFailing: 0,
			description:     "Pod waiting for containers to start should count as pending",
		},
		{
			name: "Pending pod with PodReadyToStartContainers=False (volume mount failure)",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "pod-volume-fail",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						Conditions: []corev1.PodCondition{
							{
								Type:   corev1.PodReadyToStartContainers,
								Status: corev1.ConditionFalse,
							},
						},
					},
				},
			},
			expectedPending: 0,
			expectedFailing: 1,
			description:     "Pod with PodReadyToStartContainers=False should count as failing",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = corev1.AddToScheme(scheme)
			_ = asyav1alpha1.AddToScheme(scheme)

			objs := []client.Object{}
			for i := range tt.pods {
				objs = append(objs, &tt.pods[i])
			}

			fakeClient := fake.NewClientBuilder().
				WithScheme(scheme).
				WithObjects(objs...).
				Build()

			r := &AsyncActorReconciler{
				Client: fakeClient,
				Scheme: scheme,
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
			}

			r.updatePodStateCounts(context.Background(), asya)

			if asya.Status.PendingReplicas == nil {
				t.Errorf("PendingReplicas is nil")
			} else if *asya.Status.PendingReplicas != tt.expectedPending {
				t.Errorf("PendingReplicas = %d, want %d (%s)", *asya.Status.PendingReplicas, tt.expectedPending, tt.description)
			}

			if asya.Status.FailingPods == nil {
				t.Errorf("FailingPods is nil")
			} else if *asya.Status.FailingPods != tt.expectedFailing {
				t.Errorf("FailingPods = %d, want %d (%s)", *asya.Status.FailingPods, tt.expectedFailing, tt.description)
			}
		})
	}
}

func TestIsPodFailing(t *testing.T) {
	tests := []struct {
		name     string
		pod      corev1.Pod
		expected bool
	}{
		{
			name: "Pod with volume mount failure",
			pod: corev1.Pod{
				Status: corev1.PodStatus{
					Conditions: []corev1.PodCondition{
						{
							Type:    corev1.ContainersReady,
							Status:  corev1.ConditionFalse,
							Message: "MountVolume.SetUp failed for volume \"config\" : configmap \"missing-config\" not found",
						},
					},
				},
			},
			expected: true,
		},
		{
			name: "Pod with secret not found",
			pod: corev1.Pod{
				Status: corev1.PodStatus{
					Conditions: []corev1.PodCondition{
						{
							Type:    corev1.ContainersReady,
							Status:  corev1.ConditionFalse,
							Message: "secret \"api-credentials\" not found",
						},
					},
				},
			},
			expected: true,
		},
		{
			name: "Pod with unschedulable condition",
			pod: corev1.Pod{
				Status: corev1.PodStatus{
					Conditions: []corev1.PodCondition{
						{
							Type:   corev1.PodScheduled,
							Status: corev1.ConditionFalse,
							Reason: "Unschedulable",
						},
					},
				},
			},
			expected: true,
		},
		{
			name: "Pod with ImagePullBackOff in init container",
			pod: corev1.Pod{
				Status: corev1.PodStatus{
					InitContainerStatuses: []corev1.ContainerStatus{
						{
							State: corev1.ContainerState{
								Waiting: &corev1.ContainerStateWaiting{Reason: "ImagePullBackOff"},
							},
						},
					},
				},
			},
			expected: true,
		},
		{
			name: "Pod with CrashLoopBackOff in regular container",
			pod: corev1.Pod{
				Status: corev1.PodStatus{
					ContainerStatuses: []corev1.ContainerStatus{
						{
							State: corev1.ContainerState{
								Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"},
							},
						},
					},
				},
			},
			expected: true,
		},
		{
			name: "Healthy pod waiting for containers",
			pod: corev1.Pod{
				Status: corev1.PodStatus{
					Conditions: []corev1.PodCondition{
						{
							Type:   corev1.PodScheduled,
							Status: corev1.ConditionTrue,
						},
					},
				},
			},
			expected: false,
		},
		{
			name: "Running pod",
			pod: corev1.Pod{
				Status: corev1.PodStatus{
					Phase: corev1.PodRunning,
					Conditions: []corev1.PodCondition{
						{Type: corev1.PodReady, Status: corev1.ConditionTrue},
					},
					ContainerStatuses: []corev1.ContainerStatus{
						{State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}}},
					},
				},
			},
			expected: false,
		},
		{
			name: "Pod with PodReadyToStartContainers=False",
			pod: corev1.Pod{
				Status: corev1.PodStatus{
					Conditions: []corev1.PodCondition{
						{
							Type:   corev1.PodReadyToStartContainers,
							Status: corev1.ConditionFalse,
						},
					},
				},
			},
			expected: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := isPodFailing(&tt.pod)
			if result != tt.expected {
				t.Errorf("isPodFailing() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestCheckPodHealth(t *testing.T) {
	tests := []struct {
		name          string
		pods          []corev1.Pod
		expectHealthy bool
		expectMessage string
	}{
		{
			name: "Healthy pods",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-1",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						ContainerStatuses: []corev1.ContainerStatus{
							{Name: runtimeContainerName, RestartCount: 0, State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}}},
							{Name: sidecarName, RestartCount: 0, State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}}},
						},
					},
				},
			},
			expectHealthy: true,
			expectMessage: "All pods healthy",
		},
		{
			name: "Init container in CrashLoopBackOff",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-backoff",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name: "migrations-waiting-init",
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"},
								},
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Init container migrations-waiting-init in CrashLoopBackOff (pod: test-pod-backoff)",
		},
		{
			name: "Init container in ImagePullBackOff",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-imagepull",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name: "init-container",
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "ImagePullBackOff"},
								},
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Init container init-container in ImagePullBackOff (pod: test-pod-imagepull)",
		},
		{
			name: "Runtime container in CrashLoopBackOff",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-runtime",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						ContainerStatuses: []corev1.ContainerStatus{
							{
								Name: runtimeContainerName,
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"},
								},
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Container asya-runtime in CrashLoopBackOff (pod: test-pod-runtime)",
		},
		{
			name: "Pod in Failed phase",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-failed",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodFailed,
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Pod test-pod-failed in Failed phase",
		},
		{
			name: "Init container with too many restarts",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-restarts",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name:         "init-container",
								RestartCount: 10,
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Init container init-container has 10 restarts (pod: test-pod-restarts)",
		},
		{
			name: "Runtime container with too many restarts",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-restarts",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						ContainerStatuses: []corev1.ContainerStatus{
							{
								Name:         runtimeContainerName,
								RestartCount: 10,
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Container asya-runtime has 10 restarts (pod: test-pod-restarts)",
		},
		{
			name:          "No pods",
			pods:          []corev1.Pod{},
			expectHealthy: false,
			expectMessage: "No pods found",
		},
		{
			name: "Init container in ErrImagePull",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-errimagepull",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name: "init-container",
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "ErrImagePull"},
								},
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Init container init-container in ErrImagePull (pod: test-pod-errimagepull)",
		},
		{
			name: "Init container in CreateContainerConfigError",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-config-error",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodPending,
						InitContainerStatuses: []corev1.ContainerStatus{
							{
								Name: "init-container",
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "CreateContainerConfigError"},
								},
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Init container init-container in CreateContainerConfigError (pod: test-pod-config-error)",
		},
		{
			name: "Runtime container in CreateContainerError",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-create-error",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						ContainerStatuses: []corev1.ContainerStatus{
							{
								Name: runtimeContainerName,
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "CreateContainerError"},
								},
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Container asya-runtime in CreateContainerError (pod: test-pod-create-error)",
		},
		{
			name: "Runtime container in RunContainerError",
			pods: []corev1.Pod{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-run-error",
						Namespace: "default",
						Labels:    map[string]string{"asya.sh/asya": "test-actor"},
					},
					Status: corev1.PodStatus{
						Phase: corev1.PodRunning,
						ContainerStatuses: []corev1.ContainerStatus{
							{
								Name: sidecarName,
								State: corev1.ContainerState{
									Waiting: &corev1.ContainerStateWaiting{Reason: "RunContainerError"},
								},
							},
						},
					},
				},
			},
			expectHealthy: false,
			expectMessage: "Container asya-sidecar in RunContainerError (pod: test-pod-run-error)",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = corev1.AddToScheme(scheme)
			_ = asyav1alpha1.AddToScheme(scheme)

			objs := []client.Object{}
			for i := range tt.pods {
				objs = append(objs, &tt.pods[i])
			}

			fakeClient := fake.NewClientBuilder().
				WithScheme(scheme).
				WithObjects(objs...).
				Build()

			r := &AsyncActorReconciler{
				Client: fakeClient,
				Scheme: scheme,
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
			}

			healthy, message := r.checkPodHealth(context.Background(), asya)

			if healthy != tt.expectHealthy {
				t.Errorf("checkPodHealth() healthy = %v, want %v", healthy, tt.expectHealthy)
			}

			if message != tt.expectMessage {
				t.Errorf("checkPodHealth() message = %q, want %q", message, tt.expectMessage)
			}
		})
	}
}

func TestBuildSidecarEnv_GatewayURL(t *testing.T) {
	tests := []struct {
		name                 string
		reconcilerGatewayURL string
		asyncActorGatewayURL string
		expectedGatewayURL   string
	}{
		{
			name:                 "operator-level gateway URL",
			reconcilerGatewayURL: "http://asya-gateway.asya-system.svc.cluster.local:8080",
			asyncActorGatewayURL: "",
			expectedGatewayURL:   "http://asya-gateway.asya-system.svc.cluster.local:8080",
		},
		{
			name:                 "AsyncActor-level gateway URL (fallback)",
			reconcilerGatewayURL: "",
			asyncActorGatewayURL: "http://asya-gateway.custom.svc.cluster.local:9090",
			expectedGatewayURL:   "http://asya-gateway.custom.svc.cluster.local:9090",
		},
		{
			name:                 "operator-level takes precedence over AsyncActor-level",
			reconcilerGatewayURL: "http://asya-gateway.asya-system.svc.cluster.local:8080",
			asyncActorGatewayURL: "http://asya-gateway.custom.svc.cluster.local:9090",
			expectedGatewayURL:   "http://asya-gateway.asya-system.svc.cluster.local:8080",
		},
		{
			name:                 "no gateway URL configured",
			reconcilerGatewayURL: "",
			asyncActorGatewayURL: "",
			expectedGatewayURL:   "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)
			_ = corev1.AddToScheme(scheme)

			r := &AsyncActorReconciler{
				Client:     fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme:     scheme,
				GatewayURL: tt.reconcilerGatewayURL,
				TransportRegistry: &asyaconfig.TransportRegistry{
					Transports: make(map[string]*asyaconfig.TransportConfig),
				},
			}

			containers := []corev1.Container{
				{
					Name:  "asya-runtime",
					Image: "python:3.13-slim",
				},
			}

			if tt.asyncActorGatewayURL != "" {
				containers[0].Env = []corev1.EnvVar{
					{Name: "ASYA_GATEWAY_URL", Value: tt.asyncActorGatewayURL},
				}
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Workload: asyav1alpha1.WorkloadConfig{
						Template: asyav1alpha1.PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: containers,
							},
						},
					},
				},
			}

			sidecarEnv := r.buildSidecarEnv(asya)

			var gatewayURL string
			for _, env := range sidecarEnv {
				if env.Name == "ASYA_GATEWAY_URL" {
					gatewayURL = env.Value
					break
				}
			}

			if gatewayURL != tt.expectedGatewayURL {
				t.Errorf("buildSidecarEnv() ASYA_GATEWAY_URL = %q, want %q", gatewayURL, tt.expectedGatewayURL)
			}
		})
	}
}

func TestValidateAsyncActorSpec_ForbiddenSidecarContainer(t *testing.T) {
	tests := []struct {
		name        string
		containers  []corev1.Container
		expectError bool
		errorMsg    string
	}{
		{
			name: "valid spec with only asya-runtime",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
			},
			expectError: false,
		},
		{
			name: "forbidden asya-sidecar container",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{Name: "asya-sidecar", Image: "malicious:latest"},
			},
			expectError: true,
			errorMsg:    "container name 'asya-sidecar' is reserved for the injected sidecar and cannot be defined in the AsyncActor spec",
		},
		{
			name: "only asya-sidecar without asya-runtime",
			containers: []corev1.Container{
				{Name: "asya-sidecar", Image: "custom:latest"},
			},
			expectError: true,
			errorMsg:    "container name 'asya-sidecar' is reserved",
		},
		{
			name: "multiple containers with asya-sidecar",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{Name: "helper", Image: "helper:latest"},
				{Name: "asya-sidecar", Image: "malicious:latest"},
			},
			expectError: true,
			errorMsg:    "container name 'asya-sidecar' is reserved",
		},
		{
			name: "valid multi-container without asya-sidecar",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{Name: "helper", Image: "helper:latest"},
				{Name: "redis", Image: "redis:7-alpine"},
			},
			expectError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)
			_ = corev1.AddToScheme(scheme)

			r := &AsyncActorReconciler{
				Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme: scheme,
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Workload: asyav1alpha1.WorkloadConfig{
						Template: asyav1alpha1.PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: tt.containers,
							},
						},
					},
				},
			}

			err := r.validateAsyncActorSpec(asya)

			if tt.expectError {
				if err == nil {
					t.Errorf("Expected error containing %q, got nil", tt.errorMsg)
				} else if !strings.Contains(err.Error(), tt.errorMsg) {
					t.Errorf("Expected error containing %q, got %q", tt.errorMsg, err.Error())
				}
			} else {
				if err != nil {
					t.Errorf("Expected no error, got %v", err)
				}
			}
		})
	}
}

func TestValidateAsyncActorSpec_ForbiddenInitContainer(t *testing.T) {
	tests := []struct {
		name           string
		containers     []corev1.Container
		initContainers []corev1.Container
		expectError    bool
		errorMsg       string
	}{
		{
			name: "valid spec with init container",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
			},
			initContainers: []corev1.Container{
				{Name: "setup", Image: "busybox:latest"},
			},
			expectError: false,
		},
		{
			name: "forbidden asya-sidecar in init containers",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
			},
			initContainers: []corev1.Container{
				{Name: "asya-sidecar", Image: "malicious:latest"},
			},
			expectError: true,
			errorMsg:    "init container name 'asya-sidecar' is reserved for operator use and cannot be defined in the AsyncActor spec",
		},
		{
			name: "multiple init containers with asya-sidecar",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
			},
			initContainers: []corev1.Container{
				{Name: "setup", Image: "busybox:latest"},
				{Name: "asya-sidecar", Image: "malicious:latest"},
			},
			expectError: true,
			errorMsg:    "init container name 'asya-sidecar' is reserved",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)
			_ = corev1.AddToScheme(scheme)

			r := &AsyncActorReconciler{
				Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme: scheme,
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Workload: asyav1alpha1.WorkloadConfig{
						Template: asyav1alpha1.PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers:     tt.containers,
								InitContainers: tt.initContainers,
							},
						},
					},
				},
			}

			err := r.validateAsyncActorSpec(asya)

			if tt.expectError {
				if err == nil {
					t.Errorf("Expected error containing %q, got nil", tt.errorMsg)
				} else if !strings.Contains(err.Error(), tt.errorMsg) {
					t.Errorf("Expected error containing %q, got %q", tt.errorMsg, err.Error())
				}
			} else {
				if err != nil {
					t.Errorf("Expected no error, got %v", err)
				}
			}
		})
	}
}

func TestValidateAsyncActorSpec_MissingRuntimeContainer(t *testing.T) {
	tests := []struct {
		name        string
		containers  []corev1.Container
		expectError bool
		errorMsg    string
	}{
		{
			name: "valid spec with asya-runtime",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
			},
			expectError: false,
		},
		{
			name: "missing asya-runtime container",
			containers: []corev1.Container{
				{Name: "custom-runtime", Image: "python:3.13-slim"},
			},
			expectError: true,
			errorMsg:    "workload must contain exactly one container named 'asya-runtime'",
		},
		{
			name:        "no containers",
			containers:  []corev1.Container{},
			expectError: true,
			errorMsg:    "workload must contain exactly one container named 'asya-runtime'",
		},
		{
			name: "multiple containers with asya-runtime",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{Name: "helper", Image: "helper:latest"},
			},
			expectError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)
			_ = corev1.AddToScheme(scheme)

			r := &AsyncActorReconciler{
				Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme: scheme,
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Workload: asyav1alpha1.WorkloadConfig{
						Template: asyav1alpha1.PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: tt.containers,
							},
						},
					},
				},
			}

			err := r.validateAsyncActorSpec(asya)

			if tt.expectError {
				if err == nil {
					t.Errorf("Expected error containing %q, got nil", tt.errorMsg)
				} else if !strings.Contains(err.Error(), tt.errorMsg) {
					t.Errorf("Expected error containing %q, got %q", tt.errorMsg, err.Error())
				}
			} else {
				if err != nil {
					t.Errorf("Expected no error, got %v", err)
				}
			}
		})
	}
}

func TestValidateAsyncActorSpec_CommandOverride(t *testing.T) {
	tests := []struct {
		name        string
		containers  []corev1.Container
		expectError bool
		errorMsg    string
	}{
		{
			name: "valid spec without command override",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
			},
			expectError: false,
		},
		{
			name: "asya-runtime with command override",
			containers: []corev1.Container{
				{
					Name:    "asya-runtime",
					Image:   "python:3.13-slim",
					Command: []string{"python", "malicious.py"},
				},
			},
			expectError: true,
			errorMsg:    "container 'asya-runtime' cannot override command (command is managed by operator)",
		},
		{
			name: "asya-runtime with empty command array",
			containers: []corev1.Container{
				{
					Name:    "asya-runtime",
					Image:   "python:3.13-slim",
					Command: []string{},
				},
			},
			expectError: false,
		},
		{
			name: "helper container with command is allowed",
			containers: []corev1.Container{
				{Name: "asya-runtime", Image: "python:3.13-slim"},
				{
					Name:    "helper",
					Image:   "helper:latest",
					Command: []string{"sh", "-c", "echo hello"},
				},
			},
			expectError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			scheme := runtime.NewScheme()
			_ = asyav1alpha1.AddToScheme(scheme)
			_ = corev1.AddToScheme(scheme)

			r := &AsyncActorReconciler{
				Client: fake.NewClientBuilder().WithScheme(scheme).Build(),
				Scheme: scheme,
			}

			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-actor",
					Namespace: "default",
				},
				Spec: asyav1alpha1.AsyncActorSpec{
					Transport: testTransportRabbitMQ,
					Workload: asyav1alpha1.WorkloadConfig{
						Template: asyav1alpha1.PodTemplateSpec{
							Spec: corev1.PodSpec{
								Containers: tt.containers,
							},
						},
					},
				},
			}

			err := r.validateAsyncActorSpec(asya)

			if tt.expectError {
				if err == nil {
					t.Errorf("Expected error containing %q, got nil", tt.errorMsg)
				} else if !strings.Contains(err.Error(), tt.errorMsg) {
					t.Errorf("Expected error containing %q, got %q", tt.errorMsg, err.Error())
				}
			} else {
				if err != nil {
					t.Errorf("Expected no error, got %v", err)
				}
			}
		})
	}
}
