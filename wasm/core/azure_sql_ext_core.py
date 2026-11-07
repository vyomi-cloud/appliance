# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure SQL database watcher + SQL Data Sync, run against the REAL SQL engine behind the database (sqlite in Nano;
Postgres behind the same seam offline).  Substrate-free; called from core/azure_sql_core.dispatch.

Database watcher   ``collect`` takes a sample from the live engine: size (the engine's own page accounting), every user table
                   with its real row count, and the measured statement timings of the last window (the same ring Query
                   Performance Insight reads).  Samples are kept in a bounded ring per database; ``watch`` returns the series
                   plus alerts computed over it (latency p95 jump, failures, table growth).  Collection happens when asked
                   (the console polls while open) -- there is no background scheduler, so nothing is collected while nobody is
                   watching.  Not Data Explorer/Kusto: there is no KQL store behind it.
Data Sync          ``sync`` copies rows from a hub database to a member database (same simulator): tables are created in the
                   member from the hub's own DDL when missing, rows are upserted by primary key, and with ``deleteMissing`` rows
                   absent in the hub are removed from the member.  ``conflict``: hub-wins (default, overwrite) or skip.  Result
                   is a real per-table report; history is kept.  One direction per run (bidirectional = run both ways).
"""
from __future__ import annotations

import re
import time

CAP = 500
_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ring(store, name):
    m = getattr(store, name, None)
    if m is None:
        m = {}
        setattr(store, name, m)
    return m


def _tables(store, db_id):
    try:
        r = store.execute_sql(db_id, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return [row[0] for row in r["rows"]]
    except Exception:
        r = store.execute_sql(db_id, "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1")
        return [row[0] for row in r["rows"]]


def collect(store, db_id, rings, size_fn, window_s=60.0, now=None):
    now = now if now is not None else time.time()
    tables = []
    for t in _tables(store, db_id):
        if not _SAFE.match(t):
            continue
        n = store.execute_sql(db_id, f'SELECT COUNT(*) FROM "{t}"')["rows"][0][0]
        tables.append({"name": t, "rows": int(n)})
    recent = [r for r in rings.get(db_id, []) if r["ts"] >= now - window_s]
    lats = sorted(r["ms"] for r in recent)
    sample = {"ts": now, "sizeBytes": size_fn(store, db_id), "tables": tables, "totalRows": sum(t["rows"] for t in tables),
              "statements": len(recent), "failed": sum(1 for r in recent if not r["ok"]),
              "p95Ms": lats[min(len(lats) - 1, int(0.95 * len(lats)))] if lats else 0, "maxMs": lats[-1] if lats else 0}
    ring = _ring(store, "_azure_sql_watch").setdefault(db_id, [])
    ring.append(sample)
    del ring[:-CAP]
    return sample


def watch(store, db_id):
    ring = _ring(store, "_azure_sql_watch").get(db_id, [])
    alerts = []
    if len(ring) >= 2:
        a, b = ring[-2], ring[-1]
        if b["failed"] > 0:
            alerts.append({"severity": "Warning", "message": f"{b['failed']} statement(s) failed in the last sample window."})
        if a["p95Ms"] and b["p95Ms"] > 3 * a["p95Ms"] and b["p95Ms"] > 20:
            alerts.append({"severity": "Warning", "message": f"p95 latency rose from {a['p95Ms']} ms to {b['p95Ms']} ms."})
        prev = {t["name"]: t["rows"] for t in a["tables"]}
        for t in b["tables"]:
            if t["name"] in prev and prev[t["name"]] and t["rows"] > 2 * prev[t["name"]]:
                alerts.append({"severity": "Info", "message": f"Table {t['name']} grew from {prev[t['name']]} to {t['rows']} rows."})
        if b["sizeBytes"] > 1.5 * a["sizeBytes"] > 0:
            alerts.append({"severity": "Info", "message": f"Database size grew from {a['sizeBytes']} to {b['sizeBytes']} bytes."})
    return {"samples": ring[-200:], "latest": ring[-1] if ring else None, "alerts": alerts, "sampleCount": len(ring)}


def _ddl(store, db_id, table):
    r = store.execute_sql(db_id, "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", [table])
    return r["rows"][0][0] if r["rows"] else None


def _pk_cols(store, db_id, table):
    r = store.execute_sql(db_id, f'PRAGMA table_info("{table}")')
    pk = sorted((row[5], row[1]) for row in r["rows"] if row[5])
    return [c for _, c in pk]


def sync(store, hub_id, member_id, tables=None, conflict="hub-wins", delete_missing=False):
    if conflict not in ("hub-wins", "skip"):
        return {"ok": False, "code": "BadRequest", "message": "conflict must be hub-wins or skip."}
    hub_tables = [t for t in _tables(store, hub_id) if _SAFE.match(t)]
    want = tables or hub_tables
    report, ok = [], True
    for t in want:
        if t not in hub_tables or not _SAFE.match(t):
            report.append({"table": t, "error": "table does not exist in the hub database"})
            ok = False
            continue
        entry = {"table": t, "created": False, "inserted": 0, "updated": 0, "skipped": 0, "deleted": 0}
        if t not in _tables(store, member_id):
            ddl = _ddl(store, hub_id, t)
            if not ddl:
                report.append({"table": t, "error": "cannot read the hub table definition"})
                ok = False
                continue
            store.execute_sql(member_id, ddl)
            entry["created"] = True
        hub = store.execute_sql(hub_id, f'SELECT * FROM "{t}"')
        cols = hub["columns"]
        pk = _pk_cols(store, hub_id, t) or ([cols[0]] if cols else [])
        pkidx = [cols.index(c) for c in pk if c in cols]
        mem = store.execute_sql(member_id, f'SELECT * FROM "{t}"')
        mkeys = {tuple(r[cols.index(c)] for c in pk): list(r) for r in mem["rows"]} if all(c in mem["columns"] for c in pk) else {}
        mcols = mem["columns"]
        if mcols and mcols != cols:
            report.append({"table": t, "error": f"member table has different columns ({', '.join(mcols)}); drop or align it first"})
            ok = False
            continue
        seen = set()
        ph = ",".join("?" for _ in cols)
        qcols = ",".join(f'"{c}"' for c in cols)
        for row in hub["rows"]:
            key = tuple(row[i] for i in pkidx)
            seen.add(key)
            if key in mkeys:
                if list(row) == mkeys[key]:
                    continue
                if conflict == "skip":
                    entry["skipped"] += 1
                    continue
                sets = ",".join(f'"{c}"=?' for c in cols if c not in pk)
                where = " AND ".join(f'"{c}"=?' for c in pk)
                if sets:
                    store.execute_sql(member_id, f'UPDATE "{t}" SET {sets} WHERE {where}', [row[cols.index(c)] for c in cols if c not in pk] + list(key))
                entry["updated"] += 1
            else:
                store.execute_sql(member_id, f'INSERT INTO "{t}" ({qcols}) VALUES ({ph})', list(row))
                entry["inserted"] += 1
        if delete_missing:
            for key in set(mkeys) - seen:
                where = " AND ".join(f'"{c}"=?' for c in pk)
                store.execute_sql(member_id, f'DELETE FROM "{t}" WHERE {where}', list(key))
                entry["deleted"] += 1
        report.append(entry)
    job = {"ts": time.time(), "hub": hub_id, "member": member_id, "conflict": conflict, "deleteMissing": bool(delete_missing), "tables": report,
           "status": "Succeeded" if ok else "CompletedWithErrors"}
    h = _ring(store, "_azure_sql_syncs").setdefault(hub_id, [])
    h.append(job)
    del h[:-50]
    return {"ok": True, **job}


def sync_history(store, hub_id):
    return _ring(store, "_azure_sql_syncs").get(hub_id, [])
