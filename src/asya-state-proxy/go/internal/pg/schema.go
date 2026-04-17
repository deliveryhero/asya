package pg

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

// validFieldName matches simple field identifiers used in index expressions.
var validFieldName = regexp.MustCompile(`^[a-zA-Z_][a-zA-Z0-9_]*$`)

// validCastExpr matches cast expressions like (field_name)::type.
var validCastExpr = regexp.MustCompile(`^\([a-zA-Z_][a-zA-Z0-9_]*\)::[a-zA-Z]+$`)

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

		var sqlExpr, idxName string

		if strings.HasPrefix(expr, "(") {
			// Cast expression: (field)::type
			if !validCastExpr.MatchString(expr) {
				return fmt.Errorf("invalid index expression: %q", expr)
			}
			closeParen := strings.Index(expr, ")")
			field := expr[1:closeParen]
			castType := expr[closeParen+3:] // skip ")::""
			idxName = "idx_kv_expr_" + field
			sqlExpr = fmt.Sprintf("((value->>'%s')::%s)", field, castType)
		} else {
			// Simple field: value->>'field'
			if !validFieldName.MatchString(expr) {
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
		if _, err := pool.Exec(ctx, sql); err != nil { // nosemgrep -- idxName and sqlExpr validated by regex
			return fmt.Errorf("create index %s: %w", idxName, err)
		}
	}
	return nil
}
