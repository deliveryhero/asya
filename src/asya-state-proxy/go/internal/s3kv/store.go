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

// connector is the combined Connector + QueryEngine that satisfies ServerConnector.
type connector struct {
	*Connector
	*QueryEngine
}

// NewServerConnector wires a Connector and QueryEngine together.
func NewServerConnector(c *Connector, q *QueryEngine) ServerConnector {
	return &connector{Connector: c, QueryEngine: q}
}
