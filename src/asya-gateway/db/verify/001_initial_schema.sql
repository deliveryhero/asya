-- Verify asya-gateway:001_initial_schema on pg

BEGIN;

-- Verify tables exist
SELECT id, status, route_steps, route_current, payload, result, error, timeout_sec, deadline, created_at, updated_at
FROM jobs WHERE FALSE;

SELECT id, job_id, status, message, result, error, timestamp
FROM job_updates WHERE FALSE;

-- Verify indexes exist
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'jobs' AND indexname = 'idx_jobs_status';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'jobs' AND indexname = 'idx_jobs_created_at';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'jobs' AND indexname = 'idx_jobs_updated_at';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'jobs' AND indexname = 'idx_jobs_deadline';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'job_updates' AND indexname = 'idx_job_updates_job_id';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'job_updates' AND indexname = 'idx_job_updates_timestamp';

-- Verify function exists
SELECT 1/COUNT(*) FROM pg_proc WHERE proname = 'update_updated_at_column';

ROLLBACK;
