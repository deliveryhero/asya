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

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/deliveryhero/asya/asya-sidecar/internal/router"
	"github.com/deliveryhero/asya/asya-sidecar/internal/runtime"
	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
	"github.com/deliveryhero/asya/asya-sidecar/pkg/messages"
)

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
	handlersFile := filepath.Join(projectRoot, "tests", "mock_runtime", "handlers", "mock_payload_handlers.py")
	mockRuntimeDir := filepath.Join(projectRoot, "tests", "mock_runtime")

	// Verify files exist
	if _, err := os.Stat(runtimeScript); err != nil {
		t.Fatalf("Runtime script not found: %s", runtimeScript)
	}
	if _, err := os.Stat(handlersFile); err != nil {
		t.Fatalf("Handlers file not found: %s", handlersFile)
	}

	// Create command
	cmd := exec.Command("python3", runtimeScript)

	// Set environment variables
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, fmt.Sprintf("ASYA_HANDLER=handlers.mock_payload_handlers.%s", handler))
	cmd.Env = append(cmd.Env, fmt.Sprintf("ASYA_SOCKET_PATH=%s", socketPath))
	cmd.Env = append(cmd.Env, fmt.Sprintf("PYTHONPATH=%s", mockRuntimeDir))

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
		rp.cmd.Process.Kill()
		rp.cmd.Wait()
	}
	os.Remove(rp.socketPath)
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
func createTestRouter(t *testing.T, socketPath string, timeout time.Duration) (*router.Router, *MockTransport) {
	t.Helper()

	mockTransport := NewMockTransport()
	runtimeClient := runtime.NewClient(socketPath, timeout)

	cfg := &config.Config{
		QueueName:     "test-queue",
		HappyEndQueue: "happy-end",
		ErrorEndQueue: "error-end",
		SocketPath:    socketPath,
		Timeout:       timeout,
	}

	r := router.NewRouter(cfg, mockTransport, runtimeClient, nil)
	return r, mockTransport
}

// createTestMessage creates a test message with the given payload
func createTestMessage(payload map[string]interface{}) transport.QueueMessage {
	route := messages.Route{
		Steps:   []string{"test-queue", "happy-end"},
		Current: 0,
	}

	payloadBytes, _ := json.Marshal(payload)

	msg := messages.Message{
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
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-happy.sock"
	defer os.Remove(socketPath)

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
	err := r.ProcessMessage(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to happy-end queue
	sentMessages := mockTransport.GetMessages("happy-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in happy-end, got %d", len(sentMessages))
	}

	// Verify payload contains expected fields
	var sentMsg messages.Message
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
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-error.sock"
	defer os.Remove(socketPath)

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
	err := r.ProcessMessage(ctx, testMsg)
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

	if errorStr, ok := errorMsg["error"].(string); !ok || !strings.Contains(strings.ToLower(errorStr), "error") {
		t.Errorf("Expected error field in message, got %v", errorMsg)
	}
}

func TestSocketIntegration_OOM(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-oom.sock"
	defer os.Remove(socketPath)

	// Start runtime with oom_handler and OOM detection enabled
	runtimeProc := StartRuntime(t, "oom_handler", socketPath, map[string]string{
		"ASYA_ENABLE_OOM_DETECTION": "true",
	})
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 5*time.Second)

	// Create and process test message
	testMsg := createTestMessage(map[string]interface{}{
		"test": "oom_simulation",
	})

	ctx := context.Background()
	err := r.ProcessMessage(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to error-end queue
	sentMessages := mockTransport.GetMessages("error-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in error-end, got %d", len(sentMessages))
	}

	// Verify error message mentions OOM
	var errorMsg map[string]interface{}
	if err := json.Unmarshal(sentMessages[0].Body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal error message: %v", err)
	}

	errorStr := strings.ToLower(fmt.Sprintf("%v", errorMsg))
	if !strings.Contains(errorStr, "oom") && !strings.Contains(errorStr, "memory") {
		t.Errorf("Expected OOM error, got %v", errorMsg)
	}
}

