package stateproxypg

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// QueryRequest is the JSON body for POST /query.
type QueryRequest struct {
	Prefix string         `json:"prefix,omitempty"`
	Filter map[string]any `json:"filter,omitempty"`
	Sort   []string       `json:"sort,omitempty"`
	Limit  int            `json:"limit,omitempty"`
	Offset int            `json:"offset,omitempty"`
	Count  bool           `json:"count,omitempty"`
}

// QueryResponse is returned from POST /query.
type QueryResponse struct {
	Rows  []KVRow `json:"rows,omitempty"`
	Total int     `json:"total"`
}

// topLevelColumns are columns directly on the kv table (not inside value JSONB).
var topLevelColumns = map[string]bool{
	"key":        true,
	"created_at": true,
	"updated_at": true,
}

// buildFilterSQL constructs a parameterized SELECT query from a QueryRequest.
// Returns the SQL string and a slice of positional parameters.
func buildFilterSQL(req QueryRequest) (string, []any) {
	var conditions []string
	var args []any
	paramIdx := 1

	// Prefix filter on key column
	if req.Prefix != "" {
		conditions = append(conditions, fmt.Sprintf("key LIKE $%d", paramIdx))
		args = append(args, req.Prefix+"%")
		paramIdx++
	}

	// Build filter conditions from Mango-style filter map
	for field, val := range req.Filter {
		conds, newArgs, newIdx := buildFieldCondition(field, val, paramIdx)
		conditions = append(conditions, conds...)
		args = append(args, newArgs...)
		paramIdx = newIdx
	}

	// Build WHERE clause
	whereClause := ""
	if len(conditions) > 0 {
		whereClause = " WHERE " + strings.Join(conditions, " AND ")
	}

	// Build ORDER BY clause
	orderClause := ""
	if len(req.Sort) > 0 {
		var orderParts []string
		for _, s := range req.Sort {
			desc := false
			field := s
			if strings.HasPrefix(s, "-") {
				desc = true
				field = s[1:]
			}
			var col string
			if topLevelColumns[field] {
				col = field
			} else {
				col = fmt.Sprintf("value->>'%s'", field)
			}
			if desc {
				col += " DESC"
			} else {
				col += " ASC"
			}
			orderParts = append(orderParts, col)
		}
		orderClause = " ORDER BY " + strings.Join(orderParts, ", ")
	}

	// Build LIMIT/OFFSET clause
	limitClause := ""
	if req.Limit > 0 {
		limitClause = fmt.Sprintf(" LIMIT %d", req.Limit)
	}
	if req.Offset > 0 {
		limitClause += fmt.Sprintf(" OFFSET %d", req.Offset)
	}

	if req.Count {
		return "SELECT count(*) FROM kv" + whereClause, args
	}

	sql := "SELECT key, value, created_at, updated_at FROM kv" +
		whereClause + orderClause + limitClause

	return sql, args
}

// buildFieldCondition translates a single Mango field filter into SQL conditions.
func buildFieldCondition(field string, val any, paramIdx int) ([]string, []any, int) {
	var conditions []string
	var args []any

	// Check if val is an operator map (e.g., {"$gt": 50})
	opMap, isMap := val.(map[string]any)
	if !isMap {
		// Implicit $eq: use @> containment for simple equality
		jsonVal, _ := json.Marshal(map[string]any{field: val})
		conditions = append(conditions, fmt.Sprintf("value @> $%d::jsonb", paramIdx))
		args = append(args, string(jsonVal))
		paramIdx++
		return conditions, args, paramIdx
	}

	// Process each operator
	for op, operand := range opMap {
		switch op {
		case "$eq":
			jsonVal, _ := json.Marshal(map[string]any{field: operand})
			conditions = append(conditions, fmt.Sprintf("value @> $%d::jsonb", paramIdx))
			args = append(args, string(jsonVal))
			paramIdx++

		case "$ne":
			conditions = append(conditions, fmt.Sprintf("value->>'%s' != $%d", field, paramIdx))
			args = append(args, fmt.Sprintf("%v", operand))
			paramIdx++

		case "$gt":
			conditions = append(conditions, fmt.Sprintf("(value->>'%s')::numeric > $%d", field, paramIdx))
			args = append(args, operand)
			paramIdx++

		case "$gte":
			conditions = append(conditions, fmt.Sprintf("(value->>'%s')::numeric >= $%d", field, paramIdx))
			args = append(args, operand)
			paramIdx++

		case "$lt":
			conditions = append(conditions, fmt.Sprintf("(value->>'%s')::numeric < $%d", field, paramIdx))
			args = append(args, operand)
			paramIdx++

		case "$lte":
			conditions = append(conditions, fmt.Sprintf("(value->>'%s')::numeric <= $%d", field, paramIdx))
			args = append(args, operand)
			paramIdx++

		case "$in":
			conditions = append(conditions, fmt.Sprintf("value->>'%s' = ANY($%d)", field, paramIdx))
			args = append(args, toStringSlice(operand))
			paramIdx++

		case "$nin":
			conditions = append(conditions, fmt.Sprintf("NOT (value->>'%s' = ANY($%d))", field, paramIdx))
			args = append(args, toStringSlice(operand))
			paramIdx++

		case "$exists":
			b, _ := operand.(bool)
			if b {
				conditions = append(conditions, fmt.Sprintf("value ? '%s'", field))
			} else {
				conditions = append(conditions, fmt.Sprintf("NOT (value ? '%s')", field))
			}

		case "$contains":
			jsonVal, _ := json.Marshal(operand)
			conditions = append(conditions, fmt.Sprintf("value @> $%d::jsonb", paramIdx))
			args = append(args, string(jsonVal))
			paramIdx++
		}
	}

	return conditions, args, paramIdx
}

// toStringSlice converts an interface{} (expected []interface{}) to []string.
func toStringSlice(v any) []string {
	arr, ok := v.([]any)
	if !ok {
		return nil
	}
	result := make([]string, 0, len(arr))
	for _, item := range arr {
		result = append(result, fmt.Sprintf("%v", item))
	}
	return result
}

// Query executes a Mango-style filter query against the kv table.
func (c *Connector) Query(ctx context.Context, req QueryRequest) (*QueryResponse, error) {
	if req.Count {
		sql, args := buildFilterSQL(req)
		var total int
		err := c.pool.QueryRow(ctx, sql, args...).Scan(&total)
		if err != nil {
			return nil, fmt.Errorf("query count: %w", err)
		}
		return &QueryResponse{Total: total}, nil
	}

	sql, args := buildFilterSQL(req)
	rows, err := c.pool.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("query: %w", err)
	}
	defer rows.Close()

	var result []KVRow
	for rows.Next() {
		var kv KVRow
		if err := rows.Scan(&kv.Key, &kv.Value, &kv.CreatedAt, &kv.UpdatedAt); err != nil {
			return nil, fmt.Errorf("query scan: %w", err)
		}
		result = append(result, kv)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("query rows: %w", err)
	}

	return &QueryResponse{Rows: result, Total: len(result)}, nil
}
