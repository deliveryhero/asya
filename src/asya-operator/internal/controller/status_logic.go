package controller

import (
	"fmt"
	"strings"
	"time"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/log"
)

const (
	statusReady            = "Running"
	statusTransportReady   = "Ready"
	statusWorkloadError    = "WorkloadError"
	statusPendingResources = "PendingResources"
	statusImagePullError   = "ImagePullError"
	statusRuntimeError     = "RuntimeError"
	statusSidecarError     = "SidecarError"
	statusVolumeError      = "VolumeError"
	statusConfigError      = "ConfigError"
)

// updateDisplayFields updates formatted display fields for kubectl output
// Implements the new 17-status design with granular error states
func (r *AsyncActorReconciler) updateDisplayFields(asya *asyav1alpha1.AsyncActor) {
	logger := log.Log.WithValues("asyncactor", asya.Name, "namespace", asya.Namespace)
	logger.Info("Starting updateDisplayFields")

	// Get transport readiness
	transportReady := r.isConditionTrue(asya, "TransportReady")
	asya.Status.TransportStatus = "NotReady"
	if transportReady {
		asya.Status.TransportStatus = statusTransportReady
	}

	// Update pod readiness summary (ready/total format)
	r.updateReadyReplicasSummary(asya)

	// Determine overall status using priority logic
	asya.Status.Status = r.determineStatus(asya)
	logger.Info("Status determined", "status", asya.Status.Status, "transport", asya.Status.TransportStatus)

	// Update replicas fields for DESIRED column
	current := int32(0)
	if asya.Status.Replicas != nil {
		current = *asya.Status.Replicas
	}
	desired := current
	if asya.Status.DesiredReplicas != nil {
		desired = *asya.Status.DesiredReplicas
	}

	// Ensure individual fields are always set for kubectl columns
	asya.Status.Replicas = &current
	asya.Status.DesiredReplicas = &desired
	asya.Status.ReplicasSummary = fmt.Sprintf("%d/%d", current, desired)

	// Update scaling mode
	if asya.Spec.Scaling.Enabled {
		asya.Status.ScalingMode = "KEDA"
	} else {
		asya.Status.ScalingMode = "Manual"
	}

	// Deprecated: Keep for backward compatibility
	totalConditions := 2
	readyConditions := 0
	if transportReady {
		readyConditions++
	}
	if r.isConditionTrue(asya, "WorkloadReady") {
		readyConditions++
	}
	if asya.Spec.Scaling.Enabled {
		totalConditions++
		if r.isConditionTrue(asya, "ScalingReady") {
			readyConditions++
		}
	}
	asya.Status.ReadySummary = fmt.Sprintf("%d/%d", readyConditions, totalConditions)

	// Format last scale time with direction
	if asya.Status.LastScaleTime != nil {
		age := metav1.Now().Sub(asya.Status.LastScaleTime.Time)
		ageStr := ""

		switch {
		case age < time.Minute:
			ageStr = fmt.Sprintf("%ds ago", int(age.Seconds()))
		case age < time.Hour:
			ageStr = fmt.Sprintf("%dm ago", int(age.Minutes()))
		case age < 24*time.Hour:
			ageStr = fmt.Sprintf("%dh ago", int(age.Hours()))
		default:
			ageStr = fmt.Sprintf("%dd ago", int(age.Hours()/24))
		}

		if asya.Status.LastScaleDirection != "" {
			asya.Status.LastScaleFormatted = fmt.Sprintf("%s (%s)", ageStr, asya.Status.LastScaleDirection)
		} else {
			asya.Status.LastScaleFormatted = ageStr
		}
	} else {
		asya.Status.LastScaleFormatted = "-"
	}

	logger.Info("Display fields updated", "status", asya.Status.Status, "readyReplicas", asya.Status.ReadyReplicasSummary)
}

// updateReadyReplicasSummary sets ReadyReplicas, TotalReplicas, and ReadyReplicasSummary
func (r *AsyncActorReconciler) updateReadyReplicasSummary(asya *asyav1alpha1.AsyncActor) {
	ready := int32(0)
	total := int32(0)

	if asya.Status.ReadyReplicas != nil {
		ready = *asya.Status.ReadyReplicas
	}
	if asya.Status.TotalReplicas != nil {
		total = *asya.Status.TotalReplicas
	}

	asya.Status.ReadyReplicas = &ready
	asya.Status.TotalReplicas = &total
	asya.Status.ReadyReplicasSummary = fmt.Sprintf("%d/%d", ready, total)
}

