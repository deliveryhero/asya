BEGIN;

SELECT name, actor, description, parameters, timeout_sec, progress,
       mcp_enabled, a2a_enabled, a2a_tags, a2a_input_modes,
       a2a_output_modes, route_next, a2a_examples, created_at, updated_at
  FROM tools
 WHERE FALSE;

ROLLBACK;
