package controller

import (
	"fmt"
	"testing"
	"time"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

const (
	statusScalingUp = "ScalingUp"
)

// TestDetermineStatus tests all 17 status scenarios
func TestDetermineStatus(t *testing.T) {
	r := &AsyncActorReconciler{}

	tests := []struct {
		name              string
		asya              *asyav1alpha1.AsyncActor
		expectedStatus    string
		expectedTransport string
	}{
		// Lifecycle States
		{
			name: "Creating - ObservedGeneration is 0",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 0,
				},
			},
			expectedStatus: "Creating",
		},
		{
			name: "Terminating - DeletionTimestamp set",
			asya: &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					DeletionTimestamp: &metav1.Time{Time: time.Now()},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
				},
			},
			expectedStatus: "Terminating",
		},

		// Error States
		{
			name: "TransportError - TransportReady is False",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionFalse},
					},
				},
			},
			expectedStatus:    "TransportError",
			expectedTransport: "NotReady",
		},
		{
			name: "WorkloadError - WorkloadReady is False",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionFalse},
					},
				},
			},
			expectedStatus:    "WorkloadError",
			expectedTransport: "Ready",
		},
		{
			name: "ScalingError - ScalingReady is False when KEDA enabled",
			asya: &asyav1alpha1.AsyncActor{
				Spec: asyav1alpha1.AsyncActorSpec{
					Scaling: asyav1alpha1.ScalingConfig{
						Enabled: true,
					},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
						{Type: "ScalingReady", Status: metav1.ConditionFalse},
					},
				},
			},
			expectedStatus:    "ScalingError",
			expectedTransport: "Ready",
		},
		{
			name: "PendingResources - Insufficient GPU/CPU/memory",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{
							Type:    "WorkloadReady",
							Status:  metav1.ConditionFalse,
							Reason:  "PodsNotHealthy",
							Message: "Pod grounding-dino-0 in Pending: 0/7 nodes available: 2 Insufficient cpu, 2 Insufficient memory, 2 Insufficient nvidia.com/gpu",
						},
					},
				},
			},
			expectedStatus:    "PendingResources",
			expectedTransport: "Ready",
		},
		{
			name: "ImagePullError - ImagePullBackOff",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{
							Type:    "WorkloadReady",
							Status:  metav1.ConditionFalse,
							Reason:  "PodsNotHealthy",
							Message: "Container asya-runtime in ImagePullBackOff (pod: test-actor-abc123)",
						},
					},
				},
			},
			expectedStatus:    "ImagePullError",
			expectedTransport: "Ready",
		},
		{
			name: "ImagePullError - ErrImagePull",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{
							Type:    "WorkloadReady",
							Status:  metav1.ConditionFalse,
							Reason:  "PodsNotHealthy",
							Message: "Container asya-sidecar in ErrImagePull (pod: test-actor-xyz789)",
						},
					},
				},
			},
			expectedStatus:    "ImagePullError",
			expectedTransport: "Ready",
		},
		{
			name: "RuntimeError - Runtime container CrashLoopBackOff",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{
							Type:    "WorkloadReady",
							Status:  metav1.ConditionFalse,
							Reason:  "PodsNotHealthy",
							Message: "Container asya-runtime in CrashLoopBackOff (pod: test-actor-def456)",
						},
					},
				},
			},
			expectedStatus:    "RuntimeError",
			expectedTransport: "Ready",
		},
		{
			name: "SidecarError - Sidecar container CrashLoopBackOff",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{
							Type:    "WorkloadReady",
							Status:  metav1.ConditionFalse,
							Reason:  "PodsNotHealthy",
							Message: "Container asya-sidecar in CrashLoopBackOff (pod: test-actor-ghi789)",
						},
					},
				},
			},
			expectedStatus:    "SidecarError",
			expectedTransport: "Ready",
		},
		{
			name: "VolumeError - MountVolume failed",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{
							Type:    "WorkloadReady",
							Status:  metav1.ConditionFalse,
							Reason:  "PodsNotHealthy",
							Message: "MountVolume.SetUp failed for volume \"data-volume\" : persistentvolumeclaim \"data-pvc\" not found",
						},
					},
				},
			},
			expectedStatus:    "VolumeError",
			expectedTransport: "Ready",
		},
		{
			name: "ConfigError - ConfigMap not found",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{
							Type:    "WorkloadReady",
							Status:  metav1.ConditionFalse,
							Reason:  "PodsNotHealthy",
							Message: "configmap \"app-config\" not found",
						},
					},
				},
			},
			expectedStatus:    "ConfigError",
			expectedTransport: "Ready",
		},
		{
			name: "ConfigError - Secret not found",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{
							Type:    "WorkloadReady",
							Status:  metav1.ConditionFalse,
							Reason:  "PodsNotHealthy",
							Message: "secret \"db-credentials\" not found",
						},
					},
				},
			},
			expectedStatus:    "ConfigError",
			expectedTransport: "Ready",
		},

		// Transitional States
		{
			name: statusScalingUp + " - total < desired",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(3)),
					TotalReplicas:   ptr(int32(3)),
					DesiredReplicas: ptr(int32(10)),
				},
			},
			expectedStatus:    statusScalingUp,
			expectedTransport: "Ready",
		},
		{
			name: "ScalingDown - total > desired",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(3)),
					TotalReplicas:   ptr(int32(8)),
					DesiredReplicas: ptr(int32(3)),
				},
			},
			expectedStatus:    "ScalingDown",
			expectedTransport: "Ready",
		},

		// Operational States
		{
			name: "Ready - all conditions true, replicas match desired",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(5)),
					TotalReplicas:   ptr(int32(5)),
					DesiredReplicas: ptr(int32(5)),
				},
			},
			expectedStatus:    "Running",
			expectedTransport: "Ready",
		},
		{
			name: "Napping - scaled to zero with KEDA enabled",
			asya: &asyav1alpha1.AsyncActor{
				Spec: asyav1alpha1.AsyncActorSpec{
					Scaling: asyav1alpha1.ScalingConfig{
						Enabled: true,
					},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
						{Type: "ScalingReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(0)),
					TotalReplicas:   ptr(int32(0)),
					DesiredReplicas: ptr(int32(0)),
				},
			},
			expectedStatus:    "Napping",
			expectedTransport: "Ready",
		},
		{
			name: "Napping - desired=0 with pending terminating pods",
			asya: &asyav1alpha1.AsyncActor{
				Spec: asyav1alpha1.AsyncActorSpec{
					Scaling: asyav1alpha1.ScalingConfig{
						Enabled: true,
					},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
						{Type: "ScalingReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(0)),
					TotalReplicas:   ptr(int32(0)),
					DesiredReplicas: ptr(int32(0)),
					PendingReplicas: ptr(int32(1)),
				},
			},
			expectedStatus:    "Napping",
			expectedTransport: "Ready",
		},
		{
			name: "Degraded - some pods not ready for >5min",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(3)),
					TotalReplicas:   ptr(int32(5)),
					DesiredReplicas: ptr(int32(5)),
					LastScaleTime:   &metav1.Time{Time: time.Now().Add(-10 * time.Minute)},
				},
			},
			expectedStatus:    "Degraded",
			expectedTransport: "Ready",
		},
		{
			name: statusScalingUp + " (not Degraded) - some pods not ready for <5min",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(3)),
					TotalReplicas:   ptr(int32(5)),
					DesiredReplicas: ptr(int32(5)),
					LastScaleTime:   &metav1.Time{Time: time.Now().Add(-2 * time.Minute)},
				},
			},
			expectedStatus:    statusScalingUp,
			expectedTransport: "Ready",
		},

		// Edge Cases
		{
			name: "Ready - manual scaling with zero replicas",
			asya: &asyav1alpha1.AsyncActor{
				Spec: asyav1alpha1.AsyncActorSpec{
					Scaling: asyav1alpha1.ScalingConfig{
						Enabled: false,
					},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(0)),
					TotalReplicas:   ptr(int32(0)),
					DesiredReplicas: ptr(int32(0)),
				},
			},
			expectedStatus:    "Running",
			expectedTransport: "Ready",
		},

		// Failing Pods (takes precedence over scaling states)
		{
			name: "WorkloadError - failing pods with total > desired (not ScalingDown)",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(0)),
					TotalReplicas:   ptr(int32(2)),
					DesiredReplicas: ptr(int32(1)),
					FailingPods:     ptr(int32(1)),
				},
			},
			expectedStatus:    "WorkloadError",
			expectedTransport: "Ready",
		},
		{
			name: "WorkloadError - all pods failing during scale up",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(0)),
					TotalReplicas:   ptr(int32(2)),
					DesiredReplicas: ptr(int32(5)),
					FailingPods:     ptr(int32(2)),
				},
			},
			expectedStatus:    "WorkloadError",
			expectedTransport: "Ready",
		},
		{
			name: statusScalingUp + " - no failing pods, normal scale up",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(2)),
					TotalReplicas:   ptr(int32(2)),
					DesiredReplicas: ptr(int32(5)),
					FailingPods:     ptr(int32(0)),
				},
			},
			expectedStatus:    statusScalingUp,
			expectedTransport: "Ready",
		},
		{
			name: "WorkloadError - failing pods when ready < desired",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(3)),
					TotalReplicas:   ptr(int32(5)),
					DesiredReplicas: ptr(int32(5)),
					FailingPods:     ptr(int32(2)),
					LastScaleTime:   &metav1.Time{Time: time.Now().Add(-10 * time.Minute)},
				},
			},
			expectedStatus:    "WorkloadError",
			expectedTransport: "Ready",
		},
		{
			name: "ScalingDown - failing pods with ready == desired (not WorkloadError)",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(5)),
					TotalReplicas:   ptr(int32(7)),
					DesiredReplicas: ptr(int32(5)),
					FailingPods:     ptr(int32(2)),
				},
			},
			expectedStatus:    "ScalingDown",
			expectedTransport: "Ready",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Run updateDisplayFields which calls determineStatus
			r.updateDisplayFields(tt.asya)

			if tt.asya.Status.Status != tt.expectedStatus {
				t.Errorf("Status = %q, want %q", tt.asya.Status.Status, tt.expectedStatus)
			}

			if tt.expectedTransport != "" && tt.asya.Status.TransportStatus != tt.expectedTransport {
				t.Errorf("TransportStatus = %q, want %q", tt.asya.Status.TransportStatus, tt.expectedTransport)
			}
		})
	}
}

