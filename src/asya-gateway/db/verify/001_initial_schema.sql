-- Verify asya-gateway:001_initial_schema on pg

BEGIN;

-- Verify tables exist
SELECT id, status, route_actors, route_current, payload, result, error, timeout_sec, deadline, created_at, updated_at
FROM envelopes WHERE FALSE;

SELECT id, envelope_id, status, message, result, error, timestamp
FROM envelope_updates WHERE FALSE;

-- Verify indexes exist
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'envelopes' AND indexname = 'idx_envelopes_status';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'envelopes' AND indexname = 'idx_envelopes_created_at';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'envelopes' AND indexname = 'idx_envelopes_updated_at';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'envelopes' AND indexname = 'idx_envelopes_deadline';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'envelope_updates' AND indexname = 'idx_envelope_updates_envelope_id';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'envelope_updates' AND indexname = 'idx_envelope_updates_timestamp';

-- Verify function exists
SELECT 1/COUNT(*) FROM pg_proc WHERE proname = 'update_updated_at_column';

ROLLBACK;
