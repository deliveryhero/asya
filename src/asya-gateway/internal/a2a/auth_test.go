package a2a

import (
	"crypto/rand"
	"crypto/rsa"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math/big"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func okHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("OK"))
	})
}

func TestAPIKeyMiddleware_ValidKey(t *testing.T) {
	handler := APIKeyMiddleware("secret-key")(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("X-API-Key", "secret-key")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if rec.Body.String() != "OK" {
		t.Fatalf("expected OK body, got %q", rec.Body.String())
	}
}

func TestAPIKeyMiddleware_MissingKey(t *testing.T) {
	handler := APIKeyMiddleware("secret-key")(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}

	var resp map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to decode JSON-RPC error: %v", err)
	}

	errObj, ok := resp["error"].(map[string]any)
	if !ok {
		t.Fatal("missing error object in response")
	}
	code, ok := errObj["code"].(float64)
	if !ok || int(code) != -32005 {
		t.Fatalf("expected error code -32005, got %v", errObj["code"])
	}
}

func TestAPIKeyMiddleware_WrongKey(t *testing.T) {
	handler := APIKeyMiddleware("secret-key")(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("X-API-Key", "wrong-key")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
}

func TestAPIKeyMiddleware_AgentCardBypass(t *testing.T) {
	handler := APIKeyMiddleware("secret-key")(okHandler())

	req := httptest.NewRequest(http.MethodGet, "/.well-known/agent.json", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 for agent card bypass, got %d", rec.Code)
	}
}

func TestA2AAuthMiddleware_APIKey(t *testing.T) {
	auth := &APIKeyAuthenticator{Key: "test-key"}
	handler := A2AAuthMiddleware(auth)(okHandler())

	t.Run("ValidKey", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
		req.Header.Set("X-API-Key", "test-key")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)

		if rec.Code != http.StatusOK {
			t.Fatalf("expected 200, got %d", rec.Code)
		}
	})

	t.Run("MissingKey", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)

		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("expected 401, got %d", rec.Code)
		}
	})

	t.Run("AgentCardBypass", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/.well-known/agent.json", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)

		if rec.Code != http.StatusOK {
			t.Fatalf("expected 200 for agent card bypass, got %d", rec.Code)
		}
	})
}

func TestAPIKeyMiddleware_EmptyAPIKey(t *testing.T) {
	handler := APIKeyMiddleware("")(okHandler())

	// Empty key configured, empty header provided: should pass (constant-time compare matches)
	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 when both API key and header are empty, got %d", rec.Code)
	}

	// Empty key configured, non-empty header: should fail
	req2 := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req2.Header.Set("X-API-Key", "some-key")
	rec2 := httptest.NewRecorder()

	handler.ServeHTTP(rec2, req2)

	if rec2.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 when API key is empty but header is set, got %d", rec2.Code)
	}
}

// --- JWT test helpers ---

// setupJWKSServer generates an RSA key pair and starts an httptest.Server
// that serves the public key as a JWKS document. Returns the server,
// private key, and key ID.
func setupJWKSServer(t *testing.T) (*httptest.Server, *rsa.PrivateKey, string) {
	t.Helper()

	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("failed to generate RSA key: %v", err)
	}

	kid := "test-key-1"

	jwksJSON := fmt.Sprintf(`{
		"keys": [{
			"kty": "RSA",
			"kid": "%s",
			"use": "sig",
			"alg": "RS256",
			"n": "%s",
			"e": "%s"
		}]
	}`,
		kid,
		base64.RawURLEncoding.EncodeToString(privateKey.N.Bytes()),
		base64.RawURLEncoding.EncodeToString(big.NewInt(int64(privateKey.E)).Bytes()),
	)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(jwksJSON))
	}))
	t.Cleanup(srv.Close)

	return srv, privateKey, kid
}

// signToken creates a signed JWT string with the given claims and key.
func signToken(t *testing.T, key *rsa.PrivateKey, kid string, claims jwt.MapClaims) string {
	t.Helper()

	token := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	token.Header["kid"] = kid

	signed, err := token.SignedString(key)
	if err != nil {
		t.Fatalf("failed to sign token: %v", err)
	}
	return signed
}

func validClaims() jwt.MapClaims {
	return jwt.MapClaims{
		"iss": "https://test-issuer.example.com",
		"aud": "test-audience",
		"exp": jwt.NewNumericDate(time.Now().Add(time.Hour)),
		"iat": jwt.NewNumericDate(time.Now()),
		"sub": "user-123",
	}
}

func TestJWTAuthenticator_ValidToken(t *testing.T) {
	srv, key, kid := setupJWKSServer(t)

	auth, err := NewJWTAuthenticator(srv.URL, "https://test-issuer.example.com", "test-audience")
	if err != nil {
		t.Fatalf("failed to create JWTAuthenticator: %v", err)
	}
	t.Cleanup(auth.Close)

	tokenStr := signToken(t, key, kid, validClaims())

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)

	if !auth.Authenticate(req) {
		t.Fatal("expected valid token to authenticate successfully")
	}
}

