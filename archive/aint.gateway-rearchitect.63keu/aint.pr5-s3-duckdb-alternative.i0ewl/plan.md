# PR5: S3 State-Proxy Connector with DuckDB Query

## Goal

Build a Go binary implementing the state-proxy HTTP interface (same contract as
the PG connector from PR1) backed by S3 for KV operations and DuckDB (embedded)
for `/query`. Target: ~400-600 LOC Go. Use case: high-latency ML training
deployments that don't want PostgreSQL as a dependency.

## Architecture

```
mesh-api -> HTTP/Unix socket -> state-proxy-s3 -> S3 (KV)
                                       |
                                       +-> DuckDB (in-memory, query-time only)
```

KV operations go directly to S3 via aws-sdk-go-v2. Query operations create an
ephemeral DuckDB table from S3 JSON objects, apply filter/sort/limit, and
return results. DuckDB is never a source of truth -- S3 is.

## File Layout

All new files live under `src/asya-gateway/`:

```
src/asya-gateway/
  cmd/
    state-proxy-s3/
      main.go                    # ~60 LOC  -- binary entrypoint
  internal/
    stateproxys3/
      connector.go               # ~200 LOC -- S3 KV operations
      connector_test.go           # ~180 LOC -- unit tests (mocked S3)
      query.go                    # ~150 LOC -- DuckDB query engine
      query_test.go               # ~120 LOC -- unit tests (temp DuckDB)
      server.go                   # ~80 LOC  -- HTTP handler over Unix socket
      server_test.go              # ~60 LOC  -- integration test
  Dockerfile.state-proxy-s3       # ~40 LOC  -- multi-stage with CGO for DuckDB
```

Test infrastructure:
```
testing/component/state-proxy-s3/
  Makefile                        # ~30 LOC
  docker-compose.yml              # ~50 LOC
  tests/
    test_kv_operations.py         # ~80 LOC
    test_query.py                 # ~80 LOC
    conftest.py                   # ~30 LOC
```

## Dependencies

Add to `src/asya-gateway/go.mod`:
```
github.com/aws/aws-sdk-go-v2/service/s3     # S3 client
github.com/marcboeker/go-duckdb              # DuckDB Go driver (CGo)
```

go-duckdb requires CGO_ENABLED=1 at build time. The Dockerfile must use a
builder image with C toolchain (golang:1.25 not golang:1.25-alpine).

## Detailed Steps

### Step 1: S3 KV Connector

**File**: `src/asya-gateway/internal/stateproxys3/connector.go`

```go
package stateproxys3

import (
    "bytes"
    "context"
    "encoding/json"
    "fmt"
    "io"
    "log/slog"
    "strings"

    "github.com/aws/aws-sdk-go-v2/aws"
    "github.com/aws/aws-sdk-go-v2/service/s3"
    s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
)

// S3Client is the subset of s3.Client used by the connector. Enables mocking.
type S3Client interface {
    GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
    PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
    DeleteObject(ctx context.Context, params *s3.DeleteObjectInput, optFns ...func(*s3.Options)) (*s3.DeleteObjectOutput, error)
    HeadObject(ctx context.Context, params *s3.HeadObjectInput, optFns ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
    ListObjectsV2(ctx context.Context, params *s3.ListObjectsV2Input, optFns ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
}

// Connector implements state-proxy KV operations backed by S3.
type Connector struct {
    client S3Client
    bucket string
    prefix string // e.g. "mesh/msg" -- all keys stored under s3://{bucket}/{prefix}/{key}.json
    logger *slog.Logger
}

// NewConnector creates a new S3 connector.
// prefix is prepended to all keys: s3://{bucket}/{prefix}/{key}.json
func NewConnector(client S3Client, bucket, prefix string, logger *slog.Logger) *Connector {
    return &Connector{
        client: client,
        bucket: bucket,
        prefix: prefix,
        logger: logger,
    }
}
```

**KV operations** (same file):

