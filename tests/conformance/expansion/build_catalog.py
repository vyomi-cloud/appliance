#!/usr/bin/env python3
"""Full AWS / GCP / Azure service catalog vs what Vyomi ships, ranked.

Sources (all public, machine-readable):
  AWS    every botocore service model (the definition AWS SDKs + CLI use)
  GCP    every Google API in the Discovery directory (preferred versions)
  Azure  every area in Azure/azure-rest-api-specs/specification
Joined with services/registry.json (what Vyomi has released) and
priorities.json (P1/P2 build order; the rest is P3).

Writes services/catalog.json and docs/expansion/CLOUD-CATALOG.md.

    GITHUB_TOKEN=... python3 tests/conformance/expansion/build_catalog.py
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PRI = json.load(open(os.path.join(HERE, "priorities.json")))
REG = json.load(open(os.path.join(ROOT, "services", "registry.json")))
# Azure namespaces in the registry → spec directories
AZ_NS = {"Microsoft.Compute": "compute", "Microsoft.Storage": "storage", "Microsoft.Sql": "sql",
         "Microsoft.ServiceBus": "servicebus", "Microsoft.DocumentDB": "cosmos-db", "Microsoft.Web": "web",
         "Microsoft.ApiManagement": "apimanagement", "Microsoft.Network": "network",
         "Microsoft.EventGrid": "eventgrid", "Microsoft.KeyVault": "keyvault", "Microsoft.Authorization": "authorization"}


def get(url: str):
    h = {"User-Agent": "vyomi-catalog", "Accept": "application/json"}
    if "api.github.com" in url and os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        return json.loads(r.read())


def priority(cloud: str, sid: str) -> str:
    for p in ("P1", "P2"):
        if sid in PRI[p].get(cloud, []):
            return p
    return "P3"


def main() -> None:
    implemented = {"aws": set(), "gcp": set(), "azure": set()}
    for s in REG["services"]:
        if s.get("status") != "released":
            continue
        up = s.get("upstream") or s["key"]
        implemented[s["cloud"]].add(AZ_NS.get(up, up) if s["cloud"] == "azure" else up)
    implemented["aws"].add("rds-data")  # ships with RDS

    botocore = get("https://pypi.org/pypi/botocore/json")["info"]["version"]
    aws = []
    for d in get(f"https://api.github.com/repos/boto/botocore/contents/botocore/data?ref={botocore}"):
        if d["type"] != "dir":
            continue
        sid = d["name"]
        entry = {"cloud": "aws", "id": sid, "name": sid, "priority": priority("aws", sid),
                 "status": "released" if sid in implemented["aws"] else "not started"}
        if entry["priority"] != "P3" or entry["status"] == "released":
            try:
                vers = sorted(x["name"] for x in get(f"https://api.github.com/repos/boto/botocore/contents/botocore/data/{sid}?ref={botocore}") if x["type"] == "dir")
                m = get(f"https://raw.githubusercontent.com/boto/botocore/{botocore}/botocore/data/{sid}/{vers[-1]}/service-2.json")
                entry["name"] = m.get("metadata", {}).get("serviceFullName", sid)
                entry["operations"] = len(m.get("operations", {}))
            except Exception:
                pass
        aws.append(entry)

    gcp = []
    for it in get("https://www.googleapis.com/discovery/v1/apis")["items"]:
        if not it.get("preferred"):
            continue
        sid = f"{it['name']}/{it['version']}"
        # Match by API name: Vyomi may target a different version than the
        # directory's preferred one (e.g. cloudfunctions/v2 vs v1).
        released = it["name"] in {i.split("/")[0] for i in implemented["gcp"]}
        gcp.append({"cloud": "gcp", "id": sid, "name": it.get("title", sid), "priority": priority("gcp", sid),
                    "status": "released" if released else "not started"})

    azure = []
    for d in get("https://api.github.com/repos/Azure/azure-rest-api-specs/contents/specification"):
        if d["type"] != "dir":
            continue
        sid = d["name"]
        azure.append({"cloud": "azure", "id": sid, "name": sid, "priority": priority("azure", sid),
                      "status": "released" if sid in implemented["azure"] else "not started"})

    services = aws + gcp + azure
    summary = {}
    for cloud, rows in (("aws", aws), ("gcp", gcp), ("azure", azure)):
        summary[cloud] = {"total": len(rows), "released": sum(r["status"] == "released" for r in rows),
                          "P1": sum(r["priority"] == "P1" and r["status"] != "released" for r in rows),
                          "P2": sum(r["priority"] == "P2" and r["status"] != "released" for r in rows)}
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "botocore": botocore,
           "summary": summary, "services": services}
    json.dump(out, open(os.path.join(ROOT, "services", "catalog.json"), "w"), indent=1)

    L = ["# AWS / GCP / Azure service catalog", "",
         f"Generated {out['generated']} from botocore {botocore}, the Google API Discovery directory and "
         "Azure/azure-rest-api-specs. Build order: P1 → P2 → P3 (see `tests/conformance/expansion/priorities.json`). "
         "A service is **released** only after it passes the service gate (API, SDK, CLI, console UI offline + Nano, "
         "Java + Go + Playwright conformance) — see `tests/conformance/expansion/EXPANSION.md`.", "",
         "| Cloud | Services upstream | Released in Vyomi | P1 to build | P2 to build |", "|---|---|---|---|---|"]
    for c in ("aws", "gcp", "azure"):
        sm = summary[c]
        L.append(f"| {c.upper()} | {sm['total']} | {sm['released']} | {sm['P1']} | {sm['P2']} |")
    for p in ("P1", "P2"):
        L += ["", f"## {p}", "", "| Cloud | Service | Id | Operations | Status |", "|---|---|---|---|---|"]
        for r in services:
            if r["priority"] == p:
                L.append(f"| {r['cloud'].upper()} | {r['name']} | `{r['id']}` | {r.get('operations', '')} | {r['status']} |")
    L += ["", "## Released", "", "| Cloud | Service | Id |", "|---|---|---|"]
    L += [f"| {r['cloud'].upper()} | {r['name']} | `{r['id']}` |" for r in services if r["status"] == "released"]
    L += ["", "## P3 (everything else)", ""]
    for c in ("aws", "gcp", "azure"):
        ids = [r["id"] for r in services if r["cloud"] == c and r["priority"] == "P3" and r["status"] != "released"]
        L += [f"<details><summary>{c.upper()} — {len(ids)}</summary>", "", ", ".join(f"`{i}`" for i in ids), "", "</details>", ""]
    os.makedirs(os.path.join(ROOT, "docs", "expansion"), exist_ok=True)
    open(os.path.join(ROOT, "docs", "expansion", "CLOUD-CATALOG.md"), "w").write("\n".join(L) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
