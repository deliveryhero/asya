-- Deploy asya-gateway:002_add_progress_tracking to pg

BEGIN;

-- Add progress tracking to envelopes table
ALTER TABLE envelopes
ADD COLUMN progress_percent DECIMAL(5,2) DEFAULT 0.0 CHECK (progress_percent >= 0 AND progress_percent <= 100),
ADD COLUMN current_actor_idx INTEGER DEFAULT 0,
ADD COLUMN current_actor_name TEXT,
ADD COLUMN message TEXT,
ADD COLUMN actors_completed INTEGER DEFAULT 0 CHECK (actors_completed >= 0),
ADD COLUMN total_actors INTEGER DEFAULT 0 CHECK (total_actors >= 0);

-- Add progress info to envelope_updates table
ALTER TABLE envelope_updates
ADD COLUMN progress_percent DECIMAL(5,2),
ADD COLUMN actor TEXT,
ADD COLUMN envelope_state TEXT CHECK (envelope_state IS NULL OR envelope_state IN ('received', 'processing', 'completed'));

-- Index for progress queries
CREATE INDEX idx_envelopes_progress ON envelopes(progress_percent) WHERE progress_percent < 100;

COMMIT;
