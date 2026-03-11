package transport

import (
	"context"
	"encoding/binary"
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/google/uuid"
)

// socketAck is sent from receiver to sender after buffering an incoming message.
const socketAck byte = 0x01

// SocketTransport implements Transport using Unix domain sockets on a shared
// Docker volume. Intended for local Docker Compose testing without a message broker.
//
// Layout: each actor listens on <meshDir>/<queueName>.sock. All sidecar
// containers mount the same volume at meshDir, so any sidecar can address any
// other by queue name.
//
// Wire protocol (framed messages in both directions):
//
//	[4-byte big-endian uint32 length][body bytes]
//
// Delivery handshake: after reading the body, the receiver sends one ack byte
// (socketAck = 0x01) so Send unblocks only once the message is in memory.
//
// Constraints (acceptable for local testing):
//   - Sequential FIFO: one in-flight message per actor at a time
//   - Single replica per actor (no competing consumers)
//   - No persistence: messages are in-memory only
type SocketTransport struct {
	meshDir   string
	mu        sync.Mutex
	listener  net.Listener
	listenOn  string      // queue name we're listening on (set on first Receive)
	requeueCh chan []byte // avoids self-dial deadlock in Requeue
}

// SocketConfig holds configuration for the socket transport.
type SocketConfig struct {
	// MeshDir is the directory containing actor sockets (shared Docker volume).
	MeshDir string
}

// NewSocketTransport creates a new Unix socket transport.
// MeshDir must already exist (created by the Docker volume mount or the test harness).
func NewSocketTransport(cfg SocketConfig) (*SocketTransport, error) {
	if cfg.MeshDir == "" {
		return nil, fmt.Errorf("socket transport: MeshDir must not be empty")
	}
	if _, err := os.Stat(cfg.MeshDir); err != nil {
		return nil, fmt.Errorf("socket transport: mesh dir %s must exist before starting (mount the Docker volume first): %w", cfg.MeshDir, err)
	}
	return &SocketTransport{
		meshDir:   cfg.MeshDir,
		requeueCh: make(chan []byte, 4),
	}, nil
}

// sockPath returns the filesystem path for the socket of a given queue.
// filepath.Base strips any directory components so queueName cannot escape meshDir.
func (t *SocketTransport) sockPath(queueName string) string {
	return filepath.Join(t.meshDir, filepath.Base(queueName)+".sock")
}

// startListener starts listening on <meshDir>/<queueName>.sock.
// Idempotent: subsequent calls are no-ops if already listening.
func (t *SocketTransport) startListener(queueName string) error {
	t.mu.Lock()
	defer t.mu.Unlock()

	if t.listener != nil {
		return nil
	}

	path := t.sockPath(queueName)
	_ = os.Remove(path) // remove stale socket from a previous run

	// All containers sharing the mesh volume must run as the same UID so that
	// the socket file created here (owned by this process) is connectable by
	// peer containers without needing world-writable permissions.
	l, err := net.Listen("unix", path)
	if err != nil {
		return fmt.Errorf("socket transport: listen on %s: %w", path, err)
	}

	t.listener = l
	t.listenOn = queueName
	slog.Info("Socket transport: listening", "path", path)
	return nil
}

// Receive blocks until a message arrives on this actor's socket or ctx is cancelled.
// The first call starts the Unix socket listener for queueName.
func (t *SocketTransport) Receive(ctx context.Context, queueName string) (QueueMessage, error) {
	if err := t.startListener(queueName); err != nil {
		return QueueMessage{}, err
	}

	// Drain the requeue buffer before accepting new connections so requeued
	// messages are re-delivered without waiting for the next sender.
	select {
	case body := <-t.requeueCh:
		slog.Debug("Socket transport: re-delivering requeued message", "queue", queueName)
		return QueueMessage{ID: uuid.New().String(), Body: body}, nil
	default:
	}

	// Accept the next connection. Run in a goroutine so ctx cancellation can
	// interrupt the blocking Accept. The goroutine exits when Close() shuts
	// down the listener, bounding the leak to at most one goroutine.
	type acceptResult struct {
		conn net.Conn
		err  error
	}
	ch := make(chan acceptResult, 1)
	go func() {
		conn, err := t.listener.Accept()
		ch <- acceptResult{conn, err}
	}()

	var conn net.Conn
	select {
	case <-ctx.Done():
		return QueueMessage{}, ctx.Err()
	case r := <-ch:
		if r.err != nil {
			select {
			case <-ctx.Done():
				return QueueMessage{}, ctx.Err()
			default:
				return QueueMessage{}, fmt.Errorf("socket transport: accept: %w", r.err)
			}
		}
		conn = r.conn
	}
	defer func() { _ = conn.Close() }()

	body, err := readFramed(conn)
	if err != nil {
		return QueueMessage{}, fmt.Errorf("socket transport: read message from %s: %w", queueName, err)
	}

	// Confirm receipt so the sender's Send call unblocks.
	if _, err := conn.Write([]byte{socketAck}); err != nil {
		return QueueMessage{}, fmt.Errorf("socket transport: send ack for %s: %w", queueName, err)
	}

	slog.Debug("Socket transport: received message", "queue", queueName, "bytes", len(body))
	return QueueMessage{ID: uuid.New().String(), Body: body}, nil
}

