"""
A2A authentication component tests.

Verifies the gateway's A2A auth middleware with a real gateway process:
- Agent card (/.well-known/agent.json) is always public
- A2A endpoint requires auth when both API Key and JWT are configured
- API key auth: valid passes, wrong key rejected
- JWT auth: valid token passes; expired / wrong issuer / wrong audience rejected
- /mesh/expose requires API key
"""

import os
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8089")
API_KEY = os.getenv("ASYA_A2A_API_KEY", "test-api-key-12345")
JWT_ISSUER = os.getenv("ASYA_A2A_JWT_ISSUER", "https://test-issuer.local")
JWT_AUDIENCE = os.getenv("ASYA_A2A_JWT_AUDIENCE", "asya-gateway-test")
PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH", "/key-data/private_key.pem")

# Minimal A2A JSON-RPC request: tasks/get with a non-existent ID exercises the
# full middleware chain without touching the message queue.
_A2A_PROBE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tasks/get",
    "params": {"id": "probe-does-not-exist"},
}


def _load_private_key():
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _make_jwt(private_key, *, expired=False, wrong_issuer=False, wrong_audience=False):
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {
            "iss": "https://wrong-issuer.local" if wrong_issuer else JWT_ISSUER,
            "aud": "wrong-audience" if wrong_audience else JWT_AUDIENCE,
            "sub": "test-user",
            "iat": now,
            "exp": now - timedelta(hours=1) if expired else now + timedelta(hours=1),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )


@pytest.fixture(scope="session")
def private_key():
    """Load RSA private key written by the jwks-server container."""
    deadline = time.time() + 30
    while time.time() < deadline:
        if os.path.exists(PRIVATE_KEY_PATH):
            return _load_private_key()
        time.sleep(0.5)  # Poll until jwks-server writes the key
    pytest.fail(f"Private key not available at {PRIVATE_KEY_PATH} after 30s")


class TestA2AAuth:
    def test_agent_card_is_public(self):
        """Agent card is accessible without any credentials."""
        resp = requests.get(f"{GATEWAY_URL}/.well-known/agent.json", timeout=5)
        assert resp.status_code == 200

    def test_a2a_no_auth_returns_401(self):
        """A2A endpoint rejects requests with no credentials."""
        resp = requests.post(f"{GATEWAY_URL}/a2a/", json=_A2A_PROBE, timeout=5)
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == -32005, f"expected JSON-RPC -32005, got: {body}"

    def test_a2a_valid_api_key_passes(self):
        """Valid API key grants access to the A2A endpoint."""
        resp = requests.post(
            f"{GATEWAY_URL}/a2a/",
            json=_A2A_PROBE,
            headers={"X-API-Key": API_KEY},
            timeout=5,
        )
        assert resp.status_code != 401, f"expected auth to pass, got 401: {resp.text}"

    def test_a2a_wrong_api_key_returns_401(self):
        """Wrong API key is rejected."""
        resp = requests.post(
            f"{GATEWAY_URL}/a2a/",
            json=_A2A_PROBE,
            headers={"X-API-Key": "wrong-key"},
            timeout=5,
        )
        assert resp.status_code == 401

    def test_a2a_valid_jwt_passes(self, private_key):
        """Valid Bearer JWT grants access to the A2A endpoint."""
        token = _make_jwt(private_key)
        resp = requests.post(
            f"{GATEWAY_URL}/a2a/",
            json=_A2A_PROBE,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        assert resp.status_code != 401, f"expected JWT to pass, got 401: {resp.text}"

    def test_a2a_expired_jwt_returns_401(self, private_key):
        """Expired JWT is rejected."""
        token = _make_jwt(private_key, expired=True)
        resp = requests.post(
            f"{GATEWAY_URL}/a2a/",
            json=_A2A_PROBE,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        assert resp.status_code == 401

    def test_a2a_wrong_issuer_returns_401(self, private_key):
        """JWT with wrong issuer is rejected."""
        token = _make_jwt(private_key, wrong_issuer=True)
        resp = requests.post(
            f"{GATEWAY_URL}/a2a/",
            json=_A2A_PROBE,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        assert resp.status_code == 401

    def test_a2a_wrong_audience_returns_401(self, private_key):
        """JWT with wrong audience is rejected."""
        token = _make_jwt(private_key, wrong_audience=True)
        resp = requests.post(
            f"{GATEWAY_URL}/a2a/",
            json=_A2A_PROBE,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        assert resp.status_code == 401

    def test_a2a_malformed_token_returns_401(self):
        """Non-JWT Bearer string is rejected."""
        resp = requests.post(
            f"{GATEWAY_URL}/a2a/",
            json=_A2A_PROBE,
            headers={"Authorization": "Bearer not-a-valid-jwt"},
            timeout=5,
        )
        assert resp.status_code == 401

    def test_expose_endpoint_requires_auth(self):
        """/mesh/expose rejects unauthenticated GET requests."""
        resp = requests.get(f"{GATEWAY_URL}/mesh/expose", timeout=5)
        assert resp.status_code == 401

    def test_expose_endpoint_with_api_key(self):
        """/mesh/expose is accessible with a valid API key."""
        resp = requests.get(
            f"{GATEWAY_URL}/mesh/expose",
            headers={"X-API-Key": API_KEY},
            timeout=5,
        )
        assert resp.status_code != 401
