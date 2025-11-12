-- Revert asya-gateway:001_initial_schema from pg

BEGIN;

DROP TRIGGER IF EXISTS update_envelopes_updated_at ON envelopes;
DROP FUNCTION IF EXISTS update_updated_at_column();
DROP TABLE IF EXISTS envelope_updates;
DROP TABLE IF EXISTS envelopes;

COMMIT;
