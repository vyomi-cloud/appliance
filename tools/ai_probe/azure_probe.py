#!/usr/bin/env python3
"""Phase 0 (AI enterprise plan): Azure REST probe. For every operation in azure_inventory.csv, send the request (path template filled with
probe values, ?api-version= from the spec, minimal JSON body) to the offline wire path (core.wire_ingress + the appliance router over real
HTTP) as the simulator's single subscription, and classify the answer:

  served_ok      2xx
  served_error   a JSON error answer other than an "unsupported" one (e.g. ResourceNotFound, InvalidParameter): the route exists
  unimplemented  ResourceTypeNotSupported / NoRegisteredProviderFound ("is not simulated"), no route (S3 fall-through XML), a non-JSON body,
                 404/501 without a JSON error, 5xx, or a connection failure

Same caveats as the GCP and AWS probes: wire format only, not semantics; catch-alls overstate coverage. Data-plane specs (openai, content
safety, agents) use their own host/paths: they are probed on the same ingress by path, so they read as an upper bound.

usage: PYTHONPATH=<repo root> python3 azure_probe.py [--csv azure_inventory.csv] [--out azure_probe.csv] [--only spec[,spec]] [--url http://host:port]
"""
import argparse, collections, csv, json, re, sys, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gcp_probe import start_server  # noqa: E402  (one in-process server implementation for both probes)

SUB = "00000000-0000-0000-0000-cloudlearn01"      # core/azure_arm_core.DEFAULT_SUBSCRIPTION: the one simulated subscription
UNSUPPORTED = ("ResourceTypeNotSupported", "NoRegisteredProviderFound", "InvalidResourceType", "UnsupportedApi", "not simulated")


def fill(path):
    def sub(m):
        k = m.group(1)
        if k == "subscriptionId":
            return SUB
        if k in ("resourceGroupName", "resourceGroup"):
            return "probe-rg"
        return "probe-x"
    return re.sub(r"\{([^}]+)\}", sub, path)


def classify(status, body):
    if isinstance(status, int) and 200 <= status < 300:
        return "served_ok"
    if body.lstrip()[:1] == "{" and isinstance(status, int) and status != 501 and status < 500:
        if any(u in body for u in UNSUPPORTED):
            return "unimplemented"
        try:
            return "served_error" if "error" in json.loads(body) else "served_ok"
        except Exception:
            return "unimplemented"
    return "unimplemented"


def one(url, row):
    verb = row["http"]
    path = fill(row["path"])
    q = "" if "api-version" in path else ("&" if "?" in path else "?") + "api-version=" + row["api_version"]
    data = b"{}" if verb in ("POST", "PUT", "PATCH") else None
    req = urllib.request.Request(url + path + q, method=verb, data=data, headers={"content-type": "application/json", "authorization": "Bearer probe"})
    try:
        r = urllib.request.urlopen(req, timeout=20); st, body = r.status, r.read(500).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        st, body = e.code, e.read(500).decode("utf-8", "replace")
    except Exception as e:
        st, body = "EXC", str(e)[:120]
    return {"spec": row["spec"], "operation_id": row["operation_id"], "http": verb, "path": path, "status": classify(st, body), "http_status": st, "detail": body[:100].replace("\n", " ")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="tools/ai_probe/azure_inventory.csv")
    ap.add_argument("--out", default="tools/ai_probe/azure_probe.csv")
    ap.add_argument("--only", default="")
    ap.add_argument("--url", default="")
    a = ap.parse_args()
    only = {s for s in a.only.split(",") if s}
    rows = [r for r in csv.DictReader(open(a.csv)) if not only or r["spec"] in only]
    url = a.url or start_server()
    with ThreadPoolExecutor(8) as ex:
        out = list(ex.map(lambda r: one(url, r), rows))
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    by = collections.defaultdict(collections.Counter)
    for o in out:
        by[o["spec"]][o["status"]] += 1
    tot = collections.Counter()
    for s, c in sorted(by.items()):
        t = sum(c.values()); ok = c["served_ok"] + c["served_error"]; tot.update(c)
        print(f"{s:26} {t:5} routed {ok:5} ({100 * ok / t:5.1f}%)  ok={c['served_ok']} err={c['served_error']} unimpl={c['unimplemented']}")
    T = sum(tot.values()); R = tot["served_ok"] + tot["served_error"]
    print(f"TOTAL {T} routed {R} ({100 * R / T:.1f}%) {dict(tot)}")
    print("HTTP 5xx:", sum(1 for o in out if isinstance(o["http_status"], int) and o["http_status"] >= 500))


if __name__ == "__main__":
    main()
