package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
	sidecartesting "github.com/deliveryhero/asya/asya-sidecar/pkg/testing"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/testutil"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/transport"
)

func integrationTempDir(t *testing.T) string {
	t.Helper()
	dir, cleanup, err := testutil.TempDir()
	if err != nil {
		t.Fatalf("failed to create temp dir: %v", err)
	}
	t.Cleanup(cleanup)
	return dir
}

// RuntimeProcess manages a Python runtime subprocess for testing
type RuntimeProcess struct {
	cmd        *exec.Cmd
	socketPath string
	handler    string
}

// StartRuntime starts a Python runtime subprocess with the specified handler
func StartRuntime(t *testing.T, handler string, socketPath string, envVars map[string]string) *RuntimeProcess {
	t.Helper()

	// Get path to asya-runtime asya_runtime.py
	projectRoot := getProjectRoot(t)
	runtimeScript := filepath.Join(projectRoot, "src", "asya-runtime", "asya_runtime.py")
	handlersFile := filepath.Join(projectRoot, "src", "asya-testing", "asya_testing", "handlers", "payload.py")
	testingDir := filepath.Join(projectRoot, "src", "asya-testing")

	// Verify files exist
	if _, err := os.Stat(runtimeScript); err != nil {
		t.Fatalf("Runtime script not found: %s", runtimeScript)
	}
	if _, err := os.Stat(handlersFile); err != nil {
		t.Fatalf("Handlers file not found: %s", handlersFile)
	}

	// Create command
	cmd := exec.Command("python3", runtimeScript) //nolint:gosec

	// Set environment variables
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, fmt.Sprintf("ASYA_HANDLER=asya_testing.handlers.payload.%s", handler))
	cmd.Env = append(cmd.Env, fmt.Sprintf("ASYA_SOCKET_DIR=%s", filepath.Dir(socketPath)))
	cmd.Env = append(cmd.Env, fmt.Sprintf("PYTHONPATH=%s", testingDir))

	// Add custom environment variables
	for k, v := range envVars {
		cmd.Env = append(cmd.Env, fmt.Sprintf("%s=%s", k, v))
	}

	// Capture output for debugging
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	// Start the process
	if err := cmd.Start(); err != nil {
		t.Fatalf("Failed to start runtime: %v", err)
	}

	rp := &RuntimeProcess{
		cmd:        cmd,
		socketPath: socketPath,
		handler:    handler,
	}

	// Wait for socket to be created
	if !waitForSocket(socketPath, 5*time.Second) {
		rp.Stop()
		t.Fatalf("Socket %s not created within timeout", socketPath)
	}

	t.Logf("Started runtime: handler=%s, socket=%s, pid=%d", handler, socketPath, cmd.Process.Pid)
	return rp
}

// Stop stops the runtime process
func (rp *RuntimeProcess) Stop() {
	if rp.cmd != nil && rp.cmd.Process != nil {
		_ = rp.cmd.Process.Kill()
		_ = rp.cmd.Wait()
	}
	_ = os.Remove(rp.socketPath)
}

// waitForSocket waits for a Unix socket to be created
func waitForSocket(socketPath string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(socketPath); err == nil {
			return true
		}
		time.Sleep(100 * time.Millisecond) // Poll interval: check socket existence every 100ms
	}
	return false
}

// getProjectRoot returns the project root directory
func getProjectRoot(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("Failed to get working directory: %v", err)
	}

	// Navigate up to find project root (contains src/ and tests/)
	dir := wd
	for {
		if _, err := os.Stat(filepath.Join(dir, "src", "asya-runtime")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatalf("Could not find project root from %s", wd)
		}
		dir = parent
	}
}

// createTestRouter creates a router for testing with mock transport
func createTestRouter(t *testing.T, socketPath string, timeout time.Duration) (sidecartesting.EnvelopeProcessor, *sidecartesting.MockTransport) {
	t.Helper()

	mockTransport := sidecartesting.NewMockTransport()
	r := sidecartesting.NewTestRouter(socketPath, timeout, mockTransport)
	return r, mockTransport
}

// createTestMessage creates a test message with the given payload
func createTestMessage(payload map[string]interface{}) transport.QueueMessage {
	route := envelopes.Route{
		Actors:  []string{"test-actor"},
		Current: 0,
	}

	payloadBytes, _ := json.Marshal(payload)

	msg := envelopes.Envelope{
		ID:      "test-envelope-1",
		Route:   route,
		Payload: json.RawMessage(payloadBytes),
	}

	msgBody, _ := json.Marshal(msg)

	return transport.QueueMessage{
		ID:   "test-msg-1",
		Body: msgBody,
	}
}