func TestJWTAuthenticator_ExpiredToken(t *testing.T) {
	srv, key, kid := setupJWKSServer(t)

	auth, err := NewJWTAuthenticator(srv.URL, "https://test-issuer.example.com", "test-audience")
	if err != nil {
		t.Fatalf("failed to create JWTAuthenticator: %v", err)
	}
	t.Cleanup(auth.Close)

	claims := validClaims()
	claims["exp"] = jwt.NewNumericDate(time.Now().Add(-time.Hour))

	tokenStr := signToken(t, key, kid, claims)

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)

	if auth.Authenticate(req) {
		t.Fatal("expected expired token to fail authentication")
	}
}

func TestJWTAuthenticator_WrongIssuer(t *testing.T) {
	srv, key, kid := setupJWKSServer(t)

	auth, err := NewJWTAuthenticator(srv.URL, "https://test-issuer.example.com", "test-audience")
	if err != nil {
		t.Fatalf("failed to create JWTAuthenticator: %v", err)
	}
	t.Cleanup(auth.Close)

	claims := validClaims()
	claims["iss"] = "https://wrong-issuer.example.com"

	tokenStr := signToken(t, key, kid, claims)

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)

	if auth.Authenticate(req) {
		t.Fatal("expected wrong issuer to fail authentication")
	}
}

func TestJWTAuthenticator_WrongAudience(t *testing.T) {
	srv, key, kid := setupJWKSServer(t)

	auth, err := NewJWTAuthenticator(srv.URL, "https://test-issuer.example.com", "test-audience")
	if err != nil {
		t.Fatalf("failed to create JWTAuthenticator: %v", err)
	}
	t.Cleanup(auth.Close)

	claims := validClaims()
	claims["aud"] = "wrong-audience"

	tokenStr := signToken(t, key, kid, claims)

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)

	if auth.Authenticate(req) {
		t.Fatal("expected wrong audience to fail authentication")
	}
}

func TestJWTAuthenticator_NoAuthHeader(t *testing.T) {
	srv, _, _ := setupJWKSServer(t)

	auth, err := NewJWTAuthenticator(srv.URL, "https://test-issuer.example.com", "test-audience")
	if err != nil {
		t.Fatalf("failed to create JWTAuthenticator: %v", err)
	}
	t.Cleanup(auth.Close)

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)

	if auth.Authenticate(req) {
		t.Fatal("expected missing auth header to fail authentication")
	}
}

func TestA2AAuthMiddleware_MultiScheme(t *testing.T) {
	srv, key, kid := setupJWKSServer(t)

	jwtAuth, err := NewJWTAuthenticator(srv.URL, "https://test-issuer.example.com", "test-audience")
	if err != nil {
		t.Fatalf("failed to create JWTAuthenticator: %v", err)
	}
	t.Cleanup(jwtAuth.Close)

	apiKeyAuth := &APIKeyAuthenticator{Key: "multi-key"}
	handler := A2AAuthMiddleware(apiKeyAuth, jwtAuth)(okHandler())

	t.Run("APIKeyPasses", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
		req.Header.Set("X-API-Key", "multi-key")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)

		if rec.Code != http.StatusOK {
			t.Fatalf("expected 200, got %d", rec.Code)
		}
	})

	t.Run("JWTPasses", func(t *testing.T) {
		tokenStr := signToken(t, key, kid, validClaims())

		req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
		req.Header.Set("Authorization", "Bearer "+tokenStr)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)

		if rec.Code != http.StatusOK {
			t.Fatalf("expected 200, got %d", rec.Code)
		}
	})

	t.Run("NeitherFails", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)

		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("expected 401, got %d", rec.Code)
		}
	})
}

func TestJWTAuthenticator_MalformedToken(t *testing.T) {
	srv, _, _ := setupJWKSServer(t)

	auth, err := NewJWTAuthenticator(srv.URL, "https://test-issuer.example.com", "test-audience")
	if err != nil {
		t.Fatalf("failed to create JWTAuthenticator: %v", err)
	}
	t.Cleanup(auth.Close)

	req := httptest.NewRequest(http.MethodPost, "/a2a/", nil)
	req.Header.Set("Authorization", "Bearer not-a-valid-jwt")

	if auth.Authenticate(req) {
		t.Fatal("expected malformed token to fail authentication")
	}
}

func TestA2AAuthMiddleware_PanicsWithNoAuthenticators(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Fatal("expected panic with no authenticators")
		}
	}()
	A2AAuthMiddleware()
}

// --- BearerTokenAuthenticator tests ---

