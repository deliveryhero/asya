package mesh

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// Component tests run against a real mesh-api instance (Docker Compose).
// They are skipped when MESH_API_URL is not set.

func meshURL(t *testing.T) string {
	t.Helper()
	url := os.Getenv("MESH_API_URL")
	if url == "" {
		t.Skip("MESH_API_URL not set")
	}
	return url
}

func meshInternalURL(t *testing.T) string {
	t.Helper()
	url := os.Getenv("MESH_API_INTERNAL_URL")
	if url == "" {
		t.Skip("MESH_API_INTERNAL_URL not set")
	}
	return url
}

func TestComponentCreateAndGet(t *testing.T) {
	base := meshURL(t)

	// POST /api/v1/mesh/?actor=mesh-echo with payload
	resp, err := http.Post(
		base+"/api/v1/mesh/?actor=mesh-echo",
		"application/json",
		strings.NewReader(`{"payload":{"greeting":"hello"}}`),
	)
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusCreated, resp.StatusCode)

	var createResult map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&createResult))
	id, ok := createResult["id"].(string)
	require.True(t, ok)
	require.NotEmpty(t, id)

	// GET /api/v1/mesh/{id}
	resp2, err := http.Get(base + "/api/v1/mesh/" + id)
	require.NoError(t, err)
	defer resp2.Body.Close()
	assert.Equal(t, http.StatusOK, resp2.StatusCode)

	var getResult map[string]any
	require.NoError(t, json.NewDecoder(resp2.Body).Decode(&getResult))
	assert.Equal(t, id, getResult["id"])
	assert.Equal(t, "pending", getResult["status"])
	data, _ := getResult["data"].(map[string]any)
	assert.Equal(t, "mesh-echo", data["actor"])
}

func TestComponentCreateAndReceiveStatusSSE(t *testing.T) {
	base := meshURL(t)
	intBase := meshInternalURL(t)

	// Create message
	resp, err := http.Post(
		base+"/api/v1/mesh/?actor=mesh-echo",
		"application/json",
		strings.NewReader(`{"payload":{"x":1}}`),
	)
	require.NoError(t, err)
	defer resp.Body.Close()

	var result map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	id := result["id"].(string)

	// Start SSE reader in goroutine
	var sseData []string
	done := make(chan struct{})
	go func() {
		defer close(done)
		sseResp, err := http.Get(base + "/api/v1/mesh/" + id + "/events")
		if err != nil {
			return
		}
		defer sseResp.Body.Close()
		scanner := bufio.NewScanner(sseResp.Body)
		for scanner.Scan() {
			line := scanner.Text()
			if strings.HasPrefix(line, "data: ") {
				sseData = append(sseData, line[6:])
			}
		}
	}()

	// Brief pause to let SSE connection establish
	time.Sleep(200 * time.Millisecond)

	// Simulate sidecar: POST running
	runBody := `{"type":"status","status":"running","data":{"actor":"mesh-echo","progress":50}}`
	resp2, err := http.Post(intBase+"/api/v1/mesh/"+id+"/events", "application/json", strings.NewReader(runBody))
	require.NoError(t, err)
	resp2.Body.Close()
	assert.Equal(t, http.StatusNoContent, resp2.StatusCode)

	// Brief pause
	time.Sleep(100 * time.Millisecond)

	// Simulate sidecar: POST terminal
	termBody := `{"type":"status","status":"succeeded","data":{"actor":"x-sink"}}`
	resp3, err := http.Post(intBase+"/api/v1/mesh/"+id+"/events", "application/json", strings.NewReader(termBody))
	require.NoError(t, err)
	resp3.Body.Close()
	assert.Equal(t, http.StatusNoContent, resp3.StatusCode)

	// Wait for SSE to close (terminal event)
	select {
	case <-done:
		// Should have received: catch-up (pending) + running + succeeded
		require.GreaterOrEqual(t, len(sseData), 2, "expected at least 2 SSE data events, got %d", len(sseData))
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for SSE to close")
	}
}

func TestComponentMonotonicStatusOrdering(t *testing.T) {
	base := meshURL(t)
	intBase := meshInternalURL(t)

	// Create message
	resp, err := http.Post(
		base+"/api/v1/mesh/?actor=mesh-echo",
		"application/json",
		strings.NewReader(`{"payload":{}}`),
	)
	require.NoError(t, err)
	defer resp.Body.Close()

	var result map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	id := result["id"].(string)

	// Update to running
	resp2, _ := http.Post(intBase+"/api/v1/mesh/"+id+"/events", "application/json",
		strings.NewReader(`{"type":"status","status":"running","data":{"actor":"echo"}}`))
	resp2.Body.Close()

	// Update to succeeded
	resp3, _ := http.Post(intBase+"/api/v1/mesh/"+id+"/events", "application/json",
		strings.NewReader(`{"type":"status","status":"succeeded","data":{"actor":"x-sink"}}`))
	resp3.Body.Close()

	// Try updating back to running (should be ignored)
	resp4, _ := http.Post(intBase+"/api/v1/mesh/"+id+"/events", "application/json",
		strings.NewReader(`{"type":"status","status":"running","data":{"actor":"echo"}}`))
	resp4.Body.Close()

	// Verify status is still succeeded
	resp5, err := http.Get(base + "/api/v1/mesh/" + id)
	require.NoError(t, err)
	defer resp5.Body.Close()
	var getResult map[string]any
	require.NoError(t, json.NewDecoder(resp5.Body).Decode(&getResult))
	assert.Equal(t, "succeeded", getResult["status"])
}

