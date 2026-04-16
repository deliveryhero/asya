# PR1: PG State-Proxy + Mesh-API Core -- Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** Build the PG state-proxy connector (Go, HTTP on Unix socket) and asya-mesh-api core binary (/api/v1/mesh/) as the foundation for the gateway rearchitecture.

**Architecture:** The mesh-api binary exposes two ports -- 8080 (external: create/get/list/subscribe/cancel) and 8081 (internal: sidecar event publishing and heartbeat). It talks to PostgreSQL exclusively through a PG state-proxy connector via HTTP over Unix socket. The connector implements the standard state-proxy KV interface plus a /query endpoint with Mango-style filter DSL. In-process Go channel pub/sub connects POST /events (sidecar) to GET /events (SSE client).

**Tech Stack:** Go 1.25, pgx/v5 (connector only), net/http stdlib, chi router (or stdlib ServeMux), encoding/json, google/uuid, stretchr/testify

---

### Task 1: Shared Types (pkg/types/)

**Files:**
- Create: `src/asya-gateway/pkg/types/message.go`
- Test: `src/asya-gateway/pkg/types/message_test.go`

- [ ] **Step 1: Define Message type**
  ```go
  // src/asya-gateway/pkg/types/message.go
  package types

  import (
      "encoding/json"
      "time"
  )

  // MessageStatus represents the lifecycle status of a mesh message.
  type MessageStatus string

  const (
      MessageStatusPending   MessageStatus = "pending"
      MessageStatusRunning   MessageStatus = "running"
      MessageStatusPaused    MessageStatus = "paused"
      MessageStatusSucceeded MessageStatus = "succeeded"
      MessageStatusFailed    MessageStatus = "failed"
      MessageStatusCanceled  MessageStatus = "canceled"
  )

  // statusOrder defines monotonic ordering for status transitions.
  // Higher values can overwrite lower ones, never the reverse.
  var statusOrder = map[MessageStatus]int{
      MessageStatusPending:   0,
      MessageStatusRunning:   1,
      MessageStatusPaused:    2,
      MessageStatusSucceeded: 3,
      MessageStatusFailed:    3,
      MessageStatusCanceled:  3,
  }

  // StatusAdvances returns true if newStatus can overwrite currentStatus
  // according to monotonic ordering rules.
  func StatusAdvances(current, new MessageStatus) bool {
      return statusOrder[new] > statusOrder[current]
  }

  // IsTerminal returns true if the status is a terminal state.
  func (s MessageStatus) IsTerminal() bool {
      return statusOrder[s] == 3
  }

  // Message is the mesh-api's view of an envelope in flight.
  // Stored as JSONB in the state-proxy KV table.
  type Message struct {
      ID        string          `json:"id"`
      Status    MessageStatus   `json:"status"`
      Data      json.RawMessage `json:"data"`
      CreatedAt time.Time       `json:"created_at"`
      UpdatedAt time.Time       `json:"updated_at"`
  }

  // MessageData holds the JSONB fields stored inside Message.Data.
  type MessageData struct {
      Actor      string   `json:"actor"`
      Progress   float64  `json:"progress,omitempty"`
      Message    string   `json:"message,omitempty"`
      Error      string   `json:"error,omitempty"`
      ContextID  string   `json:"context_id,omitempty"`
      TraceID    string   `json:"trace_id,omitempty"`
      ParentID   string   `json:"parent_id,omitempty"`
      DeadlineAt string   `json:"deadline_at,omitempty"`
      Payload    any      `json:"payload,omitempty"`
      Headers    any      `json:"headers,omitempty"`
      Result     any      `json:"result,omitempty"`
      RouteNext  []string `json:"route_next,omitempty"`
  }

  // Event is a single event published by a sidecar or consumed by an SSE client.
  type Event struct {
      Type   string          `json:"type"`   // "status" or "fly"
      Status MessageStatus   `json:"status,omitempty"`
      Data   json.RawMessage `json:"data,omitempty"`
  }

  // ListParams defines filtering and pagination for message listing.
  type ListParams struct {
      Prefix  string         `json:"prefix,omitempty"`
      Filters map[string]any `json:"filter,omitempty"`
      Sort    []string       `json:"sort,omitempty"`
      Limit   int            `json:"limit,omitempty"`
      Offset  int            `json:"offset,omitempty"`
  }
  ```

- [ ] **Step 2: Write unit tests for status ordering**
  ```go
  // src/asya-gateway/pkg/types/message_test.go
  package types

  import "testing"

  func TestStatusAdvances(t *testing.T) {
      // Forward transitions allowed
      assert StatusAdvances(MessageStatusPending, MessageStatusRunning) == true
      assert StatusAdvances(MessageStatusRunning, MessageStatusSucceeded) == true
      assert StatusAdvances(MessageStatusRunning, MessageStatusFailed) == true
      assert StatusAdvances(MessageStatusPaused, MessageStatusSucceeded) == true

      // Backward transitions rejected
      assert StatusAdvances(MessageStatusRunning, MessageStatusPending) == false
      assert StatusAdvances(MessageStatusSucceeded, MessageStatusRunning) == false

      // Same-level transitions rejected
      assert StatusAdvances(MessageStatusSucceeded, MessageStatusFailed) == false
      assert StatusAdvances(MessageStatusRunning, MessageStatusRunning) == false
  }

  func TestIsTerminal(t *testing.T) {
      assert MessageStatusSucceeded.IsTerminal() == true
      assert MessageStatusFailed.IsTerminal() == true
      assert MessageStatusCanceled.IsTerminal() == true
      assert MessageStatusRunning.IsTerminal() == false
      assert MessageStatusPending.IsTerminal() == false
      assert MessageStatusPaused.IsTerminal() == false
  }
  ```
  Run: `cd src/asya-gateway && go test ./pkg/types/ -run TestStatus -v`

---

### Task 2: PG State-Proxy Connector -- KV Operations

**Files:**
- Create: `src/asya-gateway/cmd/state-proxy-pg/main.go`
- Create: `src/asya-gateway/internal/stateproxypg/connector.go`
- Create: `src/asya-gateway/internal/stateproxypg/schema.go`
- Test: `src/asya-gateway/internal/stateproxypg/connector_test.go`

