BEGIN;

CREATE TABLE oauth_clients (
    client_id     TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    client_name   TEXT NOT NULL DEFAULT '',
    redirect_uris TEXT[] NOT NULL DEFAULT '{}',
    scope         TEXT NOT NULL DEFAULT 'mcp:invoke mcp:read',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE oauth_authorization_codes (
    code                   TEXT PRIMARY KEY,
    client_id              TEXT NOT NULL REFERENCES oauth_clients (client_id) ON DELETE CASCADE,
    redirect_uri           TEXT NOT NULL,
    scope                  TEXT NOT NULL,
    code_challenge         TEXT NOT NULL,
    code_challenge_method  TEXT NOT NULL DEFAULT 'S256',
    expires_at             TIMESTAMPTZ NOT NULL,
    used_at                TIMESTAMPTZ
);

CREATE TABLE oauth_refresh_tokens (
    token_hash  TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL REFERENCES oauth_clients (client_id) ON DELETE CASCADE,
    scope       TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ
);

COMMIT;
