#!/usr/bin/env python3
"""Make a new Ed25519 signing key for Mesh session tokens (v2). docs/architecture/v4.0/MESH-SESSION-ED25519.md.

    python3 scripts/mesh-session-keygen.py [kid]          # kid defaults to portal-YYYY-MM

Prints:
  1. the portal settings, one NAME / VALUE / Encrypt / Scope block each, laid out like the DigitalOcean env-var form: paste only
     the VALUE line into the value box (no "NAME=", no quotes, no spaces). The private seed goes in the secret store and nowhere
     else: never in this repo, a Codespace, a Mesh image or a chat.
  2. the kid + PUBLIC key line to add to TRUSTED_KEYS in core/mesh_session.py AND wasm/relay/mesh-session.mjs.
  3. the public key again as the check value: the portal logs "kid=... public_key=..." at startup, and the two must match.
Nothing is written to disk.

2026-11-22: the first production rollout lost an hour to two paste slips (the seed stored under a different name, the kid stored
with two extra characters), both from copying a NAME=value line into the value box. Hence the form-shaped output.
"""
import base64
import re
import sys
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")     # the portal refuses anything else (app/mesh_session.py _signing_key)


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def setting(name: str, value: str, encrypt: bool) -> list[str]:
    return [f"  NAME:    {name}", f"  VALUE:   {value}", f"  Encrypt: {'YES' if encrypt else 'no'}    Scope: Run time", ""]


def render(kid: str, seed: bytes, pub: bytes) -> str:
    out = ["# 1. Portal settings (DigitalOcean app -> Settings -> App-level environment variables).",
           "#    Paste ONLY the VALUE text into the value box: no NAME=, no quotes, no spaces.", ""]
    out += setting("MESH_SESSION_SIGNING_KEY", b64(seed), True)
    out += setting("MESH_SESSION_SIGNING_KID", kid, False)
    out += ["#    Then, only once a Mesh image + sandbox boot-mesh.sh + relay that pin this kid are live:", ""]
    out += setting("MESH_SESSION_TOKEN_VERSION", "v2", False)
    out += ["# 2. Pin the public key (not secret) in core/mesh_session.py TRUSTED_KEYS:",
            f'    "{kid}": "{b64(pub)}",',
            "#    and in wasm/relay/mesh-session.mjs TRUSTED_KEYS:",
            f'  "{kid}": "{b64(pub)}",', "",
            "# 3. Check after the portal redeploys: its log must show exactly",
            f"#    mesh session tokens: v2 kid={kid} public_key={b64(pub)}"]
    return "\n".join(out)


def main() -> None:
    kid = sys.argv[1] if len(sys.argv) > 1 else "portal-" + datetime.now(timezone.utc).strftime("%Y-%m")
    if not KID_RE.match(kid):
        sys.exit(f"kid must match {KID_RE.pattern} (got {kid!r})")
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print(render(kid, seed, pub))


if __name__ == "__main__":
    main()
