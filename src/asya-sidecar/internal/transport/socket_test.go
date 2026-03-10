package transport

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func newTestSocketTransport(t *testing.T) (*SocketTransport, string) {
	t.Helper()
	dir := t.TempDir()
	tp, err := NewSocketTransport(SocketConfig{MeshDir: dir})
	if err != nil {
		t.Fatalf("NewSocketTransport: %v", err)
	}
	return tp, dir
}

func TestSocketTransport_SendReceive(t *testing.T) {
	tp, _ := newTestSocketTransport(t)
	t.Cleanup(func() { _ = tp.Close() })

	ctx := context.Background()
	payload := map[string]string{"hello": "world"}
	body, _ := json.Marshal(payload)

	type result struct {
		msg QueueMessage
		err error
	}
	ch := make(chan result, 1)
	go func() {
		msg, err := tp.Receive(ctx, "test-actor")
		ch <- result{msg, err}
	}()

	time.Sleep(50 * time.Millisecond) // wait for goroutine to start listening

	if err := tp.Send(ctx, "test-actor", body); err != nil {
		t.Fatalf("Send: %v", err)
	}

	select {
	case r := <-ch:
		if r.err != nil {
			t.Fatalf("Receive: %v", r.err)
		}
		if string(r.msg.Body) != string(body) {
			t.Errorf("body mismatch: got %q, want %q", r.msg.Body, body)
		}
		if r.msg.ID == "" {
			t.Error("message ID should not be empty")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timeout waiting for message")
	}
}

func TestSocketTransport_Ack(t *testing.T) {
	tp, _ := newTestSocketTransport(t)
	t.Cleanup(func() { _ = tp.Close() })

	ctx := context.Background()
	body := []byte(`{"test":"ack"}`)

	go func() { _, _ = tp.Receive(ctx, "ack-actor") }()
	time.Sleep(50 * time.Millisecond) // wait for listener to start
	if err := tp.Send(ctx, "ack-actor", body); err != nil {
		t.Fatalf("Send: %v", err)
	}

	if err := tp.Ack(ctx, QueueMessage{ID: "x", Body: body}); err != nil {
		t.Errorf("Ack should be a no-op, got: %v", err)
	}
}

func TestSocketTransport_Requeue(t *testing.T) {
	tp, _ := newTestSocketTransport(t)
	t.Cleanup(func() { _ = tp.Close() })

	ctx := context.Background()
	body := []byte(`{"test":"requeue"}`)

	// Push to the requeue channel before the listener starts.
	if err := tp.Requeue(ctx, QueueMessage{ID: "x", Body: body}); err != nil {
		t.Fatalf("Requeue: %v", err)
	}

	// Start listener, then Receive — should drain the requeue buffer first.
	if err := tp.startListener("requeue-actor"); err != nil {
		t.Fatalf("startListener: %v", err)
	}
	msg, err := tp.Receive(ctx, "requeue-actor")
	if err != nil {
		t.Fatalf("Receive: %v", err)
	}
	if string(msg.Body) != string(body) {
		t.Errorf("requeued body mismatch: got %q, want %q", msg.Body, body)
	}
}

func TestSocketTransport_ContextCancellation(t *testing.T) {
	tp, _ := newTestSocketTransport(t)
	t.Cleanup(func() { _ = tp.Close() })

	ctx, cancel := context.WithCancel(context.Background())

	errCh := make(chan error, 1)
	go func() {
		_, err := tp.Receive(ctx, "cancel-actor")
		errCh <- err
	}()

	time.Sleep(50 * time.Millisecond) // wait for goroutine to block on Accept
	cancel()

	select {
	case err := <-errCh:
		if !errors.Is(err, context.Canceled) {
			t.Errorf("expected context.Canceled, got: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timeout: Receive did not respect context cancellation")
	}
}

func TestSocketTransport_SendWithDelay(t *testing.T) {
	tp, _ := newTestSocketTransport(t)
	t.Cleanup(func() { _ = tp.Close() })

	err := tp.SendWithDelay(context.Background(), "q", []byte("x"), time.Second)
	if !errors.Is(err, ErrDelayNotSupported) {
		t.Errorf("expected ErrDelayNotSupported, got: %v", err)
	}
}

func TestSocketTransport_Close(t *testing.T) {
	tp, dir := newTestSocketTransport(t)

	if err := tp.startListener("close-actor"); err != nil {
		t.Fatalf("startListener: %v", err)
	}

	sockPath := filepath.Join(dir, "close-actor.sock")
	if _, err := os.Stat(sockPath); err != nil {
		t.Fatalf("socket file should exist before Close: %v", err)
	}

	if err := tp.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	if _, err := os.Stat(sockPath); !os.IsNotExist(err) {
		t.Error("socket file should be removed after Close")
	}

	// Second Close should be a no-op.
	if err := tp.Close(); err != nil {
		t.Errorf("second Close should be no-op, got: %v", err)
	}
}

func TestSocketTransport_MultiMessage(t *testing.T) {
	tp, _ := newTestSocketTransport(t)
	t.Cleanup(func() { _ = tp.Close() })

	ctx := context.Background()
	if err := tp.startListener("multi-actor"); err != nil {
		t.Fatalf("startListener: %v", err)
	}

	const n = 5
	for i := 0; i < n; i++ {
		body := []byte(`{"i":` + string(rune('0'+i)) + `}`)

		type result struct {
			msg QueueMessage
			err error
		}
		ch := make(chan result, 1)
		go func() {
			msg, err := tp.Receive(ctx, "multi-actor")
			ch <- result{msg, err}
		}()

		time.Sleep(20 * time.Millisecond) // wait for goroutine to block on Accept

		if err := tp.Send(ctx, "multi-actor", body); err != nil {
			t.Fatalf("Send[%d]: %v", i, err)
		}

		select {
		case r := <-ch:
			if r.err != nil {
				t.Fatalf("Receive[%d]: %v", i, r.err)
			}
			if string(r.msg.Body) != string(body) {
				t.Errorf("message %d body mismatch: got %q, want %q", i, r.msg.Body, body)
			}
		case <-time.After(3 * time.Second):
			t.Fatalf("timeout on message %d", i)
		}
	}
}

func TestNewSocketTransport_EmptyMeshDir(t *testing.T) {
	_, err := NewSocketTransport(SocketConfig{MeshDir: ""})
	if err == nil {
		t.Error("expected error for empty MeshDir, got nil")
	}
}

func TestSockPath_NoPathTraversal(t *testing.T) {
	tp, dir := newTestSocketTransport(t)
	t.Cleanup(func() { _ = tp.Close() })

	cases := []struct {
		queue string
		want  string // expected base name of the socket file
	}{
		{"actor", "actor.sock"},
		{"../evil", "evil.sock"},
		{"../../etc/passwd", "passwd.sock"},
		{"sub/dir/actor", "actor.sock"},
	}
	for _, c := range cases {
		got := tp.sockPath(c.queue)
		wantPath := filepath.Join(dir, c.want)
		if got != wantPath {
			t.Errorf("sockPath(%q): got %q, want %q", c.queue, got, wantPath)
		}
	}
}

func TestReadFramed_OversizeRejected(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}

	// Write a length field that exceeds maxFrameSize without sending any body bytes.
	go func() {
		buf := make([]byte, 4)
		buf[0] = 0x10 // 0x10_00_00_01 = 268435457 bytes > 100 MB
		buf[1] = 0x00
		buf[2] = 0x00
		buf[3] = 0x01
		_, _ = w.Write(buf)
		_ = w.Close()
	}()

	_, readErr := readFramed(r)
	_ = r.Close()
	if readErr == nil {
		t.Error("expected error for oversize frame, got nil")
	}
}

func TestSocketFraming(t *testing.T) {
	cases := [][]byte{
		{},
		[]byte("hello"),
		[]byte(`{"route":{"prev":[],"curr":"a","next":["b"]}}`),
	}
	for _, want := range cases {
		r, w, err := os.Pipe()
		if err != nil {
			t.Fatalf("os.Pipe: %v", err)
		}

		done := make(chan error, 1)
		go func() {
			err := writeFramed(w, want)
			_ = w.Close()
			done <- err
		}()

		got, readErr := readFramed(r)
		_ = r.Close()

		if writeErr := <-done; writeErr != nil {
			t.Errorf("writeFramed(%q): %v", want, writeErr)
		}
		if readErr != nil {
			t.Errorf("readFramed(%q): %v", want, readErr)
		}
		if string(got) != string(want) {
			t.Errorf("framing roundtrip: got %q, want %q", got, want)
		}
	}
}