func TestSocketIntegration_CUDAoom(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-cuda-oom.sock"
	defer os.Remove(socketPath)

	// Start runtime with cuda_oom_handler
	runtimeProc := StartRuntime(t, "cuda_oom_handler", socketPath, map[string]string{
		"ASYA_ENABLE_OOM_DETECTION": "true",
		"ASYA_CUDA_CLEANUP_ON_OOM":  "true",
	})
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 5*time.Second)

	// Create and process test message
	testMsg := createTestMessage(map[string]interface{}{
		"test": "cuda_oom_simulation",
	})

	ctx := context.Background()
	err := r.ProcessMessage(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to error-end queue
	sentMessages := mockTransport.GetMessages("error-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in error-end, got %d", len(sentMessages))
	}

	// Verify error message mentions CUDA OOM
	var errorMsg map[string]interface{}
	if err := json.Unmarshal(sentMessages[0].Body, &errorMsg); err != nil {
		t.Fatalf("Failed to unmarshal error message: %v", err)
	}

	errorStr := strings.ToLower(fmt.Sprintf("%v", errorMsg))
	if !strings.Contains(errorStr, "cuda") && !strings.Contains(errorStr, "memory") {
		t.Errorf("Expected CUDA OOM error, got %v", errorMsg)
	}
}

func TestSocketIntegration_Timeout(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-timeout.sock"
	defer os.Remove(socketPath)

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
	err := r.ProcessMessage(ctx, testMsg)
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

	errorStr := strings.ToLower(fmt.Sprintf("%v", errorMsg))
	if !strings.Contains(errorStr, "timeout") && !strings.Contains(errorStr, "deadline") {
		t.Errorf("Expected timeout error, got %v", errorMsg)
	}
}

func TestSocketIntegration_Fanout(t *testing.T) {
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-fanout.sock"
	defer os.Remove(socketPath)

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
	err := r.ProcessMessage(ctx, testMsg)
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
		var sentMsg messages.Message
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
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-empty.sock"
	defer os.Remove(socketPath)

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
	err := r.ProcessMessage(ctx, testMsg)
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
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-large.sock"
	defer os.Remove(socketPath)

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
	err := r.ProcessMessage(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to happy-end queue
	sentMessages := mockTransport.GetMessages("happy-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in happy-end, got %d", len(sentMessages))
	}

	// Verify payload contains large data
	var sentMsg messages.Message
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
	tempDir := t.TempDir()
	socketPath := tempDir + "/test-socket-unicode.sock"
	defer os.Remove(socketPath)

	// Start runtime with unicode_handler
	runtimeProc := StartRuntime(t, "unicode_handler", socketPath, nil)
	defer runtimeProc.Stop()

	// Create router
	r, mockTransport := createTestRouter(t, socketPath, 5*time.Second)

	// Create message with unicode text
	testMsg := createTestMessage(map[string]interface{}{
		"test": "unicode",
		"text": "Hello 世界 🌍",
	})

	ctx := context.Background()
	err := r.ProcessMessage(ctx, testMsg)
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	// Verify message was sent to happy-end queue
	sentMessages := mockTransport.GetMessages("happy-end")
	if len(sentMessages) != 1 {
		t.Errorf("Expected 1 message in happy-end, got %d", len(sentMessages))
	}

	// Verify payload contains emoji
	var sentMsg messages.Message
	if err := json.Unmarshal(sentMessages[0].Body, &sentMsg); err != nil {
		t.Fatalf("Failed to unmarshal sent message: %v", err)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(sentMsg.Payload, &payload); err != nil {
		t.Fatalf("Failed to unmarshal payload: %v", err)
	}

	if _, ok := payload["emoji"]; !ok {
		t.Errorf("Expected emoji field in payload, got %v", payload)
	}
}
