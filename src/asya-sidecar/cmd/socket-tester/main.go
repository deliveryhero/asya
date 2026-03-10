// socket-tester exercises SocketTransport methods directly, used as the tester
// container in the transport component test (testing/component/transport/).
//
// Modes:
//
//	--mode test          Run all transport scenarios; exit 0 on success.
//	--mode receive-loop  Accept messages on a queue forever (peer container).
package main

import (
	"bytes"
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/transport"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	mode := flag.String("mode", "test", "Mode: test|receive-loop")
	meshDir := flag.String("mesh-dir", "/mesh", "Mesh directory for socket files")
	queue := flag.String("queue", "", "Queue name (receive-loop mode)")
	crossQueue := flag.String("cross-queue", "", "Queue for cross-container scenario (test mode)")
	flag.Parse()

	switch *mode {
	case "test":
		if code := runTests(*meshDir, *crossQueue); code != 0 {
			os.Exit(code)
		}
	case "receive-loop":
		if *queue == "" {
			slog.Error("--queue required for receive-loop mode")
			os.Exit(1)
		}
		runReceiveLoop(*meshDir, *queue)
	default:
		slog.Error("Unknown mode", "mode", *mode)
		os.Exit(1)
	}
}

// runTests runs all transport scenarios and returns 0 on success, 1 on any failure.
// Scenarios run sequentially; deferred Close() removes each socket file between runs
// so static queue names don't conflict.
func runTests(meshDir, crossQueue string) int {
	type scenario struct {
		name string
		fn   func(string) error
	}

	scenarios := []scenario{
		{"basic_send_receive", testBasicSendReceive},
		{"large_payload", testLargePayload},
		{"fifo_ordering", testFIFOOrdering},
		{"requeue", testRequeue},
		{"context_cancellation", testContextCancellation},
		{"send_with_delay", testSendWithDelay},
		{"ack_noop", testAckNoop},
	}
	if crossQueue != "" {
		q := crossQueue
		scenarios = append(scenarios, scenario{
			"cross_container",
			func(dir string) error { return testCrossContainer(dir, q) },
		})
	}

	failed := 0
	for _, s := range scenarios {
		slog.Info("[.] running", "scenario", s.name)
		if err := s.fn(meshDir); err != nil {
			slog.Error("[-] FAIL", "scenario", s.name, "error", err)
			failed++
		} else {
			slog.Info("[+] PASS", "scenario", s.name)
		}
	}
	if failed > 0 {
		slog.Error(fmt.Sprintf("[-] %d/%d scenarios failed", failed, len(scenarios)))
		return 1
	}
	slog.Info(fmt.Sprintf("[+] all %d scenarios passed", len(scenarios)))
	return 0
}

func newTP(meshDir string) (*transport.SocketTransport, error) {
	return transport.NewSocketTransport(transport.SocketConfig{MeshDir: meshDir})
}

// testBasicSendReceive verifies that a message body is delivered unchanged.
func testBasicSendReceive(meshDir string) error {
	tp, err := newTP(meshDir)
	if err != nil {
		return err
	}
	defer tp.Close() //nolint:errcheck

	want := []byte(`{"hello":"world"}`)
	ch := make(chan error, 1)
	go func() {
		msg, err := tp.Receive(context.Background(), "sc-basic")
		if err != nil {
			ch <- err
			return
		}
		if !bytes.Equal(msg.Body, want) {
			ch <- fmt.Errorf("body mismatch: got %q want %q", msg.Body, want)
			return
		}
		ch <- nil
	}()
	time.Sleep(50 * time.Millisecond) // give goroutine time to call Accept before Send dials
	if err := tp.Send(context.Background(), "sc-basic", want); err != nil {
		return fmt.Errorf("Send: %w", err)
	}
	select {
	case err := <-ch:
		return err
	case <-time.After(5 * time.Second):
		return fmt.Errorf("timeout waiting for receive")
	}
}

// testLargePayload verifies that the 4-byte length-prefix framing handles 1 MB bodies.
func testLargePayload(meshDir string) error {
	tp, err := newTP(meshDir)
	if err != nil {
		return err
	}
	defer tp.Close() //nolint:errcheck

	want := bytes.Repeat([]byte("L"), 1*1024*1024)
	ch := make(chan error, 1)
	go func() {
		msg, err := tp.Receive(context.Background(), "sc-large")
		if err != nil {
			ch <- err
			return
		}
		if !bytes.Equal(msg.Body, want) {
			ch <- fmt.Errorf("body length: got %d want %d", len(msg.Body), len(want))
			return
		}
		ch <- nil
	}()
	time.Sleep(50 * time.Millisecond) // give goroutine time to call Accept before Send dials
	if err := tp.Send(context.Background(), "sc-large", want); err != nil {
		return fmt.Errorf("Send large: %w", err)
	}
	select {
	case err := <-ch:
		return err
	case <-time.After(15 * time.Second):
		return fmt.Errorf("timeout waiting for large receive")
	}
}

