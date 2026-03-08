-- Verify asya-gateway:011_drop_tools_table on pg
-- Confirm the tools table no longer exists.

SELECT CASE
    WHEN EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'tools'
    )
    THEN 1/0  -- table still exists: fail
    ELSE 1    -- table gone: pass
END;
