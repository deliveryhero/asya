package s3kv

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"

	_ "github.com/marcboeker/go-duckdb" // registers "duckdb" database/sql driver
)

// maxQueryKeys caps the number of S3 objects fetched per query to prevent disk
// space exhaustion and unbounded AWS egress costs.
const maxQueryKeys = 10_000

// QueryRequest is the JSON body for POST /query.
type QueryRequest struct {
	Prefix string         `json:"prefix,omitempty"`
	Filter map[string]any `json:"filter,omitempty"`
	Sort   []string       `json:"sort,omitempty"`
	Limit  int            `json:"limit,omitempty"`
	Offset int            `json:"offset,omitempty"`
	Count  bool           `json:"count,omitempty"`
}

// QueryResponse is the JSON response from POST /query.
type QueryResponse struct {
	Rows  []KVRow `json:"rows,omitempty"`
	Total int     `json:"total"`
}

// validField rejects field names that would allow SQL injection via column references.
// Documents are flat JSON (no nested fields), so dot-notation is not needed.
var validField = regexp.MustCompile(`^[a-zA-Z_][a-zA-Z0-9_]*$`)

// QueryEngine executes Mango-style queries against S3 JSON objects using DuckDB.
// S3 access is handled by aws-sdk-go-v2; DuckDB reads from a temporary directory
// (no httpfs extension required).
type QueryEngine struct {
	mu        sync.Mutex // DuckDB in-process: serialize concurrent queries
	db        *sql.DB
	connector *Connector
	logger    *slog.Logger
}

// NewQueryEngine creates an in-memory DuckDB engine backed by the S3 connector.
func NewQueryEngine(c *Connector, logger *slog.Logger) (*QueryEngine, error) {
	if logger == nil {
		logger = slog.Default()
	}
	db, err := sql.Open("duckdb", "")
	if err != nil {
		return nil, fmt.Errorf("open duckdb: %w", err)
	}
	// Verify DuckDB is operational.
	if _, err := db.Exec("SELECT 1"); err != nil {
		db.Close()
		return nil, fmt.Errorf("duckdb ping: %w", err)
	}
	return &QueryEngine{db: db, connector: c, logger: logger}, nil
}

// Close shuts down the DuckDB engine.
func (q *QueryEngine) Close() error {
	return q.db.Close()
}

// Query fetches matching S3 documents, loads them into DuckDB in-memory, and
// returns filtered/sorted rows.
//
// Steps:
//  1. List S3 keys matching req.Prefix (capped at maxQueryKeys)
//  2. Fetch all documents via aws-sdk (parallel goroutines)
//  3. Write to a temp directory as individual .json files
//  4. DuckDB: CREATE TABLE _tmp AS SELECT filename, * FROM read_json_auto(glob)
//  5. COUNT(*) for Total (before limit); SELECT rows with WHERE/ORDER BY/LIMIT
//  6. Parse results, strip _ca/_ua, build []KVRow
func (q *QueryEngine) Query(ctx context.Context, req QueryRequest) (*QueryResponse, error) {
	q.mu.Lock()
	defer q.mu.Unlock()

	// Step 1: collect matching keys (bounded).
	keys, err := q.connector.List(ctx, req.Prefix)
	if err != nil {
		return nil, fmt.Errorf("list for query: %w", err)
	}
	if len(keys) == 0 {
		return &QueryResponse{Rows: nil, Total: 0}, nil
	}
	if len(keys) > maxQueryKeys {
		return nil, fmt.Errorf("query prefix %q matches %d objects, limit is %d — use a narrower prefix", req.Prefix, len(keys), maxQueryKeys)
	}

	// Step 2+3: fetch docs and write to temp dir.
	tmpDir, cleanup, err := q.fetchToTempDir(ctx, keys)
	if err != nil {
		return nil, err
	}
	defer cleanup()

	glob := filepath.Join(tmpDir, "*.json")
	q.logger.Debug("duckdb query", "glob", glob, "keys", len(keys))

	// Step 4: load into DuckDB.
	// glob is a system-generated temp path (os.MkdirTemp) — no user input.
	loadSQL := fmt.Sprintf( // nosemgrep
		`CREATE OR REPLACE TABLE _tmp AS
		 SELECT filename, * EXCLUDE (filename)
		 FROM read_json_auto('%s', filename=true, union_by_name=true, ignore_errors=true)`,
		glob,
	)
	if _, err := q.db.ExecContext(ctx, loadSQL); err != nil {
		return nil, fmt.Errorf("duckdb load: %w", err)
	}

	where, args, err := buildWhereClause(req.Filter)
	if err != nil {
		return nil, err
	}

	// Count query path.
	if req.Count {
		var total int
		if err := q.db.QueryRowContext(ctx, "SELECT count(*) FROM _tmp"+where, args...).Scan(&total); err != nil {
			return nil, fmt.Errorf("duckdb count: %w", err)
		}
		return &QueryResponse{Total: total}, nil
	}

	// Step 5a: count total matching rows before applying LIMIT (for pagination metadata).
	var total int
	if err := q.db.QueryRowContext(ctx, "SELECT count(*) FROM _tmp"+where, args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("duckdb count: %w", err)
	}

	// Step 5b: SELECT paginated rows.
	orderBy, err := buildOrderBy(req.Sort)
	if err != nil {
		return nil, err
	}
	limitOffset := buildLimitOffset(req.Limit, req.Offset)

	selectSQL := "SELECT filename, to_json(struct_pack(* EXCLUDE (filename))) AS doc FROM _tmp" +
		where + orderBy + limitOffset

	rows, err := q.db.QueryContext(ctx, selectSQL, args...)
	if err != nil {
		return nil, fmt.Errorf("duckdb select: %w", err)
	}
	defer rows.Close()

	// Step 6: build KVRow slice.
	var result []KVRow
	for rows.Next() {
		var filename, docStr string
		if err := rows.Scan(&filename, &docStr); err != nil {
			return nil, fmt.Errorf("duckdb scan: %w", err)
		}
		logKey := logicalKeyFromFile(filename, tmpDir)
		row, err := parseStored(logKey, []byte(docStr))
		if err != nil {
			q.logger.Warn("skip unparseable row", "key", logKey, "err", err)
			continue
		}
		result = append(result, *row)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("duckdb rows: %w", err)
	}

	q.logger.Debug("query done", "returned", len(result), "total", total)
	return &QueryResponse{Rows: result, Total: total}, nil
}

