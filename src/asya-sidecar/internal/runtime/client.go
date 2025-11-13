package runtime

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/pkg/envelopes"
)

// ErrorDetails represents additional information on error occurred in runtime
type ErrorDetails struct {
	Message   string `json:"message,omitempty"`
	Type      string `json:"type,omitempty"`
	Traceback string `json:"traceback,omitempty"`
}

// RuntimeResponse represents the response from the actor runtime
type RuntimeResponse struct {
	Payload json.RawMessage `json:"payload,omitempty"` // payload output from handler
	Route   envelopes.Route `json:"route,omitempty"`   // route output from handler
	Error   string          `json:"error,omitempty"`
	Details ErrorDetails    `json:"details,omitempty"`
}

// IsError returns true if the response indicates an error
func (r *RuntimeResponse) IsError() bool {
	return r.Error != ""
}

// Client handles communication with the actor runtime via Unix socket
type Client struct {
	socketPath string
	timeout    time.Duration
}

// NewClient creates a new runtime client
func NewClient(socketPath string, timeout time.Duration) *Client {
	return &Client{
		socketPath: socketPath,
		timeout:    timeout,
	}
}

// SendSocketData sends a message with length-prefix (4-byte big-endian uint32)
func SendSocketData(conn net.Conn, data []byte) error {
	// Send length prefix
	length := make([]byte, 4)
	binary.BigEndian.PutUint32(length, uint32(len(data)))
	if _, err := conn.Write(length); err != nil {
		return fmt.Errorf("failed to write length prefix: %w", err)
	}

	// Send data
	if _, err := conn.Write(data); err != nil {
		return fmt.Errorf("failed to write data: %w", err)
	}

	return nil
}

// RecvSocketData receives a message with length-prefix (4-byte big-endian uint32)
func RecvSocketData(conn net.Conn) ([]byte, error) {
	// Read length prefix
	length := make([]byte, 4)
	if _, err := io.ReadFull(conn, length); err != nil {
		return nil, fmt.Errorf("failed to read length prefix: %w", err)
	}

	// Read data
	size := binary.BigEndian.Uint32(length)
	data := make([]byte, size)
	if _, err := io.ReadFull(conn, data); err != nil {
		return nil, fmt.Errorf("failed to read data: %w", err)
	}

	return data, nil
}

// CallRuntime sends a full message (with route and payload) to the runtime and waits for response(s)
// Returns multiple responses for fan-out, empty slice for abort, or error
func (c *Client) CallRuntime(ctx context.Context, data []byte) ([]RuntimeResponse, error) {
	// Apply timeout
	ctx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()

	// Connect to Unix socket
	var dialer net.Dialer
	conn, err := dialer.DialContext(ctx, "unix", c.socketPath)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to runtime socket: %w", err)
	}
	defer func() { _ = conn.Close() }()

	// Set deadline for the entire operation
	deadline, _ := ctx.Deadline()
	_ = conn.SetDeadline(deadline)

	// Send message with length-prefix
	if err := SendSocketData(conn, data); err != nil {
		return nil, fmt.Errorf("failed to send message to runtime: %w", err)
	}

	// Read response with length-prefix
	responseData, err := RecvSocketData(conn)
	if err != nil {
		return nil, fmt.Errorf("failed to read response from runtime: %w", err)
	}

	// Parse response - runtime always returns an array
	var responses []RuntimeResponse
	if err := json.Unmarshal(responseData, &responses); err != nil {
		return nil, fmt.Errorf("failed to parse runtime response: %w", err)
	}

	return responses, nil
}