// Test Scenarios

func TestSocketIntegration_HappyPath(t *testing.T) {
	tempDir := integrationTempDir(t)
	socketPath := tempDir + "/asya-runtime.sock"
	defer func() { _ = os.Remove(socketPath) }()

	// Start runtime with echo_handler
	runtimeProc := StartRuntime(t, "echo_handler", socketPath, nil)
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 5*time.Second)

	// Create and process test message
	testMsg := createTestMessage(map[string]interface{}{
		"test":   "happy_path",
		"data":   "integration test",
		"status": "processed",
	})

	ctx := context.Background()
	err := r.ProcessEnvelope(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to happy-end queue
	sentMessages := mockTransport.GetMessages("happy-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in happy-end, got %d", len(sentMessages))
	}

	// Verify payload contains expected fields
	var sentMsg envelopes.Envelope
	if err := json.Unmarshal(sentMessages[0].Body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(sentMsg.Payload, &payload); err != nil {
		t.Fatalf("Failed to unmarshal payload: %v", err)
	}

	if status, ok := payload["status"].(string); !ok || status != "processed" {
		t.Errorf("Expected status=processed, got %v", payload["status"])
	}
}

func TestSocketIntegration_Error(t *testing.T) {
	tempDir := integrationTempDir(t)
	socketPath := tempDir + "/asya-runtime.sock"
	defer func() { _ = os.Remove(socketPath) }()

	// Start runtime with error_handler
	runtimeProc := StartRuntime(t, "error_handler", socketPath, nil)
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 5*time.Second)

	// Create and process test message
	testMsg := createTestMessage(map[string]interface{}{
		"test": "error_handling",
	})

	ctx := context.Background()
	err := r.ProcessEnvelope(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to error-end queue
	sentMessages := mockTransport.GetMessages("error-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in error-end, got %d", len(sentMessages))
	}

	// Verify error message contains error details
	var errorMsg map[string]interface{}
	if err := json.Unmarshal(sentMessages[0].Body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal error message: %v", err)
	}

	// Error is in payload.error, not top-level error
	payload, ok := errorMsg["payload"].(map[string]interface{})
	if !ok {
		t.Fatalf("Expected payload field in error message, got %v", errorMsg)
	}

	if errorStr, ok := payload["error"].(string); !ok || !strings.Contains(strings.ToLower(errorStr), "error") {
		t.Errorf("Expected error field in payload, got %v", payload)
	}
}

func TestSocketIntegration_Timeout(t *testing.T) {
	t.Skip("Timeout test causes pod crash - tested in e2e tests instead")
	tempDir := t.TempDir()
	socketPath := tempDir + "/asya-runtime.sock"
	defer func() { _ = os.Remove(socketPath) }()

	// Start runtime with timeout_handler
	runtimeProc := StartRuntime(t, "timeout_handler", socketPath, nil)
	defer runtimeProc.Stop()

	// Create router with SHORT timeout (1 second)
	r, mockTransport := createTestRouter(t, socketPath, 1*time.Second)

	// Create message that will sleep for 60 seconds
	testMsg := createTestMessage(map[string]interface{}{
		"test":  "timeout",
		"sleep": 60,
	})

	ctx := context.Background()
	err := r.ProcessEnvelope(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to error-end queue due to timeout
	sentMessages := mockTransport.GetMessages("error-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in error-end, got %d", len(sentMessages))
	}

	// Verify error message mentions timeout
	var errorMsg map[string]interface{}
	if err := json.Unmarshal(sentMessages[0].Body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal error message: %v", err)
	}

	// Error is in payload.error
	payload, ok := errorMsg["payload"].(map[string]interface{})
	if !ok {
		t.Fatalf("Expected payload field in error message, got %v", errorMsg)
	}

	errorStr := strings.ToLower(fmt.Sprintf("%v", payload))
	if !strings.Contains(errorStr, "timeout") && !strings.Contains(errorStr, "deadline") {
		t.Errorf("Expected timeout error, got %v", payload)
	}
}

