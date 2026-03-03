package toolstore

import (
	"context"
	"fmt"
	"sync/atomic"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Registry manages tools with an in-memory cache and optional DB persistence.
type Registry struct {
	pool  *pgxpool.Pool
	cache atomic.Value // *[]Tool
}

// NewInMemoryRegistry creates a registry without database persistence (for tests).
func NewInMemoryRegistry() *Registry {
	r := &Registry{}
	r.cache.Store(&[]Tool{})
	return r
}

// NewRegistry creates a DB-backed registry and loads all tools from the database.
func NewRegistry(ctx context.Context, pool *pgxpool.Pool) (*Registry, error) {
	r := &Registry{
		pool: pool,
	}

	// Load initial tools from database
	if err := r.Refresh(ctx); err != nil {
		return nil, fmt.Errorf("failed to load tools: %w", err)
	}

	return r, nil
}

// Upsert validates and persists a tool, then refreshes the cache.
func (r *Registry) Upsert(ctx context.Context, tool Tool) error {
	// Validation
	if tool.Name == "" {
		return fmt.Errorf("tool name is required")
	}
	if tool.Actor == "" {
		return fmt.Errorf("tool actor is required")
	}

	// Persist to DB if available
	if r.pool != nil {
		query := `
			INSERT INTO tools (
				name, actor, description, parameters, timeout_sec, progress,
				mcp_enabled, a2a_enabled, a2a_tags, a2a_input_modes, a2a_output_modes, a2a_examples
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
			ON CONFLICT (name) DO UPDATE SET
				actor = EXCLUDED.actor,
				description = EXCLUDED.description,
				parameters = EXCLUDED.parameters,
				timeout_sec = EXCLUDED.timeout_sec,
				progress = EXCLUDED.progress,
				mcp_enabled = EXCLUDED.mcp_enabled,
				a2a_enabled = EXCLUDED.a2a_enabled,
				a2a_tags = EXCLUDED.a2a_tags,
				a2a_input_modes = EXCLUDED.a2a_input_modes,
				a2a_output_modes = EXCLUDED.a2a_output_modes,
				a2a_examples = EXCLUDED.a2a_examples
		`

		_, err := r.pool.Exec(ctx, query,
			tool.Name,
			tool.Actor,
			tool.Description,
			tool.Parameters,
			tool.TimeoutSec,
			tool.Progress,
			tool.MCPEnabled,
			tool.A2AEnabled,
			tool.A2ATags,
			tool.A2AInputModes,
			tool.A2AOutputModes,
			tool.A2AExamples,
		)
		if err != nil {
			return fmt.Errorf("failed to upsert tool: %w", err)
		}

		// Reload from DB to get updated timestamps
		return r.Refresh(ctx)
	}

	// In-memory only - add or update in cache
	tools := r.All()
	newTools := make([]Tool, 0, len(tools)+1)
	found := false

	for _, t := range tools {
		if t.Name == tool.Name {
			newTools = append(newTools, tool)
			found = true
		} else {
			newTools = append(newTools, t)
		}
	}

	if !found {
		newTools = append(newTools, tool)
	}

	r.cache.Store(&newTools)
	return nil
}

// Refresh reloads all tools from the database into the cache.
func (r *Registry) Refresh(ctx context.Context) error {
	if r.pool == nil {
		return nil
	}

	query := `
		SELECT name, actor, description, parameters, timeout_sec, progress,
			   mcp_enabled, a2a_enabled, a2a_tags, a2a_input_modes, a2a_output_modes, a2a_examples,
			   created_at, updated_at
		FROM tools
		ORDER BY name
	`

	rows, err := r.pool.Query(ctx, query)
	if err != nil {
		return fmt.Errorf("failed to query tools: %w", err)
	}
	defer rows.Close()

	tools := make([]Tool, 0)
	for rows.Next() {
		var t Tool
		if err := rows.Scan(
			&t.Name,
			&t.Actor,
			&t.Description,
			&t.Parameters,
			&t.TimeoutSec,
			&t.Progress,
			&t.MCPEnabled,
			&t.A2AEnabled,
			&t.A2ATags,
			&t.A2AInputModes,
			&t.A2AOutputModes,
			&t.A2AExamples,
			&t.CreatedAt,
			&t.UpdatedAt,
		); err != nil {
			return fmt.Errorf("failed to scan tool: %w", err)
		}
		tools = append(tools, t)
	}

	if err := rows.Err(); err != nil {
		return fmt.Errorf("error iterating tools: %w", err)
	}

	r.cache.Store(&tools)
	return nil
}

// All returns all tools from the cache.
func (r *Registry) All() []Tool {
	val := r.cache.Load()
	if val == nil {
		return nil
	}
	tools, ok := val.(*[]Tool)
	if !ok {
		return nil
	}
	return *tools
}

// GetByName returns a tool by name, or nil if not found.
func (r *Registry) GetByName(name string) *Tool {
	for _, t := range r.All() {
		if t.Name == name {
			return &t
		}
	}
	return nil
}

// MCPTools returns all tools with MCP enabled.
func (r *Registry) MCPTools() []Tool {
	all := r.All()
	result := make([]Tool, 0, len(all))
	for _, t := range all {
		if t.MCPEnabled {
			result = append(result, t)
		}
	}
	return result
}

// A2ASkills returns all tools with A2A enabled.
func (r *Registry) A2ASkills() []Tool {
	all := r.All()
	result := make([]Tool, 0, len(all))
	for _, t := range all {
		if t.A2AEnabled {
			result = append(result, t)
		}
	}
	return result
}
