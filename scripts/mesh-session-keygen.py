#!/usr/bin/env python3
"""Make a new Ed25519 signing key for Mesh session tokens (v2). docs/architecture/v4.0/MESH-SESSION-ED25519.md.

    python3 scripts/mesh-session-keygen.py [kid]          # kid defaults to portal-YYYY-MM

Prints:
  1. the PRIVATE key (base64url raw 32-byte seed) for the portal's secret VYOMI_MESH_SESSION_SIGNING_KEY. Put it in the
     secret store and nowhere else: never in this repo, a Codespace, a Mesh image or a chat.
  2. the kid + PUBLIC key line to add to TRUSTED_KEYS in core/mesh_session.py AND wasm/relay/mesh-session.mjs.
Nothing is written to disk.
"""
import base64
import sys
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main() -> None:
    kid = sys.argv[1] if len(sys.argv) > 1 else "portal-" + datetime.now(timezone.utc).strftime("%Y-%m")
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print("# 1. Portal secret (PRIVATE; secret store only):")
    print(f"VYOMI_MESH_SESSION_SIGNING_KEY={b64(seed)}")
    print(f"VYOMI_MESH_SESSION_SIGNING_KID={kid}")
    print()
    print("# 2. core/mesh_session.py TRUSTED_KEYS:")
    print(f'    "{kid}": "{b64(pub)}",')
    print("# 2. wasm/relay/mesh-session.mjs TRUSTED_KEYS:")
    print(f'  "{kid}": "{b64(pub)}",')


if __name__ == "__main__":
    main()
