# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""RDS Data API core — `boto3.client('rds-data')` over HTTP, served in-browser.

The RDS Data API (service `rds-data`, the Aurora Serverless HTTP/JSON SQL surface)
lets an app run SQL over plain HTTPS — no Postgres-wire TCP. That makes it the ONE
relational path that can traverse the Nano HTTP relay: an unmodified
`boto3.client('rds-data').execute_statement(...)` from an external app is served by
the in-browser SQL engine (PGlite real Postgres, or the sqlite3 default).

It is a rest-json service: the action is the request PATH (`/Execute`,
`/BatchExecute`, `/BeginTransaction`, `/CommitTransaction`, `/RollbackTransaction`),
the body is JSON, and field values are AWS-typed (`stringValue`/`longValue`/
`doubleValue`/`booleanValue`/`isNull`/`blobValue`). This core translates that wire
onto the SqlStore data plane (`rds_core.aexecute_sql`) — the SAME engine the RDS
control plane and the in-tab SQL bridge use — and maps results back to Data API
shape. Named `:params` are rewritten to the engine's native placeholder via the
store's `param_placeholder` (so dialect stays with the engine).

Async, because the data plane is async (PGlite). Substrate-free (stdlib + the
SqlStore seam only) so it loads on host CPython AND Pyodide, and is provable on
both. Errors use rest-json shape (`{"message": ...}` + `x-amzn-errortype` header),
which botocore surfaces as the typed exception.

Honest boundary: BeginTransaction/Commit/Rollback are accepted and well-shaped, but
each ExecuteStatement autocommits (no cross-call transactional isolation yet) — so
don't rely on rollback. ExecuteStatement + BatchExecuteStatement are the real path.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

try:
    from core import rds_core as rds
except ImportError:  # pragma: no cover - Pyodide flat layout
    import rds_core as rds  # type: ignore

# `:name`, but NOT `::cast` (negative lookbehind) and not a `::type` suffix.
_NAMED = re.compile(r"(?<!:):([A-Za-z_]\w*)")

# rest-json action = last path segment (lower-cased).
_PATHS = {"execute", "batchexecute", "begintransaction",
          "committransaction", "rollbacktransaction", "executesql"}


@dataclass
class RdsDataResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


def action_of(path: str) -> str:
    return (path or "").rstrip("/").rsplit("/", 1)[-1].lower()


def is_data_api_path(path: str) -> bool:
    return action_of(path) in _PATHS


def _ok(body: dict) -> RdsDataResponse:
    return RdsDataResponse(status=200, body=body)


def _error(status: int, err_type: str, message: str) -> RdsDataResponse:
    return RdsDataResponse(status=status, body={"message": message},
                           headers={"x-amzn-errortype": err_type})


# ── AWS-typed field <-> python value ───────────────────────────────────────
def _field_to_py(f):
    if not isinstance(f, dict):
        return None
    if f.get("isNull"):
        return None
    for k in ("stringValue", "longValue", "doubleValue", "booleanValue"):
        if k in f:
            return f[k]
    if "blobValue" in f:
        try:
            return base64.b64decode(f["blobValue"])
        except Exception:
            return None
    return None


def _py_to_field(v) -> dict:
    if v is None:
        return {"isNull": True}
    if isinstance(v, bool):          # before int — bool is a subclass of int
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"longValue": v}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (bytes, bytearray)):
        return {"blobValue": base64.b64encode(bytes(v)).decode()}
    return {"stringValue": str(v)}


def _db_id(body: dict) -> str:
    """Resolve the target instance id from resourceArn (…:cluster:<id> / …:db:<id>)
    or the `database` field."""
    arn = body.get("resourceArn") or ""
    if arn:
        return arn.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    return body.get("database") or ""


def _rewrite(store, sql: str, params_list) -> tuple[str, list]:
    """Rewrite `:name` placeholders to the engine's native style and order values."""
    values = {p.get("name"): _field_to_py(p.get("value"))
              for p in (params_list or []) if isinstance(p, dict)}
    ordered: list = []

    def repl(m):
        ordered.append(values.get(m.group(1)))
        return store.param_placeholder(len(ordered))

    return _NAMED.sub(repl, sql or ""), ordered


def _data_error(res: dict) -> RdsDataResponse:
    # The data plane already classified the failure; surface it as the Data API's
    # catch-all BadRequestException (what botocore raises for these).
    return _error(400, "BadRequestException",
                  f"{res.get('code', 'SQLError')}: {res.get('message', '')}")


def _shape_result(res: dict, include_metadata: bool) -> dict:
    is_select = bool(res.get("columns"))
    out = {"numberOfRecordsUpdated": 0 if is_select else int(res.get("rowcount") or 0),
           "generatedFields": []}
    if is_select:
        out["records"] = [[_py_to_field(c) for c in row] for row in res.get("rows", [])]
        if include_metadata:
            out["columnMetadata"] = [{"name": c, "label": c, "typeName": "text"}
                                     for c in res["columns"]]
    return out


async def _execute_statement(store, body: dict) -> RdsDataResponse:
    new_sql, params = _rewrite(store, body.get("sql") or "", body.get("parameters"))
    res = await rds.aexecute_sql(store, _db_id(body), new_sql, params)
    if not res.get("ok"):
        return _data_error(res)
    return _ok(_shape_result(res, bool(body.get("includeResultMetadata"))))


async def _batch_execute(store, body: dict) -> RdsDataResponse:
    db_id = _db_id(body)
    sql = body.get("sql") or ""
    results = []
    for pset in (body.get("parameterSets") or [[]]):
        new_sql, params = _rewrite(store, sql, pset)
        res = await rds.aexecute_sql(store, db_id, new_sql, params)
        if not res.get("ok"):
            return _data_error(res)
        results.append({"generatedFields": []})
    return _ok({"updateResults": results})


async def dispatch(store, path: str, payload: dict | None = None) -> RdsDataResponse:
    """Native RDS Data API router. `path` carries the action; `payload` is the JSON
    body. Returns an RdsDataResponse (status, body dict, headers)."""
    body = payload if isinstance(payload, dict) else {}
    action = action_of(path)
    try:
        if action == "execute":
            return await _execute_statement(store, body)
        if action == "batchexecute":
            return await _batch_execute(store, body)
        if action == "begintransaction":
            # autocommit: a token so the SDK is satisfied (see module docstring).
            return _ok({"transactionId": "nano-tx-" + (_db_id(body) or "default")})
        if action == "committransaction":
            return _ok({"transactionStatus": "Transaction Committed"})
        if action == "rollbacktransaction":
            return _ok({"transactionStatus": "Rollback Complete"})
        return _error(404, "BadRequestException", f"Unknown Data API action: {action}")
    except Exception as e:  # pragma: no cover - defensive
        return _error(400, "BadRequestException", str(e))
