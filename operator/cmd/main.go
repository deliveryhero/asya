package main

import (
	"context"
	"flag"
	"os"
	"path/filepath"

	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	"github.com/asya/operator/internal/controller"
	runtimepkg "github.com/asya/operator/internal/runtime"
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

func main() {
	var metricsAddr string
	var enableLeaderElection bool
	var probeAddr string
	var runtimeSource string
	var runtimeLocalPath string
	var runtimeGitHubRepo string
	var runtimeVersion string
	var runtimeNamespace string

	flag.StringVar(&metricsAddr, "metrics-bind-address", ":8080", "The address the metric endpoint binds to.")
	flag.StringVar(&probeAddr, "health-probe-bind-address", ":8081", "The address the probe endpoint binds to.")
	flag.BoolVar(&enableLeaderElection, "leader-elect", false,
		"Enable leader election for controller manager. "+
			"Enabling this will ensure there is only one active controller manager.")

	// Runtime ConfigMap configuration
	flag.StringVar(&runtimeSource, "runtime-source", getEnvOrDefault("ASYA_RUNTIME_SOURCE", "local"),
		"Runtime source type: 'local' or 'github'")
	flag.StringVar(&runtimeLocalPath, "runtime-local-path", getEnvOrDefault("ASYA_RUNTIME_LOCAL_PATH", "../src/asya-runtime/asya_runtime.py"),
		"Path to local asya_runtime.py file (for local source)")
	flag.StringVar(&runtimeGitHubRepo, "runtime-github-repo", getEnvOrDefault("ASYA_RUNTIME_GITHUB_REPO", ""),
		"GitHub repository (owner/repo) for runtime script (for github source)")
	flag.StringVar(&runtimeVersion, "runtime-version", getEnvOrDefault("ASYA_RUNTIME_VERSION", ""),
		"Version/tag for GitHub releases (for github source)")
	flag.StringVar(&runtimeNamespace, "runtime-namespace", getEnvOrDefault("ASYA_RUNTIME_NAMESPACE", "asya"),
		"Namespace to create runtime ConfigMap in")

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
		LeaderElectionID:       "asya-operator.asya.io",
	})
	if err != nil {
		setupLog.Error(err, "unable to start manager")
		os.Exit(1)
	}

	if err = (&controller.AsyncActorReconciler{
		Client: mgr.GetClient(),
		Scheme: mgr.GetScheme(),
	}).SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "AsyncActor")
		os.Exit(1)
	}

	// Setup runtime ConfigMap reconciler
	setupLog.Info("Setting up runtime ConfigMap", "source", runtimeSource, "namespace", runtimeNamespace)

	// Resolve local path relative to operator binary location if needed
	if runtimeSource == "local" && !filepath.IsAbs(runtimeLocalPath) {
		absPath, err := filepath.Abs(runtimeLocalPath)
		if err != nil {
			setupLog.Error(err, "failed to resolve runtime local path")
			os.Exit(1)
		}
		runtimeLocalPath = absPath
		setupLog.Info("Resolved runtime local path", "path", runtimeLocalPath)
	}

	loader, err := runtimepkg.NewLoader(runtimepkg.LoaderConfig{
		Source:     runtimeSource,
		LocalPath:  runtimeLocalPath,
		GitHubRepo: runtimeGitHubRepo,
		AssetName:  "asya_runtime.py",
		Version:    runtimeVersion,
	})
	if err != nil {
		setupLog.Error(err, "failed to create runtime loader")
		os.Exit(1)
	}

	runtimeReconciler := runtimepkg.NewConfigMapReconciler(
		mgr.GetClient(),
		loader,
		runtimeNamespace,
		runtimeVersion,
	)

	// Reconcile runtime ConfigMap at startup
	ctx := context.Background()
	if err := runtimeReconciler.Reconcile(ctx); err != nil {
		setupLog.Error(err, "failed to reconcile runtime ConfigMap at startup")
		os.Exit(1)
	}
	setupLog.Info("Runtime ConfigMap reconciled successfully")

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
