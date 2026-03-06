#!/usr/bin/env python3
"""
Generates an RSA key pair at startup, writes keys to KEY_DIR, and serves
the JWKS document via HTTP so the gateway can fetch it for JWT validation.

Run inside the jwks-server container:
  python3 generate_and_serve_jwks.py
"""

import base64
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_DIR = "/key-data"
KID = "test-key-1"
PORT = 8099


def generate_jwks_and_key():
    os.makedirs(KEY_DIR, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(f"{KEY_DIR}/private_key.pem", "wb") as f:
        f.write(private_pem)

    pub_nums = key.public_key().public_numbers()
    n_bytes = pub_nums.n.to_bytes((pub_nums.n.bit_length() + 7) // 8, "big")
    e_bytes = pub_nums.e.to_bytes((pub_nums.e.bit_length() + 7) // 8, "big")

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": KID,
                "use": "sig",
                "alg": "RS256",
                "n": base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode(),
                "e": base64.urlsafe_b64encode(e_bytes).rstrip(b"=").decode(),
            }
        ]
    }

    with open(f"{KEY_DIR}/jwks.json", "w") as f:
        json.dump(jwks, f, indent=2)

    print(f"[+] RSA key pair generated under {KEY_DIR}/", flush=True)


if __name__ == "__main__":
    generate_jwks_and_key()
    os.chdir(KEY_DIR)
    print(f"[+] JWKS server listening on port {PORT}", flush=True)
    sys.stdout.flush()
    HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler).serve_forever()
