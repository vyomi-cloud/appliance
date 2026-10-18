"""Delegate Firestore to the official Google Firestore emulator (P1.2).

When FIRESTORE_EMULATOR_HOST is set, the simulator's document handlers route
through these helpers so the console and external Firestore SDKs (pointed at the
same emulator + project) share ONE state. Handles arbitrary subcollection paths
(users/alice/orders) and converts between the Firestore REST typed-value format
({"stringValue": ...}) and native Python.
"""
from __future__ import annotations

import base64
import datetime
import os
from functools import lru_cache


def _host() -> str:
    return os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("CLOUDLEARN_FIRESTORE_EMULATOR_HOST") or ""


def available() -> bool:
    if not _host():
        return False
    try:
        import google.cloud.firestore  # noqa: F401
        return True
    except Exception:
        return False


def _ensure_env() -> None:
    h = _host()
    if h and not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        os.environ["FIRESTORE_EMULATOR_HOST"] = h


@lru_cache(maxsize=8)
def _client(project: str, database: str):
    _ensure_env()
    from google.cloud import firestore
    try:
        return firestore.Client(project=project, database=database or "(default)")
    except TypeError:
        return firestore.Client(project=project)


# ── typed-value conversion (Firestore REST <-> Python) ──────────────────────
def to_python(fields: dict) -> dict:
    return {k: _from_typed(v) for k, v in (fields or {}).items()}


def _from_typed(v):
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        try:
            return int(v["integerValue"])
        except (TypeError, ValueError):
            return 0
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "bytesValue" in v:
        try:
            return base64.b64decode(v["bytesValue"])
        except Exception:
            return b""
    if "arrayValue" in v:
        return [_from_typed(x) for x in (v["arrayValue"].get("values") or [])]
    if "mapValue" in v:
        return {k: _from_typed(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    if "geoPointValue" in v:
        return v["geoPointValue"]
    if "referenceValue" in v:
        return v["referenceValue"]
    return None


def to_typed(data: dict) -> dict:
    return {k: _to_typed(v) for k, v in (data or {}).items()}


def _to_typed(val):
    if val is None:
        return {"nullValue": None}
    if isinstance(val, bool):
        return {"booleanValue": val}
    if isinstance(val, int):
        return {"integerValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": val}
    if isinstance(val, str):
        return {"stringValue": val}
    if isinstance(val, (bytes, bytearray)):
        return {"bytesValue": base64.b64encode(bytes(val)).decode("ascii")}
    if isinstance(val, datetime.datetime):
        return {"timestampValue": val.isoformat()}
    if isinstance(val, list):
        return {"arrayValue": {"values": [_to_typed(x) for x in val]}}
    if isinstance(val, dict):
        return {"mapValue": {"fields": {k: _to_typed(x) for k, x in val.items()}}}
    return {"stringValue": str(val)}


# ── reference builders for nested subcollection paths ───────────────────────
def _coll_ref(client, coll_path: str):
    parts = [p for p in str(coll_path).split("/") if p]
    ref = client.collection(parts[0])
    for i in range(1, len(parts)):
        ref = ref.document(parts[i]) if i % 2 == 1 else ref.collection(parts[i])
    return ref


def _doc_ref(client, coll_path: str, doc_id: str):
    return _coll_ref(client, coll_path).document(doc_id)


def _ts(t) -> str:
    try:
        return t.isoformat() if t else ""
    except Exception:
        return ""


def _view(project: str, database: str, coll_path: str, doc_id: str, snap) -> dict:
    return {
        "name": f"projects/{project}/databases/{database}/documents/{coll_path}/{doc_id}",
        "fields": to_typed(snap.to_dict() or {}),
        "createTime": _ts(getattr(snap, "create_time", None)),
        "updateTime": _ts(getattr(snap, "update_time", None)),
    }


# ── CRUD ────────────────────────────────────────────────────────────────────
def create(project: str, database: str, coll_path: str, doc_id: str, fields_typed: dict) -> dict:
    c = _client(project, database)
    ref = _doc_ref(c, coll_path, doc_id)
    ref.set(to_python(fields_typed))
    return _view(project, database, coll_path, doc_id, ref.get())


def get(project: str, database: str, coll_path: str, doc_id: str) -> dict | None:
    c = _client(project, database)
    snap = _doc_ref(c, coll_path, doc_id).get()
    if not snap.exists:
        return None
    return _view(project, database, coll_path, doc_id, snap)


def update(project: str, database: str, coll_path: str, doc_id: str, fields_typed: dict) -> dict | None:
    c = _client(project, database)
    ref = _doc_ref(c, coll_path, doc_id)
    if not ref.get().exists:
        return None
    ref.set(to_python(fields_typed), merge=True)
    return _view(project, database, coll_path, doc_id, ref.get())


def delete(project: str, database: str, coll_path: str, doc_id: str) -> bool:
    c = _client(project, database)
    ref = _doc_ref(c, coll_path, doc_id)
    existed = ref.get().exists
    ref.delete()
    return existed


def list_collection(project: str, database: str, coll_path: str) -> list[dict]:
    try:
        c = _client(project, database)
        return [_view(project, database, coll_path, snap.id, snap) for snap in _coll_ref(c, coll_path).stream()]
    except Exception:
        return []


def list_root(project: str, database: str) -> list[dict]:
    try:
        c = _client(project, database)
        out = []
        for coll in c.collections():
            for snap in coll.stream():
                out.append(_view(project, database, coll.id, snap.id, snap))
        return out
    except Exception:
        return []
