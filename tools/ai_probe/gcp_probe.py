#!/usr/bin/env python3
"""Phase 0 (AI enterprise plan): GCP REST probe. For every method in gcp_inventory.csv, send the request (path template filled with probe
values, minimal JSON body) to the offline wire path (core.wire_ingress + the appliance router over real HTTP) and classify the answer:

  served_ok      2xx
  served_error   a JSON error answer (GCP-style {"error": {...}}): the route exists and answered in the right wire format
  unimplemented  no route: the request fell through to the S3 handler (XML NoSuchBucket / MethodNotAllowed), a non-JSON body, 404/501 without a
                 JSON error, a 5xx without JSON, or a connection failure

Caveats (the same as the AWS probe, plus two): "routed" is wire format only, not semantics; a generic catch-all JSON answer overstates
coverage; and the router resolves GCP APIs by PATH, so two Google APIs that share a path shape (e.g. /v1/projects/{p}/locations/{l}/...)
can be answered by the wrong engine. Read per-service numbers as an upper bound.

usage: PYTHONPATH=<repo root> python3 gcp_probe.py [--csv gcp_inventory.csv] [--out gcp_probe.csv] [--only svc[,svc]] [--url http://host:port]
"""
import argparse, collections, csv, json, re, socket, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def start_server():
    import uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app = FastAPI()
    router = wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"


PROJECT = ["nano-project"]          # replaced with the simulator's active project when the server is started in-process


def fill(path):
    """Fill discovery path templates. Discovery flat paths use {projectsId}/{locationsId}; others use {project}/{location}/{name}."""
    def sub(m):
        k = m.group(1).rstrip("+")
        if k in ("projectsId", "project", "projectId", "projects"):
            return PROJECT[0]
        if k in ("locationsId", "location", "locations", "regionsId", "region"):
            return "us-central1"
        return "probe-x"
    return re.sub(r"\{([^}]+)\}", sub, path)


def classify(status, body):
    txt = body.lstrip()[:1]
    if isinstance(status, int) and 200 <= status < 300:
        return "served_ok"
    if txt == "{" and isinstance(status, int) and status not in (501,):
        try:
            j = json.loads(body)
        except Exception:
            return "unimplemented"
        if isinstance(j, dict) and "error" in j:
            return "served_error"
        return "served_ok" if status < 400 else "unimplemented"
    return "unimplemented"


def one(url, row):
    verb = row["http"]
    path = fill(row["path"])
    if not path.startswith("/"):
        path = "/" + path                       # inventory paths are flat paths that already start with the api version (v1/...)
    data = b"{}" if verb in ("POST", "PUT", "PATCH") else None
    req = urllib.request.Request(url + path, method=verb, data=data, headers={"content-type": "application/json", "authorization": "Bearer probe"})
    try:
        r = urllib.request.urlopen(req, timeout=20); st, body = r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        st, body = e.code, e.read(400).decode("utf-8", "replace")
    except Exception as e:
        st, body = "EXC", str(e)[:120]
    return {"service": row["service"], "method_id": row["method_id"], "http": verb, "path": path, "status": classify(st, body), "http_status": st, "detail": body[:100].replace("\n", " ")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="tools/ai_probe/gcp_inventory.csv")
    ap.add_argument("--out", default="tools/ai_probe/gcp_probe.csv")
    ap.add_argument("--only", default="")
    ap.add_argument("--url", default="")
    a = ap.parse_args()
    only = {s for s in a.only.split(",") if s}
    rows = [r for r in csv.DictReader(open(a.csv)) if not only or r["service"] in only]
    url = a.url or start_server()
    if not a.url:
        try:
            from core import gcp_project
            PROJECT[0] = gcp_project.project_id()
        except Exception as e:
            print("could not read the active project, using", PROJECT[0], e, file=sys.stderr)
    print("probing as project", PROJECT[0])
    with ThreadPoolExecutor(8) as ex:
        out = list(ex.map(lambda r: one(url, r), rows))
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    by = collections.defaultdict(collections.Counter)
    for o in out:
        by[o["service"]][o["status"]] += 1
    tot = collections.Counter()
    for s, c in sorted(by.items()):
        t = sum(c.values()); ok = c["served_ok"] + c["served_error"]; tot.update(c)
        print(f"{s:18} {t:5} routed {ok:5} ({100 * ok / t:5.1f}%)  ok={c['served_ok']} err={c['served_error']} unimpl={c['unimplemented']}")
    T = sum(tot.values()); R = tot["served_ok"] + tot["served_error"]
    print(f"TOTAL {T} routed {R} ({100 * R / T:.1f}%) {dict(tot)}")


if __name__ == "__main__":
    main()