// classifyWorkloadError examines WorkloadReady condition and returns specific error type
func (r *AsyncActorReconciler) classifyWorkloadError(cond *metav1.Condition) string {
	if cond == nil || cond.Type != "WorkloadReady" || cond.Status != metav1.ConditionFalse {
		return statusWorkloadError
	}

	msg := cond.Message
	reason := cond.Reason

	if reason == "PodsNotHealthy" && msg != "" {
		if strings.Contains(msg, "Insufficient") {
			return statusPendingResources
		}

		if strings.Contains(msg, podReasonImagePullBackOff) || strings.Contains(msg, podReasonErrImagePull) {
			return statusImagePullError
		}

		if strings.Contains(msg, runtimeContainerName) && strings.Contains(msg, podReasonCrashLoopBackOff) {
			return statusRuntimeError
		}

		if strings.Contains(msg, sidecarName) && strings.Contains(msg, podReasonCrashLoopBackOff) {
			return statusSidecarError
		}

		if strings.Contains(msg, "MountVolume") || strings.Contains(msg, "VolumeMount") {
			return statusVolumeError
		}

		if (strings.Contains(msg, "configmap") || strings.Contains(msg, "secret")) && strings.Contains(msg, "not found") {
			return statusConfigError
		}
	}

	return statusWorkloadError
}

// determineStatus determines the overall AsyncActor status using priority logic
func (r *AsyncActorReconciler) determineStatus(asya *asyav1alpha1.AsyncActor) string {
	// 1. Lifecycle states
	if asya.DeletionTimestamp != nil {
		return "Terminating"
	}

	if asya.Status.ObservedGeneration == 0 {
		return "Creating"
	}

	// 2. Critical errors (highest priority)
	transportReady := r.isConditionTrue(asya, "TransportReady")
	workloadReady := r.isConditionTrue(asya, "WorkloadReady")
	scalingReady := r.isConditionTrue(asya, "ScalingReady")

	if !transportReady {
		return "TransportError"
	}

	if !workloadReady {
		for _, cond := range asya.Status.Conditions {
			if cond.Type == "WorkloadReady" && cond.Status == metav1.ConditionFalse {
				return r.classifyWorkloadError(&cond)
			}
		}
		return statusWorkloadError
	}

	if asya.Spec.Scaling.Enabled && !scalingReady {
		return "ScalingError"
	}

	// 3. Get replica counts
	ready := int32(0)
	total := int32(0)
	desired := int32(0)
	failing := int32(0)

	if asya.Status.ReadyReplicas != nil {
		ready = *asya.Status.ReadyReplicas
	}
	if asya.Status.TotalReplicas != nil {
		total = *asya.Status.TotalReplicas
	}
	if asya.Status.DesiredReplicas != nil {
		desired = *asya.Status.DesiredReplicas
	}
	if asya.Status.FailingPods != nil {
		failing = *asya.Status.FailingPods
	}

	// 4. Check for failing pods before transitional states
	// Failing pods indicate persistent issues only if we don't have enough running pods
	// If ready >= desired, we have sufficient capacity even with some failing pods
	if failing > 0 && ready < desired {
		return statusWorkloadError
	}

	// 5. Transitional states (scaling/updating)
	// TODO: Detect Updating state (check deployment revision change)

	// Check Napping state first when desired=0 to avoid showing ScalingDown during scale-to-zero
	if desired == 0 && asya.Spec.Scaling.Enabled {
		return "Napping"
	}

	if total < desired && desired > 0 {
		return "ScalingUp"
	}

	if total > desired {
		return "ScalingDown"
	}

	// 6. Operational states

	// Degraded: some pods not ready for extended period
	if ready < total && total > 0 {
		// Check if we've been in this state for >5min
		if asya.Status.LastScaleTime != nil {
			timeSinceLastScale := metav1.Now().Sub(asya.Status.LastScaleTime.Time)
			if timeSinceLastScale > 5*time.Minute {
				return "Degraded"
			}
		}
		// Still scaling up, give it time
		return "ScalingUp"
	}

	if ready == desired && ready > 0 {
		return statusReady
	}

	if ready == 0 && desired == 0 && !asya.Spec.Scaling.Enabled {
		return statusReady
	}

	return "Unknown"
}

// isConditionTrue checks if a condition exists and is True
func (r *AsyncActorReconciler) isConditionTrue(asya *asyav1alpha1.AsyncActor, condType string) bool {
	for _, cond := range asya.Status.Conditions {
		if cond.Type == condType {
			return cond.Status == metav1.ConditionTrue
		}
	}
	return false
}
