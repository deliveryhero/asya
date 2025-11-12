-- Deploy asya-gateway:001_initial_schema to pg

BEGIN;

-- Envelopes table
CREATE TABLE IF NOT EXISTS envelopes (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'unknown')),
    route_actors TEXT[] NOT NULL,
    route_current INTEGER NOT NULL DEFAULT 0,
    payload JSONB,
    result JSONB,
    error TEXT,
    timeout_sec INTEGER,
    deadline TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_envelopes_status ON envelopes(status);
CREATE INDEX IF NOT EXISTS idx_envelopes_created_at ON envelopes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_envelopes_updated_at ON envelopes(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_envelopes_deadline ON envelopes(deadline) WHERE deadline IS NOT NULL;

-- Envelope updates table for SSE streaming
CREATE TABLE IF NOT EXISTS envelope_updates (
    id BIGSERIAL PRIMARY KEY,
    envelope_id TEXT NOT NULL REFERENCES envelopes(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    message TEXT,
    result JSONB,
    error TEXT,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for envelope_updates
CREATE INDEX IF NOT EXISTS idx_envelope_updates_envelope_id ON envelope_updates(envelope_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_envelope_updates_timestamp ON envelope_updates(timestamp DESC);

-- Function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for envelopes table
DROP TRIGGER IF EXISTS update_envelopes_updated_at ON envelopes;
CREATE TRIGGER update_envelopes_updated_at
    BEFORE UPDATE ON envelopes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMIT;
