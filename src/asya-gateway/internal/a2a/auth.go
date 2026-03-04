package a2a

import (
	"context"
	"crypto/subtle"
	"encoding/json"
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

// Authenticate extracts a Bearer token from the Authorization header and
// validates it against the JWKS, issuer, and audience.
func (j *JWTAuthenticator) Authenticate(r *http.Request) bool {
	authHeader := r.Header.Get("Authorization")
	if !strings.HasPrefix(authHeader, "Bearer ") {
		return false
	}
	tokenStr := strings.TrimPrefix(authHeader, "Bearer ")

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