// TestReadyReplicasSummary tests the READY column formatting
func TestReadyReplicasSummary(t *testing.T) {
	r := &AsyncActorReconciler{}

	tests := []struct {
		name          string
		readyReplicas *int32
		totalReplicas *int32
		expected      string
	}{
		{
			name:          "All ready",
			readyReplicas: ptr(int32(5)),
			totalReplicas: ptr(int32(5)),
			expected:      "5/5",
		},
		{
			name:          "Some ready",
			readyReplicas: ptr(int32(3)),
			totalReplicas: ptr(int32(10)),
			expected:      "3/10",
		},
		{
			name:          "None ready",
			readyReplicas: ptr(int32(0)),
			totalReplicas: ptr(int32(5)),
			expected:      "0/5",
		},
		{
			name:          "Zero replicas",
			readyReplicas: ptr(int32(0)),
			totalReplicas: ptr(int32(0)),
			expected:      "0/0",
		},
		{
			name:          "Nil values default to 0",
			readyReplicas: nil,
			totalReplicas: nil,
			expected:      "0/0",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			asya := &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ReadyReplicas:      tt.readyReplicas,
					TotalReplicas:      tt.totalReplicas,
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
				},
			}

			r.updateDisplayFields(asya)

			if asya.Status.ReadyReplicasSummary != tt.expected {
				t.Errorf("ReadyReplicasSummary = %q, want %q", asya.Status.ReadyReplicasSummary, tt.expected)
			}
		})
	}
}

