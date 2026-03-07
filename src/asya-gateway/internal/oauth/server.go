// Package oauth implements the MCP OAuth 2.1 authorization server (Phase 3).
// The gateway acts as both authorization server and resource server, issuing
// self-signed HMAC-SHA256 JWTs that MCPAuthMiddleware validates.
package oauth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Config holds OAuth server configuration.
type Config struct {
	// Issuer is the OAuth authorization server issuer URL (ASYA_MCP_OAUTH_ISSUER).
	Issuer string
	// Secret is the HMAC-SHA256 signing key for access tokens (ASYA_MCP_OAUTH_SECRET).
	Secret []byte
	// TokenTTL is the access token lifetime. Defaults to 3600 seconds.
	TokenTTL time.Duration
	// RefreshTTL is the refresh token lifetime. Defaults to 30 days.
	RefreshTTL time.Duration
	// RegistrationToken optionally protects /oauth/register.
	// When non-empty, clients must send Authorization: Bearer <RegistrationToken>
	// to register. When empty, registration is open (suitable only if network-restricted).
	RegistrationToken string
}

// Server is the MCP OAuth 2.1 authorization server.
// It issues HMAC-SHA256 JWTs and stores clients, codes, and refresh tokens in PostgreSQL.
type Server struct {
	cfg  Config
	pool *pgxpool.Pool
}

// NewServer creates a new OAuth server backed by the given PostgreSQL pool.
func NewServer(pool *pgxpool.Pool, cfg Config) (*Server, error) {
	if cfg.Issuer == "" {
		return nil, fmt.Errorf("oauth: Issuer is required")
	}
	if len(cfg.Secret) == 0 {
		return nil, fmt.Errorf("oauth: Secret is required")
	}
	if cfg.TokenTTL == 0 {
		cfg.TokenTTL = 3600 * time.Second
	}
	if cfg.RefreshTTL == 0 {
		cfg.RefreshTTL = 30 * 24 * time.Hour
	}
	return &Server{cfg: cfg, pool: pool}, nil
}

// --- RFC 9728: Protected Resource Metadata ---

// HandleProtectedResourceMetadata serves /.well-known/oauth-protected-resource.
// Tells MCP clients which authorization server protects this resource.
func (s *Server) HandleProtectedResourceMetadata(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, map[string]any{
		"resource":              s.cfg.Issuer,
		"authorization_servers": []string{s.cfg.Issuer},
	})
}

// --- RFC 8414: Authorization Server Metadata ---

// HandleServerMetadata serves /.well-known/oauth-authorization-server.
func (s *Server) HandleServerMetadata(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, map[string]any{
		"issuer":                                s.cfg.Issuer,
		"authorization_endpoint":                s.cfg.Issuer + "/oauth/authorize",
		"token_endpoint":                        s.cfg.Issuer + "/oauth/token",
		"registration_endpoint":                 s.cfg.Issuer + "/oauth/register",
		"scopes_supported":                      []string{"mcp:invoke", "mcp:read"},
		"response_types_supported":              []string{"code"},
		"grant_types_supported":                 []string{"authorization_code", "refresh_token"},
		"code_challenge_methods_supported":      []string{"S256"},
		"token_endpoint_auth_methods_supported": []string{"none"},
	})
}

// --- RFC 7591: Dynamic Client Registration ---

type registerRequest struct {
	ClientName   string   `json:"client_name"`
	RedirectURIs []string `json:"redirect_uris"`
	Scope        string   `json:"scope"`
}

type registerResponse struct {
	ClientID     string   `json:"client_id"`
	ClientName   string   `json:"client_name"`
	RedirectURIs []string `json:"redirect_uris"`
	Scope        string   `json:"scope"`
}

