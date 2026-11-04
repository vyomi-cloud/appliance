# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure subscription / billing extras (Nano / dev_server / unified-ingress core).

Everything here lives in the shared ``AzureArm.state`` map (records keyed by lower-cased id, carrying ``_type`` / ``_sub``)
so it persists with the rest of ARM, and is deterministic over the real inventory:

* Quota requests -- the real ``Microsoft.Quota`` shape, scoped to a provider + location::

      PUT/GET {sub}/providers/Microsoft.Compute|Microsoft.Network/locations/{loc}/providers/Microsoft.Quota/quotas/{name}
      GET     {sub}/providers/Microsoft.Quota/quotaRequests[/{id}]

  A limit change is validated (>= current usage, <= the provider's hard cap), automatically APPROVED up to 4x the
  default limit and otherwise FAILED with the real "support request required" message; an approved request really raises the
  limit the ARM engine enforces (``limit_for`` is read by ``AzureArm._usages`` and the QuotaExceeded checks).
* Management certificates (``Microsoft.Subscription/managementCertificates``, the retired classic model): a .cer / PEM is
  really parsed (DER walk: thumbprint = SHA-1, subject CN, issuer CN, notBefore / notAfter), expired or duplicate
  certificates are refused, max 100.
* Ownership-transfer requests (``Microsoft.Billing/transferRequests``): create (validated recipient e-mail, not the current
  owner, not while another is pending), accept / decline / cancel, 15-day expiry; ACCEPT really changes the subscription's
  account administrator.
* Partner information (``Microsoft.ManagementPartner/partners``): a Microsoft Partner Network ID association (digits only).
* Top free services by usage (``Microsoft.Billing/freeServices``): the 12-month / always-free allowances, with usage MEASURED
  from the real inventory where Vyomi can measure it (VM hours of the free VM sizes, Blob GB) and marked ``measured: false``
  otherwise.
* Cost saved + simulated invoices (``Microsoft.Billing/costSaved``, ``.../invoices``): the real-cloud list price of every
  resource Vyomi runs (``azure_cost_core`` / ``cost_model``), accrued from each resource's creation instant -- what the same
  inventory would have cost on real Azure, i.e. the money kept. Invoices are one per month, marked ``simulated``: amountDue is
  always 0.00 (nothing is billed), ``avoidedAmount`` carries the would-be charge. Deleted resources leave no ledger, so past
  months are a LOWER BOUND reconstructed from the resources that still exist.

NOT modelled: real support-ticket approval of large quota increases, Microsoft Entra directory transfer, payment instruments
(never), Marketplace partner revenue.

Pure python, no framework imports. Functions return ``{"status": int, "body": ...}``.
"""
from __future__ import annotations

import base64
import calendar
import datetime
import hashlib
import re
import uuid

try:
    from core import azure_cost_core as _cost
except ImportError:
    import azure_cost_core as _cost       # type: ignore

AUTO_APPROVE_FACTOR = 4
HARD_CAP_FACTOR = 50
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _now_dt():
    return datetime.datetime.now(datetime.timezone.utc)


def _now():
    return _now_dt().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200):
    return {"status": status, "body": body}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _of_type(state, sub, t):
    return [r for r in state.values() if isinstance(r, dict) and str(r.get("_type", "")).lower() == t and r.get("_sub") == sub]


# ═════════════════════════════ quota ════════════════════════════════════════
def quota_marker(chain):
    for i in range(len(chain) - 2):
        if chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.quota" and chain[i + 2].lower() in ("quotas", "quotarequests"):
            return i
    return None


def limit_for(state, sub, namespace, location, name, default):
    rec = state.get(f"/subscriptions/{sub}/providers/microsoft.quota/limits/{namespace}:{location}:{name}".lower())
    return rec["limit"] if rec else default


def _quota_rows(defaults):
    return {n.lower(): (n, label, lim) for n, label, lim in defaults}


def quota_dispatch(state, method, sub, namespace, location, chain, payload, usage_of, defaults):
    """``chain`` = everything after ``providers/Microsoft.Quota`` (``['quotas', name?]`` or ``['quotaRequests', id?]``).
    ``usage_of(name) -> int`` gives the current usage of a quota; ``defaults`` = [(name, label, defaultLimit)]."""
    table = _quota_rows(defaults)
    ns = namespace
    loc = (location or "eastus").lower()
    scope = f"/subscriptions/{sub}/providers/{ns}/locations/{loc}"
    kind = chain[0].lower()

    def qview(key):
        n, label, default = table[key]
        lim = limit_for(state, sub, ns, loc, n, default)
        return {"id": f"{scope}/providers/Microsoft.Quota/quotas/{n}", "name": n, "type": "Microsoft.Quota/quotas",
                "properties": {"limit": {"limitObjectType": "LimitValue", "value": lim}, "currentValue": usage_of(n), "unit": "Count",
                               "name": {"value": n, "localizedValue": label}, "isQuotaApplicable": True, "properties": {},
                               "defaultLimit": default}}
    if kind == "quotas":
        if len(chain) == 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            return _ok({"value": [qview(k) for k in table]})
        key = chain[1].lower()
        if key not in table:
            return _err(404, "QuotaNotFound", f"The quota '{chain[1]}' is not defined for {ns} in {loc}.")
        if method == "GET":
            return _ok(qview(key))
        if method in ("PUT", "PATCH"):
            return _submit_quota(state, sub, ns, loc, scope, table[key], payload, usage_of)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    # quotaRequests under a provider/location scope
    reqs = [r for r in _of_type(state, sub, "microsoft.quota/quotarequests") if r["_ns"] == ns and r["_loc"] == loc]
    if len(chain) == 1:
        return _ok({"value": [_view(r) for r in reversed(reqs)]})
    r = next((x for x in reqs if x["name"] == chain[1]), None)
    return _ok(_view(r)) if r else _err(404, "ResourceNotFound", f"Quota request '{chain[1]}' was not found.")


def _submit_quota(state, sub, ns, loc, scope, row, payload, usage_of):
    name, label, default = row
    p = (payload or {}).get("properties") or {}
    lim = p.get("limit") or {}
    if lim.get("limitObjectType", "LimitValue") != "LimitValue" or "value" not in lim:
        return _err(400, "InvalidRequestContent", "properties.limit must be {limitObjectType: 'LimitValue', value: <integer>}.")
    try:
        new = int(lim["value"])
    except (TypeError, ValueError):
        return _err(400, "InvalidRequestContent", "properties.limit.value must be an integer.")
    cur_limit = limit_for(state, sub, ns, loc, name, default)
    used = usage_of(name)
    rid = f"{scope}/providers/Microsoft.Quota/quotaRequests/{uuid.uuid4()}"
    state_, msg = "Succeeded", ""
    if new < 0:
        return _err(400, "InvalidRequestContent", "The new limit must be zero or greater.")
    if new < used:
        return _err(400, "QuotaLimitBelowUsage", f"The requested limit {new} is below the current usage {used} of '{label}'.")
    if new > default * HARD_CAP_FACTOR:
        return _err(400, "QuotaLimitAboveMaximum", f"The requested limit {new} exceeds the maximum {default * HARD_CAP_FACTOR} that can be requested for '{label}'.")
    if new > cur_limit and new > default * AUTO_APPROVE_FACTOR:
        state_, msg = "Failed", "Automatic approval isn't available for this increase. Create a support request to raise the limit further."
    rec = {"id": rid, "name": rid.rsplit("/", 1)[-1], "type": "Microsoft.Quota/quotaRequests",
           "properties": {"provisioningState": state_, "message": msg, "requestSubmitTime": _now(),
                          "value": [{"resourceName": name, "name": {"value": name, "localizedValue": label}, "limit": {"limitObjectType": "LimitValue", "value": new},
                                     "previousLimit": cur_limit, "unit": "Count", "provisioningState": state_}]},
           "_type": "microsoft.quota/quotarequests", "_sub": sub, "_ns": ns, "_loc": loc}
    state[rid.lower()] = rec
    if state_ == "Succeeded":
        okey = f"/subscriptions/{sub}/providers/microsoft.quota/limits/{ns}:{loc}:{name}".lower()
        state[okey] = {"id": okey, "name": name, "limit": new, "_type": "microsoft.quota/limits", "_sub": sub}
    st = {"status": 200 if state_ == "Succeeded" else 400, "body": None}
    if state_ == "Succeeded":
        st["body"] = {"id": f"{scope}/providers/Microsoft.Quota/quotas/{name}", "name": name, "type": "Microsoft.Quota/quotas",
                      "properties": {"provisioningState": "Succeeded", "limit": {"limitObjectType": "LimitValue", "value": new}, "currentValue": used,
                                     "name": {"value": name, "localizedValue": label}, "requestId": rec["name"]}}
    else:
        st["body"] = {"error": {"code": "QuotaRequestFailed", "message": msg}, "requestId": rec["name"]}
    return st


# ═════════════════════════════ management certificates ═══════════════════════════
def _tlv(b, pos):
    tag = b[pos]
    ln = b[pos + 1]
    hdr = 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(b[pos + 2:pos + 2 + n], "big")
        hdr = 2 + n
    return tag, pos + hdr, pos + hdr + ln


def _children(b, start, end):
    out, p = [], start
    while p < end:
        tag, s, e = _tlv(b, p)
        out.append((tag, s, e))
        p = e
    return out


def _name_cn(b, s, e):
    cn = None
    for _t, rs, re_ in _children(b, s, e):
        for _t2, ss, se in _children(b, rs, re_):
            kids = _children(b, ss, se)
            if len(kids) == 2 and b[kids[0][1]:kids[0][2]] == b"\x55\x04\x03":
                cn = b[kids[1][1]:kids[1][2]].decode("utf-8", "replace")
    return cn


def _der_time(b, tag, s, e):
    t = b[s:e].decode()
    fmt = "%y%m%d%H%M%SZ" if tag == 0x17 else "%Y%m%d%H%M%SZ"
    return datetime.datetime.strptime(t, fmt).replace(tzinfo=datetime.timezone.utc)


def parse_certificate(data: str):
    """Parse a base64 DER or PEM certificate. Returns dict or raises ValueError."""
    txt = re.sub(r"-----(BEGIN|END) CERTIFICATE-----|\s", "", data or "")
    try:
        der = base64.b64decode(txt, validate=True)
        tag, s, e = _tlv(der, 0)
        if tag != 0x30:
            raise ValueError
        tbs_tag, ts, te = _tlv(der, s)
        kids = _children(der, ts, te)
        i = 1 if kids[0][0] == 0xA0 else 0
        issuer, validity, subject = kids[i + 2], kids[i + 3], kids[i + 4]
        v = _children(der, validity[1], validity[2])
        nb, na = _der_time(der, v[0][0], v[0][1], v[0][2]), _der_time(der, v[1][0], v[1][1], v[1][2])
        return {"thumbprint": hashlib.sha1(der).hexdigest().upper(), "subject": _name_cn(der, subject[1], subject[2]) or "",
                "issuer": _name_cn(der, issuer[1], issuer[2]) or "", "notBefore": nb, "notAfter": na}
    except Exception:
        raise ValueError("The certificate data is not a valid X.509 certificate (expected base64 DER or PEM).")


def certs_dispatch(state, method, sub, chain, payload):
    items = _of_type(state, sub, "microsoft.subscription/managementcertificates")
    if not chain:
        if method == "GET":
            return _ok({"value": [_view(r) for r in items]})
        if method != "POST":
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        if len(items) >= 100:
            return _err(409, "QuotaExceeded", "A subscription supports at most 100 management certificates.")
        try:
            c = parse_certificate((payload or {}).get("certificate") or (payload or {}).get("data") or "")
        except ValueError as e:
            return _err(400, "InvalidCertificate", str(e))
        if c["notAfter"] < _now_dt():
            return _err(400, "CertificateExpired", f"The certificate expired on {c['notAfter'].date()}.")
        if c["notBefore"] > _now_dt():
            return _err(400, "CertificateNotYetValid", f"The certificate is not valid before {c['notBefore'].date()}.")
        rid = f"/subscriptions/{sub}/providers/Microsoft.Subscription/managementCertificates/{c['thumbprint']}"
        if rid.lower() in state:
            return _err(409, "CertificateAlreadyExists", f"A certificate with thumbprint {c['thumbprint']} already exists.")
        rec = {"id": rid, "name": c["thumbprint"], "type": "Microsoft.Subscription/managementCertificates",
               "properties": {"thumbprint": c["thumbprint"], "subject": c["subject"], "issuer": c["issuer"],
                              "created": c["notBefore"].strftime("%Y-%m-%dT%H:%M:%SZ"), "expires": c["notAfter"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "uploaded": _now()},
               "_type": "microsoft.subscription/managementcertificates", "_sub": sub}
        state[rid.lower()] = rec
        return _ok(_view(rec), 201)
    rid = f"/subscriptions/{sub}/providers/Microsoft.Subscription/managementCertificates/{chain[0].upper()}"
    rec = state.get(rid.lower())
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"Management certificate '{chain[0]}' was not found.")
    if method == "DELETE":
        if rec is None:
            return _err(404, "ResourceNotFound", f"Management certificate '{chain[0]}' was not found.")
        state.pop(rid.lower())
        return _ok(None)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═════════════════════════════ ownership transfer ═══════════════════════════════
def transfers_dispatch(state, method, sub, chain, payload, billing):
    base = f"/subscriptions/{sub}/providers/Microsoft.Billing/transferRequests"
    items = _of_type(state, sub, "microsoft.billing/transferrequests")
    for r in items:     # lazy expiry
        if r["properties"]["status"] == "Pending" and r["properties"]["expirationTime"] < _now():
            r["properties"]["status"] = "Expired"
    owner = billing.get("accountAdmin", "")
    if not chain:
        if method == "GET":
            return _ok({"value": [_view(r) for r in reversed(items)]})
        if method != "POST":
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        to = str((payload or {}).get("recipientEmail") or "").strip()
        if not EMAIL_RE.match(to):
            return _err(400, "InvalidRecipient", "recipientEmail must be a valid e-mail address.")
        if to.lower() == str(owner).lower():
            return _err(400, "InvalidRecipient", "The recipient is already the account administrator of this subscription.")
        if any(r["properties"]["status"] == "Pending" for r in items):
            return _err(409, "TransferAlreadyPending", "A transfer request is already pending for this subscription. Cancel it first.")
        tid = str(uuid.uuid4())
        rec = {"id": f"{base}/{tid}", "name": tid, "type": "Microsoft.Billing/transferRequests",
               "properties": {"status": "Pending", "recipientEmail": to, "initiator": owner, "subscriptionId": sub,
                              "createdTime": _now(), "expirationTime": (_now_dt() + datetime.timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                              "billingOnly": bool((payload or {}).get("billingOnly", False))},
               "_type": "microsoft.billing/transferrequests", "_sub": sub}
        state[rec["id"].lower()] = rec
        return _ok(_view(rec), 201)
    rec = state.get(f"{base}/{chain[0]}".lower())
    if rec is None:
        return _err(404, "ResourceNotFound", f"Transfer request '{chain[0]}' was not found.")
    if len(chain) == 1:
        return _ok(_view(rec)) if method == "GET" else _err(405, "MethodNotAllowed", "GET only.")
    act = chain[1].lower()
    if method != "POST" or act not in ("accept", "decline", "cancel"):
        return _err(404, "ResourceNotFound", f"Unknown transfer action '{chain[1]}'.")
    if rec["properties"]["status"] != "Pending":
        return _err(409, "TransferNotPending", f"The transfer request is {rec['properties']['status']}, not Pending.")
    rec["properties"]["status"] = {"accept": "Completed", "decline": "Declined", "cancel": "Canceled"}[act]
    rec["properties"]["lastModified"] = _now()
    if act == "accept":
        billing["accountAdmin"] = rec["properties"]["recipientEmail"]
    return _ok(_view(rec))


# ═════════════════════════════ partner information ═════════════════════════════
def partner_dispatch(state, method, sub, chain, payload):
    items = _of_type(state, sub, "microsoft.managementpartner/partners")
    if not chain:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "GET only.")
        return _ok({"value": [_view(r) for r in items]})
    pid = chain[0]
    if not re.fullmatch(r"\d{1,10}", pid):
        return _err(400, "InvalidPartnerId", "The partner ID must be a Microsoft Partner Network ID (digits only, up to 10).")
    rid = f"/providers/Microsoft.ManagementPartner/partners/{pid}"
    rec = next((r for r in items if r["name"] == pid), None)
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"Partner '{pid}' is not associated with this tenant.")
    if method == "PUT":
        if items and rec is None:
            return _err(409, "PartnerAlreadyAssociated", f"Partner '{items[0]['name']}' is already associated. Update or remove it first (one association per tenant).")
        name = ((payload or {}).get("properties") or {}).get("partnerName") or ""
        if rec is None:
            rec = {"id": rid, "name": pid, "type": "Microsoft.ManagementPartner/partners",
                   "properties": {"partnerId": pid, "partnerName": name, "tenantId": "vyomi-tenant", "objectId": str(uuid.uuid4()),
                                  "version": 1, "updatedTime": _now(), "createdTime": _now(), "state": "Active"},
                   "_type": "microsoft.managementpartner/partners", "_sub": sub}
            state[f"{sub}:{rid}".lower()] = rec
            return _ok(_view(rec), 201)
        rec["properties"].update({"partnerName": name or rec["properties"]["partnerName"], "updatedTime": _now(), "version": rec["properties"]["version"] + 1})
        return _ok(_view(rec))
    if method == "DELETE":
        if rec is None:
            return _err(404, "ResourceNotFound", f"Partner '{pid}' is not associated with this tenant.")
        for k in [k for k, v in state.items() if v is rec]:
            state.pop(k)
        return _ok(None)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═════════════════════════════ top free services ════════════════════════════════
FREE_ALLOWANCES = [   # (id, label, included, unit, window)
    ("vm-b1s", "Linux/Windows B1s virtual machine", 750, "hours/month", "12 months"),
    ("blob-hot", "Blob storage (hot, LRS)", 5, "GB", "12 months"),
    ("sql-db", "Azure SQL Database (serverless free offer)", 1, "database", "always"),
    ("cosmos", "Cosmos DB (free tier)", 1, "account", "always"),
    ("keyvault", "Key Vault (standard)", 10000, "operations/month", "12 months"),
    ("functions", "Functions (consumption)", 1000000, "executions/month", "always"),
]
FREE_VM_SIZES = ("standard_b1s", "standard_b2pts_v2", "standard_b2ats_v2", "standard_b1ms")


def free_services(state, sub, blob_store=None):
    now = _now_dt()
    vms = [r for r in _of_type(state, sub, "microsoft.compute/virtualmachines")
           if str((r.get("properties") or {}).get("hardwareProfile", {}).get("vmSize", "")).lower() in FREE_VM_SIZES]
    vm_hours = 0.0
    for r in vms:
        try:
            created = datetime.datetime.strptime(r.get("_created", "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            created = now
        start = max(created, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        vm_hours += max((now - start).total_seconds() / 3600.0, 0)
    blob_gb = None
    if blob_store is not None:
        try:
            total = sum(len(e.get("data") or b"") if not isinstance(e.get("data"), str) else len(e["data"]) for c in list(blob_store.blobs.values()) for e in c.values())
            blob_gb = total / 1024 ** 3
        except Exception:
            blob_gb = None
    used = {
        "vm-b1s": (round(vm_hours, 2), True),
        "blob-hot": (round(blob_gb, 6), True) if blob_gb is not None else (0, False),
        "sql-db": (len(_of_type(state, sub, "microsoft.sql/servers/databases")), True),
        "cosmos": (len(_of_type(state, sub, "microsoft.documentdb/databaseaccounts")), True),
        "keyvault": (0, False), "functions": (0, False),
    }
    rows = []
    for fid, label, inc, unit, window in FREE_ALLOWANCES:
        u, measured = used[fid]
        rows.append({"id": fid, "name": label, "included": inc, "unit": unit, "window": window, "used": u,
                     "percentUsed": round(100.0 * u / inc, 2) if inc else 0.0, "measured": measured})
    rows.sort(key=lambda r: (-r["percentUsed"], r["name"]))
    return {"value": rows}


# ═════════════════════════════ cost saved + simulated invoices ═══════════════════
def _created_dt(rec):
    try:
        return datetime.datetime.strptime(str(rec.get("_created", ""))[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _month_overlap_fraction(created, y, m, now):
    days = calendar.monthrange(y, m)[1]
    start = datetime.datetime(y, m, 1, tzinfo=datetime.timezone.utc)
    end = min(datetime.datetime(y, m, days, 23, 59, 59, tzinfo=datetime.timezone.utc), now)
    s = max(start, created)
    if end <= s:
        return 0.0
    return min((end - s).total_seconds() / (days * 86400.0), 1.0)


def cost_saved(state, sub, now=None):
    now = now or _now_dt()
    resources = []
    for rec in state.values():
        if not isinstance(rec, dict) or rec.get("_sub") != sub:
            continue
        mapped = _cost._TYPE_MAP.get(str(rec.get("_type") or "").lower())
        if not mapped:
            continue
        created = _created_dt(rec)
        resources.append((rec, created))
    rows = _cost._collect_resource_rows(state, sub)
    by_name = {}
    for r in rows:
        by_name.setdefault((r["name"], r["full_type"]), r)
    months, per_service, per_resource = {}, {}, []
    total = 0.0
    for rec, created in resources:
        row = by_name.get((rec.get("name", ""), str(rec.get("_type", "")).lower()))
        if row is None or created is None:
            continue
        monthly = row["monthly_usd"]
        y, m = created.year, created.month
        saved = 0.0
        while (y, m) <= (now.year, now.month):
            amt = monthly * _month_overlap_fraction(created, y, m, now)
            months[f"{y:04d}-{m:02d}"] = months.get(f"{y:04d}-{m:02d}", 0.0) + amt
            saved += amt
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        total += saved
        per_service[row["service"]] = per_service.get(row["service"], 0.0) + saved
        per_resource.append({"name": rec.get("name"), "type": rec.get("type"), "service": row["service"], "resourceGroup": row["resource_group"],
                             "monthlyListPrice": monthly, "since": created.strftime("%Y-%m-%d"), "saved": round(saved, 2)})
    run_rate = round(sum(r["monthly_usd"] for r in rows), 2)
    current = f"{now.year:04d}-{now.month:02d}"
    return {"currency": "USD", "totalSaved": round(total, 2), "thisMonthSaved": round(months.get(current, 0.0), 2),
            "monthlyRunRate": run_rate, "annualizedSavings": round(run_rate * 12, 2), "actualSpend": 0.0,
            "resourceCount": len(per_resource),
            "monthly": [{"month": k, "saved": round(v, 2)} for k, v in sorted(months.items())],
            "byService": sorted([{"service": k, "saved": round(v, 2)} for k, v in per_service.items()], key=lambda x: -x["saved"]),
            "topResources": sorted(per_resource, key=lambda x: -x["saved"])[:10],
            "note": "Real-Azure list price of the resources Vyomi runs, accrued from each resource's creation. Deleted resources leave no ledger, so earlier months are a lower bound."}


def invoices(state, sub, now=None):
    now = now or _now_dt()
    cs = cost_saved(state, sub, now)
    out = []
    for mrow in reversed(cs["monthly"]):
        period = mrow["month"]
        y, m = int(period[:4]), int(period[5:])
        end = f"{period}-{calendar.monthrange(y, m)[1]:02d}"
        cur = period == f"{now.year:04d}-{now.month:02d}"
        name = f"VYOMI-{period.replace('-', '')}-{sub[-4:].upper()}"
        out.append({"id": f"/subscriptions/{sub}/providers/Microsoft.Billing/invoices/{name}", "name": name, "type": "Microsoft.Billing/invoices",
                    "properties": {"invoicePeriodStartDate": f"{period}-01", "invoicePeriodEndDate": end, "invoiceDate": end,
                                   "status": "InProgress" if cur else "Simulated", "documentType": "Invoice", "simulated": True,
                                   "amountDue": {"currency": "USD", "value": 0.0}, "billedAmount": {"currency": "USD", "value": 0.0},
                                   "avoidedAmount": {"currency": "USD", "value": mrow["saved"]},
                                   "note": "Simulated Vyomi invoice: nothing is billed. avoidedAmount is what real Azure would have charged."}})
    return out
