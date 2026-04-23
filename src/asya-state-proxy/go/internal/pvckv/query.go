package pvckv

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	_ "github.com/marcboeker/go-duckdb" // register duckdb driver

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/pg"
)

// queryEngine executes Mango-style queries over local JSON files using DuckDB.
// DuckDB reads files in-process — no network, microsecond latency.
type queryEngine struct {
	mu        sync.Mutex // DuckDB embedded is not concurrent-safe
	db        *sql.DB
	baseDir   string
	partition bool
}

func newQueryEngine(baseDir string, partition bool) *queryEngine {
	return &queryEngine{baseDir: baseDir, partition: partition}
}

func (q *queryEngine) openDB() error {
	if q.db != nil {
		return nil
	}
	db, err := sql.Open("duckdb", "")
	if err != nil {
		return fmt.Errorf("open duckdb: %w", err)
	}
	q.db = db
	return nil
}

func (q *queryEngine) query(ctx context.Context, req pg.QueryRequest) (*pg.QueryResponse, error) {
	q.mu.Lock()
	defer q.mu.Unlock()

	if err := q.openDB(); err != nil {
		return nil, err
	}

	scanDir := q.baseDir
	if q.partition {
		scanDir = filepath.Join(q.baseDir, "active")
	}

	glob := filepath.Join(scanDir, req.Prefix+"*.json")

	// read_text avoids the duckdb.Map type issue that read_json_auto produces
	loadSQL := fmt.Sprintf(
		"CREATE OR REPLACE TABLE _pvckv AS SELECT filename, content FROM read_text('%s')",
		strings.ReplaceAll(glob, "'", "''"),
	)
	if _, err := q.db.ExecContext(ctx, loadSQL); err != nil {
		errStr := err.Error()
		if strings.Contains(errStr, "No files found") || strings.Contains(errStr, "no files") {
			return &pg.QueryResponse{Rows: []pg.KVRow{}, Total: 0}, nil
		}
		return nil, fmt.Errorf("duckdb load: %w", err)
	}

	where, args, err := buildDuckDBWhere(req.Filter)
	if err != nil {
		return nil, err
	}

	orderBy := buildDuckDBOrderBy(req.Sort)

	if req.Count {
		var total int
		if err := q.db.QueryRowContext(ctx, "SELECT count(*) FROM _pvckv"+where, args...).Scan(&total); err != nil {
			return nil, fmt.Errorf("duckdb count: %w", err)
		}
		return &pg.QueryResponse{Total: total}, nil
	}

	limitClause := ""
	if req.Limit > 0 {
		limitClause = fmt.Sprintf(" LIMIT %d", req.Limit)
	}
	if req.Offset > 0 {
		limitClause += fmt.Sprintf(" OFFSET %d", req.Offset)
	}

	rows, err := q.db.QueryContext(ctx,
		"SELECT filename, content FROM _pvckv"+where+orderBy+limitClause, args...)
	if err != nil {
		return nil, fmt.Errorf("duckdb query: %w", err)
	}
	defer rows.Close()

	var result []pg.KVRow
	for rows.Next() {
		var filename, content string
		if err := rows.Scan(&filename, &content); err != nil {
			return nil, fmt.Errorf("duckdb scan: %w", err)
		}
		key := filenameToKey(filename, scanDir)
		row, err := parseKVRow(key, []byte(content))
		if err != nil {
			continue
		}
		result = append(result, *row)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("duckdb rows: %w", err)
	}

	return &pg.QueryResponse{Rows: result, Total: len(result)}, nil
}

func filenameToKey(filename, scanDir string) string {
	key := strings.TrimPrefix(filename, scanDir+"/")
	key = strings.TrimSuffix(key, ".json")
	return key
}

// buildDuckDBWhere translates a Mango filter map into a DuckDB WHERE clause.
// Uses json_extract_string(content, '$.field') for all field access.
func buildDuckDBWhere(filter map[string]any) (string, []any, error) {
	if len(filter) == 0 {
		return "", nil, nil
	}

	// Sort keys for deterministic SQL (test stability)
	keys := make([]string, 0, len(filter))
	for k := range filter {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	var conditions []string
	var args []any
	idx := 1

	for _, field := range keys {
		condition := filter[field]
		expr := fmt.Sprintf("json_extract_string(content, '$.%s')", field)

		switch cond := condition.(type) {
		case map[string]any:
			for op, operand := range cond {
				switch op {
				case "$exists":
					want, _ := operand.(bool)
					if want {
						conditions = append(conditions, expr+" IS NOT NULL")
					} else {
						conditions = append(conditions, expr+" IS NULL")
					}
				case "$in", "$nin":
					arr, _ := operand.([]any)
					placeholders := make([]string, len(arr))
					for i, v := range arr {
						placeholders[i] = fmt.Sprintf("$%d", idx)
						args = append(args, fmt.Sprintf("%v", v))
						idx++
					}
					inList := strings.Join(placeholders, ", ")
					if op == "$in" {
						conditions = append(conditions, fmt.Sprintf("%s IN (%s)", expr, inList))
					} else {
						conditions = append(conditions, fmt.Sprintf("%s NOT IN (%s)", expr, inList))
					}
				default:
					sqlOp, err := numericOp(op)
					if err != nil {
						return "", nil, err
					}
					conditions = append(conditions, fmt.Sprintf("TRY_CAST(%s AS DOUBLE) %s $%d", expr, sqlOp, idx))
					args = append(args, operand)
					idx++
				}
			}
		default:
			conditions = append(conditions, fmt.Sprintf("%s = $%d", expr, idx))
			args = append(args, fmt.Sprintf("%v", cond))
			idx++
		}
	}

	return " WHERE " + strings.Join(conditions, " AND "), args, nil
}

func numericOp(op string) (string, error) {
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
	}
	return "", fmt.Errorf("unsupported operator: %s", op)
}

func buildDuckDBOrderBy(sortSpec []string) string {
	if len(sortSpec) == 0 {
		return ""
	}
	var parts []string
	for _, s := range sortSpec {
		desc := strings.HasPrefix(s, "-")
		field := strings.TrimPrefix(s, "-")
		expr := fmt.Sprintf("json_extract_string(content, '$.%s')", field)
		if desc {
			parts = append(parts, expr+" DESC")
		} else {
			parts = append(parts, expr+" ASC")
		}
	}
	return " ORDER BY " + strings.Join(parts, ", ")
}
