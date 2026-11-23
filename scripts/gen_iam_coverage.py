#!/usr/bin/env python3
"""IAM coverage report: per inventory service, which IAM catalog slice covers it and how much of it the request->permission map reproduces.

    python3 scripts/gen_iam_coverage.py                 # regenerate wasm/iam-coverage.json + docs/architecture/v4.0/IAM-COVERAGE.md
    python3 scripts/gen_iam_coverage.py --check         # exit 1 if either is stale (CI / tests/conformance/test_iam_onboarding_gate.py)
    python3 scripts/gen_iam_coverage.py --bump-floors   # raise each service floor in core/iam_catalog/service_map.json to the current floor(%)

Inputs: wasm/service-inventory.json (the services), core/iam_catalog/service_map.json (THE mapping service -> catalog slice(s) + floor),
core/iam_catalog/<cloud>/*.json (catalog), core/iam_engine/map_{aws,gcp,azure}.py (request maps).
Coverage definition (all measured from the committed catalog, no network, deterministic):
  aws   operations of the slice's prefixes whose synthesized wire request maps back to that operation (map_aws.coverage()).
  gcp   catalog permissions of the slice emitted by at least one REST method in core/iam_catalog/gcp/_methods.json.
  azure control-plane catalog actions (read/write/delete/<op>/action) whose synthesized ARM request maps back to the same action
        (the round trip of tests/conformance/test_iam_map_azure.py), restricted to the service's filters when it shares a provider.
enforceable = catalog slice exists AND coverage >= ENFORCE_PCT. Rule 14 in docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md."""
import glob, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
INV = os.path.join(ROOT, "wasm", "service-inventory.json")
MAP = os.path.join(ROOT, "core", "iam_catalog", "service_map.json")
OUT = os.path.join(ROOT, "wasm", "iam-coverage.json")
MD = os.path.join(ROOT, "docs", "architecture", "v4.0", "IAM-COVERAGE.md")
ENFORCE_PCT = 90.0
CLOUDS = ("aws", "gcp", "azure")


