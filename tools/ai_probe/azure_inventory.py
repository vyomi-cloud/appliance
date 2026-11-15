#!/usr/bin/env python3
"""Phase 0 (AI enterprise plan), Azure side: mechanical operation inventory from the official OpenAPI specs
(github.com/Azure/azure-rest-api-specs). For each in-scope spec folder it takes the newest stable api-version (preview if no stable)
and writes one row per (path, verb) operation. The Azure analogue of aws_inventory.py / gcp_inventory.py.
Scope follows docs/architecture/v4.0/AI-ENTERPRISE-REFERENCE-PLAN.md section 2.1.

usage: python3 azure_inventory.py [--out azure_inventory.csv] [--only key[,key]]
needs: `gh` logged in (directory listings; avoids the anonymous API rate limit) and network for raw.githubusercontent.com.
"""
import argparse, csv, json, subprocess, sys, urllib.request

REPO = "Azure/azure-rest-api-specs"
# key -> (spec folder holding the <stable|preview>/<api-version> dirs, plan components)
SPECS = {
    "cognitiveservices-arm": ("specification/cognitiveservices/resource-manager/Microsoft.CognitiveServices", "C3 C10"),
    "search-arm": ("specification/search/resource-manager/Microsoft.Search", "C6"),
    "logic-arm": ("specification/logic/resource-manager/Microsoft.Logic", "C5"),
    "eventgrid-arm": ("specification/eventgrid/resource-manager/Microsoft.EventGrid", "C12"),
    "apim-arm": ("specification/apimanagement/resource-manager/Microsoft.ApiManagement", "C1 C4"),
    "ml-arm": ("specification/machinelearningservices/resource-manager/Microsoft.MachineLearningServices", "C3 C8 C10"),
    "keyvault-arm": ("specification/keyvault/resource-manager/Microsoft.KeyVault", "C13"),
    "operationalinsights-arm": ("specification/operationalinsights/resource-manager/Microsoft.OperationalInsights", "C8 C13"),
    "insights-arm": ("specification/applicationinsights/resource-manager/Microsoft.Insights", "C8"),
    "frontdoor-arm": ("specification/frontdoor/resource-manager/Microsoft.Network", "C1"),
    "openai-data": ("specification/cognitiveservices/data-plane/OpenAIInference", "C10 C11"),
    "contentsafety-data": ("specification/cognitiveservices/data-plane/ContentSafety", "C2 C11"),
    "foundry-agents-data": ("specification/ai/data-plane/AIAgents", "C3 C9"),
    "foundry-projects-data": ("specification/ai/data-plane/AIProjects", "C3 C8 C10"),
    "openai-v1-data": ("specification/ai/data-plane/OpenAI.v1", "C10 C11"),
    "model-inference-data": ("specification/ai/data-plane/ModelInference", "C10"),
}


def gh(path):
    r = subprocess.run(["gh", "api", f"repos/{REPO}/contents/{path}", "-q", ".[]|[.name,.type]|@tsv"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:120])
    return [l.split("\t") for l in r.stdout.splitlines() if l]


def newest(base, depth=0):
    """Yield (kind, api-version dir path, version) for every spec group under `base`, preferring the newest stable version.
    ARM specs sit one folder deeper (Microsoft.X/<Group>/<stable|preview>/<api-version>); data-plane layouts vary."""
    top = {n for n, t in gh(base) if t == "dir"}
    for kind in ("stable", "preview"):
        if kind in top:
            vers = sorted((n for n, t in gh(f"{base}/{kind}") if t == "dir"), reverse=True)
            if vers:
                yield kind, f"{base}/{kind}/{vers[0]}", vers[0]
                return
    vers = sorted((n for n in top if n[:2] == "20"), reverse=True)
    if vers:
        yield "stable", f"{base}/{vers[0]}", vers[0]
        return
    if depth < 2:
        for n in sorted(top):
            yield from newest(f"{base}/{n}", depth + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="azure_inventory.csv")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = {s for s in a.only.split(",") if s}
    rows, fails = [], []
    for key, (base, comps) in SPECS.items():
        if only and key not in only:
            continue
        try:
            n = 0
            for kind, d, ver in newest(base):
              for name, t in gh(d):
                    if t != "file" or not name.endswith(".json"):
                        continue
                    with urllib.request.urlopen(f"https://raw.githubusercontent.com/{REPO}/main/{d}/{name}", timeout=60) as r:
                        spec = json.load(r)
                    for path, item in (spec.get("paths") or {}).items():
                        for verb, op in item.items():
                            if verb in ("get", "put", "post", "delete", "patch", "head") and isinstance(op, dict):
                                rows.append({"spec": key, "api_version": ver, "kind": kind, "components": comps, "operation_id": op.get("operationId", ""),
                                             "http": verb.upper(), "path": path, "file": name})
                                n += 1
            print(f"{key}: {n} operations")
        except Exception as e:
            fails.append(f"{key}: {e}")
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["spec", "api_version", "kind", "components", "operation_id", "http", "path", "file"])
        w.writeheader()
        w.writerows(rows)
    print(f"total {len(rows)} operations -> {a.out}")
    for x in fails:
        print("FAILED", x, file=sys.stderr)


if __name__ == "__main__":
    main()
