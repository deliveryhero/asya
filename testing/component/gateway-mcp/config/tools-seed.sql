-- Seed test tools for gateway-mcp component tests.
-- Matches the tools previously defined in config/tools.yml.

INSERT INTO tools (name, actor, route_next, description, parameters, progress) VALUES
('echo', 'echo', '{}',
 'Echo tool for testing - returns input payload',
 '{"type":"object","properties":{"message":{"type":"string","description":"Message to echo back"}},"required":["message"]}',
 false),

('test_progress', 'echo', '{}',
 'Test tool with progress reporting',
 '{"type":"object","properties":{"value":{"type":"number","description":"Test value"}},"required":["value"]}',
 true),

('test_validation', 'echo', '{}',
 'Test parameter validation',
 '{"type":"object","properties":{"required_string":{"type":"string","description":"Required string parameter"},"optional_number":{"type":"number","description":"Optional number parameter"},"boolean_flag":{"type":"boolean","description":"Optional boolean flag"}},"required":["required_string"]}',
 false)

ON CONFLICT (name) DO UPDATE SET
  actor = EXCLUDED.actor,
  route_next = EXCLUDED.route_next,
  description = EXCLUDED.description,
  parameters = EXCLUDED.parameters,
  progress = EXCLUDED.progress;
