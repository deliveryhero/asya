package a2a

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/MicahParks/keyfunc/v3"
	"github.com/golang-jwt/jwt/v5"
)

// Authenticator checks if a request is authenticated.
type Authenticator interface {
	Authenticate(r *http.Request) bool
}

// APIKeyAuthenticator validates X-API-Key header using constant-time comparison.
type APIKeyAuthenticator struct {
	Key string
}

// Authenticate returns true if the X-API-Key header matches the configured key.
func (a *APIKeyAuthenticator) Authenticate(r *http.Request) bool {
	provided := r.Header.Get("X-API-Key")
	return subtle.ConstantTimeCompare([]byte(provided), []byte(a.Key)) == 1
}

// JWTAuthenticator validates Bearer tokens using JWKS for key resolution.
type JWTAuthenticator struct {
	jwks     keyfunc.Keyfunc
	cancel   context.CancelFunc
	issuer   string
	audience string
}

// NewJWTAuthenticator creates a JWTAuthenticator that fetches keys from the
// given JWKS URL. The issuer and audience are validated on every token.
func NewJWTAuthenticator(jwksURL, issuer, audience string) (*JWTAuthenticator, error) {
	ctx, cancel := context.WithCancel(context.Background())
	k, err := keyfunc.NewDefaultCtx(ctx, []string{jwksURL})
	if err != nil {
		cancel()
		return nil, err
	}
	return &JWTAuthenticator{
		jwks:     k,
		cancel:   cancel,
		issuer:   issuer,
		audience: audience,
	}, nil
}

// Close releases background resources held by the JWKS fetcher.
func (j *JWTAuthenticator) Close() {
	j.cancel()
}

// extractBearerToken returns the token string from Authorization: Bearer <token>,
// and false if the header is missing or uses a different scheme.
func extractBearerToken(r *http.Request) (string, bool) {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		return "", false
	}
	return strings.TrimPrefix(h, "Bearer "), true
}

// Authenticate extracts a Bearer token from the Authorization header and
// validates it against the JWKS, issuer, and audience.
func (j *JWTAuthenticator) Authenticate(r *http.Request) bool {
	tokenStr, ok := extractBearerToken(r)
	if !ok {
		return false
	}

	token, err := jwt.Parse(tokenStr, j.jwks.Keyfunc,
		jwt.WithIssuer(j.issuer),
		jwt.WithAudience(j.audience),
		jwt.WithExpirationRequired(),
	)
	if err != nil {
		return false
	}
	return token.Valid
}

// BearerTokenAuthenticator validates Authorization: Bearer <static-token> using
// constant-time comparison. Used for MCP API key authentication (Phase 2).
type BearerTokenAuthenticator struct {
	Token string
}

// Authenticate returns true if the Authorization: Bearer header matches the configured token.
func (b *BearerTokenAuthenticator) Authenticate(r *http.Request) bool {
	provided, ok := extractBearerToken(r)
	if !ok {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(provided), []byte(b.Token)) == 1
}

// OAuthBearerAuthenticator validates gateway-issued HMAC-SHA256 JWTs.
// Used by MCPAuthMiddleware in OAuth 2.1 mode (Phase 3).
type OAuthBearerAuthenticator struct {
	secret   []byte
	issuer   string
	audience string
}

// NewOAuthBearerAuthenticator creates an authenticator for gateway-issued OAuth tokens.
func NewOAuthBearerAuthenticator(secret []byte, issuer, audience string) *OAuthBearerAuthenticator {
	return &OAuthBearerAuthenticator{
		secret:   secret,
		issuer:   issuer,
		audience: audience,
	}
}

// Authenticate extracts a Bearer token from the Authorization header and
// validates it as a gateway-issued HMAC-SHA256 JWT.
func (o *OAuthBearerAuthenticator) Authenticate(r *http.Request) bool {
	tokenStr, ok := extractBearerToken(r)
	if !ok {
		return false
	}
	token, err := jwt.Parse(tokenStr,
		func(t *jwt.Token) (any, error) {
			if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
			}
			return o.secret, nil
		},
		jwt.WithIssuer(o.issuer),
		jwt.WithAudience(o.audience),
		jwt.WithExpirationRequired(),
	)
	if err != nil {
		return false
	}
	return token.Valid
}

// MCPAuthMiddleware returns middleware that requires Bearer token auth on MCP endpoints.
// If no authenticators are provided, auth is disabled (dev/testing mode, no key configured).
// On failure, returns 401 with WWW-Authenticate: Bearer per RFC 6750.
func MCPAuthMiddleware(authenticators ...Authenticator) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		if len(authenticators) == 0 {
			// Auth disabled: ASYA_MCP_API_KEY and ASYA_MCP_OAUTH_ENABLED are both unset.
			// MCP endpoints are accessible without credentials. Acceptable in network-restricted
			// deployments; set ASYA_MCP_API_KEY for production use.
			return next
		}
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			for _, auth := range authenticators {
				if auth.Authenticate(r) {
					next.ServeHTTP(w, r)
					return
				}
			}
			w.Header().Set("WWW-Authenticate", `Bearer realm="asya-gateway"`)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(`{"error":"unauthorized","error_description":"Bearer token required"}`))
		})
	}
}

// A2AAuthMiddleware returns middleware that checks all configured authenticators.
// A request passes if ANY authenticator succeeds.
// Agent Card (/.well-known/agent.json) is always bypassed.
func A2AAuthMiddleware(authenticators ...Authenticator) func(http.Handler) http.Handler {
	if len(authenticators) == 0 {
		panic("A2AAuthMiddleware requires at least one authenticator")
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent.json" {
				next.ServeHTTP(w, r)
				return
			}

			for _, auth := range authenticators {
				if auth.Authenticate(r) {
					next.ServeHTTP(w, r)
					return
				}
			}

			writeJSONRPCError(w, http.StatusUnauthorized, -32005, "Authentication required")
		})
	}
}

// APIKeyMiddleware returns middleware that validates X-API-Key header.
// Agent Card (/.well-known/agent.json) is excluded from auth.
// Deprecated: Use A2AAuthMiddleware with APIKeyAuthenticator.
func APIKeyMiddleware(apiKey string) func(http.Handler) http.Handler {
	return A2AAuthMiddleware(&APIKeyAuthenticator{Key: apiKey})
}

func writeJSONRPCError(w http.ResponseWriter, httpStatus, code int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(httpStatus)
	resp := map[string]any{
		"jsonrpc": "2.0",
		"error": map[string]any{
			"code":    code,
			"message": message,
		},
	}
	_ = json.NewEncoder(w).Encode(resp)
}
