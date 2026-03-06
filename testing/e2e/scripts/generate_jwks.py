#!/usr/bin/env python3
"""
Generates an RSA key pair and writes both the private key and JWKS document
to the specified directory.

Used by deploy.sh during e2e cluster setup to prepare JWT auth test fixtures.
Unlike the component-test version (generate_and_serve_jwks.py), this script
only writes files — it does NOT serve an HTTP endpoint.

Usage:
  uv run --with cryptography python3 generate_jwks.py --key-dir /path/to/.jwks
"""

import argparse
import base64
import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KID = "test-key-1"


def generate(key_dir: str) -> None:
    os.makedirs(key_dir, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(os.path.join(key_dir, "private_key.pem"), "wb") as f:
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

    with open(os.path.join(key_dir, "jwks.json"), "w") as f:
        json.dump(jwks, f, indent=2)

    print(f"[+] RSA key pair written to {key_dir}/", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-dir", required=True, help="Directory to write keys to")
    args = parser.parse_args()
    generate(args.key_dir)
