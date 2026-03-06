package oauth

import (
	"crypto/sha256"
	"encoding/base64"
	"testing"
)

func TestVerifyCodeChallenge_ValidS256(t *testing.T) {
	verifier := "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
	h := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(h[:])

	if !VerifyCodeChallenge(verifier, challenge, "S256") {
		t.Fatal("expected valid S256 challenge to pass")
	}
}

func TestVerifyCodeChallenge_InvalidVerifier(t *testing.T) {
	verifier := "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
	h := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(h[:])

	if VerifyCodeChallenge("wrong-verifier", challenge, "S256") {
		t.Fatal("expected wrong verifier to fail")
	}
}

func TestVerifyCodeChallenge_UnsupportedMethod(t *testing.T) {
	if VerifyCodeChallenge("verifier", "challenge", "plain") {
		t.Fatal("expected unsupported method 'plain' to fail")
	}
}
