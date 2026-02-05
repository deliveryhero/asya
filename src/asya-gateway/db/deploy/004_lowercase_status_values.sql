-- Deploy asya-gateway:004_lowercase_status_values to pg
-- Migrate status values from title case to lowercase for MCP compliance

BEGIN;

-- Update existing envelope status values to lowercase
UPDATE envelopes SET status = 'pending' WHERE status = 'Pending';
UPDATE envelopes SET status = 'running' WHERE status = 'Running';
UPDATE envelopes SET status = 'succeeded' WHERE status = 'Succeeded';
UPDATE envelopes SET status = 'failed' WHERE status = 'Failed';
UPDATE envelopes SET status = 'unknown' WHERE status = 'Unknown';

-- Update existing envelope_updates status values to lowercase
UPDATE envelope_updates SET status = 'pending' WHERE status = 'Pending';
UPDATE envelope_updates SET status = 'running' WHERE status = 'Running';
UPDATE envelope_updates SET status = 'succeeded' WHERE status = 'Succeeded';
UPDATE envelope_updates SET status = 'failed' WHERE status = 'Failed';
UPDATE envelope_updates SET status = 'unknown' WHERE status = 'Unknown';

-- Drop old constraint and add new one with lowercase values
ALTER TABLE envelopes DROP CONSTRAINT IF EXISTS envelopes_status_check;
ALTER TABLE envelopes ADD CONSTRAINT envelopes_status_check
    CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'unknown'));

COMMIT;
