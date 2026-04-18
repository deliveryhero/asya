package a2aadapter

import (
	"context"
	"crypto/rsa"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"math/big"
	"net/http"
	"strings"
	"sync"
	"time"

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

// jwkSet holds a minimal set of RSA public keys fetched from a JWKS endpoint.
type jwkSet struct {
	mu    sync.RWMutex
	keys  map[string]*rsa.PublicKey
	url   string
	close context.CancelFunc
}

func newJWKSet(ctx context.Context, url string) (*jwkSet, error) {
	s := &jwkSet{keys: make(map[string]*rsa.PublicKey), url: url}
	if err := s.refresh(ctx); err != nil {
		return nil, err
	}
	rctx, cancel := context.WithCancel(ctx)
	s.close = cancel
	go s.refreshLoop(rctx)
	return s, nil
}

// refreshLoop refreshes the JWKS every hour.
func (s *jwkSet) refreshLoop(ctx context.Context) {
	ticker := time.NewTicker(time.Hour)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := s.refresh(ctx); err != nil {
				slog.Warn("JWKS refresh failed", "url", s.url, "error", err)
			}
		}
	}
}

func (s *jwkSet) refresh(ctx context.Context) error {
	fetchCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(fetchCtx, http.MethodGet, s.url, nil)
	if err != nil {
		return err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close() //nolint:errcheck
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	var jwks struct {
		Keys []struct {
			Kid string `json:"kid"`
			Kty string `json:"kty"`
			N   string `json:"n"`
			E   string `json:"e"`
		} `json:"keys"`
	}
	if err := json.Unmarshal(body, &jwks); err != nil {
		return err
	}
	newKeys := make(map[string]*rsa.PublicKey, len(jwks.Keys))
	for _, k := range jwks.Keys {
		if k.Kty != "RSA" {
			continue
		}
		pub, err := decodeRSAPublicKey(k.N, k.E)
		if err != nil {
			slog.Warn("Invalid RSA key in JWKS", "kid", k.Kid, "error", err)
			continue
		}
		newKeys[k.Kid] = pub
	}
	s.mu.Lock()
	s.keys = newKeys
	s.mu.Unlock()
	slog.Info("JWKS refreshed", "url", s.url, "keys", len(newKeys))
	return nil
}

func (s *jwkSet) getKey(kid string) (*rsa.PublicKey, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if kid == "" {
		// Return any key if no kid specified
		for _, k := range s.keys {
			return k, true
		}
		return nil, false
	}
	k, ok := s.keys[kid]
	return k, ok
}

func decodeRSAPublicKey(nStr, eStr string) (*rsa.PublicKey, error) {
	nBytes, err := base64.RawURLEncoding.DecodeString(nStr)
	if err != nil {
		return nil, fmt.Errorf("decode n: %w", err)
	}
	eBytes, err := base64.RawURLEncoding.DecodeString(eStr)
	if err != nil {
		return nil, fmt.Errorf("decode e: %w", err)
	}
	n := new(big.Int).SetBytes(nBytes)
	e := new(big.Int).SetBytes(eBytes)
	return &rsa.PublicKey{N: n, E: int(e.Int64())}, nil
}

// JWTAuthenticator validates Bearer tokens using a simple JWKS fetch.
// Uses only golang-jwt/jwt/v5 without the keyfunc background-refresh library.
type JWTAuthenticator struct {
	jwks     *jwkSet
	issuer   string
	audience string
}

// NewJWTAuthenticator fetches keys from jwksURL and validates issuer+audience on every token.
func NewJWTAuthenticator(jwksURL, issuer, audience string) (*JWTAuthenticator, error) {
	s, err := newJWKSet(context.Background(), jwksURL)
	if err != nil {
		return nil, fmt.Errorf("fetch JWKS: %w", err)
	}
	return &JWTAuthenticator{jwks: s, issuer: issuer, audience: audience}, nil
}

// Close stops the JWKS background refresh goroutine.
func (j *JWTAuthenticator) Close() { j.jwks.close() }

func (j *JWTAuthenticator) Authenticate(r *http.Request) bool {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		return false
	}
	tokenStr := strings.TrimPrefix(h, "Bearer ")
	token, err := jwt.Parse(tokenStr,
		func(t *jwt.Token) (any, error) {
			if _, ok := t.Method.(*jwt.SigningMethodRSA); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
			}
			kid, _ := t.Header["kid"].(string)
			pub, ok := j.jwks.getKey(kid)
			if !ok {
				return nil, fmt.Errorf("key not found: %q", kid)
			}
			return pub, nil
		},
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