```go
// fullKey returns the S3 object key for a logical key.
// e.g. key="abc123" -> "mesh/msg/abc123.json"
func (c *Connector) fullKey(key string) string {
    if c.prefix != "" {
        return c.prefix + "/" + key + ".json"
    }
    return key + ".json"
}

// Read fetches a JSON document from S3.
// Returns the raw JSON bytes. Returns ErrNotFound if the key does not exist.
func (c *Connector) Read(ctx context.Context, key string) (json.RawMessage, error) {
    out, err := c.client.GetObject(ctx, &s3.GetObjectInput{
        Bucket: aws.String(c.bucket),
        Key:    aws.String(c.fullKey(key)),
    })
    if err != nil {
        if isNotFound(err) {
            return nil, ErrNotFound
        }
        return nil, fmt.Errorf("s3 get %s: %w", key, err)
    }
    defer out.Body.Close()
    data, err := io.ReadAll(out.Body)
    if err != nil {
        return nil, fmt.Errorf("s3 read body %s: %w", key, err)
    }
    c.logger.Debug("read", "key", key, "size", len(data))
    return data, nil
}

// Write stores a JSON document to S3 (upsert semantics).
func (c *Connector) Write(ctx context.Context, key string, data json.RawMessage) error {
    _, err := c.client.PutObject(ctx, &s3.PutObjectInput{
        Bucket:      aws.String(c.bucket),
        Key:         aws.String(c.fullKey(key)),
        Body:        bytes.NewReader(data),
        ContentType: aws.String("application/json"),
    })
    if err != nil {
        return fmt.Errorf("s3 put %s: %w", key, err)
    }
    c.logger.Debug("write", "key", key, "size", len(data))
    return nil
}

// Exists checks whether a key exists in S3.
func (c *Connector) Exists(ctx context.Context, key string) (bool, error) {
    _, err := c.client.HeadObject(ctx, &s3.HeadObjectInput{
        Bucket: aws.String(c.bucket),
        Key:    aws.String(c.fullKey(key)),
    })
    if err != nil {
        if isNotFound(err) {
            return false, nil
        }
        return false, fmt.Errorf("s3 head %s: %w", key, err)
    }
    return true, nil
}

// Delete removes a key from S3. Returns ErrNotFound if the key does not exist.
func (c *Connector) Delete(ctx context.Context, key string) error {
    // S3 DeleteObject is idempotent -- check existence first to match interface contract.
    exists, err := c.Exists(ctx, key)
    if err != nil {
        return err
    }
    if !exists {
        return ErrNotFound
    }
    _, err = c.client.DeleteObject(ctx, &s3.DeleteObjectInput{
        Bucket: aws.String(c.bucket),
        Key:    aws.String(c.fullKey(key)),
    })
    if err != nil {
        return fmt.Errorf("s3 delete %s: %w", key, err)
    }
    c.logger.Debug("delete", "key", key)
    return nil
}

// List returns all keys under a prefix. Keys are returned without the
// .json suffix and without the connector prefix.
func (c *Connector) List(ctx context.Context, keyPrefix string) ([]string, error) {
    s3Prefix := c.fullKey(keyPrefix)
    // fullKey appends ".json", but for listing we want the prefix without it
    s3Prefix = strings.TrimSuffix(s3Prefix, ".json")

    var keys []string
    paginator := s3.NewListObjectsV2Paginator(c.client, &s3.ListObjectsV2Input{
        Bucket: aws.String(c.bucket),
        Prefix: aws.String(s3Prefix),
    })
    for paginator.HasMorePages() {
        page, err := paginator.NextPage(ctx)
        if err != nil {
            return nil, fmt.Errorf("s3 list prefix=%s: %w", keyPrefix, err)
        }
        for _, obj := range page.Contents {
            k := aws.ToString(obj.Key)
            k = strings.TrimPrefix(k, c.prefix+"/")
            k = strings.TrimSuffix(k, ".json")
            keys = append(keys, k)
        }
    }
    c.logger.Debug("list", "prefix", keyPrefix, "count", len(keys))
    return keys, nil
}
```

**Error helpers** (same file):

```go
var ErrNotFound = fmt.Errorf("key not found")

// isNotFound checks if an S3 error is a 404/NoSuchKey.
func isNotFound(err error) bool {
    var nsk *s3types.NoSuchKey
    if errors.As(err, &nsk) {
        return true
    }
    var nf *s3types.NotFound
    if errors.As(err, &nf) {
        return true
    }
    // aws-sdk-go-v2 may wrap HTTP 404 without typed error
    return strings.Contains(err.Error(), "StatusCode: 404") ||
        strings.Contains(err.Error(), "NoSuchKey")
}
```

### Step 2: DuckDB Query Engine

**File**: `src/asya-gateway/internal/stateproxys3/query.go`