// HandleRegister handles POST /oauth/register (Dynamic Client Registration).
// When Config.RegistrationToken is set, the request must carry
// Authorization: Bearer <RegistrationToken>.
func (s *Server) HandleRegister(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Protect registration when a token is configured.
	if s.cfg.RegistrationToken != "" {
		authHeader := r.Header.Get("Authorization")
		provided := strings.TrimPrefix(authHeader, "Bearer ")
		if !strings.HasPrefix(authHeader, "Bearer ") || subtle.ConstantTimeCompare([]byte(provided), []byte(s.cfg.RegistrationToken)) != 1 {
			w.Header().Set("WWW-Authenticate", `Bearer realm="asya-gateway"`)
			writeOAuthError(w, http.StatusUnauthorized, "unauthorized_client", "registration token required")
			return
		}
	}

	// Limit body to 1 MiB to prevent DoS via large payloads.
	r.Body = http.MaxBytesReader(w, r.Body, 1024*1024)
	var req registerRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeOAuthError(w, http.StatusBadRequest, "invalid_request", "invalid JSON body")
		return
	}

	if len(req.RedirectURIs) == 0 {
		writeOAuthError(w, http.StatusBadRequest, "invalid_client_metadata", "redirect_uris is required")
		return
	}

	// Only allow supported scopes; default to all if none requested.
	scope := intersectScopes(req.Scope, "mcp:invoke mcp:read")
	if scope == "" {
		scope = "mcp:invoke mcp:read"
	}

	clientID, err := s.insertClient(r.Context(), req.ClientName, req.RedirectURIs, scope)
	if err != nil {
		slog.Error("oauth: failed to register client", "error", err)
		writeOAuthError(w, http.StatusInternalServerError, "server_error", "failed to register client")
		return
	}

	w.WriteHeader(http.StatusCreated)
	writeJSON(w, registerResponse{
		ClientID:     clientID,
		ClientName:   req.ClientName,
		RedirectURIs: req.RedirectURIs,
		Scope:        scope,
	})
}

// --- Authorization Endpoint ---

// HandleAuthorize handles GET/POST /oauth/authorize.
// Auto-approves registered public clients (no user login UI — gateway is machine-to-machine).
func (s *Server) HandleAuthorize(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	clientID := q.Get("client_id")
	redirectURI := q.Get("redirect_uri")
	responseType := q.Get("response_type")
	codeChallenge := q.Get("code_challenge")
	codeChallengeMethod := q.Get("code_challenge_method")
	state := q.Get("state")
	scope := q.Get("scope")

	if responseType != "code" {
		writeOAuthError(w, http.StatusBadRequest, "unsupported_response_type", "only 'code' is supported")
		return
	}
	if codeChallenge == "" || codeChallengeMethod != "S256" {
		writeOAuthError(w, http.StatusBadRequest, "invalid_request", "code_challenge (S256) is required")
		return
	}

	client, err := s.findClient(r.Context(), clientID)
	if err != nil || client == nil {
		writeOAuthError(w, http.StatusBadRequest, "invalid_client", "unknown client_id")
		return
	}

	// Look up the canonical redirect URI from the DB-sourced registered list.
	// Using the registered value (not the raw query param) breaks the taint chain
	// for static analysis: the URL we parse comes from the database, not user input.
	registeredURI := findRegisteredURI(client.RedirectURIs, redirectURI)
	if registeredURI == "" {
		writeOAuthError(w, http.StatusBadRequest, "invalid_request", "redirect_uri not registered")
		return
	}

	// Intersect requested scopes with client's registered scopes.
	if scope != "" {
		scope = intersectScopes(scope, client.Scope)
		if scope == "" {
			writeOAuthError(w, http.StatusBadRequest, "invalid_scope", "no valid scopes in request")
			return
		}
	} else {
		scope = client.Scope
	}

	// Issue authorization code (auto-approve for machine clients)
	code := mustGenerateToken(32)
	expires := time.Now().Add(5 * time.Minute)
	if err := s.insertAuthCode(r.Context(), code, clientID, registeredURI, scope, codeChallenge, codeChallengeMethod, expires); err != nil {
		slog.Error("oauth: failed to insert auth code", "error", err)
		writeOAuthError(w, http.StatusInternalServerError, "server_error", "failed to issue code")
		return
	}

	u, err := url.Parse(registeredURI)
	if err != nil {
		slog.Error("oauth: registered redirect_uri is not a valid URL", "uri", registeredURI, "error", err)
		writeOAuthError(w, http.StatusInternalServerError, "server_error", "invalid redirect_uri configuration")
		return
	}
	params := u.Query()
	params.Set("code", code)
	if state != "" {
		params.Set("state", state)
	}
	u.RawQuery = params.Encode()
	// Set Location directly instead of http.Redirect to avoid taint-analysis false
	// positives: u is built from client.RedirectURIs (DB-sourced) and is always
	// absolute, so r is not needed for relative-URL resolution.
	w.Header().Set("Location", u.String())
	w.WriteHeader(http.StatusFound)
}

// --- Token Endpoint ---

// HandleToken handles POST /oauth/token.
func (s *Server) HandleToken(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	if err := r.ParseForm(); err != nil {
		writeOAuthError(w, http.StatusBadRequest, "invalid_request", "failed to parse form")
		return
	}

	switch r.FormValue("grant_type") {
	case "authorization_code":
		s.handleCodeExchange(w, r)
	case "refresh_token":
		s.handleRefreshToken(w, r)
	default:
		writeOAuthError(w, http.StatusBadRequest, "unsupported_grant_type", "supported: authorization_code, refresh_token")
	}
}

