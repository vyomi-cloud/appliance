#!/usr/bin/env python3
"""Detect new features in the Nano and offline simulators, and what lacks tests.

Each run builds a feature INVENTORY for both targets and diffs it against the
previous run's (published on the conformance-report branch):

  console features — from each cloud's console catalog (offline: the live
    /api/{aws,gcp,azure}/catalog; Nano: wasm/fixtures/*-catalog.json):
    services, tabs (subBlades), create fields, grid columns, console actions
  SDK operations   — the operation names each engine implements
    (offline: core/*_core.py; Nano: wasm/core/*_core.py), read from their
    dispatch tables / handler names
  API routes       — every FastAPI /api route in server.py + routes/

Writes out/inventory.json (next run's baseline) and out/new_features.json:
  new / removed  — features added or dropped since the last run
  parity         — features one target has and the other doesn't
  untested_ops   — SDK operations no Java/Go/Python/CLI test calls
  uncovered      — /api routes no test mentions
Console services/tabs/actions are exercised every hour by the UI crawler and
the catalog-driven console-actions suite, so for those "new" means "watch the
next crawl"; SDK operations need a dedicated test, which the agent writes.

    PREV_INVENTORY=prev/inventory.json VYOMI_BASE_URL=http://localhost:9000 \
      python3 tests/conformance/hourly/detect_new_features.py
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CLOUDS = ("aws", "gcp", "azure")
ROUTE_RE = re.compile(r"""@(?:app|router)\.(get|post|put|patch|delete|api_route)\(\s*["']([^"']+)["']""")
OP_RE = re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+$")            # PascalCase: PutItem, CreateDBInstance
VERB_RE = re.compile(r"^_?(create|list|get|delete|update|put|patch|describe|publish|pull|acknowledge|ack|modify|set|"
                     r"insert|query|scan|upload|download|copy|invoke|add|remove|attach|detach|start|stop|restart|"
                     r"enable|disable|encrypt|decrypt|sign|verify|rotate|restore|purge|send|receive|batch|run|"
                     r"generate|import|export|tag|untag|subscribe|unsubscribe|commit|rollback|begin|execute|"
                     r"lease|break|renew|regenerate|deallocate|poweroff|reboot|resize|seek|snapshot)_[a-z0-9_]+$")
TEST_DIRS = ("tests", "wasm/ui-tests", "samples")
SDK_TEST_EXT = (".java", ".go", ".py", ".sh", ".mjs", ".js")


# ── Inventory ─────────────────────────────────────────────────────────────
def _fetch_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _catalog(target: str, cloud: str):
    if target == "nano":
        path = os.path.join(ROOT, "wasm", "fixtures", f"{cloud}-catalog.json")
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return None
    base = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
    return _fetch_json(f"{base}/api/{cloud}/catalog")


def _tabs(sub_blades) -> list[str]:
    out = []
    for b in sub_blades or []:
        if isinstance(b, dict) and "items" in b:
            out += _tabs(b["items"])
        elif isinstance(b, dict):
            out.append(str(b.get("label") or b.get("key") or ""))
    return [t for t in out if t]


def console_features(target: str, cloud: str) -> list[dict]:
    cat = _catalog(target, cloud)
    if not isinstance(cat, dict):
        return []
    feats = []
    services = list(cat.get("services") or [])
    for key, extra in (cat.get("extras") or {}).items():
        if isinstance(extra, dict):
            services.append({"key": key, "label": extra.get("label", key), "columns": extra.get("columns", [])})
    for s in services:
        if not isinstance(s, dict):
            continue
        svc = str(s.get("label") or s.get("key"))
        base = {"target": target, "cloud": cloud, "service": svc}
        feats.append({**base, "kind": "service", "name": svc})
        feats += [{**base, "kind": "tab", "name": t} for t in _tabs(s.get("subBlades"))]
        feats += [{**base, "kind": "create_field", "name": str(f.get("label") or f.get("name"))}
                  for f in s.get("createFields") or [] if isinstance(f, dict)]
        feats += [{**base, "kind": "column", "name": str(c[1] if isinstance(c, list) and len(c) > 1 else c)}
                  for c in s.get("columns") or []]
        for name, ap in (s.get("api_paths") or {}).items():
            if isinstance(ap, dict):
                feats.append({**base, "kind": "action", "name": name,
                              "method": ap.get("method", ""), "path": ap.get("path", "")})
    return feats


def _ops_in(path: str) -> set[str]:
    """Operation names an engine implements: PascalCase keys of its dispatch
    tables (AWS JSON/query cores) plus verb-named handlers (REST cores)."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return set()
    ops = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict) and len(n.keys) >= 3:
            keys = [k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if len(keys) == len(n.keys) and all(isinstance(v, (ast.Name, ast.Attribute, ast.Lambda)) for v in n.values) \
                    and all(OP_RE.match(k) for k in keys):
                ops |= set(keys)
        elif isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id in ("op", "action", "target", "operation"):
            for c in n.comparators:
                vals = [c] if isinstance(c, ast.Constant) else list(getattr(c, "elts", []))
                ops |= {v.value for v in vals if isinstance(v, ast.Constant) and isinstance(v.value, str) and OP_RE.match(v.value)}
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and VERB_RE.match(n.name):
            ops.add("".join(p.capitalize() for p in n.name.strip("_").split("_")))
    return ops


def _cloud_of(core_file: str) -> str:
    b = os.path.basename(core_file)
    return "azure" if b.startswith("azure_") else "gcp" if b.startswith("gcp_") else "aws"


def operations(target: str) -> list[dict]:
    pattern = "wasm/core/*_core.py" if target == "nano" else "core/*_core.py"
    feats = []
    for f in sorted(glob.glob(os.path.join(ROOT, pattern))):
        engine = os.path.basename(f)[:-3]
        for op in sorted(_ops_in(f)):
            feats.append({"target": target, "cloud": _cloud_of(f), "service": engine, "kind": "operation", "name": op})
    return feats


def api_routes() -> list[dict]:
    feats = []
    files = ["server.py"] + [os.path.join("routes", f) for f in sorted(os.listdir(os.path.join(ROOT, "routes"))) if f.endswith(".py")]
    for path in files:
        try:
            text = open(os.path.join(ROOT, path), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in ROUTE_RE.finditer(text):
            if m.group(2).startswith("/api/"):
                p = m.group(2)
                cloud = "azure" if "azure" in p else "gcp" if "/gcp" in p or "storage/v1" in p else \
                    "aws" if re.search(r"/(aws|s3|ec2|iam|dynamodb|sqs|sns|rds|lambda|kms)\b", p) else "all"
                feats.append({"target": "offline", "cloud": cloud, "service": path, "kind": "route",
                              "name": f"{m.group(1).upper()} {p}", "method": m.group(1).upper(), "path": p})
    return feats


def key(f: dict) -> str:
    return "|".join(str(f.get(k, "")) for k in ("target", "cloud", "service", "kind", "name"))


# ── Coverage ──────────────────────────────────────────────────────────────
def test_corpus(exts=None) -> str:
    chunks = []
    for d in TEST_DIRS:
        for base, _, files in os.walk(os.path.join(ROOT, d)):
            if any(x in base for x in ("/out", "node_modules", "/target", "/hourly")):
                continue
            for f in files:
                if f.endswith(exts or (".py", ".mjs", ".js", ".go", ".java", ".sh", ".json")):
                    try:
                        chunks.append(open(os.path.join(base, f), encoding="utf-8", errors="replace").read())
                    except OSError:
                        pass
    return "\n".join(chunks)


def op_spellings(op: str) -> list[str]:
    """How an SDK/CLI test would call the operation: PutItem / putItem /
    put_item / put-item."""
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z][a-z0-9]*", op)
    snake = "_".join(w.lower() for w in words)
    return [op, op[0].lower() + op[1:], snake, snake.replace("_", "-")]


def op_tested(op: str, corpus: str) -> bool:
    return any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(s) + r"(?![A-Za-z0-9_])", corpus) for s in op_spellings(op))