```go
package stateproxys3

import (
    "context"
    "database/sql"
    "encoding/json"
    "fmt"
    "log/slog"
    "strings"
    "sync"

    _ "github.com/marcboeker/go-duckdb"
)

// QueryEngine executes Mango-style queries against S3 JSON objects using DuckDB.
type QueryEngine struct {
    mu     sync.Mutex // DuckDB embedded: serialize query access
    db     *sql.DB
    bucket string
    prefix string
    region string
    endpoint string // empty for real AWS, set for MinIO
    logger *slog.Logger
}

// NewQueryEngine creates a DuckDB-backed query engine.
func NewQueryEngine(bucket, prefix, region, endpoint string, logger *slog.Logger) (*QueryEngine, error) {
    db, err := sql.Open("duckdb", "")
    if err != nil {
        return nil, fmt.Errorf("open duckdb: %w", err)
    }

    // Install and load httpfs extension for S3 access
    for _, stmt := range []string{
        "INSTALL httpfs",
        "LOAD httpfs",
        fmt.Sprintf("SET s3_region='%s'", region),
    } {
        if _, err := db.Exec(stmt); err != nil {
            db.Close()
            return nil, fmt.Errorf("duckdb init %q: %w", stmt, err)
        }
    }

    // Configure MinIO / custom S3 endpoint if provided
    if endpoint != "" {
        for _, stmt := range []string{
            fmt.Sprintf("SET s3_endpoint='%s'", strings.TrimPrefix(strings.TrimPrefix(endpoint, "http://"), "https://")),
            "SET s3_url_style='path'",
            "SET s3_use_ssl=false",
        } {
            if _, err := db.Exec(stmt); err != nil {
                db.Close()
                return nil, fmt.Errorf("duckdb minio config %q: %w", stmt, err)
            }
        }
    }

    // Configure AWS credentials from environment (DuckDB reads
    // AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN)
    if _, err := db.Exec("SET s3_access_key_id=getenv('AWS_ACCESS_KEY_ID')"); err != nil {
        // Non-fatal: may use instance profile
        logger.Warn("duckdb: could not set s3_access_key_id from env", "err", err)
    }
    if _, err := db.Exec("SET s3_secret_access_key=getenv('AWS_SECRET_ACCESS_KEY')"); err != nil {
        logger.Warn("duckdb: could not set s3_secret_access_key from env", "err", err)
    }

    return &QueryEngine{
        db:       db,
        bucket:   bucket,
        prefix:   prefix,
        region:   region,
        endpoint: endpoint,
        logger:   logger,
    }, nil
}

// Close shuts down the DuckDB engine.
func (q *QueryEngine) Close() error {
    return q.db.Close()
}

// QueryParams is the Mango-style query request body.
type QueryParams struct {
    Prefix string                  `json:"prefix"`           // key prefix filter (e.g. "msg/")
    Filter map[string]any          `json:"filter,omitempty"` // Mango operators
    Sort   []string                `json:"sort,omitempty"`   // ["-created_at", "status"]
    Limit  int                     `json:"limit,omitempty"`  // max results
    Offset int                     `json:"offset,omitempty"` // pagination offset
}

// QueryResult is a single row from the query.
type QueryResult struct {
    Key   string          `json:"key"`
    Value json.RawMessage `json:"value"`
}

// Query executes a Mango-style filter against JSON objects in S3.
//
// Implementation:
//   1. CREATE OR REPLACE TABLE tmp AS SELECT * FROM read_json_auto('s3://...')
//   2. SELECT filename, * FROM tmp WHERE ... ORDER BY ... LIMIT ... OFFSET ...
//
// The S3 glob pattern is derived from prefix: s3://{bucket}/{prefix}/{queryPrefix}*.json
func (q *QueryEngine) Query(ctx context.Context, params QueryParams) ([]QueryResult, error) {
    q.mu.Lock()
    defer q.mu.Unlock()

    s3Path := fmt.Sprintf("s3://%s/%s/%s*.json", q.bucket, q.prefix, params.Prefix)
    q.logger.Debug("query scan", "s3_path", s3Path)

    // Step 1: Load JSON objects into ephemeral table
    loadSQL := fmt.Sprintf(
        `CREATE OR REPLACE TABLE tmp AS
         SELECT filename, * EXCLUDE (filename)
         FROM read_json_auto('%s', filename=true, union_by_name=true)`,
        s3Path,
    )
    if _, err := q.db.ExecContext(ctx, loadSQL); err != nil {
        return nil, fmt.Errorf("duckdb load from s3: %w", err)
    }

    // Step 2: Build filtered SELECT
    where, args, err := buildWhereClause(params.Filter)
    if err != nil {
        return nil, fmt.Errorf("build filter: %w", err)
    }

    orderBy := buildOrderBy(params.Sort)
    limitOffset := buildLimitOffset(params.Limit, params.Offset)

    selectSQL := fmt.Sprintf(
        "SELECT filename, to_json(struct_pack(* EXCLUDE (filename))) AS doc FROM tmp%s%s%s",
        where, orderBy, limitOffset,
    )

    rows, err := q.db.QueryContext(ctx, selectSQL, args...)
    if err != nil {
        return nil, fmt.Errorf("duckdb query: %w", err)
    }
    defer rows.Close()

    var results []QueryResult
    for rows.Next() {
        var filename, doc string
        if err := rows.Scan(&filename, &doc); err != nil {
            return nil, fmt.Errorf("duckdb scan: %w", err)
        }
        // Extract logical key from filename: s3://bucket/prefix/key.json -> key
        key := extractKey(filename, q.bucket, q.prefix)
        results = append(results, QueryResult{
            Key:   key,
            Value: json.RawMessage(doc),
        })
    }
    if err := rows.Err(); err != nil {
        return nil, fmt.Errorf("duckdb rows: %w", err)
    }

    q.logger.Debug("query result", "count", len(results), "filter", params.Filter)
    return results, nil
}
```

**Filter-to-SQL translator** (same file):

```go
// buildWhereClause translates Mango-style filter to DuckDB SQL WHERE.
//
// Supported operators:
//   $eq (implicit), $ne, $gt, $gte, $lt, $lte, $in, $nin, $exists
//
// Example filter:
//   {"status": "running", "progress": {"$gt": 50}}
// Produces:
//   " WHERE status = $1 AND progress > $2" with args ["running", 50]
func buildWhereClause(filter map[string]any) (string, []any, error) {
    if len(filter) == 0 {
        return "", nil, nil
    }

    var conditions []string
    var args []any
    idx := 1

    for field, value := range filter {
        switch v := value.(type) {
        case map[string]any:
            // Operator expression: {"$gt": 50}
            for op, operand := range v {
                sqlOp, err := mangoOpToSQL(op)
                if err != nil {
                    return "", nil, err
                }
                if op == "$in" || op == "$nin" {
                    // $in / $nin use ANY() with array parameter
                    conditions = append(conditions, fmt.Sprintf("%s %s ($%d)", field, sqlOp, idx))
                } else if op == "$exists" {
                    if operand == true {
                        conditions = append(conditions, fmt.Sprintf("%s IS NOT NULL", field))
                    } else {
                        conditions = append(conditions, fmt.Sprintf("%s IS NULL", field))
                    }
                    continue // no parameter for $exists
                } else {
                    conditions = append(conditions, fmt.Sprintf("%s %s $%d", field, sqlOp, idx))
                }
                args = append(args, operand)
                idx++
            }
        default:
            // Implicit $eq: {"status": "running"}
            conditions = append(conditions, fmt.Sprintf("%s = $%d", field, idx))
            args = append(args, value)
            idx++
        }
    }

    return " WHERE " + strings.Join(conditions, " AND "), args, nil
}

// mangoOpToSQL maps Mango operators to SQL operators.
func mangoOpToSQL(op string) (string, error) {
    switch op {
    case "$eq":
        return "=", nil
    case "$ne":
        return "!=", nil
    case "$gt":
        return ">", nil
    case "$gte":
        return ">=", nil
    case "$lt":
        return "<", nil
    case "$lte":
        return "<=", nil
    case "$in":
        return "IN", nil
    case "$nin":
        return "NOT IN", nil
    case "$exists":
        return "", nil // handled specially
    default:
        return "", fmt.Errorf("unsupported operator: %s", op)
    }
}

// buildOrderBy translates sort specs to SQL ORDER BY.
// "-field" means DESC, "field" means ASC.
func buildOrderBy(sort []string) string {
    if len(sort) == 0 {
        return ""
    }
    var parts []string
    for _, s := range sort {
        if strings.HasPrefix(s, "-") {
            parts = append(parts, s[1:]+" DESC")
        } else {
            parts = append(parts, s+" ASC")
        }
    }
    return " ORDER BY " + strings.Join(parts, ", ")
}

// buildLimitOffset produces the LIMIT/OFFSET SQL clause.
func buildLimitOffset(limit, offset int) string {
    var sb strings.Builder
    if limit > 0 {
        fmt.Fprintf(&sb, " LIMIT %d", limit)
    }
    if offset > 0 {
        fmt.Fprintf(&sb, " OFFSET %d", offset)
    }
    return sb.String()
}

// extractKey extracts the logical key from an S3 filename path.
// e.g. "s3://bucket/mesh/msg/abc123.json" -> "abc123"
func extractKey(filename, bucket, prefix string) string {
    // Remove s3://bucket/prefix/ prefix and .json suffix
    full := fmt.Sprintf("s3://%s/%s/", bucket, prefix)
    key := strings.TrimPrefix(filename, full)
    key = strings.TrimSuffix(key, ".json")
    return key
}
```