// fetchToTempDir downloads S3 documents for the given logical keys and writes
// them to a new temporary directory. Returns the dir path and a cleanup func.
func (q *QueryEngine) fetchToTempDir(ctx context.Context, keys []string) (string, func(), error) {
	tmpDir, err := os.MkdirTemp("", "s3kv-query-*")
	if err != nil {
		return "", nil, fmt.Errorf("create temp dir: %w", err)
	}
	cleanup := func() { os.RemoveAll(tmpDir) }

	type result struct {
		key string
		err error
	}

	// Bound concurrency to 20 parallel S3 GETs.
	sem := make(chan struct{}, 20)
	results := make(chan result, len(keys))

	for _, k := range keys {
		k := k
		sem <- struct{}{}
		go func() {
			defer func() { <-sem }()
			row, err := q.connector.Read(ctx, k)
			if err != nil {
				results <- result{key: k, err: err}
				return
			}
			// Re-build the stored document (including _ca/_ua) for DuckDB to parse.
			storedDoc, err := buildStored(row.Value, row.CreatedAt, row.UpdatedAt)
			if err != nil {
				results <- result{key: k, err: err}
				return
			}
			safeName := encodeKeyAsFilename(k) + ".json"
			path := filepath.Join(tmpDir, safeName)
			if writeErr := os.WriteFile(path, storedDoc, 0600); writeErr != nil {
				results <- result{key: k, err: writeErr}
				return
			}
			results <- result{key: k}
		}()
	}
	for range keys {
		r := <-results
		if r.err != nil {
			cleanup()
			return "", nil, fmt.Errorf("fetch %s: %w", r.key, r.err)
		}
	}
	return tmpDir, cleanup, nil
}

// encodeKeyAsFilename encodes a logical key into a flat filename that is
// collision-free even when keys contain "/" or "%".
//
// Encoding: "%" → "%25", then "/" → "%2F".
// Decoding (decodeFilenameAsKey): "%2F" → "/", then "%25" → "%".
func encodeKeyAsFilename(key string) string {
	key = strings.ReplaceAll(key, "%", "%25")
	return strings.ReplaceAll(key, "/", "%2F")
}

// logicalKeyFromFile reconstructs the logical key from a temp-file path.
// e.g. "/tmp/s3kv-123/msg%2Ftest-1.json" → "msg/test-1"
func logicalKeyFromFile(filename, tmpDir string) string {
	base := filepath.Base(filename)
	encoded := strings.TrimSuffix(base, ".json")
	// Reverse the encoding: %2F → /, %25 → %  (order matters).
	key := strings.ReplaceAll(encoded, "%2F", "/")
	return strings.ReplaceAll(key, "%25", "%")
}

