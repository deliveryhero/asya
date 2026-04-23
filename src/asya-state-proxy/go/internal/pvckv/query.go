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

	// glob all JSON files recursively; prefix filtering happens in WHERE clause
	glob := filepath.Join(scanDir, "**/*.json")

	// read_text avoids the duckdb.Map type issue that read_json_auto produces.
	// CREATE TABLE (not VIEW) materializes results once per query, which is
	// efficient for local files since subsequent WHERE/ORDER/LIMIT passes avoid
	// re-scanning the directory.
	loadSQL := fmt.Sprintf( // nosemgrep -- glob is a server-controlled filesystem path; single-quotes escaped
		"CREATE OR REPLACE TABLE _pvckv AS SELECT filename, content FROM read_text('%s')",
		strings.ReplaceAll(glob, "'", "''"),
	)
	if _, err := q.db.ExecContext(ctx, loadSQL); err != nil { // nosemgrep -- loadSQL is server-constructed (glob path only)
		errStr := err.Error()
		if strings.Contains(errStr, "No files found") || strings.Contains(errStr, "no files") {
			return &pg.QueryResponse{Rows: []pg.KVRow{}, Total: 0}, nil
		}
		return nil, fmt.Errorf("duckdb load: %w", err)
	}

	where, args, err := buildDuckDBWhere(req.Filter, req.Prefix, scanDir)
	if err != nil {
		return nil, err
	}

	orderBy, err := buildDuckDBOrderBy(req.Sort)
	if err != nil {
		return nil, err
	}

	if req.Count {
		var total int
		if err := q.db.QueryRowContext(ctx, "SELECT count(*) FROM _pvckv"+where, args...).Scan(&total); err != nil { // nosemgrep -- where built from validateFieldName + $N params
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

	rows, err := q.db.QueryContext(ctx, // nosemgrep -- where/orderBy from validateFieldName + $N params; limitClause is integer-only
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

// escapeLike escapes LIKE special characters (%, _, \) in a literal string.
func escapeLike(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, `%`, `\%`)
	s = strings.ReplaceAll(s, `_`, `\_`)
	return s
}

// buildDuckDBWhere translates a Mango filter map into a DuckDB WHERE clause.
// Field names are validated against a strict identifier pattern to prevent SQL
// injection. Prefix filter uses LIKE with escaped special characters.
func buildDuckDBWhere(filter map[string]any, prefix, scanDir string) (string, []any, error) {
	var conditions []string
	var args []any
	idx := 1

	// Prefix filter on the absolute filename path, with LIKE special chars escaped.
	if prefix != "" {
		conditions = append(conditions, fmt.Sprintf("filename LIKE $%d ESCAPE '\\'", idx))
		args = append(args, escapeLike(filepath.Join(scanDir, prefix))+"%")
		idx++
	}

	if len(filter) == 0 {
		if len(conditions) == 0 {
			return "", nil, nil
		}
		return " WHERE " + strings.Join(conditions, " AND "), args, nil
	}

	// Sort keys for deterministic SQL (test stability)
	keys := make([]string, 0, len(filter))
	for k := range filter {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	for _, field := range keys {
		if err := validateFieldName(field); err != nil {
			return "", nil, err
		}
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

// buildDuckDBOrderBy translates sort specs into a DuckDB ORDER BY clause.
// Field names are validated against a strict identifier pattern to prevent SQL
// injection. Prefix "-" means descending order.
func buildDuckDBOrderBy(sortSpec []string) (string, error) {
	if len(sortSpec) == 0 {
		return "", nil
	}
	var parts []string
	for _, s := range sortSpec {
		desc := strings.HasPrefix(s, "-")
		field := strings.TrimPrefix(s, "-")
		if err := validateFieldName(field); err != nil {
			return "", err
		}
		expr := fmt.Sprintf("json_extract_string(content, '$.%s')", field)
		if desc {
			parts = append(parts, expr+" DESC")
		} else {
			parts = append(parts, expr+" ASC")
		}
	}
	return " ORDER BY " + strings.Join(parts, ", "), nil
}