### Step 3: HTTP Server

**File**: `src/asya-gateway/internal/stateproxys3/server.go`

The HTTP server exposes the state-proxy interface over Unix socket. Same
contract as the Python state-proxy server in
`src/asya-state-proxy/asya_state_proxy/server.py`.

```go
package stateproxys3

import (
    "context"
    "encoding/json"
    "fmt"
    "io"
    "log/slog"
    "net"
    "net/http"
    "os"
    "strings"
)

// Server is the HTTP server that exposes the state-proxy interface.
type Server struct {
    connector *Connector
    query     *QueryEngine
    logger    *slog.Logger
    listener  net.Listener
    server    *http.Server
}

// NewServer creates a new state-proxy HTTP server.
func NewServer(connector *Connector, query *QueryEngine, logger *slog.Logger) *Server {
    s := &Server{
        connector: connector,
        query:     query,
        logger:    logger,
    }
    mux := http.NewServeMux()
    mux.HandleFunc("GET /healthz", s.handleHealthz)
    mux.HandleFunc("GET /keys/", s.handleGetKey)
    mux.HandleFunc("GET /keys", s.handleListKeys)
    mux.HandleFunc("PUT /keys/", s.handlePutKey)
    mux.HandleFunc("HEAD /keys/", s.handleHeadKey)
    mux.HandleFunc("DELETE /keys/", s.handleDeleteKey)
    mux.HandleFunc("POST /query", s.handleQuery)
    s.server = &http.Server{Handler: mux}
    return s
}

// ListenAndServe starts the server on a Unix socket.
func (s *Server) ListenAndServe(socketPath string) error {
    if err := os.Remove(socketPath); err != nil && !os.IsNotExist(err) {
        return fmt.Errorf("remove stale socket: %w", err)
    }
    ln, err := net.Listen("unix", socketPath)
    if err != nil {
        return fmt.Errorf("listen %s: %w", socketPath, err)
    }
    s.listener = ln
    s.logger.Info("listening", "socket", socketPath)
    return s.server.Serve(ln)
}

// Shutdown gracefully stops the server.
func (s *Server) Shutdown(ctx context.Context) error {
    return s.server.Shutdown(ctx)
}
```

**HTTP handlers** (same file):

```go
func (s *Server) handleHealthz(w http.ResponseWriter, r *http.Request) {
    writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
}

func (s *Server) handleGetKey(w http.ResponseWriter, r *http.Request) {
    key := strings.TrimPrefix(r.URL.Path, "/keys/")
    if key == "" {
        writeJSONError(w, http.StatusBadRequest, "key required")
        return
    }
    data, err := s.connector.Read(r.Context(), key)
    if err != nil {
        s.handleError(w, err)
        return
    }
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    w.Write(data)
}

func (s *Server) handleListKeys(w http.ResponseWriter, r *http.Request) {
    prefix := r.URL.Query().Get("prefix")
    keys, err := s.connector.List(r.Context(), prefix)
    if err != nil {
        s.handleError(w, err)
        return
    }
    writeJSON(w, http.StatusOK, map[string]any{"keys": keys})
}

func (s *Server) handlePutKey(w http.ResponseWriter, r *http.Request) {
    key := strings.TrimPrefix(r.URL.Path, "/keys/")
    if key == "" {
        writeJSONError(w, http.StatusBadRequest, "key required")
        return
    }
    body, err := io.ReadAll(r.Body)
    if err != nil {
        writeJSONError(w, http.StatusBadRequest, "read body: "+err.Error())
        return
    }
    if err := s.connector.Write(r.Context(), key, body); err != nil {
        s.handleError(w, err)
        return
    }
    w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleHeadKey(w http.ResponseWriter, r *http.Request) {
    key := strings.TrimPrefix(r.URL.Path, "/keys/")
    exists, err := s.connector.Exists(r.Context(), key)
    if err != nil {
        s.handleError(w, err)
        return
    }
    if !exists {
        w.WriteHeader(http.StatusNotFound)
        return
    }
    w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleDeleteKey(w http.ResponseWriter, r *http.Request) {
    key := strings.TrimPrefix(r.URL.Path, "/keys/")
    if key == "" {
        writeJSONError(w, http.StatusBadRequest, "key required")
        return
    }
    if err := s.connector.Delete(r.Context(), key); err != nil {
        s.handleError(w, err)
        return
    }
    w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleQuery(w http.ResponseWriter, r *http.Request) {
    var params QueryParams
    if err := json.NewDecoder(r.Body).Decode(&params); err != nil {
        writeJSONError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
        return
    }
    results, err := s.query.Query(r.Context(), params)
    if err != nil {
        s.handleError(w, err)
        return
    }
    writeJSON(w, http.StatusOK, map[string]any{"results": results, "total": len(results)})
}

func (s *Server) handleError(w http.ResponseWriter, err error) {
    if err == ErrNotFound {
        writeJSONError(w, http.StatusNotFound, "key not found")
        return
    }
    s.logger.Error("handler error", "err", err)
    writeJSONError(w, http.StatusInternalServerError, err.Error())
}

func writeJSON(w http.ResponseWriter, status int, data any) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(status)
    json.NewEncoder(w).Encode(data)
}

func writeJSONError(w http.ResponseWriter, status int, message string) {
    writeJSON(w, status, map[string]string{"error": message})
}
```