func (s *Server) handleCodeExchange(w http.ResponseWriter, r *http.Request) {
	code := r.FormValue("code")
	clientID := r.FormValue("client_id")
	redirectURI := r.FormValue("redirect_uri")
	codeVerifier := r.FormValue("code_verifier")

	// consumeAuthCode atomically validates and marks the code as used (UPDATE ... RETURNING),
	// preventing TOCTOU race conditions with concurrent token requests.
	authCode, err := s.consumeAuthCode(r.Context(), code)
	if err != nil || authCode == nil {
		writeOAuthError(w, http.StatusBadRequest, "invalid_grant", "invalid or expired code")
		return
	}
	if authCode.ClientID != clientID {
		writeOAuthError(w, http.StatusBadRequest, "invalid_grant", "client_id mismatch")
		return
	}
	if authCode.RedirectURI != redirectURI {
		writeOAuthError(w, http.StatusBadRequest, "invalid_grant", "redirect_uri mismatch")
		return
	}
	if !VerifyCodeChallenge(codeVerifier, authCode.CodeChallenge, authCode.CodeChallengeMethod) {
		writeOAuthError(w, http.StatusBadRequest, "invalid_grant", "code_verifier does not match challenge")
		return
	}

	s.issueTokenResponse(w, r.Context(), clientID, authCode.Scope)
}

func (s *Server) handleRefreshToken(w http.ResponseWriter, r *http.Request) {
	rawToken := r.FormValue("refresh_token")
	clientID := r.FormValue("client_id")

	// consumeRefreshToken atomically revokes the token and returns its data,
	// preventing TOCTOU race conditions with concurrent refresh requests.
	tokenHash := hashToken(rawToken)
	rt, err := s.consumeRefreshToken(r.Context(), tokenHash)
	if err != nil || rt == nil {
		writeOAuthError(w, http.StatusBadRequest, "invalid_grant", "invalid or expired refresh token")
		return
	}
	if rt.ClientID != clientID {
		writeOAuthError(w, http.StatusBadRequest, "invalid_grant", "client_id mismatch")
		return
	}

	s.issueTokenResponse(w, r.Context(), clientID, rt.Scope)
}

func (s *Server) issueTokenResponse(w http.ResponseWriter, ctx context.Context, clientID, scope string) {
	accessToken, err := s.issueAccessToken(clientID, scope)
	if err != nil {
		slog.Error("oauth: failed to issue access token", "error", err)
		writeOAuthError(w, http.StatusInternalServerError, "server_error", "failed to issue token")
		return
	}

	refreshToken, err := s.insertNewRefreshToken(ctx, clientID, scope)
	if err != nil {
		slog.Error("oauth: failed to issue refresh token", "error", err)
		writeOAuthError(w, http.StatusInternalServerError, "server_error", "failed to issue refresh token")
		return
	}

	writeJSON(w, map[string]any{
		"access_token":  accessToken,
		"token_type":    "Bearer",
		"expires_in":    int(s.cfg.TokenTTL.Seconds()),
		"refresh_token": refreshToken,
		"scope":         scope,
	})
}

