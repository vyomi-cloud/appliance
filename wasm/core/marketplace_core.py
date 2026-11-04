# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS Marketplace, Vyomi edition (service `aws-marketplace`, SigV4 signing name `aws-marketplace`, rest-json).

The catalog is Vyomi's OWN products, not AWS Marketplace listings: "SaaS spaces" (simulators of third-party SaaS APIs a
developer integrates into cloud code — payments, identity, e-mail, SMS, observability, git hosting) and a handful of AMI
products (hardened / pre-configured images). Subscribing is real:

 * a SaaS product creates an agreement + a *space* (endpoint URL, API key, creation time) the app can be pointed at;
 * an AMI product registers an AMI (owner `aws-marketplace`, a product code) in the account's EC2 model, so it shows in
   DescribeImages / the AMI catalog and can be launched; unsubscribing is refused while an instance still runs it, and
   deregisters the AMI otherwise.

Community AMIs (public images owned by other accounts) are seeded into the EC2 model the first time they are listed.

API (Marketplace Catalog API shapes + Vyomi subscription ops):
  POST /ListEntities                    EntityType SaaSProduct | AmiProduct | CommunityAmi, FilterList, paging
  GET|POST /DescribeEntity?catalog&entityId
  POST /agreements {productId, acceptEula}      GET /agreements      DELETE /agreements/{agreementId}
State: s3_store.account["marketplace"]. Pure Python, Pyodide-loadable.

Honest limits: no real third-party SaaS is contacted, no metering/billing, no seller portal, no offers/private pricing.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

_ACCOUNT = "123456789012"
_CATALOG = "AWSMarketplace"

_SAAS = [
    ("vyomi-pay", "Vyomi Payments Sandbox", "Payments", "Card charges, customers, refunds and webhooks (Stripe-style API).", ["POST /v1/charges", "POST /v1/customers", "POST /v1/refunds"]),
    ("vyomi-identity", "Vyomi Identity Sandbox", "Identity", "Hosted sign-in, OIDC discovery and JWKS for app authentication tests.", ["GET /.well-known/openid-configuration", "POST /oauth/token"]),
    ("vyomi-mail", "Vyomi Email Sandbox", "Messaging", "Transactional e-mail relay that captures messages instead of delivering them.", ["POST /v3/mail/send", "GET /v3/messages"]),
    ("vyomi-sms", "Vyomi SMS Sandbox", "Messaging", "SMS and verification-code API that records messages instead of sending them.", ["POST /2010-04-01/Messages", "GET /2010-04-01/Messages"]),
    ("vyomi-observe", "Vyomi Observability Sandbox", "Monitoring", "Metrics, logs and monitors ingest API (Datadog-style).", ["POST /api/v1/series", "POST /api/v2/logs"]),
    ("vyomi-git", "Vyomi Git Hosting Sandbox", "Developer tools", "Repositories, pull requests and webhooks (GitHub-style API).", ["POST /repos", "GET /repos/{owner}/{repo}/pulls"]),
]
_AMI = [
    ("vyomi-ami-ubuntu-cis", "Vyomi Hardened Ubuntu 24.04 (CIS Level 1)", "Operating systems", "x86_64", "", "Ubuntu 24.04 LTS with CIS Level 1 benchmark settings applied."),
    ("vyomi-ami-nginx", "Vyomi Nginx Web Server", "Web servers", "x86_64", "", "Ubuntu 24.04 with Nginx installed and enabled on boot."),
    ("vyomi-ami-postgres", "Vyomi PostgreSQL 16 Server", "Databases", "x86_64", "", "Ubuntu 24.04 with PostgreSQL 16 preconfigured on the data volume."),
    ("vyomi-ami-docker", "Vyomi Docker Host", "Containers", "arm64", "", "Amazon Linux 2023 with Docker Engine and Compose."),
    ("vyomi-ami-win-iis", "Vyomi Windows Server 2022 with IIS", "Operating systems", "x86_64", "windows", "Windows Server 2022 Base with the IIS role installed."),
]
_COMMUNITY = [
    ("Ubuntu 24.04 LTS minimal (community)", "099720109477", "x86_64", ""), ("Rocky Linux 9 (community)", "792107900819", "x86_64", ""),
    ("AlmaLinux 9 (community)", "764336703387", "x86_64", ""), ("Fedora Cloud 40 (community)", "125523088429", "x86_64", ""),
    ("FreeBSD 14.0 (community)", "782442783595", "x86_64", ""), ("Alpine Linux 3.20 (community)", "538276064493", "x86_64", ""),
]


def _s3c():
    try:
        from core import s3_object_core as m
    except ImportError:                       # Pyodide flat layout
        import s3_object_core as m            # type: ignore
    return m


def _vpcc():
    try:
        from core import vpc_core as m
    except ImportError:
        import vpc_core as m                  # type: ignore
    return m


def _resp(status, doc):
    m = _s3c()
    body = b"" if doc is None else json.dumps(doc).encode()
    return m.S3Response(status=status, headers=m._amz_headers(), body=body, media_type="application/json")