// buildWhereClause translates a Mango-style filter map into a DuckDB WHERE clause.
// Returns the SQL fragment (including " WHERE "), positional args, and any error.
//
// Supported operators: $eq (implicit), $ne, $gt, $gte, $lt, $lte, $in, $nin, $exists.
func buildWhereClause(filter map[string]any) (string, []any, error) {
	if len(filter) == 0 {
		return "", nil, nil
	}

	var conditions []string
	var args []any
	idx := 1

	for field, value := range filter {
		if !validField.MatchString(field) {
			return "", nil, fmt.Errorf("invalid field name: %q", field)
		}
		switch v := value.(type) {
		case map[string]any:
			for op, operand := range v {
				cond, extraArgs, newIdx, err := buildOperatorCondition(field, op, operand, idx)
				if err != nil {
					return "", nil, err
				}
				if cond != "" {
					conditions = append(conditions, cond)
				}
				args = append(args, extraArgs...)
				idx = newIdx
			}
		default:
			// Implicit $eq.
			conditions = append(conditions, fmt.Sprintf("%s = $%d", field, idx))
			args = append(args, v)
			idx++
		}
	}

	if len(conditions) == 0 {
		return "", nil, nil
	}
	return " WHERE " + strings.Join(conditions, " AND "), args, nil
}

// buildOperatorCondition translates one Mango operator into a SQL condition.
// extraArgs holds the positional parameters for the condition; nextIdx is the
// next free parameter index after consuming the operator's arguments.
func buildOperatorCondition(field, op string, operand any, idx int) (cond string, extraArgs []any, nextIdx int, err error) {
	switch op {
	case "$eq":
		return fmt.Sprintf("%s = $%d", field, idx), []any{operand}, idx + 1, nil
	case "$ne":
		return fmt.Sprintf("%s != $%d", field, idx), []any{operand}, idx + 1, nil
	case "$gt":
		return fmt.Sprintf("%s > $%d", field, idx), []any{operand}, idx + 1, nil
	case "$gte":
		return fmt.Sprintf("%s >= $%d", field, idx), []any{operand}, idx + 1, nil
	case "$lt":
		return fmt.Sprintf("%s < $%d", field, idx), []any{operand}, idx + 1, nil
	case "$lte":
		return fmt.Sprintf("%s <= $%d", field, idx), []any{operand}, idx + 1, nil
	case "$in":
		vals := toAnySlice(operand)
		if len(vals) == 0 {
			return "FALSE", nil, idx, nil // empty $in never matches
		}
		phs := make([]string, len(vals))
		for i := range vals {
			phs[i] = fmt.Sprintf("$%d", idx+i)
		}
		return fmt.Sprintf("%s IN (%s)", field, strings.Join(phs, ", ")), vals, idx + len(vals), nil
	case "$nin":
		vals := toAnySlice(operand)
		if len(vals) == 0 {
			return "", nil, idx, nil // empty $nin is a no-op
		}
		phs := make([]string, len(vals))
		for i := range vals {
			phs[i] = fmt.Sprintf("$%d", idx+i)
		}
		return fmt.Sprintf("%s NOT IN (%s)", field, strings.Join(phs, ", ")), vals, idx + len(vals), nil
	case "$exists":
		b, _ := operand.(bool)
		if b {
			return fmt.Sprintf("%s IS NOT NULL", field), nil, idx, nil
		}
		return fmt.Sprintf("%s IS NULL", field), nil, idx, nil
	default:
		return "", nil, idx, fmt.Errorf("unsupported filter operator: %s", op)
	}
}

// buildOrderBy translates a sort spec slice into a DuckDB ORDER BY clause.
// "-field" means DESC; "field" means ASC.
func buildOrderBy(sort []string) (string, error) {
	if len(sort) == 0 {
		return "", nil
	}
	parts := make([]string, 0, len(sort))
	for _, s := range sort {
		field := s
		dir := "ASC"
		if strings.HasPrefix(s, "-") {
			field = s[1:]
			dir = "DESC"
		}
		if !validField.MatchString(field) {
			return "", fmt.Errorf("invalid sort field: %q", field)
		}
		parts = append(parts, field+" "+dir)
	}
	return " ORDER BY " + strings.Join(parts, ", "), nil
}

// buildLimitOffset returns the LIMIT/OFFSET SQL clause.
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

// toAnySlice converts a []any interface value to []any, preserving element types.
func toAnySlice(v any) []any {
	arr, ok := v.([]any)
	if !ok {
		return nil
	}
	return arr
}
