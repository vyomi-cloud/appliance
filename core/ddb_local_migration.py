"""One-time migration: DynamoDB Local → the v4 shared DynamoDB core (Pro/Max only).

Before v4 "C0" the offline appliance proxied the DynamoDB wire to an
amazon/dynamodb-local container (CLOUDLEARN_DYNAMODB_URL, data in its /data volume).
Since C0 the wire is served by core/dynamodb_core.py over the appliance's own
space-scoped state (core/appliance_stores.ddb_store()). Without a migration, an
upgraded appliance would show EMPTY DynamoDB — every table a user created through
an SDK / the CLI before the upgrade lived only in DynamoDB Local.

On appliance start (server.py startup hook) `maybe_migrate()` copies, ONCE:
  * every table: KeySchema, AttributeDefinitions, billing mode + provisioned
    throughput, GSIs + LSIs (projections), table class, deletion protection,
    TTL settings, point-in-time-recovery flag and tags (each "where readable":
    DynamoDB Local rejects tagging, so tags are usually absent);
  * every item (Scan with ExclusiveStartKey paging), written through the core's
    own PutItem so typed values (sets, lists, exact numbers, binary) are preserved.

Preconditions (all must hold, otherwise nothing is touched):
  * VYOMI_DDB_MIGRATE_FROM_LOCAL is not "0" (set it to "0" to opt out);
  * the native DynamoDB wire is served by the unified core (C0, the default);
  * no migration marker is recorded yet (STATE["migrations"]["ddb_local"]);
  * a DynamoDB Local endpoint answers ListTables (CLOUDLEARN_DYNAMODB_URL,
    default http://cloudlearn-dynamodb:8000);
  * the core's (active space) DynamoDB state has NO tables yet — so a migration
    can never overwrite or merge into data created after the upgrade.
    (VYOMI_DDB_MIGRATE_FROM_LOCAL=merge relaxes this: tables missing from the core
    are copied whole, tables present in both are left untouched.)

The marker is recorded after a completed copy (also when DynamoDB Local is
reachable but holds no tables), so it never repeats. When DynamoDB Local is not
reachable nothing is recorded: the next start tries again (the background retry
covers a dynamodb container that comes up after the appliance).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

MARKER_KEY = "ddb_local"
_DEFAULT_URL = "http://cloudlearn-dynamodb:8000"
_TARGET = "DynamoDB_20120810."
_LOCK = threading.Lock()


def _log_default(msg: str) -> None:
    print(msg, flush=True)


def _endpoint() -> str:
    return os.environ.get("CLOUDLEARN_DYNAMODB_URL", _DEFAULT_URL).rstrip("/")


def mode() -> str:
    """"off" | "merge" | "on" (default)."""
    raw = os.environ.get("VYOMI_DDB_MIGRATE_FROM_LOCAL", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return "off"
    return "merge" if raw == "merge" else "on"


class _Local:
    """Minimal DynamoDB JSON-wire client for the source (no boto3 dependency)."""

    def __init__(self, url: str, timeout: float = 10.0):
        self.url, self.timeout = url, timeout

    def call(self, op: str, payload: dict, timeout: float | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            self.url + "/", data=json.dumps(payload).encode(), method="POST",
            headers={"X-Amz-Target": _TARGET + op, "Content-Type": "application/x-amz-json-1.0",
                     "Authorization": "AWS4-HMAC-SHA256 Credential=vyomi/20260101/us-east-1/dynamodb/aws4_request, "
                                      "SignedHeaders=host, Signature=00"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}

    def reachable(self) -> bool:
        try:
            return self.call("ListTables", {"Limit": 1}, timeout=2.0)[0] == 200
        except Exception:
            return False

    def table_names(self) -> list[str]:
        names, start = [], None
        while True:
            body = {"Limit": 100, **({"ExclusiveStartTableName": start} if start else {})}
            st, out = self.call("ListTables", body)
            if st != 200:
                raise RuntimeError(f"ListTables failed: {st} {out}")
            names += out.get("TableNames", [])
            start = out.get("LastEvaluatedTableName")
            if not start:
                return names


def _create_payload(desc: dict) -> dict:
    """DescribeTable → CreateTable request (schema, billing, indexes, settings)."""
    billing = ((desc.get("BillingModeSummary") or {}).get("BillingMode") or "PROVISIONED").upper()
    p: dict[str, Any] = {"TableName": desc["TableName"], "KeySchema": desc.get("KeySchema") or [],
                         "AttributeDefinitions": desc.get("AttributeDefinitions") or [], "BillingMode": billing}
    pt = desc.get("ProvisionedThroughput") or {}
    if billing == "PROVISIONED":
        p["ProvisionedThroughput"] = {"ReadCapacityUnits": int(pt.get("ReadCapacityUnits") or 5),
                                      "WriteCapacityUnits": int(pt.get("WriteCapacityUnits") or 5)}
    for src, dst in (("GlobalSecondaryIndexes", "GlobalSecondaryIndexes"), ("LocalSecondaryIndexes", "LocalSecondaryIndexes")):
        idx = []
        for i in desc.get(src) or []:
            spec = {"IndexName": i["IndexName"], "KeySchema": i.get("KeySchema") or [],
                    "Projection": i.get("Projection") or {"ProjectionType": "ALL"}}
            if dst == "GlobalSecondaryIndexes" and billing == "PROVISIONED":
                ipt = i.get("ProvisionedThroughput") or pt
                spec["ProvisionedThroughput"] = {"ReadCapacityUnits": int(ipt.get("ReadCapacityUnits") or 5),
                                                 "WriteCapacityUnits": int(ipt.get("WriteCapacityUnits") or 5)}
            idx.append(spec)
        if idx:
            p[dst] = idx
    tc = (desc.get("TableClassSummary") or {}).get("TableClass")
    if tc:
        p["TableClass"] = tc
    if desc.get("DeletionProtectionEnabled"):
        p["DeletionProtectionEnabled"] = True
    sse = desc.get("SSEDescription") or {}
    if sse.get("Status") == "ENABLED" and sse.get("SSEType"):
        p["SSESpecification"] = {"Enabled": True, "SSEType": sse["SSEType"]}
    return p


def migrate_table(src: _Local, store, name: str, log: Callable[[str], None]) -> int:
    """Copy one table (schema + settings + items) into `store`. Returns items copied."""
    from core import dynamodb_core as ddb

    def core(op: str, payload: dict) -> dict:
        r = ddb.dispatch(store, _TARGET + op, payload)
        if r.status != 200:
            raise RuntimeError(f"{op} {name}: {r.body.get('__type')}: {r.body.get('message')}")
        return r.body

    st, out = src.call("DescribeTable", {"TableName": name})
    if st != 200:
        raise RuntimeError(f"DescribeTable {name}: {st} {out}")
    desc = out["Table"]
    core("CreateTable", _create_payload(desc))

    count, esk = 0, None
    while True:
        body = {"TableName": name, **({"ExclusiveStartKey": esk} if esk else {})}
        st, page = src.call("Scan", body)
        if st != 200:
            raise RuntimeError(f"Scan {name}: {st} {page}")
        for item in page.get("Items", []):
            core("PutItem", {"TableName": name, "Item": item})
            count += 1
        esk = page.get("LastEvaluatedKey")
        if not esk:
            break

    # settings that live outside DescribeTable — best effort, "where readable"
    st, ttl = src.call("DescribeTimeToLive", {"TableName": name})
    tdesc = (ttl or {}).get("TimeToLiveDescription") or {}
    if st == 200 and tdesc.get("TimeToLiveStatus") in ("ENABLED", "ENABLING") and tdesc.get("AttributeName"):
        core("UpdateTimeToLive", {"TableName": name, "TimeToLiveSpecification":
                                  {"AttributeName": tdesc["AttributeName"], "Enabled": True}})
    st, cb = src.call("DescribeContinuousBackups", {"TableName": name})
    pitr = ((cb or {}).get("ContinuousBackupsDescription") or {}).get("PointInTimeRecoveryDescription") or {}
    if st == 200 and pitr.get("PointInTimeRecoveryStatus") == "ENABLED":
        core("UpdateContinuousBackups", {"TableName": name,
                                         "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}})
    arn = desc.get("TableArn") or ""
    st, tags = src.call("ListTagsOfResource", {"ResourceArn": arn}) if arn else (0, {})
    if st == 200 and (tags or {}).get("Tags"):
        core("TagResource", {"ResourceArn": f"arn:aws:dynamodb:us-east-1:{store.account_id}:table/{name}",
                             "Tags": tags["Tags"]})
    return count


def _marker_state() -> dict:
    from core import app_context as ctx
    return ctx.STATE.setdefault("migrations", {})


def maybe_migrate(store=None, *, log: Callable[[str], None] = _log_default, persist: Callable[[], None] | None = None) -> dict:
    """Run the one-time DynamoDB Local → core migration if every precondition holds.
    Returns a summary dict ({"status": "migrated" | "skipped" | "unreachable" | "error", ...})."""
    m = mode()
    if m == "off":
        return {"status": "skipped", "reason": "VYOMI_DDB_MIGRATE_FROM_LOCAL=0"}
    from core import wire_ingress
    if not wire_ingress.is_unified("dynamodb"):
        return {"status": "skipped", "reason": "legacy DynamoDB wire (DynamoDB Local is still the backend)"}
    with _LOCK:
        markers = _marker_state()
        if MARKER_KEY in markers:
            return {"status": "skipped", "reason": "already migrated", "marker": markers[MARKER_KEY]}
        if store is None:
            from core import appliance_stores
            store = appliance_stores.ddb_store()
        existing = set(store.table_names())
        if existing and m != "merge":
            return {"status": "skipped", "reason": f"core already has {len(existing)} table(s)"}
        url = _endpoint()
        src = _Local(url)
        if not src.reachable():
            return {"status": "unreachable", "endpoint": url}
        started = time.time()
        tables, items, errors, skipped = [], 0, [], []
        try:
            names = src.table_names()
        except Exception as exc:
            log(f"[ddb-migrate] listing tables on {url} failed: {exc}")
            return {"status": "error", "endpoint": url, "error": str(exc)}
        for name in names:
            if name in existing:
                skipped.append(name)
                continue
            try:
                n = migrate_table(src, store, name, log)
                tables.append({"table": name, "items": n})
                items += n
            except Exception as exc:          # one bad table never blocks the others
                errors.append({"table": name, "error": str(exc)})
                try:
                    store.drop_table(name)    # no half-copied table left behind
                except Exception:
                    pass
        summary = {"status": "migrated", "endpoint": url, "tables": len(tables), "items": items,
                   "detail": tables, "errors": errors, "skipped_existing": skipped, "mode": m,
                   "seconds": round(time.time() - started, 2),
                   "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if not errors:          # a failed table is retried on the next start
            markers[MARKER_KEY] = {k: v for k, v in summary.items() if k != "detail"}
        try:
            store.persist()
        except Exception:
            pass
        if persist is None:
            from core import app_context as ctx
            persist = ctx.persist_state
        try:
            persist()
        except Exception as exc:
            log(f"[ddb-migrate] persisting state failed: {exc}")
        log(f"[ddb-migrate] DynamoDB Local ({url}) -> Vyomi core: {len(tables)} table(s), {items} item(s) "
            f"in {summary['seconds']}s" + (f"; {len(errors)} table(s) FAILED: {errors}" if errors else "")
            + (f"; left existing: {skipped}" if skipped else ""))
        return summary


def start_at_boot(log: Callable[[str], None] = _log_default) -> None:
    """Startup hook: try now; if DynamoDB Local isn't up yet, retry in the background
    for VYOMI_DDB_MIGRATE_WAIT_S seconds (default 120) — never blocks or breaks boot."""
    try:
        first = maybe_migrate(log=log)
    except Exception as exc:
        log(f"[ddb-migrate] skipped: {exc}")
        return
    if first.get("status") != "unreachable":
        return
    wait = float(os.environ.get("VYOMI_DDB_MIGRATE_WAIT_S", "120") or 0)
    if wait <= 0:
        return

    def _retry():
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(10)
            try:
                r = maybe_migrate(log=log)
            except Exception as exc:
                log(f"[ddb-migrate] retry failed: {exc}")
                return
            if r.get("status") != "unreachable":
                return
    threading.Thread(target=_retry, daemon=True, name="vyomi-ddb-migrate").start()
