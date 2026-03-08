package main

import (
	"net/http"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestBuildRoutes_MissingMode(t *testing.T) {
	mux := http.NewServeMux()
	err := buildRoutes(mux, "", nil, nil, nil, nil, nil, nil)
	require.Error(t, err)
	require.Contains(t, err.Error(), "ASYA_GATEWAY_MODE")
}

func TestBuildRoutes_UnknownMode(t *testing.T) {
	mux := http.NewServeMux()
	err := buildRoutes(mux, "production", nil, nil, nil, nil, nil, nil)
	require.Error(t, err)
}

func TestBuildRoutes_APIMode(t *testing.T) {
	mux := http.NewServeMux()
	err := buildRoutes(mux, "api", nil, nil, nil, nil, nil, nil)
	require.NoError(t, err)
}

func TestBuildRoutes_MeshMode(t *testing.T) {
	mux := http.NewServeMux()
	err := buildRoutes(mux, "mesh", nil, nil, nil, nil, nil, nil)
	require.NoError(t, err)
}

func TestBuildRoutes_TestingMode(t *testing.T) {
	mux := http.NewServeMux()
	err := buildRoutes(mux, "testing", nil, nil, nil, nil, nil, nil)
	require.NoError(t, err)
}

func TestGetEnvDuration_Default(t *testing.T) {
	t.Setenv("TEST_DURATION_KEY", "")
	result := getEnvDuration("TEST_DURATION_KEY", 10*time.Second)
	require.Equal(t, 10*time.Second, result)
}

func TestGetEnvDuration_ValidValue(t *testing.T) {
	t.Setenv("TEST_DURATION_KEY", "30s")
	result := getEnvDuration("TEST_DURATION_KEY", 10*time.Second)
	require.Equal(t, 30*time.Second, result)
}

func TestGetEnvDuration_InvalidValue(t *testing.T) {
	t.Setenv("TEST_DURATION_KEY", "not-a-duration")
	result := getEnvDuration("TEST_DURATION_KEY", 10*time.Second)
	require.Equal(t, 10*time.Second, result)
}
