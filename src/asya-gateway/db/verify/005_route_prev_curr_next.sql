-- Verify asya-gateway:005_route_prev_curr_next on pg

BEGIN;

-- Verify new columns exist in tasks table
SELECT id, status, route_prev, route_curr, route_next, created_at, updated_at
FROM tasks WHERE FALSE;

-- Verify new columns exist (1/COUNT(*) errors with division by zero if column is absent)
SELECT 1/COUNT(*) FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'tasks' AND column_name = 'route_prev';

SELECT 1/COUNT(*) FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'tasks' AND column_name = 'route_curr';

SELECT 1/COUNT(*) FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'tasks' AND column_name = 'route_next';

ROLLBACK;