def route_tested(path: str, corpus: str) -> bool:
    stem = path.split("{")[0].rstrip("/")
    return bool(stem) and re.search(re.escape(stem) + r"(?![A-Za-z0-9_-])", corpus) is not None


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> None:
    inventory = []
    for target in ("offline", "nano"):
        for cloud in CLOUDS:
            inventory += console_features(target, cloud)
        inventory += operations(target)
    inventory += api_routes()
    for f in inventory:
        f["id"] = key(f)

    prev_path = os.environ.get("PREV_INVENTORY", "")
    prev = []
    if prev_path and os.path.exists(prev_path):
        try:
            prev = json.load(open(prev_path)).get("features", [])
        except Exception:
            prev = []
    cur_ids, prev_ids = {f["id"] for f in inventory}, {f["id"] for f in prev}
    # Only diff targets present in both runs (offline catalog may be unreachable).
    seen_targets = {(f["target"], f["kind"]) for f in inventory}
    new = [f for f in inventory if prev and f["id"] not in prev_ids]
    removed = [f for f in prev if f["id"] not in cur_ids and (f["target"], f["kind"]) in seen_targets]

    sdk_corpus = test_corpus(SDK_TEST_EXT)
    all_corpus = test_corpus()
    for f in inventory:
        if f["kind"] == "operation":
            f["tested"] = op_tested(f["name"], sdk_corpus)
        elif f["kind"] == "route":
            f["tested"] = route_tested(f["path"], all_corpus)
        else:
            f["tested"] = None   # exercised live by the UI crawler / console-actions
    tested = {f["id"]: f.get("tested") for f in inventory}
    for f in new:
        f["tested"] = tested.get(f["id"])

    # Parity: console services / tabs / operations one target has and the other lacks.
    parity = []
    by = {}
    for f in inventory:
        if f["kind"] in ("service", "tab", "operation"):
            svc = f["service"]
            if f["kind"] == "operation":
                svc = svc  # same engine file name on both targets
            by.setdefault((f["cloud"], f["kind"], svc, f["name"]), set()).add(f["target"])
    if any(f["target"] == "offline" and f["kind"] == "service" for f in inventory):
        for (cloud, kind, svc, name), targets in sorted(by.items()):
            if len(targets) == 1:
                only = next(iter(targets))
                parity.append({"cloud": cloud, "kind": kind, "service": svc, "name": name,
                               "only_in": only, "missing_in": "nano" if only == "offline" else "offline"})

    ops = [f for f in inventory if f["kind"] == "operation"]
    routes = [f for f in inventory if f["kind"] == "route"]
    untested_ops = [f for f in ops if not f["tested"]]
    uncovered = [{"method": f["method"], "path": f["path"], "file": f["service"]} for f in routes if not f["tested"]]
    counts = {}
    for f in inventory:
        c = counts.setdefault(f["target"], {})
        c[f["kind"]] = c.get(f["kind"], 0) + 1

    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    json.dump({"features": inventory}, open(os.path.join(HERE, "out", "inventory.json"), "w"))
    out = {
        "baseline": bool(prev), "counts": counts,
        "routes_total": len(routes), "routes_uncovered": len(uncovered),
        "ops_total": len(ops), "ops_untested": len(untested_ops),
        "new": new, "removed": removed, "parity": parity,
        "untested_ops": untested_ops, "uncovered": uncovered,
    }
    json.dump(out, open(os.path.join(HERE, "out", "new_features.json"), "w"), indent=1)
    kinds = {}
    for f in new:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    print(f"inventory: {len(inventory)} features "
          + ", ".join(f"{t}: {sum(c.values())}" for t, c in counts.items()))
    print(f"since last run: {len(new)} new ({', '.join(f'{v} {k}' for k, v in kinds.items()) or 'none'}), "
          f"{len(removed)} removed" + ("" if prev else " (no baseline yet: this run becomes it)"))
    print(f"SDK operations: {len(ops) - len(untested_ops)}/{len(ops)} called by a test; "
          f"API routes: {len(routes) - len(uncovered)}/{len(routes)} referenced; "
          f"Nano/offline parity gaps: {len(parity)}")


if __name__ == "__main__":
    main()