def _err(code, message, status):
    r = _resp(status, {"Message": message, "message": message, "__type": code})
    r.headers["x-amzn-ErrorType"] = code
    return r


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _state(s3_store) -> dict:
    st = s3_store.account.setdefault("marketplace", {})
    st.setdefault("agreements", {})
    return st


def _products() -> dict:
    out = {}
    for pid, name, cat, desc, ops in _SAAS:
        out[pid] = {"EntityId": pid, "EntityType": "SaaSProduct", "Name": name, "Vendor": "Vyomi", "Category": cat, "Description": desc,
                    "Pricing": "Free in Vyomi (simulated; no metering)", "Operations": ops,
                    "EntityArn": f"arn:aws:aws-marketplace:us-east-1:{_ACCOUNT}:{_CATALOG}/SaaSProduct/{pid}"}
    for pid, name, cat, arch, plat, desc in _AMI:
        out[pid] = {"EntityId": pid, "EntityType": "AmiProduct", "Name": name, "Vendor": "Vyomi", "Category": cat, "Description": desc,
                    "Pricing": "Free in Vyomi (simulated; no metering)", "Architecture": arch, "Platform": plat,
                    "ProductCode": "vy" + hashlib.sha1(pid.encode()).hexdigest()[:23],
                    "EntityArn": f"arn:aws:aws-marketplace:us-east-1:{_ACCOUNT}:{_CATALOG}/AmiProduct/{pid}"}
    return out


def _slug_key(st, pid):
    return hashlib.sha256(f"{_ACCOUNT}:{pid}".encode()).hexdigest()


def _seed_community(vpc_store):
    m = _vpcc()._model(vpc_store)
    if m.get("_mp_community_seeded"):
        return [i for i in m["images"].values() if i.get("source") == "community"]
    m["_mp_community_seeded"] = True
    for name, owner, arch, plat in _COMMUNITY:
        ami = "ami-" + uuid.uuid4().hex[:17]
        m["images"][ami] = {"id": ami, "name": name, "description": name, "owner_id": owner, "public": True, "state": "available",
                            "architecture": arch, "platform": plat, "root_device_type": "ebs", "root_device_name": "/dev/xvda",
                            "virtualization_type": "hvm", "creation_date": _now(), "source": "community", "tags": {}, "launch_permissions": [],
                            "block_devices": [{"device_name": "/dev/xvda", "snapshot_id": "snap-" + uuid.uuid4().hex[:12], "size": 8,
                                               "volume_type": "gp3", "delete_on_termination": True}]}
    return [i for i in m["images"].values() if i.get("source") == "community"]


def _paginate(items, p):
    try:
        n = int(p.get("MaxResults", 50))
    except (TypeError, ValueError):
        n = -1
    if not 1 <= n <= 50:
        return None, None, "MaxResults must be between 1 and 50."
    try:
        start = int(p.get("NextToken") or 0)
    except ValueError:
        return None, None, "NextToken is invalid."
    page = items[start:start + n]
    return page, (str(start + n) if start + n < len(items) else None), None


def _summary(e, subscribed):
    s = {"EntityType": e["EntityType"], "EntityId": e["EntityId"], "EntityArn": e["EntityArn"], "Name": e["Name"],
         "Visibility": "Public", "Vendor": e["Vendor"], "Category": e["Category"], "Description": e["Description"],
         "Subscribed": subscribed}
    return s


def _list_entities(s3_store, vpc_store, p):
    if p.get("Catalog") != _CATALOG:
        return _err("ValidationException", f"Catalog must be {_CATALOG}.", 400)
    et = p.get("EntityType")
    if et not in ("SaaSProduct", "AmiProduct", "CommunityAmi"):
        return _err("ValidationException", "EntityType must be SaaSProduct, AmiProduct or CommunityAmi.", 400)
    st = _state(s3_store)
    subs = {a["ProductId"] for a in st["agreements"].values() if a["Status"] == "ACTIVE"}
    if et == "CommunityAmi":
        rows = [{"EntityType": "CommunityAmi", "EntityId": i["id"], "EntityArn": f"arn:aws:ec2:us-east-1::image/{i['id']}", "Name": i["name"],
                 "Visibility": "Public", "Vendor": i["owner_id"], "Category": "Community", "Description": i["description"], "Subscribed": False,
                 "Architecture": i["architecture"], "Platform": i.get("platform", "")} for i in _seed_community(vpc_store)]
    else:
        rows = [_summary(e, e["EntityId"] in subs) for e in _products().values() if e["EntityType"] == et]
    for f in p.get("FilterList") or []:
        if f.get("Name") == "Category":
            rows = [r for r in rows if r["Category"] in (f.get("ValueList") or [])]
        elif f.get("Name") == "Name":
            rows = [r for r in rows if any(v.lower() in r["Name"].lower() for v in (f.get("ValueList") or []))]
        else:
            return _err("ValidationException", f"Unsupported filter {f.get('Name')}.", 400)
    rows.sort(key=lambda r: r["Name"])
    page, nxt, bad = _paginate(rows, p)
    if bad:
        return _err("ValidationException", bad, 400)
    return _resp(200, {"EntitySummaryList": page, **({"NextToken": nxt} if nxt else {})})


