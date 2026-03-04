package a2a

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
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

// A2AAuthMiddleware returns middleware that checks all configured authenticators.
// A request passes if ANY authenticator succeeds.
// Agent Card (/.well-known/agent.json) is always bypassed.
func A2AAuthMiddleware(authenticators ...Authenticator) func(http.Handler) http.Handler {
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
