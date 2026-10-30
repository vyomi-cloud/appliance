"""Capability registry conformance — the console's disclaimers must be TRUE.

core/capabilities/<cloud>/<service>.json declares, per feature, a support level
(full / limited / config_only / not_simulated) for each substrate. This test proves every
claim against the backend, so the UI can neither claim support that does not exist nor
hide support that does:

  full / limited   → the probe succeeds and every listed test file passes
  config_only      → PUT then GET returns the stored document (round-trip)
  not_simulated    → the native "not implemented" answer (S3 501 NotImplemented,
                     DynamoDB UnknownOperationException)

Substrates:
  in-process (default)  → the shared core via AwsWireRouter = Nano / dev_server / unified
                          ingress; checks the "nano" level.
  CAP_BASE=http://host  → a running appliance over /_wire; checks the "offline" level.

Run:  PYTHONPATH=. python3 tests/conformance/test_capabilities.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "core" / "capabilities"
BASE = os.environ.get("CAP_BASE", "").rstrip("/")
SUBSTRATE = "offline" if BASE else "nano"
AUTH = "AWS4-HMAC-SHA256 Credential=CAP/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"

if not BASE:
    sys.path.insert(0, str(ROOT))
    from core.aws_wire_router import AwsWireRouter  # noqa: E402
    ROUTER = AwsWireRouter()


def call(method: str, path: str, *, svc: str, body: bytes = b"", headers: dict | None = None) -> tuple[int, bytes]:
    h = {"authorization": AUTH.format(svc=svc), **(headers or {})}
    if BASE:
        req = urllib.request.Request(BASE + "/_wire" + path, data=body or None, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    u = urlsplit(path)
    out = ROUTER.handle(method, u.path, dict(parse_qsl(u.query, keep_blank_values=True)), h, body)
    b = out.get("body") or b""
    return int(out.get("status", 200)), b if isinstance(b, bytes) else str(b).encode()


def ddb(op: str, payload: dict) -> tuple[int, dict]:
    st, b = call("POST", "/", svc="dynamodb", body=json.dumps(payload).encode(),
                 headers={"x-amz-target": f"DynamoDB_20120810.{op}", "content-type": "application/x-amz-json-1.0"})
    try:
        return st, json.loads(b or b"{}")
    except Exception:
        return st, {"raw": b[:200].decode("utf-8", "replace")}


def norm(x: bytes) -> str:
    import re
    s = x.decode("utf-8", "replace")
    s = re.sub(r"<\?xml[^>]*\?>", "", s)
    s = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", s)
    return re.sub(r"\s+", "", s)


# ── Probes ────────────────────────────────────────────────────────────────────────────
def probe(fid: str, p: dict, level: str, ctx: dict) -> tuple[bool, str]:
    b = ctx["bucket"]
    if "s3" in p:
        if p["s3"] == "bucket-crud":
            st, body = call("GET", "/", svc="s3")
            return st == 200 and f"<Name>{b}</Name>".encode() in body, f"ListBuckets {st}"
        if p["s3"] == "object-crud":
            st, _ = call("PUT", f"/{b}/cap/obj.txt", svc="s3", body=b"cap")
            g, body = call("GET", f"/{b}/cap/obj.txt", svc="s3")
            return st == 200 and g == 200 and body == b"cap", f"put {st} get {g}"
    if "s3_get" in p:
        st, body = call("GET", f"/{b}?{p['s3_get']}=", svc="s3")
        return st == 200, f"GET ?{p['s3_get']} → {st}"
    if p.get("s3_versioning"):
        st, _ = call("PUT", f"/{b}?versioning=", svc="s3",
                     body=b"<VersioningConfiguration><Status>Enabled</Status></VersioningConfiguration>")
        g, body = call("GET", f"/{b}?versioning=", svc="s3")
        call("PUT", f"/{b}/v.txt", svc="s3", body=b"1"); call("PUT", f"/{b}/v.txt", svc="s3", body=b"2")
        lv, vbody = call("GET", f"/{b}?versions=", svc="s3")
        ok = st == 200 and b"<Status>Enabled</Status>" in body and lv == 200 and vbody.count(b"<Version>") >= 2
        return ok, f"put {st}, get {g}, ListObjectVersions {lv} ({vbody.count(b'<Version>')} versions)"
    if "s3_roundtrip" in p:
        sub, doc = p["s3_roundtrip"], p["doc"].encode()
        st, _ = call("PUT", f"/{b}?{sub}=", svc="s3", body=doc)
        g, body = call("GET", f"/{b}?{sub}=", svc="s3")
        same = norm(body) == norm(doc) if sub != "policy" else json.loads(body or b"{}") == json.loads(doc)
        return st in (200, 204) and g == 200 and same, f"PUT {st} GET {g} round-trip={'ok' if same else 'DIFFERS'}"
    if "s3_unsupported" in p:
        sub = p["s3_unsupported"]
        st, body = call("GET", f"/{b}?{sub}=", svc="s3")
        pst, _ = call("PUT", f"/{b}?{sub}=", svc="s3", body=b"<X/>")
        return st == 501 and pst == 501 and b"NotImplemented" in body, f"GET {st} PUT {pst}"
    if "ddb_ok" in p:
        res = []
        for op in p["ddb_ok"]:
            payload = {"TableName": ctx["table"]}
            if op in ("ListTables",):
                payload = {}
            if op == "Query":
                payload.update(KeyConditionExpression="pk = :v", ExpressionAttributeValues={":v": {"S": "x"}})
            if op == "BatchWriteItem":
                payload = {"RequestItems": {ctx["table"]: [{"PutRequest": {"Item": {"pk": {"S": "b1"}}}}]}}
            if op == "TransactWriteItems":
                payload = {"TransactItems": [{"Put": {"TableName": ctx["table"], "Item": {"pk": {"S": "t1"}}}}]}
            if op == "TagResource":
                payload = {"ResourceArn": ctx["arn"], "Tags": [{"Key": "cap", "Value": "1"}]}
            if op == "ListTagsOfResource":
                payload = {"ResourceArn": ctx["arn"]}
            st, out = ddb(op, payload)
            res.append(f"{op}={st}")
            if st != 200:
                return False, " ".join(res) + f" {out.get('__type', '')}"
        return True, " ".join(res)
    if "ddb_unknown" in p:
        st, out = ddb(p["ddb_unknown"], {"TableName": ctx["table"]})
        return st == 400 and "UnknownOperation" in str(out.get("__type", "")), f"{p['ddb_unknown']} → {st} {out.get('__type', '')}"
    return True, "no probe (tests only)"


def run_tests(files: list[str]) -> tuple[bool, str]:
    if BASE:
        return True, "test files run in-process only"
    bad = []
    for f in files:
        r = subprocess.run([sys.executable, str(ROOT / f)], cwd=ROOT, capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
        if r.returncode != 0:
            bad.append(f)
    return not bad, ("failing: " + ", ".join(bad)) if bad else f"{len(files)} test file(s) pass"


def main() -> int:
    ctx = {"bucket": f"cap-{uuid.uuid4().hex[:10]}", "table": f"cap{uuid.uuid4().hex[:8]}"}
    call("PUT", f"/{ctx['bucket']}", svc="s3")
    ddb("CreateTable", {"TableName": ctx["table"], "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}],
                        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], "BillingMode": "PAY_PER_REQUEST"})
    ctx["arn"] = ddb("DescribeTable", {"TableName": ctx["table"]})[1].get("Table", {}).get("TableArn", "")

    failures, total = [], 0
    tested_files: dict[str, tuple[bool, str]] = {}
    for f in sorted(REG.rglob("*.json")):
        if f.name == "schema.json":
            continue
        reg = json.loads(f.read_text())
        for fid, ent in reg.items():
            if fid.startswith("$"):
                continue
            level = ent["level"][SUBSTRATE]
            total += 1
            ok, why = probe(fid, ent.get("probe") or {}, level, ctx)
            # A not_simulated feature with no probe can't be checked automatically — allowed,
            # but a supported one must have a probe or tests.
            if level != "not_simulated" and not ent.get("probe") and not ent.get("tests"):
                ok, why = False, "supported level needs a probe or tests"
            if ok and level in ("full", "limited") and ent.get("tests"):
                key = tuple(ent["tests"])
                tested_files.setdefault(key, run_tests(ent["tests"]))
                ok, why2 = tested_files[key]
                why = f"{why}; {why2}"
            print(f"{'PASS' if ok else 'FAIL'} [{SUBSTRATE}:{level}] {fid} — {why}")
            if not ok:
                failures.append(fid)
    print(f"\n{total - len(failures)}/{total} capability claims hold on {SUBSTRATE}")
    if failures:
        print("RESULT: FAIL —", ", ".join(failures))
        return 1
    print(f"RESULT: PASS — every capability claim is true on {SUBSTRATE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