### Step 4: Binary Entrypoint

**File**: `src/asya-gateway/cmd/state-proxy-s3/main.go`

```go
package main

import (
    "context"
    "log/slog"
    "os"
    "os/signal"
    "syscall"

    "github.com/aws/aws-sdk-go-v2/config"
    "github.com/aws/aws-sdk-go-v2/service/s3"

    "github.com/deliveryhero/asya/asya-gateway/internal/stateproxys3"
)

func main() {
    logger := slog.New(slog.NewJSONHandler(os.Stderr, nil))

    socketPath := os.Getenv("CONNECTOR_SOCKET")
    if socketPath == "" {
        logger.Error("CONNECTOR_SOCKET is required")
        os.Exit(1)
    }
    bucket := os.Getenv("STATE_BUCKET")
    if bucket == "" {
        logger.Error("STATE_BUCKET is required")
        os.Exit(1)
    }
    prefix := os.Getenv("STATE_PREFIX") // e.g. "mesh/msg"
    if prefix == "" {
        logger.Error("STATE_PREFIX is required")
        os.Exit(1)
    }
    region := os.Getenv("AWS_REGION")
    if region == "" {
        region = "us-east-1"
    }
    endpoint := os.Getenv("AWS_ENDPOINT_URL") // for MinIO

    ctx := context.Background()

    // Build S3 client
    cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
    if err != nil {
        logger.Error("load aws config", "err", err)
        os.Exit(1)
    }
    var s3Opts []func(*s3.Options)
    if endpoint != "" {
        s3Opts = append(s3Opts, func(o *s3.Options) {
            o.BaseEndpoint = &endpoint
            o.UsePathStyle = true
        })
    }
    s3Client := s3.NewFromConfig(cfg, s3Opts...)

    // Create connector and query engine
    conn := stateproxys3.NewConnector(s3Client, bucket, prefix, logger)
    qe, err := stateproxys3.NewQueryEngine(bucket, prefix, region, endpoint, logger)
    if err != nil {
        logger.Error("init query engine", "err", err)
        os.Exit(1)
    }
    defer qe.Close()

    // Start server
    srv := stateproxys3.NewServer(conn, qe, logger)

    sigCh := make(chan os.Signal, 1)
    signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
    go func() {
        <-sigCh
        logger.Info("shutting down")
        srv.Shutdown(context.Background())
    }()

    if err := srv.ListenAndServe(socketPath); err != nil {
        logger.Error("server error", "err", err)
        os.Exit(1)
    }
}
```

### Step 5: Dockerfile

**File**: `src/asya-gateway/Dockerfile.state-proxy-s3`

```dockerfile
FROM golang:1.25 AS builder
# CGO required for go-duckdb
ENV CGO_ENABLED=1

WORKDIR /build

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    go build -o state-proxy-s3 ./cmd/state-proxy-s3

# Runtime image
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /build/state-proxy-s3 .

ENTRYPOINT ["./state-proxy-s3"]
```

Key difference from main gateway Dockerfile: uses `golang:1.25` (not alpine)
and `debian:bookworm-slim` (not alpine) because go-duckdb requires glibc and
CGO_ENABLED=1.

### Step 6: Unit Tests

**File**: `src/asya-gateway/internal/stateproxys3/connector_test.go`

Test the S3 connector with a mock S3Client interface. No real S3 needed.

```go
package stateproxys3

import (
    "context"
    "testing"

    "github.com/stretchr/testify/assert"
    "github.com/stretchr/testify/require"
)

// mockS3Client implements S3Client for unit tests.
// Each method records calls and returns preconfigured responses.

func TestRead_Success(t *testing.T) {
    // mock GetObject returns JSON body
    // assert returned data matches
}

func TestRead_NotFound(t *testing.T) {
    // mock GetObject returns NoSuchKey error
    // assert ErrNotFound returned
}

func TestWrite_Success(t *testing.T) {
    // mock PutObject succeeds
    // assert no error, verify PutObject called with correct key
}

func TestDelete_NotFound(t *testing.T) {
    // mock HeadObject returns 404
    // assert ErrNotFound
}

func TestDelete_Success(t *testing.T) {
    // mock HeadObject succeeds, DeleteObject succeeds
    // assert no error
}

func TestList_Pagination(t *testing.T) {
    // mock ListObjectsV2 returns two pages
    // assert all keys returned, prefixes stripped, .json removed
}

func TestFullKey_WithPrefix(t *testing.T) {
    c := NewConnector(nil, "bucket", "mesh/msg", nil)
    assert.Equal(t, "mesh/msg/abc123.json", c.fullKey("abc123"))
}

func TestFullKey_NoPrefix(t *testing.T) {
    c := NewConnector(nil, "bucket", "", nil)
    assert.Equal(t, "abc123.json", c.fullKey("abc123"))
}
```

**File**: `src/asya-gateway/internal/stateproxys3/query_test.go`

Test DuckDB query engine with a temporary in-memory DuckDB (no S3 needed).
Pre-populate the `tmp` table directly for unit tests.