func TestSocketIntegration_Fanout(t *testing.T) {
	tempDir := integrationTempDir(t)
	socketPath := tempDir + "/asya-runtime.sock"
	defer func() { _ = os.Remove(socketPath) }()

	// Start runtime with fanout_handler
	runtimeProc := StartRuntime(t, "fanout_handler", socketPath, nil)
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 5*time.Second)

	// Create message requesting 3 fan-out messages
	testMsg := createTestMessage(map[string]interface{}{
		"test":  "fanout",
		"count": 3,
	})

	ctx := context.Background()
	err := r.ProcessEnvelope(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify 3 messages were sent to happy-end queue
	sentMessages := mockTransport.GetMessages("happy-end")
	if len(sentMessages) != 3 {
		t.Errorf("Expected 3 fan-out messages in happy-end, got %d", len(sentMessages))
	}

	// Verify each message has the correct index
	for i := 0; i < 3; i++ {
		var sentMsg envelopes.Envelope
		if err := json.Unmarshal(sentMessages[i].Body, &sentMsg); err != nil {
			t.Fatalf("Failed to unmarshal message %d: %v", i, err)
		}

		var payload map[string]interface{}
		if err := json.Unmarshal(sentMsg.Payload, &payload); err != nil {
			t.Fatalf("Failed to unmarshal payload %d: %v", i, err)
		}

		if index, ok := payload["index"].(float64); !ok || int(index) != i {
			t.Errorf("Expected index=%d, got %v", i, payload["index"])
		}
	}
}

func TestSocketIntegration_EmptyResponse(t *testing.T) {
	tempDir := integrationTempDir(t)
	socketPath := tempDir + "/asya-runtime.sock"
	defer func() { _ = os.Remove(socketPath) }()

	// Start runtime with empty_response_handler
	runtimeProc := StartRuntime(t, "empty_response_handler", socketPath, nil)
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 5*time.Second)

	// Create test message
	testMsg := createTestMessage(map[string]interface{}{
		"test": "empty_response",
	})

	ctx := context.Background()
	err := r.ProcessEnvelope(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to happy-end queue (empty response aborts pipeline)
	sentMessages := mockTransport.GetMessages("happy-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in happy-end, got %d", len(sentMessages))
	}
}

func TestSocketIntegration_LargePayload(t *testing.T) {
	tempDir := integrationTempDir(t)
	socketPath := tempDir + "/asya-runtime.sock"
	defer func() { _ = os.Remove(socketPath) }()

	// Start runtime with large_payload_handler
	runtimeProc := StartRuntime(t, "large_payload_handler", socketPath, nil)
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 10*time.Second)

	// Create message with large payload request
	testMsg := createTestMessage(map[string]interface{}{
		"test":    "large_payload",
		"size_kb": 100,
	})

	ctx := context.Background()
	err := r.ProcessEnvelope(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to happy-end queue
	sentMessages := mockTransport.GetMessages("happy-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in happy-end, got %d", len(sentMessages))
	}

	// Verify payload contains large data
	var sentMsg envelopes.Envelope
	if err := json.Unmarshal(sentMessages[0].Body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(sentMsg.Payload, &payload); err != nil {
		t.Fatalf("Failed to unmarshal payload: %v", err)
	}

	if sizeKB, ok := payload["data_size_kb"].(float64); !ok || int(sizeKB) != 100 {
		t.Errorf("Expected data_size_kb=100, got %v", payload["data_size_kb"])
	}
}

func TestSocketIntegration_Unicode(t *testing.T) {
	tempDir := integrationTempDir(t)
	socketPath := tempDir + "/asya-runtime.sock"
	defer func() { _ = os.Remove(socketPath) }()

	// Start runtime with unicode_handler
	runtimeProc := StartRuntime(t, "unicode_handler", socketPath, nil)
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 5*time.Second)

	// Create message with unicode text
	testMsg := createTestMessage(map[string]interface{}{
		"test": "unicode",
		"text": "Hello 世界",
	})

	ctx := context.Background()
	err := r.ProcessEnvelope(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to happy-end queue
	sentMessages := mockTransport.GetMessages("happy-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in happy-end, got %d", len(sentMessages))
	}

	// Verify payload contains unicode data
	var sentMsg envelopes.Envelope
	if err := json.Unmarshal(sentMessages[0].Body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(sentMsg.Payload, &payload); err != nil {
		t.Fatalf("Failed to unmarshal payload: %v", err)
	}

	// Verify unicode characters are properly handled
	if msg, ok := payload["message"].(string); !ok || msg != "处理成功" {
		t.Errorf("Expected message field with Chinese text, got %v", payload)
	}

	// Verify languages map with unicode characters
	if languages, ok := payload["languages"].(map[string]interface{}); !ok {
		t.Errorf("Expected languages field, got %v", payload)
	} else {
		if chinese, ok := languages["chinese"].(string); !ok || chinese != "你好世界" {
			t.Errorf("Expected Chinese greeting, got %v", languages["chinese"])
		}
	}
}
