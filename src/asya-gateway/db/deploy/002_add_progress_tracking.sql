-- Deploy asya-gateway:002_add_progress_tracking to pg

BEGIN;

-- Add progress tracking to jobs table
ALTER TABLE jobs
ADD COLUMN progress_percent DECIMAL(5,2) DEFAULT 0.0 CHECK (progress_percent >= 0 AND progress_percent <= 100),
ADD COLUMN current_step TEXT,
ADD COLUMN steps_completed INTEGER DEFAULT 0 CHECK (steps_completed >= 0),
ADD COLUMN total_steps INTEGER DEFAULT 0 CHECK (total_steps >= 0);

-- Add progress info to job_updates table
ALTER TABLE job_updates
ADD COLUMN progress_percent DECIMAL(5,2),
ADD COLUMN step TEXT,
ADD COLUMN step_status TEXT CHECK (step_status IS NULL OR step_status IN ('received', 'processing', 'completed'));

-- Index for progress queries
CREATE INDEX idx_jobs_progress ON jobs(progress_percent) WHERE progress_percent < 100;

COMMIT;