func TestBearerTokenAuthenticator_ValidToken(t *testing.T) {
	auth := &BearerTokenAuthenticator{Token: "secret-token"}
	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	req.Header.Set("Authorization", "Bearer secret-token")
	if !auth.Authenticate(req) {
		t.Fatal("expected valid Bearer token to authenticate")
	}
}

func TestBearerTokenAuthenticator_MissingHeader(t *testing.T) {
	auth := &BearerTokenAuthenticator{Token: "secret-token"}
	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	if auth.Authenticate(req) {
		t.Fatal("expected missing header to fail")
	}
}

func TestBearerTokenAuthenticator_WrongToken(t *testing.T) {
	auth := &BearerTokenAuthenticator{Token: "secret-token"}
	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	req.Header.Set("Authorization", "Bearer wrong-token")
	if auth.Authenticate(req) {
		t.Fatal("expected wrong token to fail")
	}
}

func TestBearerTokenAuthenticator_WrongScheme(t *testing.T) {
	auth := &BearerTokenAuthenticator{Token: "secret-token"}
	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	req.Header.Set("Authorization", "Basic secret-token")
	if auth.Authenticate(req) {
		t.Fatal("expected wrong scheme to fail")
	}
}

// --- OAuthBearerAuthenticator tests ---

func TestOAuthBearerAuthenticator_ValidToken(t *testing.T) {
	secret := []byte("test-secret-key-32bytes-minimum!!")
	issuer := "https://gateway.example.com"
	auth := NewOAuthBearerAuthenticator(secret, issuer, issuer)

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"iss": issuer,
		"aud": jwt.ClaimStrings{issuer},
		"sub": "test-client",
		"exp": jwt.NewNumericDate(time.Now().Add(time.Hour)),
		"iat": jwt.NewNumericDate(time.Now()),
	})
	tokenStr, err := token.SignedString(secret)
	if err != nil {
		t.Fatalf("failed to sign token: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	if !auth.Authenticate(req) {
		t.Fatal("expected valid OAuth JWT to authenticate")
	}
}

func TestOAuthBearerAuthenticator_ExpiredToken(t *testing.T) {
	secret := []byte("test-secret-key-32bytes-minimum!!")
	issuer := "https://gateway.example.com"
	auth := NewOAuthBearerAuthenticator(secret, issuer, issuer)

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"iss": issuer,
		"aud": jwt.ClaimStrings{issuer},
		"sub": "test-client",
		"exp": jwt.NewNumericDate(time.Now().Add(-time.Hour)),
		"iat": jwt.NewNumericDate(time.Now().Add(-2 * time.Hour)),
	})
	tokenStr, err := token.SignedString(secret)
	if err != nil {
		t.Fatalf("failed to sign token: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	if auth.Authenticate(req) {
		t.Fatal("expected expired token to fail")
	}
}

func TestOAuthBearerAuthenticator_WrongSigningMethod(t *testing.T) {
	secret := []byte("test-secret-key-32bytes-minimum!!")
	issuer := "https://gateway.example.com"
	auth := NewOAuthBearerAuthenticator(secret, issuer, issuer)

	// Sign with RS256 instead of HS256
	_, key, kid := setupJWKSServer(t)
	token := jwt.NewWithClaims(jwt.SigningMethodRS256, jwt.MapClaims{
		"iss": issuer,
		"aud": jwt.ClaimStrings{issuer},
		"sub": "test-client",
		"exp": jwt.NewNumericDate(time.Now().Add(time.Hour)),
	})
	token.Header["kid"] = kid
	tokenStr, err := token.SignedString(key)
	if err != nil {
		t.Fatalf("failed to sign token: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	if auth.Authenticate(req) {
		t.Fatal("expected RS256 token to fail HS256 authenticator")
	}
}

// --- MCPAuthMiddleware tests ---

func TestMCPAuthMiddleware_Disabled(t *testing.T) {
	// No authenticators = auth disabled; all requests pass
	handler := MCPAuthMiddleware()(okHandler())
	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 when MCP auth disabled, got %d", rec.Code)
	}
}

func TestMCPAuthMiddleware_ValidToken(t *testing.T) {
	auth := &BearerTokenAuthenticator{Token: "mcp-key"}
	handler := MCPAuthMiddleware(auth)(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	req.Header.Set("Authorization", "Bearer mcp-key")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
}

func TestMCPAuthMiddleware_InvalidToken(t *testing.T) {
	auth := &BearerTokenAuthenticator{Token: "mcp-key"}
	handler := MCPAuthMiddleware(auth)(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	req.Header.Set("Authorization", "Bearer wrong-key")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if rec.Header().Get("WWW-Authenticate") == "" {
		t.Fatal("expected WWW-Authenticate header in 401 response")
	}
}

func TestMCPAuthMiddleware_MissingToken(t *testing.T) {
	auth := &BearerTokenAuthenticator{Token: "mcp-key"}
	handler := MCPAuthMiddleware(auth)(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for missing token, got %d", rec.Code)
	}
}
