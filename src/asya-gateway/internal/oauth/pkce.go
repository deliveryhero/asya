package oauth

import (
	"crypto/sha256"
	"encoding/base64"
	"strings"
)

// VerifyCodeChallenge verifies an OAuth 2.1 PKCE code challenge against a verifier.
// Only S256 is supported per RFC 7636 section 4.2.
func VerifyCodeChallenge(verifier, challenge, method string) bool {
	if method != "S256" {
		return false
	}
	h := sha256.Sum256([]byte(verifier))
	expected := base64.RawURLEncoding.EncodeToString(h[:])
	return expected == strings.TrimSpace(challenge)
}
