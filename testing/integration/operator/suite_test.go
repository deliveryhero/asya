//go:build integration

package integration

import (
	"context"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/apimachinery/pkg/util/yaml"
	"k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/rest"
	"k8s.io/klog/v2"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	"github.com/asya/operator/internal/config"
	"github.com/asya/operator/internal/controller"
	"github.com/asya/operator/internal/transports"
	kedav1alpha1 "github.com/kedacore/keda/v2/apis/keda/v1alpha1"
)

var (
	cfg       *rest.Config
	k8sClient client.Client
	testEnv   *envtest.Environment
	ctx       context.Context
	cancel    context.CancelFunc
)

func TestMain(m *testing.M) {
	logf.SetLogger(zap.New(zap.WriteTo(os.Stderr), zap.UseDevMode(true)))

	// Suppress klog warnings from reflector during test teardown
	klog.InitFlags(nil)
	_ = flag.Set("v", "0")
	_ = flag.Set("logtostderr", "false")

	// Setup runtime script for integration tests
	// Create temporary /runtime directory and copy script from testdata
	tmpRuntimeDir := filepath.Join(os.TempDir(), "runtime")
	if err := os.MkdirAll(tmpRuntimeDir, 0755); err != nil {
		panic(fmt.Sprintf("failed to create runtime directory: %v", err))
	}
	runtimeSrc := filepath.Join("testdata", "runtime_symlink", "asya_runtime.py")
	runtimeDst := filepath.Join(tmpRuntimeDir, "asya_runtime.py")
	content, err := os.ReadFile(runtimeSrc)
	if err != nil {
		panic(fmt.Sprintf("failed to read runtime script from %s: %v", runtimeSrc, err))
	}
	if err := os.WriteFile(runtimeDst, content, 0644); err != nil {
		panic(fmt.Sprintf("failed to write runtime script to %s: %v", runtimeDst, err))
	}

	// Override runtime script path for tests via environment variable
	os.Setenv("ASYA_RUNTIME_SCRIPT_PATH", runtimeDst)

	// Disable queue management in integration tests (envtest has no real RabbitMQ/SQS)
	// Queue validation is tested in unit tests with mocks (queue_validation_test.go)
	os.Setenv("ASYA_DISABLE_QUEUE_MANAGEMENT", "true")

	ctx, cancel = context.WithCancel(context.TODO())

	// Bootstrap test environment
	testEnv = &envtest.Environment{
		CRDDirectoryPaths:     []string{filepath.Join("..", "..", "..", "src", "asya-operator", "config", "crd")},
		ErrorIfCRDPathMissing: true,
	}

	cfg, err = testEnv.Start()
	if err != nil {
		panic(err)
	}
	if cfg == nil {
		panic("cfg is nil")
	}

	err = asyav1alpha1.AddToScheme(scheme.Scheme)
	if err != nil {
		panic(err)
	}

	err = kedav1alpha1.AddToScheme(scheme.Scheme)
	if err != nil {
		panic(err)
	}

	k8sClient, err = client.New(cfg, client.Options{Scheme: scheme.Scheme})
	if err != nil {
		panic(err)
	}
	if k8sClient == nil {
		panic("k8sClient is nil")
	}

	// Create test namespace
	ns := &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name: "test-system",
		},
	}
	err = k8sClient.Create(ctx, ns)
	if err != nil {
		panic(err)
	}

	// Start the controller manager
	k8sManager, err := ctrl.NewManager(cfg, ctrl.Options{
		Scheme: scheme.Scheme,
		Metrics: metricsserver.Options{
			BindAddress: "0",
		},
	})
	if err != nil {
		panic(err)
	}

	// Create transport registry for integration tests
	// NOTE: Integration tests with envtest don't have real RabbitMQ/SQS services
	// Queue validation/creation is tested in unit tests with mocks (queue_validation_test.go)
	// These integration tests focus on K8s resource creation (Deployments, ConfigMaps, etc.)
	// We enable transports but rely on AutoCreate=false to skip queue operations
	// The controller will attempt validation but gracefully continue on network errors
	transportRegistry := &config.TransportRegistry{
		Transports: map[string]*config.TransportConfig{
			"rabbitmq": {
				Type:    "rabbitmq",
				Enabled: true,
				Config: &config.RabbitMQConfig{
					Host:     "rabbitmq.default.svc.cluster.local",
					Port:     5672,
					Username: "guest",
					Queues: config.QueueManagementConfig{
						AutoCreate: false, // Skip queue operations - no real RabbitMQ in envtest
					},
				},
			},
			"sqs": {
				Type:    "sqs",
				Enabled: true,
				Config: &config.SQSConfig{
					Region:            "us-east-1",
					Endpoint:          "http://localhost:4566",
					AccountID:         "000000000000",
					VisibilityTimeout: 30,
					WaitTimeSeconds:   20,
					Queues: config.QueueManagementConfig{
						AutoCreate: false, // Skip queue operations - no real SQS in envtest
					},
				},
			},
		},
	}

	// Setup controller
	err = (&controller.AsyncActorReconciler{
		Client:            k8sManager.GetClient(),
		Scheme:            k8sManager.GetScheme(),
		TransportRegistry: transportRegistry,
		TransportFactory:  transports.NewFactory(k8sManager.GetClient(), transportRegistry),
	}).SetupWithManager(k8sManager)
	if err != nil {
		panic(err)
	}

	go func() {
		if err := k8sManager.Start(ctx); err != nil {
			panic(err)
		}
	}()

	// Wait for manager cache to sync
	if !k8sManager.GetCache().WaitForCacheSync(ctx) {
		panic("failed to wait for cache sync")
	}

	// Run tests
	code := m.Run()

	// Teardown
	cancel()
	err = testEnv.Stop()
	if err != nil {
		panic(err)
	}

	os.Exit(code)
}

