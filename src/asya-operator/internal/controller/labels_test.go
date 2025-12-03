package controller

import (
	"strings"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
)

func TestPropagateLabels(t *testing.T) {
	tests := []struct {
		name           string
		asyaLabels     map[string]string
		operatorLabels map[string]string
		expected       map[string]string
	}{
		{
			name: "merge user and operator labels",
			asyaLabels: map[string]string{
				"app":  "my-app",
				"team": "ml-platform",
			},
			operatorLabels: map[string]string{
				"app.kubernetes.io/name":      "test-actor",
				"app.kubernetes.io/component": "actor",
			},
			expected: map[string]string{
				"app":                         "my-app",
				"team":                        "ml-platform",
				"app.kubernetes.io/name":      "test-actor",
				"app.kubernetes.io/component": "actor",
			},
		},
		{
			name:       "operator labels only",
			asyaLabels: map[string]string{},
			operatorLabels: map[string]string{
				"app.kubernetes.io/name": "test-actor",
			},
			expected: map[string]string{
				"app.kubernetes.io/name": "test-actor",
			},
		},
		{
			name: "user labels only",
			asyaLabels: map[string]string{
				"custom": "value",
			},
			operatorLabels: map[string]string{},
			expected: map[string]string{
				"custom": "value",
			},
		},
		{
			name:           "empty labels",
			asyaLabels:     map[string]string{},
			operatorLabels: map[string]string{},
			expected:       map[string]string{},
		},
		{
			name:       "nil asya labels",
			asyaLabels: nil,
			operatorLabels: map[string]string{
				"app.kubernetes.io/name": "test",
			},
			expected: map[string]string{
				"app.kubernetes.io/name": "test",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			asya := &asyav1alpha1.AsyncActor{
				ObjectMeta: metav1.ObjectMeta{
					Name:   "test-actor",
					Labels: tt.asyaLabels,
				},
			}

			result := propagateLabels(asya, tt.operatorLabels)

			if len(result) != len(tt.expected) {
				t.Errorf("Expected %d labels, got %d", len(tt.expected), len(result))
			}

			for k, v := range tt.expected {
				if result[k] != v {
					t.Errorf("Expected label %s=%s, got %s", k, v, result[k])
				}
			}

			for k := range result {
				if _, ok := tt.expected[k]; !ok {
					t.Errorf("Unexpected label %s in result", k)
				}
			}
		})
	}
}

func TestValidateUserLabels(t *testing.T) {
	tests := []struct {
		name        string
		labels      map[string]string
		expectError bool
		errorMsg    string
	}{
		{
			name: "valid user labels",
			labels: map[string]string{
				"app":     "my-app",
				"team":    "ml-platform",
				"env":     "production",
				"version": "v1.0.0",
			},
			expectError: false,
		},
		{
			name: "reserved prefix app.kubernetes.io",
			labels: map[string]string{
				"app.kubernetes.io/name": "test",
			},
			expectError: true,
			errorMsg:    "app.kubernetes.io/",
		},
		{
			name: "reserved prefix asya.sh",
			labels: map[string]string{
				"asya.sh/custom": "value",
			},
			expectError: true,
			errorMsg:    "asya.sh/",
		},
		{
			name: "reserved prefix keda.sh",
			labels: map[string]string{
				"keda.sh/custom": "value",
			},
			expectError: true,
			errorMsg:    "keda.sh/",
		},
		{
			name: "reserved prefix kubernetes.io",
			labels: map[string]string{
				"kubernetes.io/custom": "value",
			},
			expectError: true,
			errorMsg:    "kubernetes.io/",
		},
		{
			name: "mixed valid and invalid",
			labels: map[string]string{
				"app":                    "valid",
				"app.kubernetes.io/name": "invalid",
			},
			expectError: true,
			errorMsg:    "app.kubernetes.io/",
		},
		{
			name:        "empty labels",
			labels:      map[string]string{},
			expectError: false,
		},
		{
			name:        "nil labels",
			labels:      nil,
			expectError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateUserLabels(tt.labels)

			if tt.expectError {
				if err == nil {
					t.Errorf("Expected error containing %q, got nil", tt.errorMsg)
				} else if tt.errorMsg != "" && !strings.Contains(err.Error(), tt.errorMsg) {
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