```go
package stateproxys3

import (
    "testing"

    "github.com/stretchr/testify/assert"
)

func TestBuildWhereClause_Empty(t *testing.T) {
    where, args, err := buildWhereClause(nil)
    assert.NoError(t, err)
    assert.Equal(t, "", where)
    assert.Nil(t, args)
}

func TestBuildWhereClause_ImplicitEq(t *testing.T) {
    where, args, err := buildWhereClause(map[string]any{"status": "running"})
    assert.NoError(t, err)
    assert.Contains(t, where, "status = $1")
    assert.Equal(t, []any{"running"}, args)
}

func TestBuildWhereClause_Operators(t *testing.T) {
    filter := map[string]any{
        "progress": map[string]any{"$gt": 50},
    }
    where, args, err := buildWhereClause(filter)
    assert.NoError(t, err)
    assert.Contains(t, where, "progress > $1")
    assert.Equal(t, []any{50}, args)
}

func TestBuildWhereClause_Exists(t *testing.T) {
    filter := map[string]any{
        "error": map[string]any{"$exists": false},
    }
    where, _, err := buildWhereClause(filter)
    assert.NoError(t, err)
    assert.Contains(t, where, "error IS NULL")
}

func TestBuildWhereClause_UnsupportedOp(t *testing.T) {
    filter := map[string]any{
        "x": map[string]any{"$regex": "abc"},
    }
    _, _, err := buildWhereClause(filter)
    assert.Error(t, err)
    assert.Contains(t, err.Error(), "unsupported operator")
}

func TestBuildOrderBy(t *testing.T) {
    assert.Equal(t, "", buildOrderBy(nil))
    assert.Equal(t, " ORDER BY created_at DESC", buildOrderBy([]string{"-created_at"}))
    assert.Equal(t, " ORDER BY status ASC, created_at DESC",
        buildOrderBy([]string{"status", "-created_at"}))
}

func TestBuildLimitOffset(t *testing.T) {
    assert.Equal(t, "", buildLimitOffset(0, 0))
    assert.Equal(t, " LIMIT 10", buildLimitOffset(10, 0))
    assert.Equal(t, " LIMIT 10 OFFSET 5", buildLimitOffset(10, 5))
}

func TestExtractKey(t *testing.T) {
    key := extractKey("s3://mybucket/mesh/msg/abc123.json", "mybucket", "mesh/msg")
    assert.Equal(t, "abc123", key)
}
```

### Step 7: Component Tests (Docker Compose + MinIO)

**File**: `testing/component/state-proxy-s3/docker-compose.yml`

```yaml
x-logging: &default-logging
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "2"

services:
  minio:
    image: minio/minio:latest
    logging: *default-logging
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    tmpfs:
      - /data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 15s
      retries: 10

  storage-setup:
    image: minio/mc:latest
    logging: *default-logging
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set myminio http://minio:9000 minioadmin minioadmin;
      mc mb --ignore-existing myminio/asya-state;
      echo 'Bucket created';
      "

  state-proxy-s3:
    build:
      context: ../../../src/asya-gateway
      dockerfile: Dockerfile.state-proxy-s3
    logging: *default-logging
    environment:
      CONNECTOR_SOCKET: /var/run/asya/state/meta.sock
      STATE_BUCKET: asya-state
      STATE_PREFIX: mesh/msg
      AWS_REGION: us-east-1
      AWS_ENDPOINT_URL: http://minio:9000
      AWS_ACCESS_KEY_ID: minioadmin
      AWS_SECRET_ACCESS_KEY: minioadmin
    volumes:
      - state-sockets:/var/run/asya/state
    depends_on:
      storage-setup:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD", "test", "-S", "/var/run/asya/state/meta.sock"]
      interval: 1s
      timeout: 1s
      retries: 30

  tester:
    build:
      context: ../../../src/asya-testing
      dockerfile: Dockerfile
    logging: *default-logging
    environment:
      STATE_PROXY_SOCKET: /var/run/asya/state/meta.sock
      COVERAGE_FILE: .coverage/cov.db
    volumes:
      - ${COVERAGE_DIR}:/app/.coverage:rw
      - state-sockets:/var/run/asya/state
      - ./tests:/app/tests
    depends_on:
      state-proxy-s3:
        condition: service_healthy
    working_dir: /app
    entrypoint: /bin/bash
    command:
      - -c
      - |
        set -ex
        pytest tests/ ${PYTEST_OPTS}

volumes:
  state-sockets:
```

**File**: `testing/component/state-proxy-s3/tests/conftest.py`

```python
import http.client
import json
import os
import socket

import pytest


@pytest.fixture
def proxy():
    """HTTP client connected to state-proxy-s3 via Unix socket."""
    sock_path = os.environ["STATE_PROXY_SOCKET"]

    class UnixClient:
        def request(self, method, path, body=None):
            conn = http.client.HTTPConnection("localhost")
            conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.sock.connect(sock_path)
            headers = {}
            if body is not None:
                body = json.dumps(body).encode() if isinstance(body, dict) else body
                headers["Content-Length"] = str(len(body))
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            return resp

    return UnixClient()
```

**File**: `testing/component/state-proxy-s3/tests/test_kv_operations.py`

