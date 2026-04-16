package meshclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/sseclient"
)

// CreateRequest is the POST body for creating a new mesh message.
type CreateRequest struct {
	Payload map[string]any `json:"payload"`
	Headers map[string]any `json:"headers,omitempty"`
	Timeout int            `json:"timeout,omitempty"` // seconds
}

// CreateResponse is the response from POST /api/v1/mesh/?actor=X.
type CreateResponse struct {
	ID string `json:"id"`
}

// MessageStatus is the response from GET /api/v1/mesh/{id}.
type MessageStatus struct {
	ID        string          `json:"id"`
	Status    string          `json:"status"`
	Data      json.RawMessage `json:"data,omitempty"`
	CreatedAt time.Time       `json:"created_at"`
	UpdatedAt time.Time       `json:"updated_at"`
}

// Client wraps HTTP calls to the mesh-api.
type Client struct {
	// localURL is the mesh-api URL on the same pod (e.g. "http://localhost:8080")
	// Used for POST create, GET status, DELETE cancel.
	localURL string

	// ingressURL is the external Ingress URL for hash-routed SSE subscriptions.
	// Used for GET /api/v1/mesh/{id}/events.
	ingressURL string

	httpClient *http.Client
}

// New creates a mesh API client.
// localURL: mesh-api on the same pod (e.g. "http://localhost:8080").
// ingressURL: external Ingress for hash-routed SSE (e.g. "http://asya-mesh-api.example.com").
func New(localURL, ingressURL string) *Client {
	return &Client{
		localURL:   localURL,
		ingressURL: ingressURL,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// Create dispatches a new message to the mesh and returns the assigned ID.
func (c *Client) Create(ctx context.Context, actor string, req CreateRequest) (*CreateResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal create request: %w", err)
	}

	url := fmt.Sprintf("%s/api/v1/mesh/?actor=%s", c.localURL, actor)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create HTTP request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("mesh create: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusCreated {
		respBody, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return nil, fmt.Errorf("mesh create returned %d: %s", resp.StatusCode, string(respBody))
	}

	var result CreateResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode create response: %w", err)
	}
	return &result, nil
}

// Get retrieves the current status of a mesh message.
func (c *Client) Get(ctx context.Context, id string) (*MessageStatus, error) {
	url := fmt.Sprintf("%s/api/v1/mesh/%s", c.localURL, id)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("create GET request: %w", err)
	}

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("mesh get: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode == http.StatusNotFound {
		return nil, fmt.Errorf("message %q not found", id)
	}
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return nil, fmt.Errorf("mesh get returned %d: %s", resp.StatusCode, string(body))
	}

	var status MessageStatus
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		return nil, fmt.Errorf("decode status: %w", err)
	}
	return &status, nil
}

// SubscribeEvents opens an SSE stream for the given message ID via Ingress
// (hash-routed by X-Asya-Envelope-ID header).
func (c *Client) SubscribeEvents(ctx context.Context, id string) (<-chan sseclient.Event, <-chan error) {
	url := fmt.Sprintf("%s/api/v1/mesh/%s/events", c.ingressURL, id)
	return sseclient.Subscribe(ctx, url, id)
}

// Cancel sends a DELETE request to cancel a mesh message.
func (c *Client) Cancel(ctx context.Context, id string) error {
	url := fmt.Sprintf("%s/api/v1/mesh/%s", c.localURL, id)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodDelete, url, nil)
	if err != nil {
		return fmt.Errorf("create DELETE request: %w", err)
	}

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("mesh cancel: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("mesh cancel returned %d: %s", resp.StatusCode, string(body))
	}
	return nil
}