def _view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


def _subscribe(s3_store, vpc_store, p):
    pid = p.get("productId")
    prod = _products().get(pid)
    if not prod:
        return _err("ResourceNotFoundException", f"Product {pid} was not found in the catalog.", 404)
    if p.get("acceptEula") is not True:
        return _err("ValidationException", "You must accept the end-user license agreement (acceptEula: true) to subscribe.", 400)
    st = _state(s3_store)
    for a in st["agreements"].values():
        if a["ProductId"] == pid and a["Status"] == "ACTIVE":
            return _err("ConflictException", f"You are already subscribed to {prod['Name']} (agreement {a['AgreementId']}).", 409)
    aid = "agmt-" + uuid.uuid4().hex[:16]
    a = {"AgreementId": aid, "ProductId": pid, "ProductName": prod["Name"], "ProductType": prod["EntityType"], "Status": "ACTIVE",
         "StartTime": _now(), "Vendor": "Vyomi", "AcceptedBy": f"arn:aws:iam::{_ACCOUNT}:root"}
    if prod["EntityType"] == "SaaSProduct":
        a["Space"] = {"Endpoint": f"https://{pid}.spaces.vyomi.local", "ApiKey": "vy_" + _slug_key(st, pid)[:32], "Operations": prod["Operations"]}
    else:
        m = _vpcc()._model(vpc_store)
        ami = "ami-" + uuid.uuid4().hex[:17]
        m["images"][ami] = {"id": ami, "name": prod["Name"], "description": prod["Description"], "owner_id": "aws-marketplace", "public": False,
                            "state": "available", "architecture": prod["Architecture"], "platform": prod["Platform"], "root_device_type": "ebs",
                            "root_device_name": "/dev/xvda", "virtualization_type": "hvm", "creation_date": _now(), "source": "marketplace",
                            "product_code": prod["ProductCode"], "tags": {}, "launch_permissions": [],
                            "block_devices": [{"device_name": "/dev/xvda", "snapshot_id": "snap-" + uuid.uuid4().hex[:12], "size": 8,
                                               "volume_type": "gp3", "delete_on_termination": True}]}
        a["ImageId"], a["ProductCode"] = ami, prod["ProductCode"]
    st["agreements"][aid] = a
    s3_store.persist()
    return _resp(200, _view(a))


def _unsubscribe(s3_store, vpc_store, aid):
    st = _state(s3_store)
    a = st["agreements"].get(aid)
    if not a or a["Status"] != "ACTIVE":
        return _err("ResourceNotFoundException", f"Agreement {aid} was not found or is not active.", 404)
    if a.get("ImageId"):
        m = _vpcc()._model(vpc_store)
        busy = [i["id"] for i in m["instances"].values() if i.get("image_id") == a["ImageId"] and i.get("state") not in ("terminated", "shutting-down")]
        if busy:
            return _err("ConflictException", f"Instance {busy[0]} still runs {a['ImageId']}; terminate it before ending the subscription.", 409)
        m["images"].pop(a["ImageId"], None)
    a["Status"] = "CANCELLED"
    a["EndTime"] = _now()
    s3_store.persist()
    return _resp(200, _view(a))


def dispatch(s3_store, vpc_store, method, raw_path, query, body):
    method = method.upper()
    path = "/" + raw_path.strip("/")
    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return _err("ValidationException", "The request body must be a JSON object.", 400)
    if path == "/ListEntities" and method == "POST":
        return _list_entities(s3_store, vpc_store, p)
    if path == "/DescribeEntity" and method in ("GET", "POST"):
        q = query or {}
        if (q.get("catalog") or p.get("Catalog")) != _CATALOG:
            return _err("ValidationException", f"catalog must be {_CATALOG}.", 400)
        eid = q.get("entityId") or p.get("EntityId")
        e = _products().get(eid)
        if not e:
            return _err("ResourceNotFoundException", f"Entity {eid} was not found.", 404)
        sub = next((a for a in _state(s3_store)["agreements"].values() if a["ProductId"] == eid and a["Status"] == "ACTIVE"), None)
        return _resp(200, {"EntityType": e["EntityType"], "EntityIdentifier": eid, "EntityArn": e["EntityArn"], "LastModifiedDate": "2026-01-01T00:00:00Z",
                           "Details": {k: v for k, v in e.items() if k not in ("EntityId", "EntityType", "EntityArn")},
                           "Subscription": _view(sub) if sub else None})
    if path == "/agreements":
        if method == "POST":
            return _subscribe(s3_store, vpc_store, p)
        if method == "GET":
            rows = sorted(_state(s3_store)["agreements"].values(), key=lambda a: a["StartTime"], reverse=True)
            if (query or {}).get("status"):
                rows = [a for a in rows if a["Status"] == query["status"]]
            return _resp(200, {"Agreements": [_view(a) for a in rows]})
    mt = re.fullmatch(r"/agreements/(agmt-[0-9a-f]+)", path)
    if mt and method == "DELETE":
        return _unsubscribe(s3_store, vpc_store, mt.group(1))
    return _err("NotFoundException", f"Unsupported AWS Marketplace operation: {method} {path}", 404)