def _j(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return json.load(f)


def slice_file(cloud, name):
    return os.path.join(ROOT, "core", "iam_catalog", cloud, name + ".json")


def aws_slice(prefixes, cov):
    perms = ops = mapped = 0
    for p in prefixes:
        perms += len(_j("core", "iam_catalog", "aws", p + ".json")["actions"])
        c = cov.get(p)
        if c:
            ops += c["ops"]; mapped += c["mapped"]
    return perms, (100.0 * mapped / ops if ops else 0.0)


def gcp_slice(slugs, emitted):
    perms = got = 0
    for s in slugs:
        ps = _j("core", "iam_catalog", "gcp", s + ".json")["permissions"]
        perms += len(ps); got += sum(1 for p in ps if p in emitted)
    return perms, (100.0 * got / perms if perms else 0.0)


def azure_roundtrip(action):
    """Synthesise the ARM request for a control-plane action; True if map_azure reproduces it, None if not a testable verb."""
    from core.iam_engine import map_azure
    parts = action.split("/")
    if len(parts) < 3:
        return None
    ns, rest = parts[0], parts[1:]
    verb = rest[-1].lower()
    if verb == "action":
        types, op, method = rest[:-2], rest[-2], "POST"
        path = "/".join("%s/n%d" % (t, i) for i, t in enumerate(types))
        path = (path + "/" if path else "") + op
    elif verb in ("read", "write", "delete"):
        types = rest[:-1]
        method = {"read": "GET", "write": "PUT", "delete": "DELETE"}[verb]
        path = "/".join("%s/n%d" % (t, i) for i, t in enumerate(types))
    else:
        return None
    got = map_azure.required(method, "/subscriptions/s/resourceGroups/rg/providers/%s/%s" % (ns, path))
    return bool(got and got[0]["action"].lower() == action.lower())


def azure_slice(providers, filters):
    perms = tot = ok = 0
    fl = [f.lower() for f in filters]
    for pv in providers:
        d = _j("core", "iam_catalog", "azure", pv + ".json")
        for a in list(d["actions"]) + list(d["dataActions"]):
            if fl and not any(a.lower().startswith(f) for f in fl):
                continue
            perms += 1
        for a in d["actions"]:
            if fl and not any(a.lower().startswith(f) for f in fl):
                continue
            r = azure_roundtrip(a)
            if r is not None:
                tot += 1; ok += r
    return perms, (100.0 * ok / tot if tot else 0.0)


def build():
    inv = _j("wasm", "service-inventory.json")["services"]
    smap = _j("core", "iam_catalog", "service_map.json")["services"]
    from core.iam_engine import map_aws
    prefixes = sorted({p for e in smap["aws"].values() if e["catalog"] != "none" for p in e["catalog"]})
    acov = map_aws.coverage(prefixes)
    table = _j("core", "iam_catalog", "gcp", "_methods.json")
    emitted = {p for m in table["methods"] for p in m["perm"]}
    rows, totals = [], {c: {"services": 0, "enforceable": 0, "catalog_none": 0, "permissions": 0} for c in CLOUDS}
    for s in inv:
        c, i = s["cloud"], s["id"]
        e = smap.get(c, {}).get(i)
        if e is None:
            continue
        row = {"cloud": c, "id": i, "title": s["title"]}
        if e["catalog"] == "none":
            row.update(catalog="none", reason=e["reason"], permissions=0, mapped_pct=None, floor=e.get("floor", 0), enforceable=False)
        else:
            if c == "aws":
                n, pct = aws_slice(e["catalog"], acov)
            elif c == "gcp":
                n, pct = gcp_slice(e["catalog"], emitted)
            else:
                n, pct = azure_slice(e["catalog"], e.get("filters", []))
            row.update(catalog=list(e["catalog"]), permissions=n, mapped_pct=round(pct, 1), floor=e.get("floor", 0),
                       enforceable=bool(pct >= ENFORCE_PCT))
            if e.get("filters"):
                row["filters"] = list(e["filters"])
        rows.append(row)
        t = totals[c]
        t["services"] += 1; t["enforceable"] += row["enforceable"]; t["catalog_none"] += row["catalog"] == "none"; t["permissions"] += row["permissions"]
    return {"$doc": "Generated by scripts/gen_iam_coverage.py - do not edit. Mapping: core/iam_catalog/service_map.json. enforceable = catalog slice AND mapped_pct >= %d." % ENFORCE_PCT,
            "enforce_pct": ENFORCE_PCT, "totals": totals, "services": rows}


def render_md(doc):
    L = ["# IAM coverage per service", "",
         "Generated by `scripts/gen_iam_coverage.py` from `wasm/iam-coverage.json` - do not edit. Mapping: `core/iam_catalog/service_map.json`.",
         "Mapped % = share of the catalog slice the request->permission map reproduces (definition per cloud in the script header).",
         "Enforceable = catalog slice exists AND mapped >= %d%%. Floor = recorded minimum mapped %% (only goes up)." % doc["enforce_pct"], ""]
    for c in CLOUDS:
        t = doc["totals"][c]
        L += ["## %s: %d/%d services enforceable, %d without a catalog slice, %d catalog permissions" % (c.upper(), t["enforceable"], t["services"], t["catalog_none"], t["permissions"]), "",
              "| Service | Catalog slice | Permissions | Mapped % | Floor | Enforceable |", "|---|---|---:|---:|---:|---|"]
        for r in doc["services"]:
            if r["cloud"] != c:
                continue
            sl = "none: " + r["reason"] if r["catalog"] == "none" else ", ".join(r["catalog"])
            L.append("| %s (`%s`) | %s | %d | %s | %s | %s |" % (r["title"], r["id"], sl, r["permissions"],
                     "-" if r["mapped_pct"] is None else "%.1f" % r["mapped_pct"], r["floor"], "yes" if r["enforceable"] else "no"))
        L.append("")
    return "\n".join(L)


def dumps(doc):
    return json.dumps(doc, indent=1) + "\n"


def main(argv):
    doc = build()
    if "--bump-floors" in argv:
        m = _j("core", "iam_catalog", "service_map.json")
        for r in doc["services"]:
            e = m["services"][r["cloud"]][r["id"]]
            if r["mapped_pct"] is not None and math.floor(r["mapped_pct"]) > e.get("floor", 0):
                e["floor"] = math.floor(r["mapped_pct"])
        with open(MAP, "w") as f:
            json.dump(m, f, indent=1); f.write("\n")
        doc = build()
    js, md = dumps(doc), render_md(doc) + "\n"
    if "--check" in argv:
        bad = [p for p, t in ((OUT, js), (MD, md)) if not os.path.exists(p) or open(p).read() != t]
        if bad:
            print("STALE: %s\nRun: python3 scripts/gen_iam_coverage.py   (then commit wasm/iam-coverage.json and docs/architecture/v4.0/IAM-COVERAGE.md)" % ", ".join(os.path.relpath(p, ROOT) for p in bad))
            return 1
        print("iam coverage up to date")
        return 0
    with open(OUT, "w") as f:
        f.write(js)
    with open(MD, "w") as f:
        f.write(md)
    for c in CLOUDS:
        t = doc["totals"][c]
        print("%-6s services %2d  enforceable %2d  catalog none %d  permissions %d" % (c, t["services"], t["enforceable"], t["catalog_none"], t["permissions"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
