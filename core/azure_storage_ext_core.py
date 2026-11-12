"""Azure Storage account extras (Nano / dev_server / unified-ingress core).

* Access keys: per-account ``key1`` / ``key2`` minted on first use (random, base64, 64 bytes), returned by
  ``listKeys`` and really ROTATED by ``regenerateKey`` ({"keyName": "key1"|"key2"}), recording
  ``properties.keyCreationTime`` per key. ``properties.keyPolicy.keyExpirationPeriodInDays`` is stored (generic
  PATCH) and reported as ``keyExpiration`` per key so the portal's expiry reminders work.
* Route-specific endpoints: ``routingPreference.publishMicrosoftEndpoints`` / ``publishInternetEndpoints`` really
  add ``primaryEndpoints.microsoftEndpoints`` / ``internetEndpoints`` to the account view.

NOT modelled: the Blob data plane does not verify SharedKey signatures, so a rotated key does not invalidate
requests signed with the previous one.
"""
from __future__ import annotations

import base64
import datetime
import os

KEY_NAMES = ("key1", "key2")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _mint() -> str:
    return base64.b64encode(os.urandom(64)).decode()


def _keys(rec: dict) -> dict:
    ks = rec.setdefault("_keys", {})
    created = rec.setdefault("properties", {}).setdefault("keyCreationTime", {})
    for n in KEY_NAMES:
        if n not in ks:
            ks[n] = _mint()
            created.setdefault(n, rec.get("systemData", {}).get("createdAt") or _now())
    return ks


def list_keys(rec: dict) -> dict:
    ks = _keys(rec)
    exp_days = ((rec.get("properties") or {}).get("keyPolicy") or {}).get("keyExpirationPeriodInDays")
    out = []
    for n in KEY_NAMES:
        row = {"keyName": n, "value": ks[n], "permissions": "FULL",
               "creationTime": rec["properties"]["keyCreationTime"][n]}
        if exp_days:
            try:
                t = datetime.datetime.strptime(row["creationTime"][:19], "%Y-%m-%dT%H:%M:%S")
                row["keyExpirationTime"] = (t + datetime.timedelta(days=int(exp_days))).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass
        out.append(row)
    return {"keys": out}


def regenerate(rec: dict, payload: dict) -> dict:
    name = str((payload or {}).get("keyName") or "")
    if name.lower() not in KEY_NAMES:
        return {"status": 400, "body": {"error": {"code": "InvalidKeyName", "message": "keyName must be 'key1' or 'key2'."}}}
    name = name.lower()
    _keys(rec)
    rec["_keys"][name] = _mint()
    rec["properties"]["keyCreationTime"][name] = _now()
    return {"status": 200, "body": list_keys(rec)}


def apply_endpoints(rec: dict) -> None:
    """Maintain primaryEndpoints.microsoftEndpoints / internetEndpoints from routingPreference publish flags."""
    props = rec.setdefault("properties", {})
    rp = props.get("routingPreference") or {}
    name = rec.get("name", "")
    pe = props.setdefault("primaryEndpoints", {})
    # Vyomi is single-origin: both route-specific endpoints resolve to the SAME account data path.
    for flag, key in (("publishMicrosoftEndpoints", "microsoftEndpoints"), ("publishInternetEndpoints", "internetEndpoints")):
        if rp.get(flag):
            pe[key] = {"blob": f"/{name}/", "web": f"/{name}/__website__/"}
        else:
            pe.pop(key, None)
