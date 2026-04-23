package s3kv

import (
	"context"
	"encoding/json"
)

// Store defines the key-value operations that the S3 connector implements.
// Interface is structurally compatible with pg.Store.
type Store interface {
	Read(ctx context.Context, key string) (*KVRow, error)
	Write(ctx context.Context, key string, value json.RawMessage) error
	Exists(ctx context.Context, key string) (bool, error)
	Delete(ctx context.Context, key string) error
	List(ctx context.Context, prefix string) ([]string, error)
}

// ServerConnector extends Store with conditional writes and Mango queries —
// the two operations the HTTP handler needs beyond basic CRUD.
type ServerConnector interface {
	Store
	WriteConditional(ctx context.Context, key string, value json.RawMessage, ifStatus string) error
	Query(ctx context.Context, req QueryRequest) (*QueryResponse, error)
}

var _ ServerConnector = (*connector)(nil)

// StorageBackend is the minimal interface any KV backend must implement so that
// the HTTP server and DuckDB query engine can be shared across connectors
// (e.g. s3kv and gcskv) without code duplication.
type StorageBackend interface {
	Store
	WriteConditional(ctx context.Context, key string, value json.RawMessage, ifStatus string) error
}

// NewServerConnector wires any StorageBackend and QueryEngine together.
func NewServerConnector(c StorageBackend, q *QueryEngine) ServerConnector {
	return &connector{backend: c, QueryEngine: q}
}

// connector is the combined backend + QueryEngine that satisfies ServerConnector.
type connector struct {
	backend StorageBackend
	*QueryEngine
}

func (c *connector) Read(ctx context.Context, key string) (*KVRow, error) {
	return c.backend.Read(ctx, key)
}
func (c *connector) Write(ctx context.Context, key string, value json.RawMessage) error {
	err := c.backend.Write(ctx, key, value)
	if err == nil {
		c.QueryEngine.InvalidateCache()
	}
	return err
}
func (c *connector) WriteConditional(ctx context.Context, key string, value json.RawMessage, ifStatus string) error {
	err := c.backend.WriteConditional(ctx, key, value, ifStatus)
	if err == nil {
		c.QueryEngine.InvalidateCache()
	}
	return err
}
func (c *connector) Exists(ctx context.Context, key string) (bool, error) {
	return c.backend.Exists(ctx, key)
}
func (c *connector) Delete(ctx context.Context, key string) error {
	err := c.backend.Delete(ctx, key)
	if err == nil {
		c.QueryEngine.InvalidateCache()
	}
	return err
}
func (c *connector) List(ctx context.Context, prefix string) ([]string, error) {
	return c.backend.List(ctx, prefix)
}
