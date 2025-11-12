package runtime

import (
	"context"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"
)

const (
	// ConfigMapName is the name of the runtime ConfigMap
	ConfigMapName = "asya-runtime"
	// RuntimeScriptKey is the key for asya_runtime.py in the ConfigMap
	RuntimeScriptKey = "asya_runtime.py"
)

// ConfigMapReconciler manages the runtime ConfigMap lifecycle.
type ConfigMapReconciler struct {
	Client    client.Client
	Loader    Loader
	Namespace string
	Version   string            // Version for GitHub releases (e.g., "v1.0.0")
	Labels    map[string]string // Labels to apply to the ConfigMap
}

// NewConfigMapReconciler creates a new ConfigMap reconciler.
// If labels is nil, default labels will be applied.
func NewConfigMapReconciler(client client.Client, loader Loader, namespace string, labels map[string]string) *ConfigMapReconciler {
	if labels == nil {
		labels = map[string]string{
			"app.kubernetes.io/name":      "asya-runtime",
			"app.kubernetes.io/component": "runtime",
			"app.kubernetes.io/part-of":   "asya",
		}
	}
	return &ConfigMapReconciler{
		Client:    client,
		Loader:    loader,
		Namespace: namespace,
		Version:   "", // No longer used
		Labels:    labels,
	}
}

// Reconcile ensures the runtime ConfigMap exists with the correct content.
// It creates the ConfigMap if it doesn't exist, or updates it if the content differs.
func (r *ConfigMapReconciler) Reconcile(ctx context.Context) error {
	logger := log.FromContext(ctx)

	logger.Info("Reconciling runtime ConfigMap", "name", ConfigMapName, "namespace", r.Namespace)

	// Load runtime script content (version parameter ignored for embedded file)
	content, err := r.Loader.Load(ctx, "")
	if err != nil {
		return fmt.Errorf("failed to load runtime script: %w", err)
	}

	if content == "" {
		return fmt.Errorf("runtime script content is empty")
	}

	// Check if ConfigMap exists
	existing := &corev1.ConfigMap{}
	err = r.Client.Get(ctx, client.ObjectKey{
		Name:      ConfigMapName,
		Namespace: r.Namespace,
	}, existing)

	if err != nil {
		if !errors.IsNotFound(err) {
			return fmt.Errorf("failed to get ConfigMap: %w", err)
		}

		// ConfigMap doesn't exist, create it
		logger.Info("Creating runtime ConfigMap", "name", ConfigMapName, "namespace", r.Namespace)
		return r.createConfigMap(ctx, content)
	}

	// ConfigMap exists, check if update is needed
	existingContent, ok := existing.Data[RuntimeScriptKey]
	if !ok || existingContent != content {
		logger.Info("Updating runtime ConfigMap", "name", ConfigMapName, "namespace", r.Namespace)
		return r.updateConfigMap(ctx, existing, content)
	}

	logger.Info("Runtime ConfigMap is up to date", "name", ConfigMapName, "namespace", r.Namespace)
	return nil
}

// createConfigMap creates a new runtime ConfigMap.
func (r *ConfigMapReconciler) createConfigMap(ctx context.Context, content string) error {
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      ConfigMapName,
			Namespace: r.Namespace,
			Labels:    r.Labels,
		},
		Data: map[string]string{
			RuntimeScriptKey: content,
		},
	}

	if err := r.Client.Create(ctx, configMap); err != nil {
		return fmt.Errorf("failed to create ConfigMap: %w", err)
	}

	return nil
}

// updateConfigMap updates an existing runtime ConfigMap.
func (r *ConfigMapReconciler) updateConfigMap(ctx context.Context, existing *corev1.ConfigMap, content string) error {
	existing.Data = map[string]string{
		RuntimeScriptKey: content,
	}

	existing.Labels = r.Labels

	if err := r.Client.Update(ctx, existing); err != nil {
		return fmt.Errorf("failed to update ConfigMap: %w", err)
	}

	return nil
}

// Delete removes the runtime ConfigMap.
func (r *ConfigMapReconciler) Delete(ctx context.Context) error {
	logger := log.FromContext(ctx)

	logger.Info("Deleting runtime ConfigMap", "name", ConfigMapName, "namespace", r.Namespace)

	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      ConfigMapName,
			Namespace: r.Namespace,
		},
	}

	if err := r.Client.Delete(ctx, configMap); err != nil {
		if errors.IsNotFound(err) {
			logger.Info("Runtime ConfigMap already deleted", "name", ConfigMapName, "namespace", r.Namespace)
			return nil
		}
		return fmt.Errorf("failed to delete ConfigMap: %w", err)
	}

	return nil
}
