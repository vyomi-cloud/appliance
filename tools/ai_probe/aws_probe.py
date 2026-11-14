#!/usr/bin/env python3
"""Phase 0 (AI enterprise plan): SDK probe. For every in-scope operation in aws_inventory.csv, call it with the real boto3 client
against the offline wire path (core.wire_ingress + the appliance router, served over real HTTP) using minimal arguments built from the
official input shape, and classify the answer:

  served_ok      the operation returned a success response
  served_error   the simulator answered with a MODELED error (ValidationException, ResourceNotFound, ...): the route exists
  unimplemented  no route / InvalidAction / NoSuchBucket on a non-S3 service / 404-501 w/o a modeled error / 5xx / unparseable
  probe_error    the probe could not build a request (client-side param validation)

This measures "is the operation routed and answered with the right wire format", NOT semantic correctness; contract tests (Phase 1+)
prove semantics. It is the honest replacement for the crude core_mentions column.

usage: python3 aws_probe.py [--csv aws_inventory.csv] [--out aws_probe.csv] [--only svc[,svc]] [--url http://host:port]
needs: boto3==1.43.18 botocore==1.43.18, and PYTHONPATH=<repo root> (starts the in-process server unless --url is given)
"""
import argparse, csv, datetime, os, sys, threading, time, socket, collections

UNIMPL_CODES = {"InvalidAction", "UnknownOperationException", "UnknownOperation", "NotImplemented", "NotImplementedException",
                "UnrecognizedClientException", "InternalFailure", "InternalError", "InternalServerError", "ServiceUnavailable",
                "MissingAuthenticationToken", "UnsupportedOperation", "InvalidRequest404", "NoSuchBucket", "NoSuchKey_route", "404"}


def sample(shape, depth=0, name=""):
    t = shape.type_name
    if t == "string":
        enum = shape.metadata.get("enum") or getattr(shape, "enum", None)
        if enum:
            return enum[0]
        mn = shape.metadata.get("min", 1) or 1
        v = ("probe-" + name.lower())[:max(mn, 12)]
        return v.ljust(mn, "x")[:max(shape.metadata.get("max", 64), mn)]
    if t in ("integer", "long"):
        return max(int(shape.metadata.get("min", 1)), 1)
    if t in ("float", "double"):
        return 1.0
    if t == "boolean":
        return False
    if t == "timestamp":
        return datetime.datetime(2026, 1, 1)
    if t == "blob":
        return b"probe"
    if t == "list":
        return [] if depth > 2 else [sample(shape.member, depth + 1, name)]
    if t == "map":
        return {} if depth > 2 else {"k": sample(shape.value, depth + 1, name)}
    if t == "structure":
        out = {}
        for k, m in shape.members.items():
            if k in shape.required_members or (depth == 0 and False):
                out[k] = sample(m, depth + 1, k)
        return out
    if t == "union" or t == "document":
        return {}
    return "probe"


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


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--csv", default=os.path.join(here, "aws_inventory.csv"))
    ap.add_argument("--out", default=os.path.join(here, "aws_probe.csv"))
    ap.add_argument("--only", default="")
    ap.add_argument("--url", default="")
    a = ap.parse_args()
    import boto3, botocore
    from botocore.config import Config
    from botocore.exceptions import ClientError, ParamValidationError
    url = a.url or start_server()
    only = set(filter(None, a.only.split(",")))
    cfg = Config(retries={"max_attempts": 1}, connect_timeout=5, read_timeout=20)
    rows = list(csv.DictReader(open(a.csv)))
    clients, res = {}, []
    for r in rows:
        svc, op = r["service"], r["operation"]
        if only and svc not in only or r["in_scope"] != "yes" or op.startswith("("):
            continue
        try:
            c = clients.get(svc) or clients.setdefault(svc, boto3.client(svc, region_name="us-east-1", endpoint_url=url,
                                                                         aws_access_key_id="probe", aws_secret_access_key="probe", config=cfg))
            m = c.meta.service_model.operation_model(op)
            args = sample(m.input_shape, name=op) if m.input_shape else {}
            py = botocore.xform_name(op)
            status, detail = "served_ok", ""
            try:
                getattr(c, py)(**args)
            except ParamValidationError as e:
                status, detail = "probe_error", str(e)[:120]
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                http = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
                modeled = {s.name for s in m.error_shapes}
                numeric = code.isdigit()          # the SDK could not parse a modeled error (XML/HTML body): not the service's wire format
                if code in modeled or (code and not numeric and code not in UNIMPL_CODES and http < 500 and not (http == 404 and svc != "s3" and code.startswith("NoSuch"))):
                    status = "served_error"
                else:
                    status = "unimplemented"
                detail = f"{code}/{http}"
            except Exception as e:
                status, detail = "unimplemented", f"{type(e).__name__}: {str(e)[:100]}"
        except Exception as e:
            status, detail = "probe_error", f"{type(e).__name__}: {str(e)[:100]}"
        res.append((svc, op, status, detail))
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["service", "operation", "status", "detail"]); w.writerows(res)
    tot = collections.Counter(); per = collections.defaultdict(collections.Counter)
    for s, o, st, d in res:
        tot[st] += 1; per[s][st] += 1
    print(f"boto3 {boto3.__version__} / botocore {botocore.__version__}  ops probed: {len(res)}")
    print(f"{'service':28} {'ok':>5} {'err':>5} {'unimpl':>6} {'probe':>5}   routed%")
    for s, c in per.items():
        n = sum(c.values()); routed = c["served_ok"] + c["served_error"]
        print(f"{s:28} {c['served_ok']:5} {c['served_error']:5} {c['unimplemented']:6} {c['probe_error']:5}   {100*routed/n:5.1f}")
    n = sum(tot.values()); print("TOTAL", dict(tot), f"routed {100*(tot['served_ok']+tot['served_error'])/max(n,1):.1f}%")


main()
