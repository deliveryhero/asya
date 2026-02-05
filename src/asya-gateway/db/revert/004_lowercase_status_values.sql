-- Revert asya-gateway:004_lowercase_status_values from pg

BEGIN;

-- Revert to title case status values
UPDATE envelopes SET status = 'Pending' WHERE status = 'pending';
UPDATE envelopes SET status = 'Running' WHERE status = 'running';
UPDATE envelopes SET status = 'Succeeded' WHERE status = 'succeeded';
UPDATE envelopes SET status = 'Failed' WHERE status = 'failed';
UPDATE envelopes SET status = 'Unknown' WHERE status = 'unknown';

UPDATE envelope_updates SET status = 'Pending' WHERE status = 'pending';
UPDATE envelope_updates SET status = 'Running' WHERE status = 'running';
UPDATE envelope_updates SET status = 'Succeeded' WHERE status = 'succeeded';
UPDATE envelope_updates SET status = 'Failed' WHERE status = 'failed';
UPDATE envelope_updates SET status = 'Unknown' WHERE status = 'unknown';

-- Restore title case constraint
ALTER TABLE envelopes DROP CONSTRAINT IF EXISTS envelopes_status_check;
ALTER TABLE envelopes ADD CONSTRAINT envelopes_status_check
    CHECK (status IN ('Pending', 'Running', 'Succeeded', 'Failed', 'Unknown'));

COMMIT;
