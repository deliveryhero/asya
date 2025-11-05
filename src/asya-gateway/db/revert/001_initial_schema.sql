-- Revert asya-gateway:001_initial_schema from pg

BEGIN;

DROP TRIGGER IF EXISTS update_jobs_updated_at ON jobs;
DROP FUNCTION IF EXISTS update_updated_at_column();
DROP TABLE IF EXISTS job_updates;
DROP TABLE IF EXISTS jobs;

COMMIT;