- [ ] **Step 1: Define the schema SQL and startup logic**
  ```go
  // src/asya-gateway/internal/stateproxypg/schema.go
  package stateproxypg

  import (
      "context"
      "fmt"
      "log/slog"
      "regexp"
      "strings"

      "github.com/jackc/pgx/v5/pgxpool"
  )

  const createTableSQL = `
  CREATE TABLE IF NOT EXISTS kv (
      key        TEXT PRIMARY KEY,
      value      JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS idx_kv_gin ON kv USING gin (value jsonb_path_ops);
  `

  // EnsureSchema creates the kv table and GIN index if they do not exist.
  func EnsureSchema(ctx context.Context, pool *pgxpool.Pool) error {
      _, err := pool.Exec(ctx, createTableSQL)
      return err
  }

  // validIndexExpr matches safe expression index definitions.
  // Allows: field_name or (field_name)::type
  var validIndexExpr = regexp.MustCompile(`^[a-zA-Z_][a-zA-Z0-9_]*$|^\([a-zA-Z_][a-zA-Z0-9_]*\)::[a-zA-Z]+$`)

  // EnsureIndexes reads comma-separated index expressions from the given string
  // and creates expression indexes concurrently.
  // Example input: "status, (deadline_at)::timestamptz"
  func EnsureIndexes(ctx context.Context, pool *pgxpool.Pool, indexSpec string) error {
      if indexSpec == "" {
          return nil
      }
      for _, raw := range strings.Split(indexSpec, ",") {
          expr := strings.TrimSpace(raw)
          if expr == "" {
              continue
          }
          // Determine index expression and name
          var sqlExpr, idxName string
          if strings.HasPrefix(expr, "(") {
              // Cast expression: (field)::type
              if !validIndexExpr.MatchString(expr) {
                  return fmt.Errorf("invalid index expression: %q", expr)
              }
              // Extract field name for index name
              field := expr[1:strings.Index(expr, ")")]
              idxName = "idx_kv_expr_" + field
              sqlExpr = fmt.Sprintf("(value->>'%s')%s", field, expr[strings.Index(expr, ")"):])
              // Rewrite as proper cast
              sqlExpr = fmt.Sprintf("((value->>'%s')%s)", field, expr[strings.Index(expr, ")")+1:])
          } else {
              // Simple field: value->>'field'
              if !validIndexExpr.MatchString(expr) {
                  return fmt.Errorf("invalid index expression: %q", expr)
              }
              idxName = "idx_kv_expr_" + expr
              sqlExpr = fmt.Sprintf("(value->>'%s')", expr)
          }
          sql := fmt.Sprintf(
              "CREATE INDEX CONCURRENTLY IF NOT EXISTS %s ON kv (%s)",
              idxName, sqlExpr,
          )
          slog.Info("Creating expression index", "name", idxName, "expr", sqlExpr)
          // CONCURRENTLY cannot run inside a transaction
          if _, err := pool.Exec(ctx, sql); err != nil {
              return fmt.Errorf("create index %s: %w", idxName, err)
          }
      }
      return nil
  }
  ```

- [ ] **Step 2: Implement KV connector (read/write/head/delete/list)**
  ```go
  // src/asya-gateway/internal/stateproxypg/connector.go
  package stateproxypg

  import (
      "context"
      "encoding/json"
      "fmt"

      "github.com/jackc/pgx/v5"
      "github.com/jackc/pgx/v5/pgxpool"
  )

  // KVRow represents a row in the kv table.
  type KVRow struct {
      Key       string          `json:"key"`
      Value     json.RawMessage `json:"value"`
      CreatedAt string          `json:"created_at"`
      UpdatedAt string          `json:"updated_at"`
  }

  // Connector implements state-proxy operations over PostgreSQL.
  type Connector struct {
      pool *pgxpool.Pool
  }

  // NewConnector creates a new PG connector.
  func NewConnector(pool *pgxpool.Pool) *Connector {
      return &Connector{pool: pool}
  }

  // Read returns the value for a key. Returns nil,ErrNotFound if missing.
  func (c *Connector) Read(ctx context.Context, key string) (*KVRow, error)

  // Write upserts a key-value pair. Updates updated_at on conflict.
  func (c *Connector) Write(ctx context.Context, key string, value json.RawMessage) error

  // Exists returns true if the key exists.
  func (c *Connector) Exists(ctx context.Context, key string) (bool, error)

  // Delete removes a key. Returns ErrNotFound if missing.
  func (c *Connector) Delete(ctx context.Context, key string) error

  // List returns keys matching the prefix.
  func (c *Connector) List(ctx context.Context, prefix string) ([]string, error)
  ```

  SQL for each operation:
  - Read: `SELECT key, value, created_at, updated_at FROM kv WHERE key = $1`
  - Write: `INSERT INTO kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()`
  - Exists: `SELECT 1 FROM kv WHERE key = $1`
  - Delete: `DELETE FROM kv WHERE key = $1`
  - List: `SELECT key FROM kv WHERE key LIKE $1 ORDER BY key` (prefix + `%`)

- [ ] **Step 3: Write integration test (requires real PG)**
  Tests use `STATEPROXY_PG_TEST_URL` env var, skip if empty. Use testcontainers
  or just test in component tests. For unit tests, write a test against the
  connector_test.go that uses a real PG if available:
  ```go
  // src/asya-gateway/internal/stateproxypg/connector_test.go
  func TestConnectorCRUD(t *testing.T) {
      dbURL := os.Getenv("STATEPROXY_PG_TEST_URL")
      if dbURL == "" {
          t.Skip("STATEPROXY_PG_TEST_URL not set")
      }
      // Create pool, ensure schema, test Read/Write/Exists/Delete/List
  }
  ```
  Run: `cd src/asya-gateway && go test ./internal/stateproxypg/ -v`
  (skips without PG; full test runs in component tests)

---

### Task 3: PG State-Proxy Connector -- /query Endpoint

**Files:**
- Create: `src/asya-gateway/internal/stateproxypg/query.go`
- Test: `src/asya-gateway/internal/stateproxypg/query_test.go`

- [ ] **Step 1: Implement Mango-style filter-to-SQL translator**
  ```go
  // src/asya-gateway/internal/stateproxypg/query.go
  package stateproxypg

  // QueryRequest is the JSON body for POST /query.
  type QueryRequest struct {
      Prefix  string            `json:"prefix,omitempty"`
      Filter  map[string]any    `json:"filter,omitempty"`
      Sort    []string          `json:"sort,omitempty"`
      Limit   int               `json:"limit,omitempty"`
      Offset  int               `json:"offset,omitempty"`
      Count   bool              `json:"count,omitempty"`
  }

  // QueryResponse is returned from POST /query.
  type QueryResponse struct {
      Rows  []KVRow `json:"rows,omitempty"`
      Total int     `json:"total"`
  }

  // Query executes a Mango-style filter query.
  func (c *Connector) Query(ctx context.Context, req QueryRequest) (*QueryResponse, error)
  ```

  Filter operators and their SQL translations:
  - `{"status": "running"}` (implicit $eq) -> `value @> '{"status":"running"}'`
  - `{"progress": {"$gt": 50}}` -> `(value->>'progress')::numeric > $N`
  - `{"$gte": V}` -> `>=`, `{"$lt": V}` -> `<`, `{"$lte": V}` -> `<=`
  - `{"$ne": V}` -> `value->>'field' != $N`
  - `{"$in": [...]}` -> `value->>'field' = ANY($N)`
  - `{"$nin": [...]}` -> `NOT (value->>'field' = ANY($N))`
  - `{"$exists": true}` -> `value ? 'field'`
  - `{"$exists": false}` -> `NOT (value ? 'field')`
  - `{"$contains": {...}}` -> `value @> $N::jsonb`

  Sort translation:
  - `"-created_at"` -> `ORDER BY created_at DESC`
  - `"created_at"` -> `ORDER BY created_at ASC`
  - `"-status"` -> `ORDER BY value->>'status' DESC`
  - Any field not in `{created_at, updated_at, key}` -> `value->>'field'`

  The translator builds a parameterized query with `$1`, `$2`, etc. placeholders.
  All user input goes through parameters, never interpolated into SQL.

- [ ] **Step 2: Write unit tests for SQL generation**
  Test the SQL builder function independently (no PG required).
  ```go
  // src/asya-gateway/internal/stateproxypg/query_test.go
  func TestBuildQuery_SimpleFilter(t *testing.T) {
      sql, args := buildFilterSQL(QueryRequest{
          Prefix: "msg/",
          Filter: map[string]any{"status": "running"},
          Sort:   []string{"-created_at"},
          Limit:  10,
      })
      assert.Contains(t, sql, "key LIKE $1")
      assert.Contains(t, sql, "value @> $2")
      assert.Contains(t, sql, "ORDER BY created_at DESC")
      assert.Contains(t, sql, "LIMIT 10")
      assert.Equal(t, "msg/%", args[0])
  }

  func TestBuildQuery_ComparisonOps(t *testing.T) {
      sql, args := buildFilterSQL(QueryRequest{
          Filter: map[string]any{
              "progress": map[string]any{"$gt": 50},
          },
      })
      assert.Contains(t, sql, "(value->>'progress')::numeric > $")
      assert.Equal(t, float64(50), args[len(args)-1])
  }

  func TestBuildQuery_InOperator(t *testing.T) { ... }
  func TestBuildQuery_ExistsOperator(t *testing.T) { ... }
  func TestBuildQuery_CountMode(t *testing.T) { ... }
  ```
  Run: `cd src/asya-gateway && go test ./internal/stateproxypg/ -run TestBuild -v`

---

### Task 4: PG State-Proxy HTTP Server

**Files:**
- Create: `src/asya-gateway/internal/stateproxypg/server.go`
- Create: `src/asya-gateway/cmd/state-proxy-pg/main.go`
- Test: `src/asya-gateway/internal/stateproxypg/server_test.go`

- [ ] **Step 1: Implement HTTP handlers over Unix socket**
  ```go
  // src/asya-gateway/internal/stateproxypg/server.go
  package stateproxypg

  import (
      "net"
      "net/http"
  )

  // NewHTTPHandler returns an http.Handler that routes to the connector.
  //
  //   GET    /healthz        -> health check
  //   GET    /keys/{key}     -> Read
  //   PUT    /keys/{key}     -> Write
  //   HEAD   /keys/{key}     -> Exists
  //   DELETE /keys/{key}     -> Delete
  //   GET    /keys/?prefix=X -> List
  //   POST   /query          -> Query
  //
  func NewHTTPHandler(conn *Connector) http.Handler

  // ListenUnixSocket starts an HTTP server on the given Unix socket path.
  // Removes stale socket file if present. Blocks until ctx is canceled.
  func ListenUnixSocket(ctx context.Context, socketPath string, handler http.Handler) error
  ```

  Route matching: use `http.NewServeMux()`. The `/keys/` prefix handler checks
  method (GET/PUT/HEAD/DELETE) and presence of key in path vs query params.

- [ ] **Step 2: Implement main.go for state-proxy-pg binary**
  ```go
  // src/asya-gateway/cmd/state-proxy-pg/main.go
  package main

  import (
      "context"
      "log/slog"
      "os"
      "os/signal"
      "syscall"

      "github.com/jackc/pgx/v5/pgxpool"
      "github.com/deliveryhero/asya/asya-gateway/internal/stateproxypg"
  )

  func main() {
      // Required env vars (no defaults per project policy):
      //   CONNECTOR_SOCKET      - Unix socket path
      //   STATE_PROXY_PG_URL    - PostgreSQL connection string
      //   STATE_PROXY_PG_INDEXES - Comma-separated index expressions (optional)
      socketPath := os.Getenv("CONNECTOR_SOCKET")
      pgURL := os.Getenv("STATE_PROXY_PG_URL")
      // Fail fast on missing config
      if socketPath == "" { slog.Error("CONNECTOR_SOCKET required"); os.Exit(1) }
      if pgURL == "" { slog.Error("STATE_PROXY_PG_URL required"); os.Exit(1) }

      ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
      defer cancel()

      pool, err := pgxpool.New(ctx, pgURL)
      // ... error handling ...

      // Schema + indexes
      stateproxypg.EnsureSchema(ctx, pool)
      stateproxypg.EnsureIndexes(ctx, pool, os.Getenv("STATE_PROXY_PG_INDEXES"))

      conn := stateproxypg.NewConnector(pool)
      handler := stateproxypg.NewHTTPHandler(conn)
      stateproxypg.ListenUnixSocket(ctx, socketPath, handler)
  }
  ```

- [ ] **Step 3: Write unit tests using httptest for HTTP handlers**
  Test the HTTP handler without PG by injecting a mock Connector (extract interface
  or test against the real handler with a test PG).
  ```go
  // src/asya-gateway/internal/stateproxypg/server_test.go
  func TestHTTPHandler_PutAndGet(t *testing.T) {
      // Use httptest.NewServer with the handler, backed by a real PG
      // (skip if no PG) or a mock connector.
  }

  func TestHTTPHandler_HeadExists(t *testing.T) { ... }
  func TestHTTPHandler_DeleteNotFound(t *testing.T) { ... }
  func TestHTTPHandler_ListByPrefix(t *testing.T) { ... }
  func TestHTTPHandler_QueryEndpoint(t *testing.T) { ... }
  func TestHTTPHandler_HealthCheck(t *testing.T) { ... }
  ```
  Run: `cd src/asya-gateway && go test ./internal/stateproxypg/ -run TestHTTP -v`

- [ ] **Step 4: Add build target to Makefile**
  Add to `src/asya-gateway/Makefile`:
  ```makefile
  build-state-proxy-pg:
  	go build -o bin/state-proxy-pg ./cmd/state-proxy-pg

  build: build-gateway build-state-proxy-pg

  build-gateway:
  	go build -o bin/gateway ./cmd/gateway
  ```

---

### Task 5: State-Proxy HTTP Client (internal/store/)

**Files:**
- Create: `src/asya-gateway/internal/store/interface.go`
- Create: `src/asya-gateway/internal/store/stateproxy_client.go`
- Create: `src/asya-gateway/internal/store/memory.go`
- Test: `src/asya-gateway/internal/store/stateproxy_client_test.go`
- Test: `src/asya-gateway/internal/store/memory_test.go`

- [ ] **Step 1: Define MessageStore interface**
  ```go
  // src/asya-gateway/internal/store/interface.go
  package store

  import (
      "context"
      "errors"

      "github.com/deliveryhero/asya/asya-gateway/pkg/types"
  )

  var ErrNotFound = errors.New("message not found")
  var ErrStaleStatus = errors.New("stale status update rejected")

  // MessageStore defines the mesh-api's storage interface.
  // Persistence methods talk to the state-proxy over HTTP/Unix socket.
  // Pub/sub methods are in-process Go channels (ephemeral).
  type MessageStore interface {
      // Persistence (state-proxy)
      Create(ctx context.Context, msg *types.Message) error
      Get(ctx context.Context, id string) (*types.Message, error)
      UpdateStatus(ctx context.Context, id string, status types.MessageStatus, data json.RawMessage) error
      Delete(ctx context.Context, id string) error
      List(ctx context.Context, params types.ListParams) ([]*types.Message, int, error)

      // In-process pub/sub (ephemeral, not persisted)
      Subscribe(id string) <-chan types.Event
      Unsubscribe(id string, ch <-chan types.Event)
      Publish(id string, event types.Event)
  }
  ```

- [ ] **Step 2: Implement state-proxy HTTP client**
  ```go
  // src/asya-gateway/internal/store/stateproxy_client.go
  package store

  // StateProxyStore implements MessageStore using HTTP calls to a
  // state-proxy connector over Unix socket.
  type StateProxyStore struct {
      client     *http.Client  // transport configured for Unix socket
      subscribers *Subscribers  // in-process pub/sub
  }

  // NewStateProxyStore creates a store that talks to state-proxy-pg
  // at the given Unix socket path.
  func NewStateProxyStore(socketPath string) *StateProxyStore {
      transport := &http.Transport{
          DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
              return net.Dial("unix", socketPath)
          },
      }
      return &StateProxyStore{
          client: &http.Client{Transport: transport},
          subscribers: NewSubscribers(),
      }
  }
  ```

  Key prefix for messages: `msg/{id}`. Methods map to:
  - `Create` -> `PUT http://localhost/keys/msg/{id}` with JSONB body
  - `Get` -> `GET http://localhost/keys/msg/{id}`
  - `UpdateStatus` -> `GET` current, check `StatusAdvances()`, then `PUT` updated
  - `Delete` -> `DELETE http://localhost/keys/msg/{id}`
  - `List` -> `POST http://localhost/query` with prefix `msg/` + filters

  The host in URLs is ignored when using Unix socket transport; use `http://stateproxy/...`.

- [ ] **Step 3: Implement in-memory store for testing**
  ```go
  // src/asya-gateway/internal/store/memory.go
  package store

  // MemoryStore implements MessageStore using in-memory maps.
  // Used for unit tests and local development.
  type MemoryStore struct {
      mu          sync.RWMutex
      messages    map[string]*types.Message
      subscribers *Subscribers
  }

  func NewMemoryStore() *MemoryStore
  ```

- [ ] **Step 4: Write unit tests for MemoryStore**
  ```go
  // src/asya-gateway/internal/store/memory_test.go
  func TestMemoryStore_CreateAndGet(t *testing.T) { ... }
  func TestMemoryStore_UpdateStatus_MonotonicOrdering(t *testing.T) {
      // Create pending -> update to running (ok) -> update to pending (rejected)
      // -> update to succeeded (ok) -> update to running (rejected)
  }
  func TestMemoryStore_Delete(t *testing.T) { ... }
  func TestMemoryStore_List(t *testing.T) { ... }
  func TestMemoryStore_PubSub(t *testing.T) {
      // Subscribe, publish event, verify received on channel
      // Unsubscribe, verify channel closed
  }
  ```
  Run: `cd src/asya-gateway && go test ./internal/store/ -v`

---

### Task 6: In-Process Subscriber Hub (internal/subscribers/)

**Files:**
- Create: `src/asya-gateway/internal/subscribers/hub.go`
- Test: `src/asya-gateway/internal/subscribers/hub_test.go`

- [ ] **Step 1: Implement subscriber hub**
  ```go
  // src/asya-gateway/internal/subscribers/hub.go
  package subscribers

  import (
      "log/slog"
      "sync"

      "github.com/deliveryhero/asya/asya-gateway/pkg/types"
  )

  const channelBuffer = 100

  // Hub manages in-process Go channel subscriptions keyed by message ID.
  type Hub struct {
      mu   sync.RWMutex
      subs map[string][]chan types.Event
  }

  func New() *Hub {
      return &Hub{subs: make(map[string][]chan types.Event)}
  }

  // Subscribe returns a buffered channel that will receive events for the given ID.
  func (h *Hub) Subscribe(id string) <-chan types.Event {
      h.mu.Lock()
      defer h.mu.Unlock()
      ch := make(chan types.Event, channelBuffer)
      h.subs[id] = append(h.subs[id], ch)
      return ch
  }

  // Unsubscribe removes and closes the channel.
  func (h *Hub) Unsubscribe(id string, ch <-chan types.Event) {
      h.mu.Lock()
      defer h.mu.Unlock()
      listeners := h.subs[id]
      for i, listener := range listeners {
          if listener == ch {
              close(listener)
              h.subs[id] = append(listeners[:i], listeners[i+1:]...)
              break
          }
      }
      if len(h.subs[id]) == 0 {
          delete(h.subs, id)
      }
  }

  // Publish sends an event to all subscribers for the given ID.
  // Drops if any channel is full (logs warning).
  func (h *Hub) Publish(id string, event types.Event) {
      h.mu.RLock()
      defer h.mu.RUnlock()
      for _, ch := range h.subs[id] {
          select {
          case ch <- event:
          default:
              slog.Warn("Event dropped: subscriber channel full", "id", id)
          }
      }
  }
  ```

- [ ] **Step 2: Write unit tests**
  ```go
  // src/asya-gateway/internal/subscribers/hub_test.go
  func TestHub_SubscribeAndPublish(t *testing.T) {
      hub := New()
      ch := hub.Subscribe("msg-1")
      hub.Publish("msg-1", types.Event{Type: "status", Status: types.MessageStatusRunning})
      event := <-ch
      assert.Equal(t, types.MessageStatusRunning, event.Status)
  }

  func TestHub_Unsubscribe(t *testing.T) {
      hub := New()
      ch := hub.Subscribe("msg-1")
      hub.Unsubscribe("msg-1", ch)
      // Verify channel is closed
      _, ok := <-ch
      assert.False(t, ok)
  }

  func TestHub_PublishToMultipleSubscribers(t *testing.T) { ... }
  func TestHub_PublishNoSubscribers(t *testing.T) { ... }
  func TestHub_DropOnFullChannel(t *testing.T) { ... }
  ```
  Run: `cd src/asya-gateway && go test ./internal/subscribers/ -v`

---

### Task 7: Mesh-API HTTP Handlers (internal/mesh/)

**Files:**
- Create: `src/asya-gateway/internal/mesh/handler.go`
- Create: `src/asya-gateway/internal/mesh/create.go`
- Create: `src/asya-gateway/internal/mesh/get.go`
- Create: `src/asya-gateway/internal/mesh/events.go`
- Create: `src/asya-gateway/internal/mesh/cancel.go`
- Create: `src/asya-gateway/internal/mesh/list.go`
- Test: `src/asya-gateway/internal/mesh/handler_test.go`

- [ ] **Step 1: Define the handler struct and router**
  ```go
  // src/asya-gateway/internal/mesh/handler.go
  package mesh

  import (
      "net/http"

      "github.com/deliveryhero/asya/asya-gateway/internal/queue"
      "github.com/deliveryhero/asya/asya-gateway/internal/store"
  )

  // Handler holds dependencies for mesh API handlers.
  type Handler struct {
      store      store.MessageStore
      queue      queue.Client
      gatewayURL string // stamped into envelope headers as x-asya-gateway-url
  }

  // NewHandler creates a new mesh API handler.
  func NewHandler(s store.MessageStore, q queue.Client, gatewayURL string) *Handler {
      return &Handler{store: s, queue: q, gatewayURL: gatewayURL}
  }

  // RegisterExternal registers external API routes (port 8080).
  // POST   /api/v1/mesh/           -> Create
  // GET    /api/v1/mesh/           -> List
  // GET    /api/v1/mesh/{id}       -> Get
  // GET    /api/v1/mesh/{id}/events -> SSE Subscribe
  // DELETE /api/v1/mesh/{id}       -> Cancel
  func (h *Handler) RegisterExternal(mux *http.ServeMux)

  // RegisterInternal registers internal API routes (port 8081).
  // POST   /api/v1/mesh/{id}/events -> Publish event (sidecar)
  // GET    /api/v1/mesh/{id}        -> Get (sidecar heartbeat)
  func (h *Handler) RegisterInternal(mux *http.ServeMux)
  ```

- [ ] **Step 2: Implement POST /api/v1/mesh/ (Create)**
  ```go
  // src/asya-gateway/internal/mesh/create.go
  package mesh

  // HandleCreate processes POST /api/v1/mesh/?actor={name}
  //
  // Request body:
  //   {"payload": {...}, "headers": {...}, "timeout": 300}
  //
  // Steps:
  //   1. Parse actor from query param (required)
  //   2. Generate UUID for message ID
  //   3. Build MessageData with actor, payload, headers, deadline
  //   4. Stamp x-asya-gateway-url into headers
  //   5. Store message in state-proxy (status: pending)
  //   6. Build ActorEnvelope and send to actor queue
  //   7. Return 201 {"id": "..."}
  //
  func (h *Handler) HandleCreate(w http.ResponseWriter, r *http.Request)
  ```

  Error cases:
  - Missing `actor` query param -> 400
  - Invalid JSON body -> 400
  - Queue send failure -> 500 (message already in DB as pending; will timeout)

- [ ] **Step 3: Implement GET /api/v1/mesh/{id} (Get)**
  ```go
  // src/asya-gateway/internal/mesh/get.go
  package mesh

  // HandleGet processes GET /api/v1/mesh/{id}
  //
  // Returns 200 with Message JSON.
  // Returns 404 if not found.
  //
  func (h *Handler) HandleGet(w http.ResponseWriter, r *http.Request)
  ```

  Parse `{id}` from URL path. Use `strings.TrimPrefix(r.URL.Path, "/api/v1/mesh/")`,
  then split on `/` to extract ID and detect `/events` suffix.

- [ ] **Step 4: Implement GET /api/v1/mesh/{id}/events (SSE Subscribe)**
  ```go
  // src/asya-gateway/internal/mesh/events.go
  package mesh

  // HandleEventsGet processes GET /api/v1/mesh/{id}/events
  //
  // SSE stream. Steps:
  //   1. Get current message from store
  //   2. If terminal, write single SSE event and return
  //   3. Write current status as first SSE event (catch-up)
  //   4. Subscribe to in-process channel
  //   5. Stream events until terminal or client disconnect
  //   6. Unsubscribe on exit
  //
  func (h *Handler) HandleEventsGet(w http.ResponseWriter, r *http.Request)
  ```

  SSE format:
  ```
  event: status
  data: {"status":"running","actor":"train-model","progress":50.0}

  event: fly
  data: {"text":"token..."}

  event: status
  data: {"status":"succeeded","actor":"x-sink"}
  ```

  Set headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`,
  `Connection: keep-alive`. Flush after each event.

- [ ] **Step 5: Implement POST /api/v1/mesh/{id}/events (Publish)**
  ```go
  // HandleEventsPost processes POST /api/v1/mesh/{id}/events (internal port)
  //
  // Request body:
  //   {"type": "status", "status": "running", "data": {"actor": "x", "progress": 50}}
  //   {"type": "fly", "data": {"text": "token..."}}
  //
  // Steps:
  //   1. Parse event from request body
  //   2. If type=status: update store (monotonic ordering enforced)
  //   3. Publish event to in-process subscribers
  //   4. Return 204
  //
  func (h *Handler) HandleEventsPost(w http.ResponseWriter, r *http.Request)
  ```

- [ ] **Step 6: Implement DELETE /api/v1/mesh/{id} (Cancel)**
  ```go
  // src/asya-gateway/internal/mesh/cancel.go
  package mesh

  // HandleCancel processes DELETE /api/v1/mesh/{id}
  //
  // Steps:
  //   1. Get current message
  //   2. If already terminal, return 204 (idempotent)
  //   3. Update status to canceled
  //   4. Publish cancel event to subscribers
  //   5. Return 204
  //
  func (h *Handler) HandleCancel(w http.ResponseWriter, r *http.Request)
  ```

- [ ] **Step 7: Implement GET /api/v1/mesh/ (List)**
  ```go
  // src/asya-gateway/internal/mesh/list.go
  package mesh

  // HandleList processes GET /api/v1/mesh/?status=running&limit=10&offset=0
  //
  // Returns 200 {"messages": [...], "total": 42}
  //
  func (h *Handler) HandleList(w http.ResponseWriter, r *http.Request)
  ```

  Parse query params: `status`, `limit`, `offset`. Convert to `types.ListParams`
  with `prefix: "msg/"` and filter on `status`.

- [ ] **Step 8: Write handler unit tests with MemoryStore**
  ```go
  // src/asya-gateway/internal/mesh/handler_test.go
  package mesh

  import (
      "net/http"
      "net/http/httptest"
      "testing"
  )

  // mockQueue implements queue.Client for testing (records sent messages).
  type mockQueue struct {
      sent []queue.ActorEnvelope
  }

  func TestHandleCreate_Success(t *testing.T) {
      s := store.NewMemoryStore()
      q := &mockQueue{}
      h := NewHandler(s, q, "http://internal.test")
      req := httptest.NewRequest("POST", "/api/v1/mesh/?actor=echo", strings.NewReader(`{"payload":{"x":1}}`))
      w := httptest.NewRecorder()
      h.HandleCreate(w, req)
      assert.Equal(t, 201, w.Code)
      // Verify message created in store
      // Verify envelope sent to queue with x-asya-gateway-url header
  }

  func TestHandleCreate_MissingActor(t *testing.T) {
      // POST without ?actor= -> 400
  }

  func TestHandleGet_Found(t *testing.T) { ... }
  func TestHandleGet_NotFound(t *testing.T) { ... }

  func TestHandleEventsPost_StatusUpdate(t *testing.T) {
      // POST status event -> verify store updated + subscriber notified
  }

  func TestHandleEventsPost_MonotonicReject(t *testing.T) {
      // Create succeeded message, POST running -> ignored (no error, just 204)
  }

  func TestHandleEventsPost_FlyEvent(t *testing.T) {
      // POST fly event -> verify subscriber receives it, store NOT updated
  }

  func TestHandleEventsGet_SSE(t *testing.T) {
      // Create running message, subscribe, publish status event
      // Verify SSE format in response body
  }

  func TestHandleEventsGet_TerminalCatchUp(t *testing.T) {
      // Create already-succeeded message, GET /events
      // Should return single SSE event and close
  }

  func TestHandleCancel_Success(t *testing.T) { ... }
  func TestHandleCancel_AlreadyTerminal(t *testing.T) { ... }
  func TestHandleList_FilterByStatus(t *testing.T) { ... }

  func TestHandleCreate_StampsGatewayURL(t *testing.T) {
      // Verify the envelope sent to queue has
      // headers["x-asya-gateway-url"] = gatewayURL
  }
  ```
  Run: `cd src/asya-gateway && go test ./internal/mesh/ -v`

---

### Task 8: Mesh-API Binary (cmd/mesh-api/main.go)

**Files:**
- Create: `src/asya-gateway/cmd/mesh-api/main.go`
- Modify: `src/asya-gateway/Makefile`
- Modify: `src/asya-gateway/Dockerfile`

- [ ] **Step 1: Implement main.go for mesh-api**
  ```go
  // src/asya-gateway/cmd/mesh-api/main.go
  package main

  import (
      "context"
      "fmt"
      "log/slog"
      "net/http"
      "os"
      "os/signal"
      "syscall"
      "time"

      "github.com/deliveryhero/asya/asya-gateway/internal/mesh"
      "github.com/deliveryhero/asya/asya-gateway/internal/queue"
      "github.com/deliveryhero/asya/asya-gateway/internal/store"
      "github.com/deliveryhero/asya/asya-gateway/internal/tracing"
  )

  func main() {
      // Required env vars (no defaults):
      //   ASYA_MESH_EXTERNAL_PORT  - external API port (e.g. 8080)
      //   ASYA_MESH_INTERNAL_PORT  - internal sidecar port (e.g. 8081)
      //   ASYA_STATEPROXY_SOCKET   - Unix socket path to state-proxy-pg
      //   ASYA_INTERNAL_URL        - URL sidecars use for callbacks
      //                              (stamped as x-asya-gateway-url)
      //
      // Queue transport env vars (same as existing gateway):
      //   ASYA_PUBSUB_PROJECT_ID, ASYA_SQS_ENDPOINT, ASYA_RABBITMQ_URL, etc.

      extPort := os.Getenv("ASYA_MESH_EXTERNAL_PORT")
      intPort := os.Getenv("ASYA_MESH_INTERNAL_PORT")
      socketPath := os.Getenv("ASYA_STATEPROXY_SOCKET")
      gatewayURL := os.Getenv("ASYA_INTERNAL_URL")

      // Fail fast on missing config
      for _, kv := range []struct{ k, v string }{
          {"ASYA_MESH_EXTERNAL_PORT", extPort},
          {"ASYA_MESH_INTERNAL_PORT", intPort},
          {"ASYA_STATEPROXY_SOCKET", socketPath},
          {"ASYA_INTERNAL_URL", gatewayURL},
      } {
          if kv.v == "" {
              slog.Error("Required env var missing", "var", kv.k)
              os.Exit(1)
          }
      }

      ctx, cancel := signal.NotifyContext(context.Background(),
          syscall.SIGTERM, syscall.SIGINT)
      defer cancel()

      // OTEL tracing (optional)
      namespace := os.Getenv("ASYA_NAMESPACE")
      shutdown, _ := tracing.Init(
          os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
          "asya-mesh-api", namespace)
      defer func() {
          shutCtx, c := context.WithTimeout(context.Background(), 5*time.Second)
          defer c()
          _ = shutdown(shutCtx)
      }()

      // MessageStore over state-proxy HTTP client
      msgStore := store.NewStateProxyStore(socketPath)

      // Queue client (reuse existing initQueueClient pattern)
      queueClient, err := initQueueClient(ctx)
      if err != nil {
          slog.Error("Failed to create queue client", "error", err)
          os.Exit(1)
      }
      defer func() { _ = queueClient.Close() }()

      handler := mesh.NewHandler(msgStore, queueClient, gatewayURL)

      // External server (port 8080)
      extMux := http.NewServeMux()
      handler.RegisterExternal(extMux)
      extMux.HandleFunc("/health", healthHandler)

      // Internal server (port 8081)
      intMux := http.NewServeMux()
      handler.RegisterInternal(intMux)
      intMux.HandleFunc("/health", healthHandler)

      extServer := &http.Server{Addr: ":" + extPort, Handler: extMux}
      intServer := &http.Server{Addr: ":" + intPort, Handler: intMux}

      go func() { slog.Info("External API", "port", extPort); extServer.ListenAndServe() }()
      go func() { slog.Info("Internal API", "port", intPort); intServer.ListenAndServe() }()

      <-ctx.Done()
      slog.Info("Shutting down")
      shutCtx, shutCancel := context.WithTimeout(context.Background(), 10*time.Second)
      defer shutCancel()
      extServer.Shutdown(shutCtx)
      intServer.Shutdown(shutCtx)
  }
  ```

  The `initQueueClient` function is extracted from `cmd/gateway/main.go` into a
  shared location or duplicated initially.

- [ ] **Step 2: Update Makefile**
  Add to `src/asya-gateway/Makefile`:
  ```makefile
  build-mesh-api:
  	go build -o bin/mesh-api ./cmd/mesh-api

  build: build-gateway build-mesh-api build-state-proxy-pg
  ```

- [ ] **Step 3: Update Dockerfile to build all binaries**
  Add to `src/asya-gateway/Dockerfile` builder stage:
  ```dockerfile
  RUN --mount=type=cache,target=/root/.cache/go-build \
      --mount=type=cache,target=/go/pkg/mod \
      CGO_ENABLED=0 GOOS=linux go build -o mesh-api ./cmd/mesh-api && \
      CGO_ENABLED=0 GOOS=linux go build -o state-proxy-pg ./cmd/state-proxy-pg

  # Copy new binaries to runtime image
  COPY --from=builder /build/mesh-api .
  COPY --from=builder /build/state-proxy-pg .
  ```

---

### Task 9: Component Tests (Docker Compose)

**Files:**
- Create: `testing/component/mesh-api/Makefile`
- Create: `testing/component/mesh-api/profiles/sqs.yml`
- Create: `testing/component/mesh-api/compose/tester-go.yml`
- Create: `testing/component/mesh-api/tests_go/mesh_test.go`

- [ ] **Step 1: Create Makefile**
  ```makefile
  # testing/component/mesh-api/Makefile
  .PHONY: test test-one clean down
  MAKEFLAGS += --no-print-directory
  .EXPORT_ALL_VARIABLES:

  PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
  COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR))
  $(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

  DOCKER_COMPOSE ?= docker compose
  export DOCKER_BUILDKIT := 1
  export BUILDKIT_PROGRESS ?= plain
  export COMPOSE_ANSI ?= never
  DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester-go --build
  export ASYA_LOG_LEVEL ?= INFO
  ASYA_TRANSPORT ?= sqs
  export ASYA_TRANSPORT

  COMPOSE_FILES := -f profiles/$(ASYA_TRANSPORT).yml
  COMPOSE_PROJECT := comp-mesh-api-$(ASYA_TRANSPORT)

  test: clean
  	@echo "[.] Running mesh-api component tests"
  	$(MAKE) test-one ASYA_TRANSPORT=sqs

  test-one: require-ASYA_TRANSPORT
  	@echo "[.] Running mesh-api component tests with $(ASYA_TRANSPORT) transport"
  	COVERAGE_DIR="$(COVERAGE_DIR)" $(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester-go
  	$(MAKE) down ASYA_TRANSPORT=$(ASYA_TRANSPORT)
  	@echo "[+] Success: Mesh-API component tests passed"

  down: require-ASYA_TRANSPORT
  	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true

  clean:
  	$(MAKE) down ASYA_TRANSPORT=sqs || true
  	rm -rf $(COVERAGE_DIR)

  require-%:
  	@test -n "$($*)" || (echo "[-] $* not defined" && exit 1)
  ```

- [ ] **Step 2: Create Docker Compose profile**
  ```yaml
  # testing/component/mesh-api/profiles/sqs.yml
  include:
  - path: ../../../shared/compose/postgres.yml
  - path: ../../../shared/compose/sqs.yml

  services:
    state-proxy-pg:
      build:
        context: ../../../../src/asya-gateway
        dockerfile: Dockerfile
        target: builder
      command: ["go", "run", "./cmd/state-proxy-pg"]
      environment:
        CONNECTOR_SOCKET: /tmp/stateproxy.sock
        STATE_PROXY_PG_URL: postgres://postgres:postgres@postgres:5432/asya_test?sslmode=disable
        STATE_PROXY_PG_INDEXES: "status, (deadline_at)::timestamptz"
      volumes:
      - stateproxy-socket:/tmp
      depends_on:
        postgres:
          condition: service_healthy

    mesh-api:
      build:
        context: ../../../../src/asya-gateway
        dockerfile: Dockerfile
        target: builder
      command: ["go", "run", "./cmd/mesh-api"]
      environment:
        ASYA_MESH_EXTERNAL_PORT: "8080"
        ASYA_MESH_INTERNAL_PORT: "8081"
        ASYA_STATEPROXY_SOCKET: /tmp/stateproxy.sock
        ASYA_INTERNAL_URL: http://mesh-api:8081
        ASYA_SQS_ENDPOINT: http://sqs:9324
        ASYA_SQS_REGION: us-east-1
        ASYA_NAMESPACE: test
        ASYA_LOG_LEVEL: ${ASYA_LOG_LEVEL:-INFO}
      volumes:
      - stateproxy-socket:/tmp
      healthcheck:
        test: ["CMD", "wget", "--spider", "-q", "http://localhost:8080/health"]
        interval: 5s
        timeout: 3s
        retries: 10
      depends_on:
        state-proxy-pg:
          condition: service_started
        sqs:
          condition: service_healthy

    tester-go:
      extends:
        file: ../compose/tester-go.yml
        service: tester-go
      environment:
        MESH_API_URL: http://mesh-api:8080
        MESH_API_INTERNAL_URL: http://mesh-api:8081
      depends_on:
        mesh-api:
          condition: service_healthy

  volumes:
    stateproxy-socket:
  ```

- [ ] **Step 3: Create tester-go compose service**
  ```yaml
  # testing/component/mesh-api/compose/tester-go.yml
  services:
    tester-go:
      build:
        context: ../../../../src/asya-gateway
        dockerfile: Dockerfile
        target: tester
      working_dir: /build
      command: ["go", "test", "-v", "-count=1", "-timeout=120s",
                "/build/testing/component/mesh-api/..."]
      environment:
        MESH_API_URL: http://mesh-api:8080
        MESH_API_INTERNAL_URL: http://mesh-api:8081
  ```

  Note: The tester image needs access to the test files. We may need to adjust
  the build context or mount the test directory. Alternative: build from repo
  root as context.

- [ ] **Step 4: Write component test**
  ```go
  // testing/component/mesh-api/tests_go/mesh_test.go
  package tests

  import (
      "encoding/json"
      "net/http"
      "os"
      "testing"
      "time"

      "github.com/stretchr/testify/assert"
      "github.com/stretchr/testify/require"
  )

  func meshURL() string { return os.Getenv("MESH_API_URL") }
  func meshInternalURL() string { return os.Getenv("MESH_API_INTERNAL_URL") }

  func TestCreateAndGet(t *testing.T) {
      // POST /api/v1/mesh/?actor=echo with payload
      // Assert 201, parse ID
      // GET /api/v1/mesh/{id}
      // Assert 200, status=pending, actor=echo
  }

  func TestCreateAndReceiveStatusSSE(t *testing.T) {
      // POST /api/v1/mesh/?actor=echo -> get ID
      // Start SSE reader on GET /api/v1/mesh/{id}/events in goroutine
      // Simulate sidecar: POST internal /api/v1/mesh/{id}/events with status running
      // Assert SSE client receives status event
      // POST terminal event (succeeded)
      // Assert SSE stream closes after terminal event
  }

  func TestMonotonicStatusOrdering(t *testing.T) {
      // Create message, update to running, update to succeeded
      // Try updating to running again -> should be ignored
      // GET status should still be succeeded
  }

  func TestCancel(t *testing.T) {
      // Create message, DELETE /api/v1/mesh/{id}
      // GET -> status=canceled
  }

  func TestList(t *testing.T) {
      // Create 3 messages, list with ?limit=2
      // Assert pagination works
  }

  func TestFlyEvent(t *testing.T) {
      // Create, subscribe SSE, POST fly event internally
      // Assert SSE receives fly event
      // GET /api/v1/mesh/{id} -> status unchanged (FLY is ephemeral)
  }

  func TestGatewayURLInEnvelope(t *testing.T) {
      // Create message, check queue (or read from state-proxy)
      // Verify x-asya-gateway-url header is set
  }
  ```
  Run: `make -C testing/component/mesh-api test`

---

### Task 10: Wire Up and Final Validation

**Files:**
- Modify: `src/asya-gateway/Makefile` (final build targets)
- Modify: `Makefile` (root, add component test target)

- [ ] **Step 1: Extract initQueueClient to shared package**
  Move the `initQueueClient` function from `cmd/gateway/main.go` into a shared
  internal package so both `cmd/gateway/main.go` and `cmd/mesh-api/main.go` can
  use it without duplication.

  Create `src/asya-gateway/internal/queue/init.go`:
  ```go
  package queue

  // InitClient creates a queue.Client from environment variables.
  // Reads: ASYA_PUBSUB_PROJECT_ID, ASYA_SQS_ENDPOINT, ASYA_RABBITMQ_URL, etc.
  func InitClient(ctx context.Context) (Client, error)
  ```

  Update `cmd/gateway/main.go` to call `queue.InitClient(ctx)`.
  Update `cmd/mesh-api/main.go` to call `queue.InitClient(ctx)`.

- [ ] **Step 2: Run full unit test suite**
  ```bash
  cd src/asya-gateway && go test ./... -v
  ```
  Verify all new tests pass alongside existing tests. Ensure no import cycles.

- [ ] **Step 3: Run lint**
  ```bash
  make lint
  ```
  Fix any gofmt, goimports, or golangci-lint issues.

- [ ] **Step 4: Run build**
  ```bash
  cd src/asya-gateway && make build
  ```
  Verify all three binaries compile: `bin/gateway`, `bin/mesh-api`, `bin/state-proxy-pg`.

- [ ] **Step 5: Run component tests**
  ```bash
  make -C testing/component/mesh-api test
  ```

- [ ] **Step 6: Commit and push**
  Single commit with message:
  `feat(gateway): add PG state-proxy connector and mesh-api core (#PR_NUMBER)`

---

## Appendix: File Inventory

### New files (estimated ~1,700 LOC production + ~500 LOC test)

| File | LOC est. | Purpose |
|---|---|---|
| `src/asya-gateway/pkg/types/message.go` | ~90 | Message, Event, ListParams types |
| `src/asya-gateway/pkg/types/message_test.go` | ~50 | Status ordering tests |
| `src/asya-gateway/internal/stateproxypg/schema.go` | ~70 | Table DDL, index creation |
| `src/asya-gateway/internal/stateproxypg/connector.go` | ~150 | KV CRUD operations (pgx) |
| `src/asya-gateway/internal/stateproxypg/query.go` | ~200 | Mango filter-to-SQL translator |
| `src/asya-gateway/internal/stateproxypg/server.go` | ~120 | HTTP handler on Unix socket |
| `src/asya-gateway/internal/stateproxypg/connector_test.go` | ~80 | KV + query SQL builder tests |
| `src/asya-gateway/internal/stateproxypg/server_test.go` | ~60 | HTTP handler unit tests |
| `src/asya-gateway/internal/stateproxypg/query_test.go` | ~80 | SQL generation tests |
| `src/asya-gateway/internal/store/interface.go` | ~30 | MessageStore interface |
| `src/asya-gateway/internal/store/stateproxy_client.go` | ~180 | HTTP client over Unix socket |
| `src/asya-gateway/internal/store/memory.go` | ~150 | In-memory implementation |
| `src/asya-gateway/internal/store/stateproxy_client_test.go` | ~40 | (tested in component tests) |
| `src/asya-gateway/internal/store/memory_test.go` | ~100 | MemoryStore unit tests |
| `src/asya-gateway/internal/subscribers/hub.go` | ~70 | Go channel pub/sub hub |
| `src/asya-gateway/internal/subscribers/hub_test.go` | ~80 | Hub unit tests |
| `src/asya-gateway/internal/mesh/handler.go` | ~60 | Handler struct + router |
| `src/asya-gateway/internal/mesh/create.go` | ~90 | POST /mesh/ |
| `src/asya-gateway/internal/mesh/get.go` | ~40 | GET /mesh/{id} |
| `src/asya-gateway/internal/mesh/events.go` | ~120 | GET/POST /mesh/{id}/events |
| `src/asya-gateway/internal/mesh/cancel.go` | ~40 | DELETE /mesh/{id} |
| `src/asya-gateway/internal/mesh/list.go` | ~50 | GET /mesh/ |
| `src/asya-gateway/internal/mesh/handler_test.go` | ~200 | Handler unit tests |
| `src/asya-gateway/internal/queue/init.go` | ~80 | Shared queue init from env |
| `src/asya-gateway/cmd/mesh-api/main.go` | ~120 | Mesh-API binary entrypoint |
| `src/asya-gateway/cmd/state-proxy-pg/main.go` | ~60 | State-proxy-pg binary entrypoint |
| `testing/component/mesh-api/Makefile` | ~35 | Component test runner |
| `testing/component/mesh-api/profiles/sqs.yml` | ~55 | Docker Compose profile |
| `testing/component/mesh-api/compose/tester-go.yml` | ~15 | Tester service definition |
| `testing/component/mesh-api/tests_go/mesh_test.go` | ~150 | Component tests |

### Modified files

| File | Change |
|---|---|
| `src/asya-gateway/Makefile` | Add `build-mesh-api`, `build-state-proxy-pg` targets |
| `src/asya-gateway/Dockerfile` | Add build + copy for mesh-api and state-proxy-pg binaries |
| `src/asya-gateway/cmd/gateway/main.go` | Extract `initQueueClient` to `internal/queue/init.go` |
| `Makefile` (root) | Add `test-component-mesh-api` target (optional) |
