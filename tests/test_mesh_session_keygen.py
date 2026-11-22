"""scripts/mesh-session-keygen.py prints DigitalOcean-form-shaped settings (2026-11-22 rollout: two NAME=value paste slips)."""
import base64
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mesh-session-keygen.py"


def _load():
    spec = importlib.util.spec_from_file_location("mesh_session_keygen", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_prints_exact_portal_names_and_values_on_their_own():
    out = _run("portal-test").stdout
    names = re.findall(r"^  NAME: +(\S+)$", out, re.M)
    assert names == ["MESH_SESSION_SIGNING_KEY", "MESH_SESSION_SIGNING_KID", "MESH_SESSION_TOKEN_VERSION"]
    assert "VYOMI_MESH_SESSION" not in out                       # the portal reads these exact names, nothing prefixed
    assert not re.search(r"^\s*MESH_SESSION_\w+=", out, re.M)     # no NAME=value line to paste whole into a value box
    values = re.findall(r"^  VALUE: +(\S+)$", out, re.M)
    assert values[1:] == ["portal-test", "v2"]
    assert len(_unb64(values[0])) == 32                          # the seed: raw 32-byte Ed25519, base64url, unpadded


def test_only_the_seed_is_marked_encrypt():
    out = _run("portal-test").stdout
    enc = re.findall(r"^  Encrypt: (\S+)", out, re.M)
    assert enc == ["YES", "no", "no"]


def test_public_key_matches_seed_everywhere_it_is_printed():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    out = _run("portal-test").stdout
    seed = re.findall(r"^  VALUE: +(\S+)$", out, re.M)[0]
    pub = Ed25519PrivateKey.from_private_bytes(_unb64(seed)).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    want = base64.urlsafe_b64encode(pub).rstrip(b"=").decode()
    assert out.count(f'"portal-test": "{want}"') == 2              # core/mesh_session.py + wasm/relay/mesh-session.mjs lines
    assert f"mesh session tokens: v2 kid=portal-test public_key={want}" in out   # the portal's startup log line


@pytest.mark.parametrize("kid", ['"portal-2026-11"', "portal 2026", "MESH_SESSION_SIGNING_KID=portal-2026-11", "", "x" * 65])
def test_refuses_kids_the_portal_would_refuse(kid):
    r = _run(kid) if kid else subprocess.run([sys.executable, "-c", f"import runpy,sys; sys.argv=['k','']; "
                                                                    f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')"],
                                             capture_output=True, text=True)
    assert r.returncode != 0 and "kid must match" in (r.stderr + r.stdout)


def test_kid_rule_matches_the_portal_and_trusted_keys():
    mod = _load()
    src = (ROOT / "core" / "mesh_session.py").read_text()
    pinned = re.findall(r'^\s*"([^"]+)":\s*"[A-Za-z0-9_-]{43}",?', src, re.M)
    assert pinned and all(mod.KID_RE.match(k) for k in pinned)
