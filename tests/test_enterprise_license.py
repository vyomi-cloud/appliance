"""Enterprise claim enforcement (enterprise-access-spec.md §3.5-3.6, A4).

Mints RS256 license JWTs against a locally generated RSA key, serves them
through a monkeypatched `core.license_remote._fetch_jwks` (no network), and
exercises both verify_license_jwt's claim passthrough and server.py's
VYOMI_REQUIRED_ENTERPRISE enforcement in `_apply_license_jwt`.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_TEST_DIR = Path(tempfile.mkdtemp(prefix="cloudlearn-enterprise-license-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))

from core import license_remote as lr  # noqa: E402
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-kid-1"


def _jwks() -> dict:
    nums = _PRIVATE_KEY.public_key().public_numbers()
    n_bytes = nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")
    e_bytes = nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big")
    return {"keys": [{
        "kty": "RSA", "use": "sig", "alg": "RS256", "kid": _KID,
        "n": _b64url(n_bytes), "e": _b64url(e_bytes),
    }]}


def _mint(claims: dict, *, kid: str = _KID) -> str:
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header).encode())
    claims_b64 = _b64url(json.dumps(claims).encode())
    signing_input = f"{header_b64}.{claims_b64}".encode("ascii")
    signature = _PRIVATE_KEY.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_b64}.{claims_b64}.{_b64url(signature)}"


def _base_claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "exp": now + 3600, "nbf": now - 10,
        "aud": lr.EXPECTED_AUDIENCE, "tier": "enterprise",
        "seats": 1, "jti": f"jti-{now}-{overrides.get('ent', 'none')}",
        "sub": "user-1", "iss": "vyomi.cloud",
    }
    claims.update(overrides)
    return claims


class VerifyLicenseJwtTest(unittest.TestCase):
    """Pure unit tests against core.license_remote — no server involved."""

    def setUp(self):
        self._orig_fetch = lr._fetch_jwks
        lr._fetch_jwks = lambda backend_url: _jwks()
        lr._jwks_cache.update({"keys": [], "fetched_at": 0.0, "backend_url": ""})

    def tearDown(self):
        lr._fetch_jwks = self._orig_fetch
        lr._jwks_cache.update({"keys": [], "fetched_at": 0.0, "backend_url": ""})

    def test_valid_token_accepted_without_ent(self):
        token = _mint(_base_claims())
        claims = lr.verify_license_jwt(token)
        self.assertEqual(claims["tier"], "enterprise")
        self.assertIsNone(claims.get("ent"))

    def test_valid_token_with_enterprise_claims_accepted(self):
        token = _mint(_base_claims(ent="ent-1", ent_role="admin", gh_uid=42))
        claims = lr.verify_license_jwt(token)
        self.assertEqual(claims["ent"], "ent-1")
        self.assertEqual(claims["ent_role"], "admin")
        self.assertEqual(claims["gh_uid"], 42)

    def test_bad_signature_rejected(self):
        token = _mint(_base_claims())
        tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
        with self.assertRaises(ValueError):
            lr.verify_license_jwt(tampered)

    def test_expired_token_rejected(self):
        token = _mint(_base_claims(exp=int(time.time()) - 3600))
        with self.assertRaises(ValueError):
            lr.verify_license_jwt(token)

    def test_claims_to_tier_payload_passes_through_enterprise_claims(self):
        payload = lr.claims_to_tier_payload(_base_claims(ent="ent-9", ent_role="member", gh_uid=7))
        self.assertEqual(payload["ent"], "ent-9")
        self.assertEqual(payload["ent_role"], "member")
        self.assertEqual(payload["gh_uid"], 7)

    def test_claims_to_tier_payload_ent_absent_is_none(self):
        payload = lr.claims_to_tier_payload(_base_claims())
        self.assertIsNone(payload["ent"])
        self.assertIsNone(payload["ent_role"])
        self.assertIsNone(payload["gh_uid"])


class ApplyLicenseJwtEnterpriseGateTest(unittest.TestCase):
    """server._apply_license_jwt's VYOMI_REQUIRED_ENTERPRISE enforcement."""

    def setUp(self):
        self._orig_fetch = lr._fetch_jwks
        lr._fetch_jwks = lambda backend_url: _jwks()
        lr._jwks_cache.update({"keys": [], "fetched_at": 0.0, "backend_url": ""})
        self._orig_required_ent = os.environ.get("VYOMI_REQUIRED_ENTERPRISE")

    def tearDown(self):
        lr._fetch_jwks = self._orig_fetch
        lr._jwks_cache.update({"keys": [], "fetched_at": 0.0, "backend_url": ""})
        if self._orig_required_ent is None:
            os.environ.pop("VYOMI_REQUIRED_ENTERPRISE", None)
        else:
            os.environ["VYOMI_REQUIRED_ENTERPRISE"] = self._orig_required_ent

    def test_no_required_enterprise_accepts_any_jwt(self):
        os.environ.pop("VYOMI_REQUIRED_ENTERPRISE", None)
        token = _mint(_base_claims(ent="ent-1"))
        claims = server._apply_license_jwt(token)
        self.assertEqual(claims["ent"], "ent-1")

    def test_matching_enterprise_accepted_and_stored(self):
        os.environ["VYOMI_REQUIRED_ENTERPRISE"] = "ent-1"
        token = _mint(_base_claims(ent="ent-1"))
        server._apply_license_jwt(token)
        tid = server._active_tenant_id() or server.DEFAULT_TENANT_ID
        tenant = server._tenants_state()["tenants"][tid]
        self.assertEqual(tenant["license_enterprise"], "ent-1")

    def test_mismatched_enterprise_rejected(self):
        os.environ["VYOMI_REQUIRED_ENTERPRISE"] = "ent-1"
        token = _mint(_base_claims(ent="ent-2"))
        with self.assertRaises(HTTPException) as ctx:
            server._apply_license_jwt(token)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail["code"], "enterprise_mismatch")

    def test_missing_enterprise_claim_rejected_when_required(self):
        os.environ["VYOMI_REQUIRED_ENTERPRISE"] = "ent-1"
        token = _mint(_base_claims())  # no "ent" claim at all
        with self.assertRaises(HTTPException) as ctx:
            server._apply_license_jwt(token)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail["code"], "enterprise_mismatch")


class RevocationPollIntervalTest(unittest.TestCase):
    """A5: the revocation poll interval is configurable (was hard-coded 24h)."""

    def test_configurable_interval_detects_revocation_promptly(self):
        import threading

        jti = "jti-revoke-me"
        state = {"license_claims": {"jti": jti}}
        revoked_event = threading.Event()

        self._orig_fetch_list = lr.fetch_revocation_list
        lr.fetch_revocation_list = lambda backend_url: [jti]
        self._orig_poll_thread = lr._POLL_THREAD
        lr._POLL_THREAD = None  # force a fresh thread for this test

        def on_revoked(claims):
            revoked_event.set()

        try:
            lr.start_revocation_poll(state, interval_seconds=2, on_revoked=on_revoked)
            self.assertTrue(revoked_event.wait(timeout=5),
                             "on_revoked was not called within 5s of a 2s poll interval")
        finally:
            lr.fetch_revocation_list = self._orig_fetch_list
            lr._POLL_THREAD = self._orig_poll_thread


if __name__ == "__main__":
    unittest.main()
