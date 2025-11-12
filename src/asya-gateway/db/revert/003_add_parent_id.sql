-- Revert asya-gateway:003_add_parent_id from pg

BEGIN;

-- Drop parent_id column from envelopes table
DROP INDEX IF EXISTS idx_envelopes_parent_id;
ALTER TABLE envelopes DROP COLUMN IF EXISTS parent_id;

COMMIT;
