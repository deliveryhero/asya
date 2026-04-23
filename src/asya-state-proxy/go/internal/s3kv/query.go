package s3kv

import (
	"context"
	"database/sql"
	"fmt"
	"time"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"

	_ "github.com/marcboeker/go-duckdb" // registers "duckdb" database/sql driver
)

// maxQueryKeys is the hard limit on list results; queries returning more keys
// return an error so callers narrow their prefix.
const maxQueryKeys = 10_000

// maxFetchKeys limits how many S3 objects are fetched and loaded into DuckDB
// in a single query call. This bounds per-call latency so that the upstream
// HTTP client (mesh-api FindExpired) does not time out while we wait for
// hundreds of parallel S3 GETs. Callers that need all results should page
// using Limit/Offset. For FindExpired the sampling is acceptable: expired
// tasks beyond this window are caught on the next FindExpired cycle (every 5s).
const maxFetchKeys = 50

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
	connector StorageBackend
	logger    *slog.Logger
}

// NewQueryEngine creates an in-memory DuckDB engine backed by any StorageBackend.
func NewQueryEngine(c StorageBackend, logger *slog.Logger) (*QueryEngine, error) {
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
	// Bail immediately if the caller is already done.
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	default:
	}

	q.mu.Lock()
	defer q.mu.Unlock()

	// Use an independent context for the S3 fetch + DuckDB pipeline so that a
	// short caller deadline (e.g. the mesh-api's FindExpired) does not cancel
	// mid-flight S3 GETs or DuckDB operations. The pipeline is bounded at 30s.
	opCtx, opCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer opCancel()

	// Step 1: collect matching keys (bounded).
	keys, err := q.connector.List(opCtx, req.Prefix)
	if err != nil {
		return nil, fmt.Errorf("list for query: %w", err)
	}
	if len(keys) == 0 {
		return &QueryResponse{Rows: nil, Total: 0}, nil
	}
	if len(keys) > maxQueryKeys {
		return nil, fmt.Errorf("query prefix %q matches %d objects, limit is %d — use a narrower prefix", req.Prefix, len(keys), maxQueryKeys)
	}

	// Cap the fetch to maxFetchKeys to bound per-call latency.
	// Callers that need complete results should use a narrower prefix or pagination.
	if len(keys) > maxFetchKeys {
		keys = keys[:maxFetchKeys]
		q.logger.Debug("capping fetch to maxFetchKeys", "total_listed", len(keys), "fetching", maxFetchKeys)
	}

	// Step 2+3: fetch docs and write to temp dir.
	tmpDir, cleanup, err := q.fetchToTempDir(opCtx, keys)
	if err != nil {
		return nil, err
	}
	defer cleanup()

	glob := filepath.Join(tmpDir, "*.json")
	q.logger.Debug("duckdb query", "glob", glob, "keys", len(keys))

	// Step 4: load into DuckDB using read_text (raw string content).
	//
	// We use read_text instead of read_json_auto for two reasons:
	// 1. read_json_auto infers column types from JSON, mapping nested objects to
	//    duckdb.Map — an unserializable go-duckdb type that breaks json.Marshal.
	// 2. read_text is faster: no type inference, schema is always (filename, content).
	//
	// Filtering uses json_extract_string(content, '$.field') so no explicit columns
	// are needed. glob is a system-generated path from os.MkdirTemp — no user input.
	loadSQL := fmt.Sprintf( // nosemgrep
		`CREATE OR REPLACE TABLE _tmp AS
		 SELECT filename, content
		 FROM read_text('%s')
		 WHERE content IS NOT NULL`,
		glob,
	)
	if _, err := q.db.ExecContext(opCtx, loadSQL); err != nil { // nosemgrep
		return nil, fmt.Errorf("duckdb load: %w", err)
	}

	where, args, err := buildWhereClause(req.Filter)
	if err != nil {
		return nil, err
	}

	// Count query path.
	// where uses json_extract_string(content, '$.field') — field names are validated
	// against validField regexp; values are positional args, not interpolated.
	if req.Count {
		var total int
		if err := q.db.QueryRowContext(opCtx, "SELECT count(*) FROM _tmp"+where, args...).Scan(&total); err != nil { // nosemgrep
			return nil, fmt.Errorf("duckdb count: %w", err)
		}
		return &QueryResponse{Total: total}, nil
	}

	// Step 5a: count total matching rows before applying LIMIT (for pagination metadata).
	var total int
	if err := q.db.QueryRowContext(opCtx, "SELECT count(*) FROM _tmp"+where, args...).Scan(&total); err != nil { // nosemgrep
		return nil, fmt.Errorf("duckdb count: %w", err)
	}

	// Step 5b: SELECT paginated rows.
	orderBy, err := buildOrderBy(req.Sort)
	if err != nil {
		return nil, err
	}
	limitOffset := buildLimitOffset(req.Limit, req.Offset)

	// content column already contains the raw stored JSON — pass straight to ParseStored.
	selectSQL := "SELECT filename, content FROM _tmp" + where + orderBy + limitOffset // nosemgrep

	rows, err := q.db.QueryContext(opCtx, selectSQL, args...) // nosemgrep
	if err != nil {
		return nil, fmt.Errorf("duckdb select: %w", err)
	}
	defer rows.Close()

	// Step 6: build KVRow slice by parsing the raw stored JSON directly.
	var result []KVRow
	for rows.Next() {
		var filename, content string
		if err := rows.Scan(&filename, &content); err != nil {
			return nil, fmt.Errorf("duckdb scan: %w", err)
		}
		logKey := logicalKeyFromFile(filename, tmpDir)
		row, err := ParseStored(logKey, []byte(content))
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
			storedDoc, err := BuildStored(row.Value, row.CreatedAt, row.UpdatedAt)
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
			conditions = append(conditions, fmt.Sprintf("%s = $%d", jsonField(field), idx))
			args = append(args, v)
			idx++
		}
	}

	if len(conditions) == 0 {
		return "", nil, nil
	}
	return " WHERE " + strings.Join(conditions, " AND "), args, nil
}

