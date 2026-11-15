#!/usr/bin/env python3
"""Phase 0 (AI enterprise plan), GCP side: mechanical operation inventory from Google's own discovery documents.

For each in-scope Google API this walks the discovery document (resources -> methods) and writes one CSV row per REST method:
service, version, method id, HTTP verb, path, whether it is a long-running/streaming style call. It is the GCP analogue of
aws_inventory.py and replaces "read from code" claims with the official API surface. Scope is the cloud mapping in
docs/architecture/v4.0/AI-ENTERPRISE-REFERENCE-PLAN.md section 2.1.

usage: python3 gcp_inventory.py [--out gcp_inventory.csv] [--only svc[,svc]]
needs network (public discovery documents, no credentials).
"""
import argparse, csv, json, sys, urllib.request

# service -> (discovery version, plan component(s))
SERVICES = {
    "aiplatform": ("v1", "C3 C6 C8 C9 C10 C11"),        # Vertex AI: models, Agent Engine, Vector Search, evaluation, Memory Bank
    "discoveryengine": ("v1", "C6 C12"),                  # Vertex AI Search / RAG
    "workflows": ("v1", "C5"),
    "eventarc": ("v1", "C12"),
    "documentai": ("v1", "C12"),
    "modelarmor": ("v1", "C2"),
    "identitytoolkit": ("v2", "C1"),                      # Identity Platform
    "apigateway": ("v1", "C1 C4"),
    "cloudfunctions": ("v2", "C7"),
    "run": ("v2", "C3 C7"),
    "pubsub": ("v1", "C7 C12"),
    "cloudkms": ("v1", "C13"),
    "logging": ("v2", "C8 C13"),
    "cloudtrace": ("v2", "C8"),
    "monitoring": ("v3", "C8"),
    "iam": ("v1", "C13"),
}


def fetch(svc, ver):
    url = f"https://{svc}.googleapis.com/$discovery/rest?version={ver}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def walk(res, prefix=""):
    for name, r in (res or {}).items():
        for mname, m in (r.get("methods") or {}).items():
            yield m
        yield from walk(r.get("resources"), prefix + name + ".")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gcp_inventory.csv")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = {s for s in a.only.split(",") if s}
    rows, fails = [], []
    for svc, (ver, comps) in SERVICES.items():
        if only and svc not in only:
            continue
        try:
            d = fetch(svc, ver)
        except Exception as e:
            fails.append(f"{svc}: {e}")
            continue
        n = 0
        for m in walk(d.get("resources")):
            rows.append({"service": svc, "version": ver, "components": comps, "method_id": m.get("id", ""), "http": m.get("httpMethod", ""),
                         "path": m.get("flatPath") or m.get("path", ""), "streaming": "streamGenerateContent" in m.get("id", "") or "Stream" in m.get("id", "")})
            n += 1
        print(f"{svc} {ver}: {n} methods")
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["service", "version", "components", "method_id", "http", "path", "streaming"])
        w.writeheader()
        w.writerows(rows)
    print(f"total {len(rows)} methods -> {a.out}")
    for x in fails:
        print("FAILED", x, file=sys.stderr)


if __name__ == "__main__":
    main()
