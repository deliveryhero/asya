-- Verify asya-gateway:004_lowercase_status_values on pg

BEGIN;

-- Verify constraint exists with lowercase values
SELECT 1/COUNT(*)
FROM pg_constraint
WHERE conname = 'envelopes_status_check'
AND pg_get_constraintdef(oid) LIKE '%pending%';

ROLLBACK;
