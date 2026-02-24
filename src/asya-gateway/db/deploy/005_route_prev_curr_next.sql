-- Deploy asya-gateway:005_route_prev_curr_next to pg
-- Migrate route from {route_actors[], route_current int} to {route_prev[], route_curr text, route_next[]}

BEGIN;

-- tasks table: add new route columns
ALTER TABLE tasks
    ADD COLUMN route_prev  TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN route_curr  TEXT   NOT NULL DEFAULT '',
    ADD COLUMN route_next  TEXT[] NOT NULL DEFAULT '{}';

-- Migrate existing data from old columns to new columns.
-- PostgreSQL arrays are 1-indexed, route_current is 0-indexed.
-- route_actors[1:route_current]      -> route_prev  (actors already processed)
-- route_actors[route_current + 1]    -> route_curr  (actor currently being processed)
-- route_actors[route_current + 2:]   -> route_next  (actors remaining after curr)
UPDATE tasks SET
    route_prev = CASE
        WHEN route_current > 0 AND route_actors IS NOT NULL
        THEN route_actors[1:route_current]
        ELSE '{}'
    END,
    route_curr = COALESCE(
        CASE WHEN route_actors IS NOT NULL THEN route_actors[route_current + 1] END,
        ''
    ),
    route_next = CASE
        WHEN route_actors IS NOT NULL AND route_current + 2 <= array_length(route_actors, 1)
        THEN route_actors[route_current + 2:]
        ELSE '{}'
    END
WHERE route_actors IS NOT NULL;

-- Sync current_actor_name from route_curr for rows where it is not already set
UPDATE tasks SET current_actor_name = route_curr
WHERE route_curr != '' AND (current_actor_name IS NULL OR current_actor_name = '');

-- Drop old route columns
ALTER TABLE tasks
    DROP COLUMN IF EXISTS route_actors,
    DROP COLUMN IF EXISTS route_current,
    DROP COLUMN IF EXISTS current_actor_idx;

COMMIT;
