"""Ed25519 (v2) Mesh session tokens: MCP-GUARDRAILS-INCIDENT-DESIGN.md finding F2, MESH-SESSION-ED25519.md.

F2: a v1 (HMAC) token can be minted by anyone holding the per-session key, which the portal hands to the Codespace. v2 is
signed by the portal's private key and verified with a public key pinned in code, so the Codespace owner cannot mint one.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from core import mesh_session as ms  # noqa: E402

KID = "test-kid"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _keypair():
    k = Ed25519PrivateKey.generate()
    seed = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return seed, _b64(pub)


SEED, PUB = _keypair()
OTHER_SEED, OTHER_PUB = _keypair()


@pytest.fixture(autouse=True)
def _pinned(monkeypatch):
    monkeypatch.setattr(ms, "TRUSTED_KEYS", {KID: PUB})
    monkeypatch.setattr(ms, "V1_ACCEPTED", True)
    monkeypatch.delenv("VYOMI_MESH_SESSION_KEY", raising=False)
    monkeypatch.delenv("VYOMI_MESH_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("VYOMI_ROLE", raising=False)
    ms.reset_for_tests()
    yield
    ms.reset_for_tests()


def v2(tier="pro", end_in=3600, seed=SEED, kid=KID, **kw):
    return ms.mint_v2("acct-1", tier, time.time() + end_in, private_key=seed, kid=kid, session_id="s-1", **kw)


def _code(fn):
    try:
        fn()
    except ms.SessionError as e:
        return e.code
    return None


def test_v2_verifies_without_any_key_on_the_mesh():
    c = ms.verify(v2("max"))
    assert c["tier"] == "max" and c["kid"] == KID and c["session_id"] == "s-1"


def test_v2_signed_by_another_key_is_refused():
    assert _code(lambda: ms.verify(v2(seed=OTHER_SEED))) == "MeshSessionBadSignature"


def test_v2_unknown_kid_is_refused():
    assert _code(lambda: ms.verify(v2(seed=OTHER_SEED, kid="attacker"))) == "MeshSessionUnknownKey"


def test_v2_tampered_payload_is_refused():
    ver, body, sig = v2("pro").split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims.update(tier="max", session_end=int(time.time()) + 10 ** 7)
    forged_body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    assert _code(lambda: ms.verify(f"{ver}.{forged_body}.{sig}")) == "MeshSessionBadSignature"


def test_v2_keeps_the_claim_checks():
    assert _code(lambda: ms.verify(v2(end_in=-5))) == "MeshSessionExpired"
    assert _code(lambda: ms.verify(v2("free"))) == "MeshTierNotEligible"


def test_f2_leaked_key_mints_max_until_v1_is_retired(monkeypatch):
    """The attack: the Codespace owner signs a Max token with the per-session key the portal gave their Codespace."""
    leaked = "per-session-key-from-the-portal"
    forged = ms.mint("acct-1", "max", time.time() + 10 ** 7, key=leaked, session_id="s-1")
    assert ms.verify(forged, key=leaked)["tier"] == "max"            # today (V1_ACCEPTED): F2 is open
    monkeypatch.setattr(ms, "V1_ACCEPTED", False)
    assert _code(lambda: ms.verify(forged, key=leaked)) == "MeshSessionV1Retired"
    assert ms.verify(v2("pro"))["tier"] == "pro"                      # portal-signed v2 still works


def test_the_environment_cannot_add_a_trusted_key(monkeypatch):
    for name in ("VYOMI_MESH_SESSION_PUBKEY", "VYOMI_MESH_SESSION_PUBKEYS", "VYOMI_MESH_TRUSTED_KEYS", "VYOMI_MESH_SESSION_KEY"):
        monkeypatch.setenv(name, json.dumps({"attacker": OTHER_PUB}) if "KEYS" in name else OTHER_PUB)
    assert _code(lambda: ms.verify(v2(seed=OTHER_SEED, kid="attacker"))) == "MeshSessionUnknownKey"


def test_authorise_with_a_v2_env_token_and_no_key(monkeypatch):
    monkeypatch.setenv("VYOMI_ROLE", "mesh")
    monkeypatch.setenv("VYOMI_MESH_SESSION_TOKEN", v2("pro", primary_cloud="aws"))
    assert ms.authorise({}, "/", "aws") is None
    err = ms.authorise({}, "/", "gcp")
    assert err is not None and err.code == "tier_provider_locked"
    assert ms.effective_tier() == "pro"


def test_runner_role_v2_token_cannot_drive_the_mesh():
    err = ms.authorise({ms.HEADER: v2("max", role="llm-runner")}, "/", "aws")
    assert err is not None and err.code == "MeshSessionWrongRole"


# ---------------------------------------------------------------- Python and the relay agree

JS = ROOT / "wasm" / "relay" / "mesh-session.mjs"


def test_relay_pins_the_same_keys_and_v1_switch():
    src = JS.read_text()
    m = re.search(r"export const TRUSTED_KEYS = Object\.freeze\((\{.*?\})\);", src, re.S)
    assert m, "TRUSTED_KEYS not found in mesh-session.mjs"
    js_keys = json.loads(re.sub(r",\s*}", "}", m.group(1)) or "{}")
    py = _module_constants()          # read from the source: the test's monkeypatching must not hide a mismatch
    assert js_keys == py["TRUSTED_KEYS"]
    v1 = re.search(r"export const V1_ACCEPTED = (true|false);", src)
    assert v1 and (v1.group(1) == "true") == py["V1_ACCEPTED"]


def _module_constants() -> dict:
    import ast
    tree = ast.parse((ROOT / "core" / "mesh_session.py").read_text())
    out = {}
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id in ("TRUSTED_KEYS", "V1_ACCEPTED"):
            out[target.id] = ast.literal_eval(node.value)
    assert set(out) == {"TRUSTED_KEYS", "V1_ACCEPTED"}
    return out


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_python_minted_v2_verifies_in_the_relay_and_back():
    tok = v2("max")
    script = f"""