// testFIFOOrdering verifies that sequential sends arrive in submission order.
func testFIFOOrdering(meshDir string) error {
	tp, err := newTP(meshDir)
	if err != nil {
		return err
	}
	defer tp.Close() //nolint:errcheck

	const n = 5
	for i := 0; i < n; i++ {
		body := []byte(fmt.Sprintf(`{"seq":%d}`, i))
		ch := make(chan error, 1)
		go func() {
			msg, err := tp.Receive(context.Background(), "sc-fifo")
			if err != nil {
				ch <- err
				return
			}
			if !bytes.Equal(msg.Body, body) {
				ch <- fmt.Errorf("seq %d: got %q want %q", i, msg.Body, body)
				return
			}
			ch <- nil
		}()
		time.Sleep(20 * time.Millisecond) // give goroutine time to call Accept before Send dials
		if err := tp.Send(context.Background(), "sc-fifo", body); err != nil {
			return fmt.Errorf("Send[%d]: %w", i, err)
		}
		select {
		case err := <-ch:
			if err != nil {
				return err
			}
		case <-time.After(5 * time.Second):
			return fmt.Errorf("timeout on message %d", i)
		}
	}
	return nil
}

// testRequeue verifies that Requeue puts a message back in front of incoming network messages.
func testRequeue(meshDir string) error {
	tp, err := newTP(meshDir)
	if err != nil {
		return err
	}
	defer tp.Close() //nolint:errcheck

	body := []byte(`{"requeued":true}`)
	ctx := context.Background()
	// Requeue before the listener starts; Receive must drain the internal
	// requeue buffer before blocking on Accept.
	if err := tp.Requeue(ctx, transport.QueueMessage{ID: "x", Body: body}); err != nil {
		return fmt.Errorf("Requeue: %w", err)
	}
	ctx2, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	msg, err := tp.Receive(ctx2, "sc-requeue")
	if err != nil {
		return fmt.Errorf("Receive: %w", err)
	}
	if !bytes.Equal(msg.Body, body) {
		return fmt.Errorf("body: got %q want %q", msg.Body, body)
	}
	return nil
}

// testContextCancellation verifies that Receive unblocks when the context is cancelled.
func testContextCancellation(meshDir string) error {
	tp, err := newTP(meshDir)
	if err != nil {
		return err
	}
	defer tp.Close() //nolint:errcheck

	ctx, cancel := context.WithCancel(context.Background())
	ch := make(chan error, 1)
	go func() {
		_, err := tp.Receive(ctx, "sc-cancel")
		ch <- err
	}()
	time.Sleep(50 * time.Millisecond) // give goroutine time to block on Accept before cancelling
	cancel()
	select {
	case err := <-ch:
		if !errors.Is(err, context.Canceled) {
			return fmt.Errorf("expected context.Canceled, got %v", err)
		}
		return nil
	case <-time.After(2 * time.Second):
		return fmt.Errorf("Receive did not unblock after context cancellation")
	}
}

// testSendWithDelay verifies that SendWithDelay returns ErrDelayNotSupported.
func testSendWithDelay(meshDir string) error {
	tp, err := newTP(meshDir)
	if err != nil {
		return err
	}
	defer tp.Close() //nolint:errcheck

	err = tp.SendWithDelay(context.Background(), "sc-delay", []byte("x"), time.Second)
	if !errors.Is(err, transport.ErrDelayNotSupported) {
		return fmt.Errorf("expected ErrDelayNotSupported, got %v", err)
	}
	return nil
}

// testAckNoop verifies that Ack is a no-op and returns nil.
func testAckNoop(meshDir string) error {
	tp, err := newTP(meshDir)
	if err != nil {
		return err
	}
	defer tp.Close() //nolint:errcheck
	return tp.Ack(context.Background(), transport.QueueMessage{ID: "x", Body: []byte("y")})
}

// testCrossContainer sends one message to the receiver container and waits for the
// delivery ack. Because Send blocks until the receiver buffers and acks, a nil
// return proves cross-container delivery succeeded.
func testCrossContainer(meshDir, queue string) error {
	tp, err := newTP(meshDir)
	if err != nil {
		return err
	}
	defer tp.Close() //nolint:errcheck

	body := []byte(`{"cross_container":true}`)
	// Send blocks until the receiver (in the peer container) buffers and acks.
	if err := tp.Send(context.Background(), queue, body); err != nil {
		return fmt.Errorf("cross-container Send: %w", err)
	}
	return nil
}

// runReceiveLoop is the peer container mode: accepts messages on the given queue
// forever, logging each one. Runs until killed by Docker Compose on tester exit.
func runReceiveLoop(meshDir, queue string) {
	tp, err := transport.NewSocketTransport(transport.SocketConfig{MeshDir: meshDir})
	if err != nil {
		slog.Error("NewSocketTransport", "error", err)
		os.Exit(1)
	}
	defer tp.Close() //nolint:errcheck

	ctx := context.Background()
	for {
		msg, err := tp.Receive(ctx, queue)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				break
			}
			slog.Error("Receive", "error", err)
			os.Exit(1)
		}
		slog.Info("[+] received", "queue", queue, "bytes", len(msg.Body))
	}
}