func TestComponentCancel(t *testing.T) {
	base := meshURL(t)

	// Create
	resp, _ := http.Post(base+"/api/v1/mesh/?actor=mesh-echo", "application/json",
		strings.NewReader(`{"payload":{}}`))
	var result map[string]any
	json.NewDecoder(resp.Body).Decode(&result)
	resp.Body.Close()
	id := result["id"].(string)

	// Cancel
	req, _ := http.NewRequest(http.MethodDelete, base+"/api/v1/mesh/"+id, nil)
	resp2, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	resp2.Body.Close()
	assert.Equal(t, http.StatusNoContent, resp2.StatusCode)

	// Verify canceled
	resp3, err := http.Get(base + "/api/v1/mesh/" + id)
	require.NoError(t, err)
	defer resp3.Body.Close()
	var getResult map[string]any
	json.NewDecoder(resp3.Body).Decode(&getResult)
	assert.Equal(t, "canceled", getResult["status"])
}

func TestComponentList(t *testing.T) {
	base := meshURL(t)

	// Create 3 messages
	for i := 0; i < 3; i++ {
		resp, _ := http.Post(
			base+"/api/v1/mesh/?actor=mesh-echo",
			"application/json",
			strings.NewReader(fmt.Sprintf(`{"payload":{"i":%d}}`, i)),
		)
		resp.Body.Close()
	}

	// List with limit=2
	resp, err := http.Get(base + "/api/v1/mesh/?limit=2")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	var result map[string]any
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	msgs := result["messages"].([]any)
	assert.Len(t, msgs, 2)
	total := result["total"].(float64)
	assert.GreaterOrEqual(t, int(total), 3)
}

func TestComponentFlyEvent(t *testing.T) {
	base := meshURL(t)
	intBase := meshInternalURL(t)

	// Create and set running
	resp, _ := http.Post(base+"/api/v1/mesh/?actor=mesh-echo", "application/json",
		strings.NewReader(`{"payload":{}}`))
	var result map[string]any
	json.NewDecoder(resp.Body).Decode(&result)
	resp.Body.Close()
	id := result["id"].(string)

	// Set to running
	r, _ := http.Post(intBase+"/api/v1/mesh/"+id+"/events", "application/json",
		strings.NewReader(`{"type":"status","status":"running","data":{"actor":"echo"}}`))
	r.Body.Close()

	// POST fly event
	r2, err := http.Post(intBase+"/api/v1/mesh/"+id+"/events", "application/json",
		strings.NewReader(`{"type":"fly","data":{"text":"token chunk"}}`))
	require.NoError(t, err)
	r2.Body.Close()
	assert.Equal(t, http.StatusNoContent, r2.StatusCode)

	// Verify status unchanged (FLY is ephemeral)
	resp2, err := http.Get(base + "/api/v1/mesh/" + id)
	require.NoError(t, err)
	defer resp2.Body.Close()
	var getResult map[string]any
	json.NewDecoder(resp2.Body).Decode(&getResult)
	assert.Equal(t, "running", getResult["status"])
}

func TestComponentGatewayURLInEnvelope(t *testing.T) {
	base := meshURL(t)

	// Create message
	resp, _ := http.Post(base+"/api/v1/mesh/?actor=mesh-echo", "application/json",
		strings.NewReader(`{"payload":{}}`))
	var result map[string]any
	json.NewDecoder(resp.Body).Decode(&result)
	resp.Body.Close()
	id := result["id"].(string)

	// Get message and verify x-asya-gateway-url is in the data headers
	resp2, err := http.Get(base + "/api/v1/mesh/" + id)
	require.NoError(t, err)
	defer resp2.Body.Close()
	var getResult map[string]any
	json.NewDecoder(resp2.Body).Decode(&getResult)

	data, _ := getResult["data"].(map[string]any)
	headers, _ := data["headers"].(map[string]any)
	gwURL, ok := headers["x-asya-gateway-url"].(string)
	require.True(t, ok, "x-asya-gateway-url should be set in message data headers")
	assert.NotEmpty(t, gwURL)
}