// Send delivers body to the actor listening on <meshDir>/<queueName>.sock.
// Retries on connection failure to tolerate actor startup ordering in Docker Compose.
func (t *SocketTransport) Send(ctx context.Context, queueName string, body []byte) error {
	path := t.sockPath(queueName)

	const maxAttempts = 60
	const retryInterval = 500 * time.Millisecond

	var conn net.Conn
	var lastErr error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		d := net.Dialer{Timeout: 2 * time.Second}
		var err error
		conn, err = d.DialContext(ctx, "unix", path)
		if err == nil {
			break
		}
		lastErr = err

		if attempt == maxAttempts {
			return fmt.Errorf("socket transport: connect to %s after %d attempts: %w", path, maxAttempts, lastErr)
		}

		slog.Debug("Socket transport: waiting for actor socket",
			"path", path, "attempt", attempt, "error", err)
		timer := time.NewTimer(retryInterval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C: // poll until target actor socket is ready
		}
	}
	defer func() { _ = conn.Close() }()

	if err := writeFramed(conn, body); err != nil {
		return fmt.Errorf("socket transport: write to %s: %w", path, err)
	}

	// Wait for the receiver's ack before returning — confirms the message is buffered.
	ack := make([]byte, 1)
	if _, err := io.ReadFull(conn, ack); err != nil {
		return fmt.Errorf("socket transport: read ack from %s: %w", path, err)
	}
	if ack[0] != socketAck {
		return fmt.Errorf("socket transport: unexpected ack byte %d from %s", ack[0], path)
	}

	slog.Debug("Socket transport: sent message", "queue", queueName, "bytes", len(body))
	return nil
}

// SendWithDelay is not supported by the socket transport.
func (t *SocketTransport) SendWithDelay(_ context.Context, _ string, _ []byte, _ time.Duration) error {
	return ErrDelayNotSupported
}

// Ack is a no-op: the delivery handshake in Receive already confirmed receipt.
func (t *SocketTransport) Ack(_ context.Context, _ QueueMessage) error {
	return nil
}

// Requeue re-delivers msg to this actor for immediate re-processing.
// Uses an internal channel instead of self-dialing to avoid deadlock with Receive.
func (t *SocketTransport) Requeue(ctx context.Context, msg QueueMessage) error {
	select {
	case t.requeueCh <- msg.Body:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Close shuts down the socket listener and removes the socket file.
func (t *SocketTransport) Close() error {
	t.mu.Lock()
	defer t.mu.Unlock()

	if t.listener == nil {
		return nil
	}

	path := t.sockPath(t.listenOn)
	err := t.listener.Close()
	_ = os.Remove(path)
	t.listener = nil
	return err
}

// maxFrameSize caps the allocation in readFramed to prevent OOM from malformed senders.
const maxFrameSize = 100 * 1024 * 1024 // 100 MB

// readFramed reads a 4-byte big-endian length-prefixed message from r.
func readFramed(r io.Reader) ([]byte, error) {
	var length uint32
	if err := binary.Read(r, binary.BigEndian, &length); err != nil {
		return nil, fmt.Errorf("read length: %w", err)
	}
	if length == 0 {
		return []byte{}, nil
	}
	if length > maxFrameSize {
		return nil, fmt.Errorf("message too large: %d bytes (max %d)", length, maxFrameSize)
	}
	body := make([]byte, length)
	if _, err := io.ReadFull(r, body); err != nil {
		return nil, fmt.Errorf("read body (%d bytes): %w", length, err)
	}
	return body, nil
}

// writeFramed writes a 4-byte big-endian length-prefixed message to w.
func writeFramed(w io.Writer, body []byte) error {
	if err := binary.Write(w, binary.BigEndian, uint32(len(body))); err != nil {
		return fmt.Errorf("write length: %w", err)
	}
	if _, err := w.Write(body); err != nil {
		return fmt.Errorf("write body: %w", err)
	}
	return nil
}
