-- Deploy asya-gateway:003_add_parent_id to pg

BEGIN;

-- Add parent_id column to envelopes table for fanout traceability
ALTER TABLE envelopes
ADD COLUMN parent_id TEXT;

-- Index for finding all fanout children of a parent envelope
CREATE INDEX idx_envelopes_parent_id ON envelopes(parent_id) WHERE parent_id IS NOT NULL;

COMMIT;
