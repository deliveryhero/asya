package store

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/subscribers"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// keyPrefix is prepended to message IDs for storage in the kv table.
const keyPrefix = "msg/"

// StateProxyStore implements MessageStore using HTTP calls to a
// state-proxy connector over Unix socket.
type StateProxyStore struct {
	client *http.Client
	hub    *subscribers.Hub
}

// NewStateProxyStore creates a store that talks to the pg-kv connector
// at the given Unix socket path.
func NewStateProxyStore(socketPath string) *StateProxyStore {
	transport := &http.Transport{
		DialContext: func(_ context.Context, _, _ string) (net.Conn, error) {
			return net.Dial("unix", socketPath)
		},
	}
	return &StateProxyStore{
		client: &http.Client{Transport: transport},
		hub:    subscribers.New(),
	}
}

// baseURL is a placeholder host; ignored when using Unix socket transport.
const baseURL = "http://stateproxy"

// Create stores a new message in the state-proxy.
func (s *StateProxyStore) Create(ctx context.Context, msg *types.Message) error {
	// Build the JSONB value: merge status into data
	val := buildKVValue(msg)
	body, err := json.Marshal(val)
	if err != nil {
		return fmt.Errorf("marshal message: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPut,
		baseURL+"/keys/"+keyPrefix+msg.ID, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := s.client.Do(req)
	if err != nil {
		return fmt.Errorf("create: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusNoContent {
		return fmt.Errorf("create: unexpected status %d", resp.StatusCode)
	}
	return nil
}

// Get retrieves a message from the state-proxy.
func (s *StateProxyStore) Get(ctx context.Context, id string) (*types.Message, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		baseURL+"/keys/"+keyPrefix+id, nil)
	if err != nil {
		return nil, fmt.Errorf("get request: %w", err)
	}

	resp, err := s.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("get: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode == http.StatusNotFound {
		return nil, ErrNotFound
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("get: unexpected status %d", resp.StatusCode)
	}

	var row struct {
		Key       string          `json:"key"`
		Value     json.RawMessage `json:"value"`
		CreatedAt time.Time       `json:"created_at"`
		UpdatedAt time.Time       `json:"updated_at"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&row); err != nil {
		return nil, fmt.Errorf("get decode: %w", err)
	}

	return parseKVRow(id, row.Value, row.CreatedAt, row.UpdatedAt)
}

// UpdateStatus updates a message's status with monotonic ordering enforcement.
// Uses conditional write (if_status) to prevent TOCTOU races. Retries once on
// 409 Conflict (another writer advanced the status concurrently).
func (s *StateProxyStore) UpdateStatus(ctx context.Context, id string, status types.MessageStatus, data json.RawMessage) error {
	return s.updateStatusAttempt(ctx, id, status, data, 1)
}

func (s *StateProxyStore) updateStatusAttempt(ctx context.Context, id string, status types.MessageStatus, data json.RawMessage, retries int) error {
	current, err := s.Get(ctx, id)
	if err != nil {
		return err
	}

	// Enforce monotonic ordering
	if !types.StatusAdvances(current.Status, status) {
		return ErrStaleStatus
	}

	prevStatus := current.Status

	// Merge status and data into current value, preserving fields not in the update
	// (e.g. deadline_at stamped at creation must survive status transitions).
	current.Status = status
	if data != nil {
		current.Data = mergeData(current.Data, data)
	}
	current.UpdatedAt = time.Now().UTC()

	val := buildKVValue(current)
	body, err := json.Marshal(val)
	if err != nil {
		return fmt.Errorf("marshal update: %w", err)
	}

	url := fmt.Sprintf("%s/keys/%s%s?if_status=%s", baseURL, keyPrefix, id, string(prevStatus))
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("update request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := s.client.Do(req)
	if err != nil {
		return fmt.Errorf("update: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode == http.StatusConflict {
		if retries > 0 {
			return s.updateStatusAttempt(ctx, id, status, data, retries-1)
		}
		return ErrStaleStatus
	}

	if resp.StatusCode != http.StatusNoContent {
		return fmt.Errorf("update: unexpected status %d", resp.StatusCode)
	}
	return nil
}

// Delete removes a message from the state-proxy.
func (s *StateProxyStore) Delete(ctx context.Context, id string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete,
		baseURL+"/keys/"+keyPrefix+id, nil)
	if err != nil {
		return fmt.Errorf("delete request: %w", err)
	}

	resp, err := s.client.Do(req)
	if err != nil {
		return fmt.Errorf("delete: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode == http.StatusNotFound {
		return ErrNotFound
	}
	if resp.StatusCode != http.StatusNoContent {
		return fmt.Errorf("delete: unexpected status %d", resp.StatusCode)
	}
	return nil
}

// List queries messages from the state-proxy using the /query endpoint.
func (s *StateProxyStore) List(ctx context.Context, params types.ListParams) ([]*types.Message, int, error) {
	queryReq := map[string]any{
		"prefix": keyPrefix,
	}
	if params.Filters != nil {
		queryReq["filter"] = params.Filters
	}
	if len(params.Sort) > 0 {
		queryReq["sort"] = params.Sort
	}
	if params.Limit > 0 {
		queryReq["limit"] = params.Limit
	}
	if params.Offset > 0 {
		queryReq["offset"] = params.Offset
	}

	body, err := json.Marshal(queryReq)
	if err != nil {
		return nil, 0, fmt.Errorf("marshal query: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		baseURL+"/query", bytes.NewReader(body))
	if err != nil {
		return nil, 0, fmt.Errorf("list request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := s.client.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("list: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		return nil, 0, fmt.Errorf("list: unexpected status %d", resp.StatusCode)
	}

	var queryResp struct {
		Rows []struct {
			Key       string          `json:"key"`
			Value     json.RawMessage `json:"value"`
			CreatedAt time.Time       `json:"created_at"`
			UpdatedAt time.Time       `json:"updated_at"`
		} `json:"rows"`
		Total int `json:"total"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&queryResp); err != nil {
		return nil, 0, fmt.Errorf("list decode: %w", err)
	}

	messages := make([]*types.Message, 0, len(queryResp.Rows))
	for _, row := range queryResp.Rows {
		id := row.Key
		if len(id) > len(keyPrefix) {
			id = id[len(keyPrefix):]
		}
		msg, err := parseKVRow(id, row.Value, row.CreatedAt, row.UpdatedAt)
		if err != nil {
			continue // skip unparseable rows
		}
		messages = append(messages, msg)
	}

	return messages, queryResp.Total, nil
}

// FindExpired returns IDs of non-terminal messages whose deadline_at has passed.
// Queries for messages that have a deadline_at field set and are not in a
// terminal state, then post-filters by comparing deadline_at to now.
// (The Mango $lt operator only handles numeric comparisons, so timestamp
// comparison is done in Go after fetching the candidate set.)
func (s *StateProxyStore) FindExpired(ctx context.Context) ([]string, error) {
	params := types.ListParams{
		Prefix: keyPrefix,
		Filters: map[string]any{
			"status":      map[string]any{"$nin": []any{"succeeded", "failed", "canceled"}},
			"deadline_at": map[string]any{"$exists": true},
		},
		Limit: 1000,
	}
	msgs, _, err := s.List(ctx, params)
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	var ids []string
	for _, msg := range msgs {
		var data types.MessageData
		if err := json.Unmarshal(msg.Data, &data); err != nil || data.DeadlineAt == "" {
			continue
		}
		dl, err := time.Parse(time.RFC3339, data.DeadlineAt)
		if err != nil {
			continue
		}
		if now.After(dl) {
			ids = append(ids, msg.ID)
		}
	}
	return ids, nil
}

// Subscribe returns a channel that receives events for the given message ID.
func (s *StateProxyStore) Subscribe(id string) <-chan types.Event {
	return s.hub.Subscribe(id)
}

// Unsubscribe removes and closes the channel for the given message ID.
func (s *StateProxyStore) Unsubscribe(id string, ch <-chan types.Event) {
	s.hub.Unsubscribe(id, ch)
}

// Publish sends an event to all subscribers for the given message ID.
func (s *StateProxyStore) Publish(id string, event types.Event) {
	s.hub.Publish(id, event)
}

// mergeData merges incoming event data over existing message data, preserving
// fields in existing that are absent from incoming (e.g. deadline_at).
func mergeData(existing, incoming json.RawMessage) json.RawMessage {
	var base, update map[string]any
	if err := json.Unmarshal(existing, &base); err != nil || base == nil {
		return incoming
	}
	if err := json.Unmarshal(incoming, &update); err != nil {
		return incoming
	}
	for k, v := range update {
		base[k] = v
	}
	merged, err := json.Marshal(base)
	if err != nil {
		return incoming
	}
	return merged
}

// buildKVValue creates the JSONB object stored in the kv table.
// Merges status into the data fields.
func buildKVValue(msg *types.Message) map[string]any {
	val := make(map[string]any)

	// Unmarshal existing data fields into the value map
	if msg.Data != nil {
		_ = json.Unmarshal(msg.Data, &val)
	}

	// Status is always set at top level of the JSONB value
	val["status"] = string(msg.Status)

	return val
}

// parseKVRow converts a kv row's JSONB value back into a Message.
func parseKVRow(id string, value json.RawMessage, createdAt, updatedAt time.Time) (*types.Message, error) {
	var val map[string]any
	if err := json.Unmarshal(value, &val); err != nil {
		return nil, fmt.Errorf("parse kv value: %w", err)
	}

	status := types.MessageStatusPending
	if s, ok := val["status"].(string); ok {
		status = types.MessageStatus(s)
	}

	return &types.Message{
		ID:        id,
		Status:    status,
		Data:      value,
		CreatedAt: createdAt,
		UpdatedAt: updatedAt,
	}, nil
}
