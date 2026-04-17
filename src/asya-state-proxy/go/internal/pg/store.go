package pg

import (
	"context"
	"encoding/json"
)

// Store defines the key-value storage operations that every Go-based
// state-proxy connector must implement. Mirrors the Python
// StateProxyConnector ABC in asya_state_proxy/interface.py.
type Store interface {
	Read(ctx context.Context, key string) (*KVRow, error)
	Write(ctx context.Context, key string, value json.RawMessage) error
	Exists(ctx context.Context, key string) (bool, error)
	Delete(ctx context.Context, key string) error
	List(ctx context.Context, prefix string) ([]string, error)
}

// ServerConnector extends Store with PG-specific operations required by
// the HTTP handler: conditional writes and Mango-style queries.
type ServerConnector interface {
	Store
	WriteConditional(ctx context.Context, key string, value json.RawMessage, ifStatus string) error
	Query(ctx context.Context, req QueryRequest) (*QueryResponse, error)
}

var _ ServerConnector = (*Connector)(nil)