func (s *Server) issueAccessToken(clientID, scope string) (string, error) {
	now := time.Now()
	claims := jwt.MapClaims{
		"iss":   s.cfg.Issuer,
		"aud":   s.cfg.Issuer,
		"sub":   clientID,
		"jti":   uuid.NewString(),
		"scope": scope,
		"iat":   jwt.NewNumericDate(now),
		"exp":   jwt.NewNumericDate(now.Add(s.cfg.TokenTTL)),
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(s.cfg.Secret)
}

// --- DB helpers ---

type oauthClient struct {
	ClientID     string
	ClientName   string
	RedirectURIs []string
	Scope        string
}

type authCode struct {
	Code                string
	ClientID            string
	RedirectURI         string
	Scope               string
	CodeChallenge       string
	CodeChallengeMethod string
	ExpiresAt           time.Time
}

type refreshTokenRecord struct {
	TokenHash string
	ClientID  string
	Scope     string
	ExpiresAt time.Time
}

func (s *Server) insertClient(ctx context.Context, name string, redirectURIs []string, scope string) (string, error) {
	var clientID string
	err := s.pool.QueryRow(ctx,
		`INSERT INTO oauth_clients (client_name, redirect_uris, scope)
		 VALUES ($1, $2, $3)
		 RETURNING client_id`,
		name, redirectURIs, scope,
	).Scan(&clientID)
	return clientID, err
}

func (s *Server) findClient(ctx context.Context, clientID string) (*oauthClient, error) {
	var c oauthClient
	err := s.pool.QueryRow(ctx,
		`SELECT client_id, client_name, redirect_uris, scope
		 FROM oauth_clients WHERE client_id = $1`,
		clientID,
	).Scan(&c.ClientID, &c.ClientName, &c.RedirectURIs, &c.Scope)
	if err != nil {
		return nil, err
	}
	return &c, nil
}

func (s *Server) insertAuthCode(ctx context.Context, code, clientID, redirectURI, scope, challenge, method string, expires time.Time) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO oauth_authorization_codes
		 (code, client_id, redirect_uri, scope, code_challenge, code_challenge_method, expires_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7)`,
		code, clientID, redirectURI, scope, challenge, method, expires,
	)
	return err
}

// consumeAuthCode atomically marks the authorization code as used and returns its data.
// Using UPDATE ... RETURNING prevents TOCTOU races from concurrent token requests
// with the same code; only the first successful update returns rows.
func (s *Server) consumeAuthCode(ctx context.Context, code string) (*authCode, error) {
	var ac authCode
	err := s.pool.QueryRow(ctx,
		`UPDATE oauth_authorization_codes
		 SET used_at = now()
		 WHERE code = $1 AND used_at IS NULL AND expires_at > now()
		 RETURNING code, client_id, redirect_uri, scope, code_challenge, code_challenge_method, expires_at`,
		code,
	).Scan(&ac.Code, &ac.ClientID, &ac.RedirectURI, &ac.Scope, &ac.CodeChallenge, &ac.CodeChallengeMethod, &ac.ExpiresAt)
	if err != nil {
		return nil, err
	}
	return &ac, nil
}

func (s *Server) insertNewRefreshToken(ctx context.Context, clientID, scope string) (string, error) {
	rawToken := mustGenerateToken(32)
	tokenHash := hashToken(rawToken)
	expires := time.Now().Add(s.cfg.RefreshTTL)
	_, err := s.pool.Exec(ctx,
		`INSERT INTO oauth_refresh_tokens (token_hash, client_id, scope, expires_at)
		 VALUES ($1, $2, $3, $4)`,
		tokenHash, clientID, scope, expires,
	)
	if err != nil {
		return "", err
	}
	return rawToken, nil
}

// consumeRefreshToken atomically revokes the refresh token and returns its data.
// Using UPDATE ... RETURNING prevents TOCTOU races from concurrent refresh requests;
// only the first successful update returns rows (token rotation is safe).
func (s *Server) consumeRefreshToken(ctx context.Context, tokenHash string) (*refreshTokenRecord, error) {
	var rt refreshTokenRecord
	err := s.pool.QueryRow(ctx,
		`UPDATE oauth_refresh_tokens
		 SET revoked_at = now()
		 WHERE token_hash = $1 AND revoked_at IS NULL AND expires_at > now()
		 RETURNING token_hash, client_id, scope, expires_at`,
		tokenHash,
	).Scan(&rt.TokenHash, &rt.ClientID, &rt.Scope, &rt.ExpiresAt)
	if err != nil {
		return nil, err
	}
	return &rt, nil
}

// --- Utility functions ---

// mustGenerateToken generates a cryptographically random base64url token of n bytes.
// Panics if the system entropy source fails — rand.Read failure is unrecoverable.
func mustGenerateToken(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(fmt.Sprintf("oauth: failed to generate random token: %v", err))
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func hashToken(raw string) string {
	h := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(h[:])
}

// findRegisteredURI returns the matching entry from the DB-sourced registered list,
// or "" if not found. Using the returned value (not raw user input) as the redirect
// target eliminates the taint path that triggers open-redirect static analysis warnings.
func findRegisteredURI(uris []string, target string) string {
	for _, u := range uris {
		if u == target {
			return u
		}
	}
	return ""
}

// intersectScopes returns the space-separated subset of requested scopes
// that appear in the allowed scopes string.
func intersectScopes(requested, allowed string) string {
	allowedSet := make(map[string]bool)
	for _, s := range strings.Fields(allowed) {
		allowedSet[s] = true
	}
	var valid []string
	for _, s := range strings.Fields(requested) {
		if allowedSet[s] {
			valid = append(valid, s)
		}
	}
	return strings.Join(valid, " ")
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}

func writeOAuthError(w http.ResponseWriter, status int, errCode, desc string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error":             errCode,
		"error_description": desc,
	})
}
