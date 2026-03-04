-- Seed test tools into the tools table for integration tests.
-- Matches the tools previously defined in gateway-routes.yaml.

INSERT INTO tools (name, actor, route_next, description, parameters, timeout_sec, progress) VALUES
('test_echo', 'test-echo', '{}',
 'Echo back the input message',
 '{"type":"object","properties":{"message":{"type":"string","description":"Message to echo"}},"required":["message"]}',
 30, true),

('test_pipeline', 'test-doubler', '{test-incrementer}',
 'Test multi-actor pipeline processing',
 '{"type":"object","properties":{"value":{"type":"integer","description":"Value to process through pipeline"}},"required":["value"]}',
 45, true),

('test_error', 'test-error', '{}',
 'Test error handling and error reporting',
 '{"type":"object","properties":{"should_fail":{"type":"boolean","description":"Whether the handler should fail"}}}',
 30, true),

('test_timeout', 'test-timeout', '{}',
 'Test timeout handling',
 '{"type":"object","properties":{"sleep_seconds":{"type":"integer","description":"How long to sleep (should exceed timeout)"}}}',
 10, true),

('test_fanout', 'test-fanout', '{}',
 'Test fan-out array response',
 '{"type":"object","properties":{"count":{"type":"integer","description":"Number of items to fan out"}}}',
 30, true),

('test_empty_response', 'test-empty', '{}',
 'Test empty/null payload handling',
 '{"type":"object","properties":{"message":{"type":"string","description":"Test message"}}}',
 30, true),

('test_unicode', 'test-unicode', '{}',
 'Test Unicode payload handling',
 '{"type":"object","properties":{"message":{"type":"string","description":"Unicode message"}},"required":["message"]}',
 30, true),

('test_large_payload', 'test-large-payload', '{}',
 'Test large payload processing',
 '{"type":"object","properties":{"size_kb":{"type":"integer","description":"Payload size in KB"}}}',
 30, true),

('test_nested_data', 'test-nested', '{}',
 'Test deeply nested JSON structures',
 '{"type":"object","properties":{"message":{"type":"string","description":"Test message"}}}',
 30, true),

('test_null_values', 'test-null', '{}',
 'Test null/None value handling',
 '{"type":"object","properties":{"message":{"type":"string","description":"Test message"}}}',
 30, true),

('test_slow_boundary', 'test-slow-boundary', '{}',
 'Test timeout boundary condition (1.5s processing, adequate timeout with overhead)',
 '{"type":"object","properties":{"first_call":{"type":"boolean","description":"Is this the first call"}}}',
 10, true),

('test_cyclic_route', 'test-cycle', '{test-cycle,test-cycle}',
 'Test cyclic route detection',
 '{"type":"object","properties":{"message":{"type":"string","description":"Test message"}}}',
 30, true),

('test_param_flow', 'test-param-flow-1', '{test-param-flow-2}',
 'Test that multi-actor pipelines pass outputs correctly',
 '{"type":"object","properties":{"original_param":{"type":"string","description":"Original parameter to track"},"number":{"type":"integer","description":"Number to transform"}},"required":["original_param"]}',
 45, true),

('test_streaming', 'test-streaming', '{}',
 'Test streaming partial events (upstream) from generator handler',
 '{"type":"object","properties":{"token_count":{"type":"integer","description":"Number of partial tokens to stream"}}}',
 30, true),

('test_streaming_error', 'test-streaming-error', '{}',
 'Test mid-stream error during partial event streaming',
 '{"type":"object"}',
 30, true),

('test_pause_resume', 'test-echo', '{x-pause,test-incrementer}',
 'Test pause/resume flow with echo actor before pause',
 '{"type":"object","properties":{"message":{"type":"string","description":"Message to echo before pausing"},"value":{"type":"integer","description":"Optional value for incrementer pipeline stage"}},"required":["message"]}',
 60, true),

('test_sla_backstop', 'test-timeout', '{}',
 'Test gateway backstop fires before actor processes message',
 '{"type":"object","properties":{"sleep_seconds":{"type":"integer","description":"How long handler sleeps (must exceed gateway timeout)"}}}',
 3, true)

ON CONFLICT (name) DO UPDATE SET
  actor = EXCLUDED.actor,
  route_next = EXCLUDED.route_next,
  description = EXCLUDED.description,
  parameters = EXCLUDED.parameters,
  timeout_sec = EXCLUDED.timeout_sec,
  progress = EXCLUDED.progress;
