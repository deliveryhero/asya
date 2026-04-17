package a2aadapter

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/MicahParks/keyfunc/v3"
	"github.com/golang-jwt/jwt/v5"
)

// Authenticator checks if a request carries valid credentials.
type Authenticator interface {
	Authenticate(r *http.Request) bool
}

// APIKeyAuthenticator validates X-API-Key header using constant-time comparison.
type APIKeyAuthenticator struct {
	key string
}

// NewAPIKeyAuthenticator returns an authenticator for the given key.
func NewAPIKeyAuthenticator(key string) *APIKeyAuthenticator {
	return &APIKeyAuthenticator{key: key}
}

func (a *APIKeyAuthenticator) Authenticate(r *http.Request) bool {
	provided := r.Header.Get("X-API-Key")
	return subtle.ConstantTimeCompare([]byte(provided), []byte(a.key)) == 1
}

// JWTAuthenticator validates Bearer tokens using a remote JWKS for key resolution.
type JWTAuthenticator struct {
	jwks     keyfunc.Keyfunc
	cancel   context.CancelFunc
	issuer   string
	audience string
}

// NewJWTAuthenticator fetches keys from jwksURL and validates issuer+audience on every token.
func NewJWTAuthenticator(jwksURL, issuer, audience string) (*JWTAuthenticator, error) {
	ctx, cancel := context.WithCancel(context.Background())
	k, err := keyfunc.NewDefaultCtx(ctx, []string{jwksURL})
	if err != nil {
		cancel()
		return nil, err
	}
	return &JWTAuthenticator{jwks: k, cancel: cancel, issuer: issuer, audience: audience}, nil
}

// Close releases JWKS background resources.
func (j *JWTAuthenticator) Close() { j.cancel() }

func (j *JWTAuthenticator) Authenticate(r *http.Request) bool {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		return false
	}
	tokenStr := strings.TrimPrefix(h, "Bearer ")
	token, err := jwt.Parse(tokenStr, j.jwks.Keyfunc,
		jwt.WithIssuer(j.issuer),
		jwt.WithAudience(j.audience),
		jwt.WithExpirationRequired(),
	)
	return err == nil && token.Valid
}

// AuthMiddleware returns HTTP middleware that requires any of the provided authenticators.
// Requests to /.well-known/agent.json are always passed through unauthenticated.
// Returns 401 JSON-RPC error on failure.
func AuthMiddleware(auths ...Authenticator) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		if len(auths) == 0 {
			return next
		}
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent.json" {
				next.ServeHTTP(w, r)
				return
			}
			for _, a := range auths {
				if a.Authenticate(r) {
					next.ServeHTTP(w, r)
					return
				}
			}
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"jsonrpc": "2.0",
				"error": map[string]any{
					"code":    -32005,
					"message": "Authentication required",
				},
			})
		})
	}
}
