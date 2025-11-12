package main

import (
	"context"
	"flag"
	"os"
	"strconv"

	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	asyaconfig "github.com/asya/operator/internal/config"
	"github.com/asya/operator/internal/controller"
	runtimepkg "github.com/asya/operator/internal/runtime"
	"github.com/asya/operator/internal/transports"
	kedav1alpha1 "github.com/kedacore/keda/v2/apis/keda/v1alpha1"
)

var (
	scheme   = runtime.NewScheme()
	setupLog = ctrl.Log.WithName("setup")
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(asyav1alpha1.AddToScheme(scheme))
	utilruntime.Must(kedav1alpha1.AddToScheme(scheme))
}

// Startup reconciler removed - controller-runtime automatically reconciles
// existing resources when the controller starts via its watch mechanism

func main() {
	var metricsAddr string
	var enableLeaderElection bool
	var probeAddr string
	var runtimeNamespace string
	var maxConcurrentReconciles int

	flag.StringVar(&metricsAddr, "metrics-bind-address", ":8080", "The address the metric endpoint binds to.")
	flag.StringVar(&probeAddr, "health-probe-bind-address", ":8081", "The address the probe endpoint binds to.")
	flag.BoolVar(&enableLeaderElection, "leader-elect", false,
		"Enable leader election for controller manager. "+
			"Enabling this will ensure there is only one active controller manager.")

	// Runtime ConfigMap configuration
	flag.StringVar(&runtimeNamespace, "runtime-namespace", getEnvOrDefault("ASYA_RUNTIME_NAMESPACE", "asya"),
		"Namespace to create runtime ConfigMap in")

	// Controller configuration
	flag.IntVar(&maxConcurrentReconciles, "max-concurrent-reconciles", getEnvIntOrDefault("ASYA_MAX_CONCURRENT_RECONCILES", 10),
		"Maximum number of concurrent AsyncActor reconciliations")

	opts := zap.Options{
		Development: true,
	}
	opts.BindFlags(flag.CommandLine)
	flag.Parse()

	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
		Scheme: scheme,
		Metrics: metricsserver.Options{
			BindAddress: metricsAddr,
		},
		HealthProbeBindAddress: probeAddr,
		LeaderElection:         enableLeaderElection,
		LeaderElectionID:       "asya-operator.asya.sh",
	})
	if err != nil {
		setupLog.Error(err, "unable to start manager")
		os.Exit(1)
	}

	// Load transport registry
	setupLog.Info("Loading transport registry configuration")
	transportRegistry, err := asyaconfig.LoadTransportRegistry()
	if err != nil {
		setupLog.Error(err, "unable to load transport registry")
		os.Exit(1)
	}
	setupLog.Info("Transport registry loaded", "transports", len(transportRegistry.Transports))

	// Create transport factory
	transportFactory := transports.NewFactory(mgr.GetClient(), transportRegistry)

	// Read gateway URL from environment
	gatewayURL := os.Getenv("ASYA_GATEWAY_URL")

	asyncActorReconciler := &controller.AsyncActorReconciler{
		Client:                  mgr.GetClient(),
		Scheme:                  mgr.GetScheme(),
		TransportRegistry:       transportRegistry,
		TransportFactory:        transportFactory,
		MaxConcurrentReconciles: maxConcurrentReconciles,
		GatewayURL:              gatewayURL,
	}
	if err = asyncActorReconciler.SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "AsyncActor")
		os.Exit(1)
	}

	// Setup runtime ConfigMap reconciler
	// Runtime script is embedded in the operator image at /runtime/asya_runtime.py
	setupLog.Info("Setting up runtime ConfigMap", "namespace", runtimeNamespace)

	const embeddedRuntimePath = "/runtime/asya_runtime.py"
	loader := runtimepkg.NewLocalFileLoader(embeddedRuntimePath)

	runtimeReconciler := runtimepkg.NewConfigMapReconciler(
		mgr.GetClient(),
		loader,
		runtimeNamespace,
		nil, // Use default labels
	)

	// Add runtime reconciler as a runnable that executes after cache sync
	if err := mgr.Add(manager.RunnableFunc(func(ctx context.Context) error {
		setupLog.Info("Reconciling runtime ConfigMap after cache sync")
		if err := runtimeReconciler.Reconcile(ctx); err != nil {
			setupLog.Error(err, "failed to reconcile runtime ConfigMap")
			return err
		}
		setupLog.Info("Runtime ConfigMap reconciled successfully")
		return nil
	})); err != nil {
		setupLog.Error(err, "unable to add runtime reconciler")
		os.Exit(1)
	}

	// Note: No startup reconciler needed - controller-runtime's watch mechanism
	// automatically reconciles all existing AsyncActors when the controller starts

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up ready check")
		os.Exit(1)
	}

	setupLog.Info("starting manager")
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		setupLog.Error(err, "problem running manager")
		os.Exit(1)
	}
}

// getEnvOrDefault gets an environment variable or returns a default value
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// getEnvIntOrDefault gets an integer environment variable or returns a default value
func getEnvIntOrDefault(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if intValue, err := strconv.Atoi(value); err == nil {
			return intValue
		}
	}
	return defaultValue
}
