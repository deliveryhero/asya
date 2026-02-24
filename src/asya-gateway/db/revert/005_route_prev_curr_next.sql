-- Revert asya-gateway:005_route_prev_curr_next from pg

BEGIN;

-- Re-add old route columns
ALTER TABLE tasks
    ADD COLUMN route_actors  TEXT[]  NOT NULL DEFAULT '{}',
    ADD COLUMN route_current INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN current_actor_idx INTEGER DEFAULT 0;

-- Restore data from new columns back to old format.
-- route_prev || [route_curr] || route_next -> route_actors
-- len(route_prev) -> route_current (0-based index of curr in the combined array)
UPDATE tasks SET
    route_actors = CASE
        WHEN route_curr != ''
        THEN route_prev || ARRAY[route_curr] || route_next
        ELSE route_prev
    END,
    route_current = array_length(route_prev, 1),
    current_actor_idx = array_length(route_prev, 1);

-- Drop new route columns
ALTER TABLE tasks
    DROP COLUMN IF EXISTS route_prev,
    DROP COLUMN IF EXISTS route_curr,
    DROP COLUMN IF EXISTS route_next;

COMMIT;