```python
import json


def test_write_and_read(proxy):
    """PUT a JSON document and GET it back."""
    doc = {"status": "running", "actor": "train-model", "progress": 42.0}
    resp = proxy.request("PUT", "/keys/test-msg-001", doc)
    assert resp.status == 204

    resp = proxy.request("GET", "/keys/test-msg-001")
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data["status"] == "running"
    assert data["progress"] == 42.0


def test_read_not_found(proxy):
    """GET a non-existent key returns 404."""
    resp = proxy.request("GET", "/keys/does-not-exist")
    assert resp.status == 404


def test_head_exists(proxy):
    """HEAD returns 204 for existing key, 404 for missing."""
    doc = {"status": "pending"}
    proxy.request("PUT", "/keys/test-head-001", doc)

    resp = proxy.request("HEAD", "/keys/test-head-001")
    assert resp.status == 204

    resp = proxy.request("HEAD", "/keys/test-head-missing")
    assert resp.status == 404


def test_delete(proxy):
    """DELETE removes the key; subsequent GET returns 404."""
    proxy.request("PUT", "/keys/test-del-001", {"status": "failed"})
    resp = proxy.request("DELETE", "/keys/test-del-001")
    assert resp.status == 204

    resp = proxy.request("GET", "/keys/test-del-001")
    assert resp.status == 404


def test_delete_not_found(proxy):
    """DELETE a non-existent key returns 404."""
    resp = proxy.request("DELETE", "/keys/not-here")
    assert resp.status == 404


def test_list_keys(proxy):
    """List keys by prefix."""
    proxy.request("PUT", "/keys/list-a", {"x": 1})
    proxy.request("PUT", "/keys/list-b", {"x": 2})
    proxy.request("PUT", "/keys/other-c", {"x": 3})

    resp = proxy.request("GET", "/keys?prefix=list-")
    assert resp.status == 200
    data = json.loads(resp.read())
    keys = data["keys"]
    assert "list-a" in keys
    assert "list-b" in keys
    assert "other-c" not in keys


def test_write_overwrite(proxy):
    """PUT overwrites existing key (upsert)."""
    proxy.request("PUT", "/keys/test-overwrite", {"v": 1})
    proxy.request("PUT", "/keys/test-overwrite", {"v": 2})

    resp = proxy.request("GET", "/keys/test-overwrite")
    data = json.loads(resp.read())
    assert data["v"] == 2


def test_healthz(proxy):
    """GET /healthz returns 200."""
    resp = proxy.request("GET", "/healthz")
    assert resp.status == 200
```

**File**: `testing/component/state-proxy-s3/tests/test_query.py`

```python
import json


def _seed(proxy, messages):
    """Write a batch of message documents."""
    for key, doc in messages.items():
        resp = proxy.request("PUT", f"/keys/{key}", doc)
        assert resp.status == 204


def test_query_filter_eq(proxy):
    """Query with implicit $eq filter."""
    _seed(proxy, {
        "q-msg-1": {"status": "running", "actor": "train"},
        "q-msg-2": {"status": "succeeded", "actor": "eval"},
        "q-msg-3": {"status": "running", "actor": "deploy"},
    })
    resp = proxy.request("POST", "/query", {
        "prefix": "q-msg-",
        "filter": {"status": "running"},
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    keys = [r["key"] for r in data["results"]]
    assert "q-msg-1" in keys
    assert "q-msg-3" in keys
    assert "q-msg-2" not in keys


def test_query_filter_gt(proxy):
    """Query with $gt operator."""
    _seed(proxy, {
        "qgt-1": {"status": "running", "progress": 30},
        "qgt-2": {"status": "running", "progress": 70},
        "qgt-3": {"status": "running", "progress": 90},
    })
    resp = proxy.request("POST", "/query", {
        "prefix": "qgt-",
        "filter": {"progress": {"$gt": 50}},
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    keys = [r["key"] for r in data["results"]]
    assert "qgt-2" in keys
    assert "qgt-3" in keys
    assert "qgt-1" not in keys


def test_query_sort_and_limit(proxy):
    """Query with sort and limit."""
    _seed(proxy, {
        "qsl-1": {"status": "running", "progress": 10},
        "qsl-2": {"status": "running", "progress": 50},
        "qsl-3": {"status": "running", "progress": 90},
    })
    resp = proxy.request("POST", "/query", {
        "prefix": "qsl-",
        "sort": ["-progress"],
        "limit": 2,
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    assert len(data["results"]) == 2
    # First result should be highest progress
    assert data["results"][0]["value"]["progress"] == 90


def test_query_empty_result(proxy):
    """Query with no matches returns empty results."""
    resp = proxy.request("POST", "/query", {
        "prefix": "nonexistent-prefix-",
        "filter": {"status": "running"},
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data["results"] == [] or data["results"] is None


def test_query_no_filter(proxy):
    """Query with prefix only, no filter, returns all matching keys."""
    _seed(proxy, {
        "qnf-1": {"status": "running"},
        "qnf-2": {"status": "succeeded"},
    })
    resp = proxy.request("POST", "/query", {
        "prefix": "qnf-",
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    assert len(data["results"]) >= 2
```

**File**: `testing/component/state-proxy-s3/Makefile`

```makefile
.PHONY: test clean down
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/component/state-proxy-s3)
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

DOCKER_COMPOSE ?= docker compose
export DOCKER_BUILDKIT := 1
export BUILDKIT_PROGRESS ?= plain
export COMPOSE_ANSI ?= never
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester --build
export PYTEST_OPTS ?= -v

COMPOSE_PROJECT := comp-state-proxy-s3

test: clean ## Run state-proxy-s3 component tests
	@echo "[.] Running state-proxy-s3 component tests"
	$(DOCKER_COMPOSE) -f docker-compose.yml -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down
	@echo "[+] Success: state-proxy-s3 component tests passed!"

down: ## Stop and remove all containers and volumes
	$(DOCKER_COMPOSE) -f docker-compose.yml -p $(COMPOSE_PROJECT) down -v --remove-orphans || true

clean: down ## Clean up
	rm -rf $(COVERAGE_DIR)
	mkdir -p $(COVERAGE_DIR)
```

### Step 8: Wire into Build System

**File**: `src/asya-gateway/Makefile` (add target)

Add a new build target alongside the existing gateway build:

```makefile
build-state-proxy-s3:  ## Build state-proxy-s3 binary
	CGO_ENABLED=1 go build -o bin/state-proxy-s3 ./cmd/state-proxy-s3
```

**File**: root `Makefile` (add component test target)

Add to the component test section:

```makefile
test-component-state-proxy-s3:  ## Run state-proxy-s3 component tests
	$(MAKE) -C testing/component/state-proxy-s3 test
```

## Environment Variables

The state-proxy-s3 binary reads these environment variables. All required
variables must be set explicitly (no defaults in code per project policy).

