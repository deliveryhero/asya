-- Deploy asya-gateway:011_drop_tools_table to pg
-- Tools are now configured via ConfigMap-based flow registry (flows.yaml).
-- The tools table is no longer used by the gateway.

BEGIN;

DROP TABLE IF EXISTS tools;

COMMIT;