import {{ verify, mintV2 }} from {json.dumps(JS.as_uri())};
import crypto from "node:crypto";
const trusted = {{ {json.dumps(KID)}: {json.dumps(PUB)} }};
const c = verify({json.dumps(tok)}, "", Date.now() / 1000, {{ trusted, v1Accepted: false }});
if (c.tier !== "max") throw new Error("python->js failed");
const pkcs8 = Buffer.concat([Buffer.from("302e020100300506032b657004220420", "hex"), Buffer.from({json.dumps(_b64(SEED))}, "base64url")]);
const priv = crypto.createPrivateKey({{ key: pkcs8, format: "der", type: "pkcs8" }});
console.log(mintV2(priv, {json.dumps(KID)}, {{ tier: "pro", session_id: "s-2", session_end: Date.now() / 1000 + 600 }}));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert ms.verify(out.stdout.strip())["session_id"] == "s-2"


def test_spec_test_vector_still_holds(monkeypatch):
    """docs/architecture/v4.0/MESH-SESSION-ED25519.md §6: the portal checks its implementation against this token."""
    doc = (ROOT / "docs" / "architecture" / "v4.0" / "MESH-SESSION-ED25519.md").read_text()
    want = re.search(r"^token\s+(v2\.\S+)$", doc, re.M).group(1)
    pub = re.search(r"^public key\s+(\S+)$", doc, re.M).group(1)
    got = ms.mint_v2("acct-42", "pro", 1800000000, private_key=bytes(range(32)), kid="test-vector", primary_cloud="aws",
                     session_id="sess-42", now=1799990000)
    assert got == want
    monkeypatch.setattr(ms, "TRUSTED_KEYS", {"test-vector": pub})
    assert ms.verify(want, now=1799995000)["sub"] == "acct-42"


def test_the_test_vector_key_is_never_pinned():
    src = (ROOT / "core" / "mesh_session.py").read_text() + (ROOT / "wasm" / "relay" / "mesh-session.mjs").read_text()
    assert "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg" not in src and "test-vector" not in src