| Variable | Required | Description |
|---|---|---|
| `CONNECTOR_SOCKET` | Yes | Unix socket path (e.g. `/var/run/asya/state/meta.sock`) |
| `STATE_BUCKET` | Yes | S3 bucket name |
| `STATE_PREFIX` | Yes | Key prefix in bucket (e.g. `mesh/msg`) |
| `AWS_REGION` | No | AWS region (default: `us-east-1` -- only default allowed since SDK needs it) |
| `AWS_ENDPOINT_URL` | No | Custom endpoint for MinIO/LocalStack |
| `AWS_ACCESS_KEY_ID` | No | AWS credentials (SDK also reads instance profile) |
| `AWS_SECRET_ACCESS_KEY` | No | AWS credentials |

## S3 Key Layout

```
s3://{bucket}/{prefix}/{key}.json

Example:
s3://asya-state/mesh/msg/abc123.json
s3://asya-state/mesh/msg/def456.json
```

Each object is a JSON document containing the message metadata (same schema
as the PG connector's JSONB value):

```json
{
  "status": "running",
  "actor": "train-model",
  "progress": 50.0,
  "context_id": "session-42",
  "trace_id": "abc",
  "parent_id": "parent-456",
  "deadline_at": "2026-04-16T12:00:00Z",
  "error": null,
  "message": "Step 500/1000"
}
```

## DuckDB Query Flow

```
POST /query {"prefix":"msg/", "filter":{"status":"running"}, "sort":["-progress"], "limit":10}
  |
  v
1. Build S3 glob: s3://asya-state/mesh/msg/msg/*.json
   (DuckDB httpfs reads directly from S3 -- no download to disk)
  |
  v
2. CREATE OR REPLACE TABLE tmp AS
   SELECT filename, * EXCLUDE (filename)
   FROM read_json_auto('s3://asya-state/mesh/msg/msg/*.json',
                        filename=true, union_by_name=true)
  |
  v
3. SELECT filename, to_json(struct_pack(* EXCLUDE (filename))) AS doc
   FROM tmp
   WHERE status = $1
   ORDER BY progress DESC
   LIMIT 10
  |
  v
4. Extract logical key from filename, return [{key, value}, ...]
```

Performance characteristics:
- <1K messages: <100ms (including S3 list + read)
- 1K-10K messages: 100ms-1s (DuckDB scans are fast, S3 I/O dominates)
- >10K messages: consider PG connector instead

## Interface Compatibility with PR1 PG Connector

Both connectors expose the same HTTP interface:

| Endpoint | PG Connector | S3 Connector |
|---|---|---|
| `GET /keys/{key}` | SELECT from kv table | S3 GetObject |
| `PUT /keys/{key}` | INSERT ... ON CONFLICT UPDATE | S3 PutObject |
| `HEAD /keys/{key}` | SELECT 1 from kv | S3 HeadObject |
| `DELETE /keys/{key}` | DELETE from kv | S3 DeleteObject |
| `GET /keys/?prefix=X` | SELECT key LIKE X% | S3 ListObjectsV2 |
| `POST /query` | Mango-to-SQL on PG | Mango-to-SQL on DuckDB |
| `GET /healthz` | 200 OK | 200 OK |

mesh-api does not know which connector it talks to. Helm values choose:

```yaml
# values.yaml
stateProxy:
  connector: s3    # or "pg"
```

## Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| CGO dependency (go-duckdb) | Medium | Separate Dockerfile, debian-slim runtime, pin DuckDB version |
| DuckDB S3 auth config | Low | Pass AWS creds via env vars, same as connector |
| DuckDB httpfs install on first run | Low | Pre-install in Dockerfile via `duckdb -c "INSTALL httpfs"` or first-run init |
| Query on empty prefix (no S3 objects) | Low | DuckDB read_json_auto returns empty -- handle gracefully |
| >10K objects slow query | Low | Document as known limitation; recommend PG for high-volume |
| S3 eventual consistency | Low | S3 is strongly consistent for GET-after-PUT since 2020 |
| Concurrent query access | Low | sync.Mutex on QueryEngine serializes DuckDB access |

## Implementation Order

1. `internal/stateproxys3/connector.go` + `connector_test.go` -- S3 KV ops with mock
2. `internal/stateproxys3/query.go` + `query_test.go` -- DuckDB query engine
3. `internal/stateproxys3/server.go` + `server_test.go` -- HTTP handler
4. `cmd/state-proxy-s3/main.go` -- binary entrypoint
5. `Dockerfile.state-proxy-s3` -- container image
6. `go.mod` updates -- add aws-sdk-go-v2/service/s3 + go-duckdb
7. `testing/component/state-proxy-s3/` -- component tests with MinIO
8. Root Makefile + gateway Makefile targets

## Estimated LOC

| File | LOC |
|---|---|
| `connector.go` | ~200 |
| `query.go` | ~150 |
| `server.go` | ~80 |
| `main.go` | ~60 |
| **Total production** | **~490** |
| `connector_test.go` | ~180 |
| `query_test.go` | ~120 |
| `server_test.go` | ~60 |
| Component tests (Python) | ~190 |
| Dockerfile + Makefiles + compose | ~120 |
| **Total with tests** | **~1,160** |

## PR Checklist

- [ ] `make build` passes (CGO_ENABLED=1 for state-proxy-s3 target)
- [ ] `make test-unit` passes (Go unit tests with mocked S3 + DuckDB)
- [ ] `make test-component-state-proxy-s3` passes (MinIO + Docker Compose)
- [ ] `make lint` passes
- [ ] No env var defaults in code (except AWS_REGION which SDK requires)
- [ ] No `time.Sleep` in production code
- [ ] No emojis in code files
- [ ] Interface matches PG connector from PR1 (same HTTP endpoints, same response shapes)
