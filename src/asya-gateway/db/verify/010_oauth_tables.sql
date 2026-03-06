BEGIN;

SELECT client_id, client_name, redirect_uris, scope, created_at
  FROM oauth_clients
 WHERE FALSE;

SELECT code, client_id, redirect_uri, scope, code_challenge, code_challenge_method, expires_at, used_at
  FROM oauth_authorization_codes
 WHERE FALSE;

SELECT token_hash, client_id, scope, expires_at, revoked_at
  FROM oauth_refresh_tokens
 WHERE FALSE;

ROLLBACK;
