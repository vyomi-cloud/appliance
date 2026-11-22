"""Test-only Ed25519 (v2) session-token signer: the PUBLIC test vector of docs/architecture/v4.0/MESH-SESSION-ED25519.md.

Since v1 (HMAC) tokens are retired (V1_ACCEPTED = False, finding F2), tests need tokens the code trusts. The production key is
pinned in core/mesh_session.py TRUSTED_KEYS and its private half lives only in the portal, so tests sign with this published
seed and add its public key to TRUSTED_KEYS IN THEIR OWN PROCESS:

    from tests.mesh_testkey import trust, mint
    trust(mesh_session)                      # script-style tests; pytest: monkeypatch.setattr(ms, "TRUSTED_KEYS", trusted(ms))
    tok = mint("acct-1", "pro", time.time() + 3600, primary_cloud="aws")

Never from the environment or a file: that is what the Codespace owner controls (the whole point of pinning keys in code).
Relay processes started by tests trust it through wasm/relay/test-fixtures/trust-test-key.mjs (a `node --import` hook).
The seed is public, so a token signed with it proves nothing outside a test process that chose to trust it.
"""
from __future__ import annotations

import time
from typing import Optional

TEST_KID = "test-vector"
TEST_SEED = bytes(range(32))                                     # 0x00..0x1f, the spec's test vector
TEST_PUB = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
WRONG_SEED = bytes(range(32, 64))                                # signs tokens that claim TEST_KID but fail verification


def trusted(ms) -> dict:
    """TRUSTED_KEYS plus the test key (for monkeypatch.setattr)."""
    return {**ms.TRUSTED_KEYS, TEST_KID: TEST_PUB}


def trust(ms) -> None:
    """Add the test key to this process's TRUSTED_KEYS (script-style tests; idempotent)."""
    ms.TRUSTED_KEYS = trusted(ms)


def mint(account: str, tier: str, session_end: float, *, primary_cloud: str = "", session_id: str = "",
         now: Optional[float] = None, role: str = "", model: str = "", key: object = None, seed: bytes = TEST_SEED) -> str:
    """A v2 token signed with the test seed. `key` is accepted and ignored so v1-era call sites (mint(..., key=KEY)) port
    with a one-line import change: a v2 token needs no shared key anywhere."""
    from core import mesh_session as ms
    return ms.mint_v2(account, tier, session_end, private_key=seed, kid=TEST_KID, primary_cloud=primary_cloud,
                      session_id=session_id, now=time.time() if now is None else now, role=role, model=model)


def forged(account: str, tier: str, session_end: float, **kw) -> str:
    """Claims the trusted test kid but is signed by another key: must be refused with MeshSessionBadSignature."""
    kw.pop("key", None)
    return mint(account, tier, session_end, seed=WRONG_SEED, **kw)
