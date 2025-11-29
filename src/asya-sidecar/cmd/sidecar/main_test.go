package main

import (
	"context"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"golang.org/x/net/nettest"
)

func TestVerifySocketConnection_Success(t *testing.T) {
	socketPath, err := nettest.LocalPath()
	if err != nil {
		t.Fatalf("Failed to get local path: %v", err)
	}

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create test socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	if err := verifySocketConnection(socketPath); err != nil {
		t.Errorf("verifySocketConnection() failed: %v", err)
	}
}

func TestVerifySocketConnection_SocketNotExists(t *testing.T) {
	tmpDir := t.TempDir()
	socketPath := filepath.Join(tmpDir, "nonexistent.sock")

	err := verifySocketConnection(socketPath)
	if err == nil {
		t.Error("verifySocketConnection() expected error for non-existent socket, got nil")
	}
}

func TestVerifySocketConnection_NotASocket(t *testing.T) {
	tmpDir := t.TempDir()
	filePath := filepath.Join(tmpDir, "regular-file.txt")

	if err := os.WriteFile(filePath, []byte("test"), 0600); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}

	err := verifySocketConnection(filePath)
	if err == nil {
		t.Error("verifySocketConnection() expected error for regular file, got nil")
	}
}

func TestVerifySocketConnection_NotListening(t *testing.T) {
	socketPath, err := nettest.LocalPath()
	if err != nil {
		t.Fatalf("Failed to get local path: %v", err)
	}

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create test socket: %v", err)
	}
	_ = listener.Close()

	err = verifySocketConnection(socketPath)
	if err == nil {
		t.Error("verifySocketConnection() expected error for closed socket, got nil")
	}
}

func TestWaitForRuntime_Success(t *testing.T) {
	tmpDir := t.TempDir()
	readyFile := filepath.Join(tmpDir, "runtime-ready")
	socketPath, err := nettest.LocalPath()
	if err != nil {
		t.Fatalf("Failed to get local path: %v", err)
	}

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create test socket: %v", err)
	}
	defer func() { _ = listener.Close() }()

	go func() {
		time.Sleep(100 * time.Millisecond)
		if err := os.WriteFile(readyFile, []byte("ready"), 0600); err != nil {
			t.Logf("Failed to write ready file: %v", err)
		}
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	if err := waitForRuntime(ctx, readyFile, socketPath, 2*time.Second); err != nil {
		t.Errorf("waitForRuntime() failed: %v", err)
	}
}

func TestWaitForRuntime_Timeout(t *testing.T) {
	tmpDir := t.TempDir()
	readyFile := filepath.Join(tmpDir, "runtime-ready")
	socketPath, err := nettest.LocalPath()
	if err != nil {
		t.Fatalf("Failed to get local path: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	err = waitForRuntime(ctx, readyFile, socketPath, 500*time.Millisecond)
	if err == nil {
		t.Error("waitForRuntime() expected timeout error, got nil")
	}
}

func TestWaitForRuntime_ReadyFileButNoSocket(t *testing.T) {
	tmpDir := t.TempDir()
	readyFile := filepath.Join(tmpDir, "runtime-ready")
	socketPath, err := nettest.LocalPath()
	if err != nil {
		t.Fatalf("Failed to get local path: %v", err)
	}

	if err = os.WriteFile(readyFile, []byte("ready"), 0600); err != nil {
		t.Fatalf("Failed to write ready file: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	err = waitForRuntime(ctx, readyFile, socketPath, 1*time.Second)
	if err == nil {
		t.Error("waitForRuntime() expected error when ready file exists but socket doesn't, got nil")
	}
}

func TestWaitForRuntime_ReadyFileButSocketNotListening(t *testing.T) {
	tmpDir := t.TempDir()
	readyFile := filepath.Join(tmpDir, "runtime-ready")
	socketPath, err := nettest.LocalPath()
	if err != nil {
		t.Fatalf("Failed to get local path: %v", err)
	}

	if err = os.WriteFile(readyFile, []byte("ready"), 0600); err != nil {
		t.Fatalf("Failed to write ready file: %v", err)
	}

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("Failed to create test socket: %v", err)
	}
	_ = listener.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	err = waitForRuntime(ctx, readyFile, socketPath, 1*time.Second)
	if err == nil {
		t.Error("waitForRuntime() expected error when socket exists but not listening, got nil")
	}
}
