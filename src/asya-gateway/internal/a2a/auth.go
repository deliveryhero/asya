package a2a

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
)

// APIKeyMiddleware returns middleware that validates X-API-Key header.
// Agent Card (/.well-known/agent.json) is excluded from auth.
func APIKeyMiddleware(apiKey string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Agent Card is public (exact path only)
			if r.URL.Path == "/.well-known/agent.json" {
				next.ServeHTTP(w, r)
				return
			}

			provided := r.Header.Get("X-API-Key")
			if subtle.ConstantTimeCompare([]byte(provided), []byte(apiKey)) != 1 {
				writeJSONRPCError(w, http.StatusUnauthorized, -32005, "Authentication required")
				return
			}

			next.ServeHTTP(w, r)
		})
	}
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