// loadAsyncActorFromYAML loads an AsyncActor from a YAML file in testdata/
func loadAsyncActorFromYAML(t *testing.T, filename string) *asyav1alpha1.AsyncActor {
	t.Helper()

	yamlPath := filepath.Join("testdata", filename)
	yamlData, err := os.ReadFile(yamlPath)
	if err != nil {
		t.Fatalf("Failed to read YAML file %s: %v", yamlPath, err)
	}

	// First unmarshal to raw map to preserve the scaling.enabled value
	var rawData map[string]interface{}
	err = yaml.Unmarshal(yamlData, &rawData)
	if err != nil {
		t.Fatalf("Failed to unmarshal YAML to map %s: %v", yamlPath, err)
	}

	// Extract scaling.enabled from raw YAML
	scalingEnabled := true // default value
	if spec, ok := rawData["spec"].(map[string]interface{}); ok {
		if scaling, ok := spec["scaling"].(map[string]interface{}); ok {
			if enabled, ok := scaling["enabled"].(bool); ok {
				scalingEnabled = enabled
			}
		}
	}

	// Unmarshal to typed struct
	actor := &asyav1alpha1.AsyncActor{}
	err = yaml.Unmarshal(yamlData, actor)
	if err != nil {
		t.Fatalf("Failed to unmarshal YAML %s: %v", yamlPath, err)
	}

	// Assert scaling is disabled (KEDA not supported in integration tests)
	if scalingEnabled {
		t.Fatalf("scaling.enabled must be false in test YAML %s (KEDA ScaledObject CRDs not available in envtest)", filename)
	}

	// Explicitly set it to false in memory to work around Go omitempty on bool fields
	actor.Spec.Scaling.Enabled = false

	return actor
}

// disableScalingInK8s updates the AsyncActor in Kubernetes to disable scaling.
// Must be called after k8sClient.Create() to work around CRD default (false) being applied.
func disableScalingInK8s(t *testing.T, actor *asyav1alpha1.AsyncActor) {
	t.Helper()

	err := wait.PollImmediate(100*time.Millisecond, 2*time.Second, func() (bool, error) {
		// Get latest version
		if err := k8sClient.Get(ctx, types.NamespacedName{
			Name:      actor.Name,
			Namespace: actor.Namespace,
		}, actor); err != nil {
			return false, err
		}
		// Update scaling
		actor.Spec.Scaling.Enabled = false
		return k8sClient.Update(ctx, actor) == nil, nil
	})
	if err != nil {
		t.Fatalf("Failed to disable scaling: %v", err)
	}
}