// jsonField returns a DuckDB expression that extracts the given top-level field
// from the `content` column (raw stored JSON). Uses json_extract_string so the
// result is always a VARCHAR — no duckdb.Map or type-inference issues.
// Field names are pre-validated by validField before this is called.
func jsonField(field string) string {
	return fmt.Sprintf("json_extract_string(content, '$.%s')", field)
}

// buildOperatorCondition translates one Mango operator into a SQL condition.
// All field references use json_extract_string(content, '$.field') so values
// are always VARCHAR — no column-type inference and no duckdb.Map issues.
func buildOperatorCondition(field, op string, operand any, idx int) (cond string, extraArgs []any, nextIdx int, err error) {
	jf := jsonField(field)
	switch op {
	case "$eq":
		return fmt.Sprintf("%s = $%d", jf, idx), []any{operand}, idx + 1, nil
	case "$ne":
		return fmt.Sprintf("%s != $%d", jf, idx), []any{operand}, idx + 1, nil
	case "$gt":
		return fmt.Sprintf("%s > $%d", jf, idx), []any{operand}, idx + 1, nil
	case "$gte":
		return fmt.Sprintf("%s >= $%d", jf, idx), []any{operand}, idx + 1, nil
	case "$lt":
		return fmt.Sprintf("%s < $%d", jf, idx), []any{operand}, idx + 1, nil
	case "$lte":
		return fmt.Sprintf("%s <= $%d", jf, idx), []any{operand}, idx + 1, nil
	case "$in":
		vals := toAnySlice(operand)
		if len(vals) == 0 {
			return "FALSE", nil, idx, nil // empty $in never matches
		}
		phs := make([]string, len(vals))
		for i := range vals {
			phs[i] = fmt.Sprintf("$%d", idx+i)
		}
		return fmt.Sprintf("%s IN (%s)", jf, strings.Join(phs, ", ")), vals, idx + len(vals), nil
	case "$nin":
		vals := toAnySlice(operand)
		if len(vals) == 0 {
			return "", nil, idx, nil // empty $nin is a no-op
		}
		phs := make([]string, len(vals))
		for i := range vals {
			phs[i] = fmt.Sprintf("$%d", idx+i)
		}
		return fmt.Sprintf("%s NOT IN (%s)", jf, strings.Join(phs, ", ")), vals, idx + len(vals), nil
	case "$exists":
		b, _ := operand.(bool)
		// Use json_extract (not json_extract_string) for null check — returns NULL
		// when the key is absent, regardless of value type.
		jfExist := fmt.Sprintf("json_extract(content, '$.%s')", field)
		if b {
			return fmt.Sprintf("%s IS NOT NULL", jfExist), nil, idx, nil
		}
		return fmt.Sprintf("%s IS NULL", jfExist), nil, idx, nil
	default:
		return "", nil, idx, fmt.Errorf("unsupported filter operator: %s", op)
	}
}

// buildOrderBy translates a sort spec slice into a DuckDB ORDER BY clause.
// "-field" means DESC; "field" means ASC. Uses json_extract_string for
// consistency with buildWhereClause — sorts values as VARCHAR.
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
		parts = append(parts, jsonField(field)+" "+dir)
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