// TestScalingModeDisplay tests the SCALING column values
func TestScalingModeDisplay(t *testing.T) {
	r := &AsyncActorReconciler{}

	tests := []struct {
		name           string
		scalingEnabled bool
		expected       string
	}{
		{
			name:           "KEDA enabled",
			scalingEnabled: true,
			expected:       "KEDA",
		},
		{
			name:           "Manual scaling",
			scalingEnabled: false,
			expected:       "Manual",
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
					ObservedGeneration: 1,
				},
			}

			r.updateDisplayFields(asya)

			if asya.Status.ScalingMode != tt.expected {
				t.Errorf("ScalingMode = %q, want %q", asya.Status.ScalingMode, tt.expected)
			}
		})
	}
}

// TestStatusConsistency verifies status values are consistent with replica counts and other fields
func TestStatusConsistency(t *testing.T) {
	r := &AsyncActorReconciler{}

	tests := []struct {
		name             string
		asya             *asyav1alpha1.AsyncActor
		expectError      bool
		errorDescription string
	}{
		{
			name: "Ready status must have replicas > 0 or be 0/0",
			asya: &asyav1alpha1.AsyncActor{
				Spec: asyav1alpha1.AsyncActorSpec{
					Scaling: asyav1alpha1.ScalingConfig{Enabled: false},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(3)),
					TotalReplicas:   ptr(int32(3)),
					DesiredReplicas: ptr(int32(3)),
				},
			},
			expectError: false,
		},
		{
			name: "Napping status only with KEDA enabled and 0 replicas",
			asya: &asyav1alpha1.AsyncActor{
				Spec: asyav1alpha1.AsyncActorSpec{
					Scaling: asyav1alpha1.ScalingConfig{Enabled: true},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
						{Type: "ScalingReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(0)),
					TotalReplicas:   ptr(int32(0)),
					DesiredReplicas: ptr(int32(0)),
				},
			},
			expectError:      false,
			errorDescription: "KEDA enabled with 0/0 replicas should be Napping",
		},
		{
			name: "TransportError must have TransportReady=False",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionFalse},
					},
					ReadyReplicas:   ptr(int32(0)),
					TotalReplicas:   ptr(int32(0)),
					DesiredReplicas: ptr(int32(0)),
				},
			},
			expectError:      false,
			errorDescription: "TransportReady=False should result in TransportError status",
		},
		{
			name: statusScalingUp + " must have total < desired",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(3)),
					TotalReplicas:   ptr(int32(3)),
					DesiredReplicas: ptr(int32(10)),
				},
			},
			expectError:      false,
			errorDescription: "total < desired should result in " + statusScalingUp + " status",
		},
		{
			name: "ScalingDown must have total > desired",
			asya: &asyav1alpha1.AsyncActor{
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(3)),
					TotalReplicas:   ptr(int32(8)),
					DesiredReplicas: ptr(int32(3)),
				},
			},
			expectError:      false,
			errorDescription: "total > desired should result in ScalingDown status",
		},
		{
			name: "Manual scaling with 0/0 should be Ready (not Napping)",
			asya: &asyav1alpha1.AsyncActor{
				Spec: asyav1alpha1.AsyncActorSpec{
					Scaling: asyav1alpha1.ScalingConfig{Enabled: false},
				},
				Status: asyav1alpha1.AsyncActorStatus{
					ObservedGeneration: 1,
					Conditions: []metav1.Condition{
						{Type: "TransportReady", Status: metav1.ConditionTrue},
						{Type: "WorkloadReady", Status: metav1.ConditionTrue},
					},
					ReadyReplicas:   ptr(int32(0)),
					TotalReplicas:   ptr(int32(0)),
					DesiredReplicas: ptr(int32(0)),
				},
			},
			expectError:      false,
			errorDescription: "Manual scaling with 0/0 should be Running, not Napping",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r.updateDisplayFields(tt.asya)

			status := tt.asya.Status.Status
			ready := tt.asya.Status.ReadyReplicas
			total := tt.asya.Status.TotalReplicas
			desired := tt.asya.Status.DesiredReplicas
			transportStatus := tt.asya.Status.TransportStatus
			scalingMode := tt.asya.Status.ScalingMode

			// Verify consistency rules
			switch status {
			case "Running":
				if tt.asya.Spec.Scaling.Enabled && desired != nil && *desired == 0 {
					t.Errorf("Status is Running but KEDA enabled with desired=0 (should be Napping)")
				}

			case "Napping":
				if !tt.asya.Spec.Scaling.Enabled {
					t.Errorf("Status is Napping but KEDA not enabled")
				}
				if desired == nil || *desired != 0 {
					t.Errorf("Status is Napping but desired != 0")
				}

			case "TransportError":
				if transportStatus != "NotReady" {
					t.Errorf("Status is TransportError but TransportStatus=%q (should be NotReady)", transportStatus)
				}

			case statusScalingUp:
				if total != nil && desired != nil && *total >= *desired {
					t.Errorf("Status is %s but total(%d) >= desired(%d)", statusScalingUp, *total, *desired)
				}

			case "ScalingDown":
				if total != nil && desired != nil && *total <= *desired {
					t.Errorf("Status is ScalingDown but total(%d) <= desired(%d)", *total, *desired)
				}
			}

			// Verify ReadyReplicasSummary format
			if tt.asya.Status.ReadyReplicasSummary != "" {
				readyVal := int32(0)
				totalVal := int32(0)
				if ready != nil {
					readyVal = *ready
				}
				if total != nil {
					totalVal = *total
				}
				expectedSummary := fmt.Sprintf("%d/%d", readyVal, totalVal)
				if tt.asya.Status.ReadyReplicasSummary != expectedSummary {
					t.Errorf("ReadyReplicasSummary = %q, want %q", tt.asya.Status.ReadyReplicasSummary, expectedSummary)
				}
			}

			// Verify ScalingMode matches spec
			if tt.asya.Spec.Scaling.Enabled {
				if scalingMode != "KEDA" {
					t.Errorf("KEDA enabled but ScalingMode = %q (should be KEDA)", scalingMode)
				}
			} else {
				if scalingMode != "Manual" {
					t.Errorf("KEDA disabled but ScalingMode = %q (should be Manual)", scalingMode)
				}
			}
		})
	}
}
