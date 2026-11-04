# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Google Security Command Center REST API v2 (securitycenter.googleapis.com/v2) — substrate-independent.

Real surface (parents `projects/{p}`, `organizations/{o}`, `folders/{f}`, optional `/locations/{loc}`):
  sources            list / get / create (custom sources) / patch (displayName, description)
  findings           list (filter grammar, orderBy, pageSize/pageToken, totalSize), get, create + patch (CUSTOM sources only),
                     :setState, :setMute, :bulkMute, :group (groupBy + filter), securityMarks patch
  muteConfigs        create / get / list / patch / delete; a config's filter mutes matching findings (muteInitiator)
  notificationConfigs create / get / list / patch / delete; matching new/changed findings are PUBLISHED to the config's
                     Pub/Sub topic in the simulator's Pub/Sub (NotificationMessage JSON), see `sync_notifications`

Built-in sources are generated from real simulator state (they are read-only, as Google-owned sources are): Security Health
Analytics (core/gcp_posture_core misconfigurations over VM / firewall / bucket state), Event Threat Detection (the
deterministic vyomi-rules detector over the audit feed) and Container Analysis vulnerabilities (core/vuln_scan_core over Artifact
Registry images). Only operator state — state/mute overlays, security marks, custom sources/findings, mute and notification
configs — is stored, in `bag` (the S3 store's persisted account dict).

Honest limits: finding "detectors" are Vyomi's rule engines + advisory snapshot, not Google's ML/threat intelligence; org/folder
parents aggregate the single simulated project; no BigQuery exports, resource value configs, attack paths or IAM on sources.
Pure Python, loads under Pyodide.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone

DEFAULT_PROJECT = "vyomi-project"
SRC_SHA, SRC_ETD, SRC_CA = "3811549927", "3811549928", "3811549929"
BUILTIN = {
    SRC_SHA: ("Security Health Analytics", "Scans for vulnerabilities and misconfigurations in resources (Vyomi rule engine)."),
    SRC_ETD: ("Event Threat Detection", "Detects threats from the audit feed (Vyomi deterministic rules, detector=vyomi-rules)."),
    SRC_CA: ("Container Analysis", "Vulnerability findings for images in Artifact Registry (Vyomi advisory snapshot / Trivy)."),
}
SEVS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "SEVERITY_UNSPECIFIED")
STATES = ("ACTIVE", "INACTIVE")
MUTES = ("MUTED", "UNMUTED", "UNDEFINED")
CLASSES = ("THREAT", "VULNERABILITY", "MISCONFIGURATION", "OBSERVATION", "SCC_ERROR", "POSTURE_VIOLATION", "TOXIC_COMBINATION", "SENSITIVE_DATA_RISK")


class Resp:
    def __init__(self, status, obj):
        self.status, self.headers, self.body = status, {}, json.dumps(obj).encode()
        self.media_type = "application/json"


class _E(Exception):
    def __init__(self, status, code, msg):
        self.status, self.code, self.msg = status, code, msg


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _nf(msg):
    return _E(404, "NOT_FOUND", msg)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _state(bag):
    bag.setdefault("sources", {})
    bag.setdefault("custom", {})        # finding name -> finding
    bag.setdefault("overlay", {})       # finding name -> {state, mute, muteInitiator, marks, updated}
    bag.setdefault("mutes", {})
    bag.setdefault("notifs", {})
    bag.setdefault("seen", {})          # notif name -> {finding name -> signature}
    bag.setdefault("sent", [])
    return bag


def _projnum(p):
    return str(int(hashlib.sha1(p.encode()).hexdigest()[:10], 16) % 10 ** 12).zfill(12)


# ── generated findings ────────────────────────────────────────────────────────────────
def generate(project, posture_findings):
    """gcp_posture_core rows -> v2 Finding dicts (parent projects/{p}). Stable ids."""
    out = []
    for f in posture_findings:
        cls = f.get("findingClass") or "MISCONFIGURATION"
        src = SRC_ETD if cls == "THREAT" else SRC_CA if cls == "VULNERABILITY" else SRC_SHA
        fid = hashlib.sha1((src + f["category"] + f["resourceName"] + f.get("description", "")).encode()).hexdigest()[:32]
        d = {"name": f"projects/{project}/sources/{src}/findings/{fid}",
             "canonicalName": f"projects/{_projnum(project)}/sources/{src}/locations/global/findings/{fid}",
             "parent": f"projects/{project}/sources/{src}", "resourceName": f["resourceName"], "state": "ACTIVE", "category": f["category"],
             "externalUri": f"https://console.cloud.google.com/security/command-center/findings?project={project}",
             "sourceProperties": {"Recommendation": f.get("recommendation", ""), "Explanation": f.get("description", "")},
             "securityMarks": {"name": f"projects/{project}/sources/{src}/findings/{fid}/securityMarks", "marks": {}},
             "eventTime": f.get("eventTime") or _now(), "createTime": f.get("eventTime") or _now(),
             "severity": f["severity"] if f["severity"] in SEVS else "LOW", "mute": "UNDEFINED", "findingClass": cls,
             "description": f.get("description", ""), "nextSteps": f.get("recommendation", "")}
        if f.get("principal"):
            d["access"] = {"principalEmail": f["principal"]}
        if cls == "VULNERABILITY":
            d["vulnerability"] = {"cve": {"id": f["category"], "cvssv3": {"baseScore": f.get("cvssScore", 0)}}}
        out.append(d)
    return out


# ── filter grammar ────────────────────────────────────────────────────────────────────
_TOK = re.compile(r'\s*(\(|\)|!=|<=|>=|=|<|>|:|-(?=\S)|"(?:[^"\\]|\\.)*"|[^\s()=!<>:"]+)')


def _tokens(s):
    out, pos = [], 0
    s = s or ""
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m:
            if s[pos:].strip() == "":
                break
            raise _bad(f"Invalid filter near '{s[pos:pos + 20]}'")
        out.append(m.group(1))
        pos = m.end()
    return out


def _field(f, name):
    n = name.strip()
    m = {"state": "state", "category": "category", "severity": "severity", "resource_name": "resourceName", "mute": "mute",
         "finding_class": "findingClass", "parent": "parent", "name": "name", "event_time": "eventTime", "create_time": "createTime",
         "description": "description", "external_uri": "externalUri"}
    if n in m:
        return f.get(m[n])
    if n.startswith("source_properties."):
        return (f.get("sourceProperties") or {}).get(n.split(".", 1)[1])
    if n.startswith("security_marks.marks."):
        return ((f.get("securityMarks") or {}).get("marks") or {}).get(n.split(".", 2)[2])
    raise _bad(f"Invalid filter field '{n}'")


def compile_filter(expr):
    toks = _tokens(expr)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def eat():
        pos[0] += 1
        return toks[pos[0] - 1]

    def p_or():
        n = p_and()
        while (peek() or "").upper() == "OR":
            eat()
            n = ("or", n, p_and())
        return n

    def p_and():
        n = p_not()
        while peek() is not None and peek() != ")" and (peek() or "").upper() != "OR":
            if (peek() or "").upper() == "AND":
                eat()
            n = ("and", n, p_not())
        return n

    def p_not():
        t = peek()
        if t is not None and (t == "-" or t.upper() == "NOT"):
            eat()
            return ("not", p_not())
        return p_atom()

    def p_atom():
        t = peek()
        if t is None:
            raise _bad("Invalid filter: unexpected end")
        if t == "(":
            eat()
            n = p_or()
            if peek() != ")":
                raise _bad("Invalid filter: missing )")
            eat()
            return n
        name = eat()
        _field({}, name)          # reject unknown fields at compile time, like the API does
        op = peek()
        if op not in ("=", "!=", ":", "<", ">", "<=", ">="):
            raise _bad(f"Invalid filter: expected an operator after '{name}'")
        eat()
        if peek() is None:
            raise _bad("Invalid filter: missing value")
        v = eat()
        if v.startswith('"'):
            v = json.loads(v)
        return ("cmp", name, op, v)

    if not toks:
        return lambda f: True
    tree = p_or()
    if pos[0] != len(toks):
        raise _bad("Invalid filter: trailing tokens")

    def ev(n, f):
        k = n[0]
        if k == "or":
            return ev(n[1], f) or ev(n[2], f)
        if k == "and":
            return ev(n[1], f) and ev(n[2], f)
        if k == "not":
            return not ev(n[1], f)
        _, name, op, v = n
        got = _field(f, name)
        if op == ":":
            return got is not None and v.lower() in str(got).lower()
        if op == "=":
            return got is not None and str(got) == v
        if op == "!=":
            return got is None or str(got) != v
        if got is None:
            return False
        a, b = str(got), v
        try:
            a, b = float(a), float(b)
        except ValueError:
            pass
        return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    return lambda f: ev(tree, f)


# ── assembling the visible finding set ────────────────────────────────────────────────
def _all_findings(bag, project, generated):
    st = _state(bag)
    rows = [json.loads(json.dumps(f)) for f in generated] + [json.loads(json.dumps(f)) for f in st["custom"].values() if f["parent"].split("/sources/")[0].endswith(project)]
    mutes = [(k, compile_filter(m["filter"])) for k, m in sorted(st["mutes"].items())]
    for f in rows:
        o = st["overlay"].get(f["name"]) or {}
        if o.get("state"):
            f["state"] = o["state"]
        if o.get("marks"):
            f["securityMarks"]["marks"] = dict(o["marks"])
        if o.get("mute"):
            f["mute"], f["muteInitiator"], f["muteUpdateTime"] = o["mute"], o.get("muteInitiator", ""), o.get("updated", "")
        elif f["mute"] == "UNDEFINED":
            for k, fn in mutes:
                try:
                    hit = fn(f)
                except _E:
                    hit = False
                if hit:
                    f["mute"], f["muteInitiator"], f["muteUpdateTime"] = "MUTED", f"{k}", st["mutes"][k].get("updateTime", "")
                    break
    return rows


def _parent(path):
    m = re.match(r"^/v2/((?:projects|organizations|folders)/[^/]+)(?:/locations/([^/]+))?(/.*)?$", path)
    if not m:
        raise _nf(f"Unknown path {path}")
    return m.group(1), m.group(2), m.group(3) or ""


def _proj_of(parent, default):
    return parent.split("/", 1)[1] if parent.startswith("projects/") else default


def _src_view(parent, sid, st):
    if sid in BUILTIN:
        n, d = BUILTIN[sid]
        return {"name": f"{parent}/sources/{sid}", "displayName": n, "description": d, "canonicalName": f"{parent}/sources/{sid}"}
    s = st["sources"].get(f"{parent}/sources/{sid}")
    if not s:
        raise _nf(f"Source {parent}/sources/{sid} not found")
    return s


def _page(items, q, default=10):
    try:
        size = int(q.get("pageSize") or default)
    except ValueError:
        raise _bad("pageSize must be an integer")
    if size < 0 or size > 1000:
        raise _bad("pageSize must be between 0 and 1000")
    size = size or default
    try:
        start = int(base64.urlsafe_b64decode((q.get("pageToken") or "MA==").encode()).decode())
    except Exception:
        raise _bad("Invalid pageToken")
    nxt = base64.urlsafe_b64encode(str(start + size).encode()).decode() if start + size < len(items) else ""
    return items[start:start + size], nxt


def _sort(rows, order):
    if not order:
        return rows
    for part in reversed([p.strip() for p in order.split(",") if p.strip()]):
        bits = part.split()
        field, desc = bits[0], len(bits) > 1 and bits[1].lower() == "desc"
        key = {"event_time": "eventTime", "create_time": "createTime", "resource_name": "resourceName", "category": "category",
               "severity": "severity", "state": "state", "name": "name"}.get(field)
        if not key:
            raise _bad(f"Invalid orderBy field '{field}'")
        rows = sorted(rows, key=lambda f: str(f.get(key, "")), reverse=desc)
    return rows


# ── dispatch ──────────────────────────────────────────────────────────────────────────
def dispatch(bag, method, path, query, body, ctx):
    """ctx: generated(project)->[posture rows], default_project, publish(topic, data_b64, attrs)->bool, topic_exists(topic)->bool."""
    st = _state(bag)
    method = method.upper()
    path = path.split("?", 1)[0]
    try:
        payload = json.loads(body.decode() or "{}") if body else {}
    except ValueError:
        return Resp(400, {"error": {"code": 400, "message": "Invalid JSON payload", "status": "INVALID_ARGUMENT"}})
    if not isinstance(payload, dict):
        payload = {}
    try:
        out = _route(bag, st, method, path, query or {}, payload, ctx)
        if method != "GET":
            sync_notifications(bag, ctx)
        return Resp(200, out)
    except _E as e:
        return Resp(e.status, {"error": {"code": e.status, "message": e.msg, "status": e.code}})


def _route(bag, st, method, path, q, p, ctx):
    parent, loc, rest = _parent(path)
    project = _proj_of(parent, ctx["default_project"])
    seg = [s for s in rest.split("/") if s]
    # sources
    if seg[:1] == ["sources"] or (seg and seg[0].startswith("sources")):
        if seg == ["sources"]:
            if method == "GET":
                items = [_src_view(parent, sid, st) for sid in BUILTIN] + [s for k, s in sorted(st["sources"].items()) if k.startswith(parent + "/sources/")]
                page, nxt = _page(items, q)
                return {"sources": page, "nextPageToken": nxt}
            if method == "POST":
                dn = p.get("displayName") or ""
                if not (1 <= len(dn) <= 64):
                    raise _bad("Source displayName must be 1-64 characters")
                if any(s["displayName"] == dn for k, s in st["sources"].items() if k.startswith(parent + "/sources/")) or dn in [b[0] for b in BUILTIN.values()]:
                    raise _E(409, "ALREADY_EXISTS", f"Source with display name '{dn}' already exists")
                sid = str(int(uuid.uuid4().int % 10 ** 16)).zfill(16)
                s = {"name": f"{parent}/sources/{sid}", "displayName": dn, "description": p.get("description", ""), "canonicalName": f"{parent}/sources/{sid}"}
                st["sources"][s["name"]] = s
                return s
            raise _E(405, "UNIMPLEMENTED", "Method not allowed")
        sid = seg[1] if len(seg) > 1 else ""
        rest2 = seg[2:]
        if not rest2 or rest2[0].startswith(":"):
            pass
        if len(seg) == 2:
            if method == "GET":
                return _src_view(parent, sid, st)
            if method == "PATCH":
                if sid in BUILTIN:
                    raise _E(403, "PERMISSION_DENIED", "Google-owned sources cannot be modified")
                s = _src_view(parent, sid, st)
                for k in (q.get("updateMask") or "displayName,description").split(","):
                    if k in ("displayName", "description") and k in p:
                        s[k] = p[k]
                return s
        if len(seg) >= 3 and seg[2].split(":")[0] == "findings":
            return _findings(bag, st, method, parent, project, sid, seg[2:], q, p, ctx)
    if seg[:1] == ["findings"] or (seg and seg[0].split(":")[0] == "findings"):
        return _findings(bag, st, method, parent, project, "-", seg, q, p, ctx)
    if seg[:1] == ["muteConfigs"]:
        return _mutes(st, method, parent, loc, seg[1:], q, p)
    if seg[:1] == ["notificationConfigs"]:
        return _notifs(bag, st, method, parent, loc, seg[1:], q, p, ctx)
    raise _nf(f"Unknown path {path}")


def _findings(bag, st, method, parent, project, sid, seg, q, p, ctx):
    # seg[0] = "findings" or "findings:group"/"findings:bulkMute"; seg[1] = finding id (maybe with :verb)
    head = seg[0]
    verb = head.split(":", 1)[1] if ":" in head else None
    generated = generate(project, ctx["generated"](project))
    if sid != "-" and sid not in BUILTIN and f"{parent}/sources/{sid}" not in st["sources"]:
        raise _nf(f"Source {parent}/sources/{sid} not found")
    rows = [f for f in _all_findings(bag, project, generated) if sid == "-" or f["parent"].endswith("/sources/" + sid)]
    if verb == "group" and method == "POST":
        fn = compile_filter(p.get("filter"))
        rows = [f for f in rows if fn(f)]
        keys = [k.strip() for k in (p.get("groupBy") or "").split(",") if k.strip()]
        if not keys:
            raise _bad("groupBy is required")
        groups = {}
        for f in rows:
            g = tuple((k, _field(f, k)) for k in keys)
            groups[g] = groups.get(g, 0) + 1
        res = [{"properties": {k: v for k, v in g}, "count": str(n)} for g, n in sorted(groups.items(), key=lambda kv: -kv[1])]
        page, nxt = _page(res, p, 10)
        return {"groupByResults": page, "nextPageToken": nxt, "totalSize": len(res)}
    if verb == "bulkMute" and method == "POST":
        ms = p.get("muteState") or "MUTED"
        if ms not in MUTES:
            raise _bad("Invalid muteState")
        fn = compile_filter(p.get("filter"))
        n = 0
        for f in rows:
            if fn(f):
                st["overlay"].setdefault(f["name"], {}).update({"mute": ms, "muteInitiator": "bulk-mute", "updated": _now()})
                n += 1
        return {"done": True, "name": f"{parent}/operations/bulk-mute-{uuid.uuid4().hex[:12]}", "response": {"@type": "type.googleapis.com/google.protobuf.Empty"}}
    if len(seg) == 1:
        if method == "GET":
            fn = compile_filter(q.get("filter"))
            rows = _sort([f for f in rows if fn(f)], q.get("orderBy"))
            page, nxt = _page(rows, q)
            return {"listFindingsResults": [{"finding": f, "resource": {"name": f["resourceName"], "projectDisplayName": project, "type": _rtype(f["resourceName"])}} for f in page],
                    "nextPageToken": nxt, "totalSize": len(rows)}
        if method == "POST":
            return _create_finding(st, parent, sid, q, p)
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    fid_raw = seg[1]
    fid, _, fverb = fid_raw.partition(":")
    name_tail = f"/sources/{sid}/findings/{fid}"
    cur = next((f for f in rows if f["name"].endswith(name_tail)), None) if sid != "-" else None
    if len(seg) == 3 and seg[2] == "securityMarks" and method == "PATCH":
        if cur is None:
            raise _nf("Finding not found")
        marks = p.get("marks") or {}
        o = st["overlay"].setdefault(cur["name"], {})
        m = dict(o.get("marks") or cur["securityMarks"]["marks"])
        mask = (q.get("updateMask") or "").strip()
        if mask:
            for k in mask.split(","):
                k = k.strip().replace("marks.", "")
                if k in marks:
                    m[k] = marks[k]
                else:
                    m.pop(k, None)
        else:
            m = dict(marks)
        o["marks"] = m
        return {"name": cur["name"] + "/securityMarks", "marks": m}
    if cur is None:
        raise _nf(f"Finding {parent}/sources/{sid}/findings/{fid} not found")
    if fverb == "setState" and method == "POST":
        if p.get("state") not in STATES:
            raise _bad("state must be ACTIVE or INACTIVE")
        st["overlay"].setdefault(cur["name"], {})["state"] = p["state"]
        cur["state"] = p["state"]
        return cur
    if fverb == "setMute" and method == "POST":
        if p.get("mute") not in MUTES:
            raise _bad("mute must be MUTED, UNMUTED or UNDEFINED")
        st["overlay"].setdefault(cur["name"], {}).update({"mute": p["mute"], "muteInitiator": "operator", "updated": _now()})
        cur["mute"] = p["mute"]
        return cur
    if method == "GET" and not fverb:
        return cur
    if method == "PATCH" and not fverb:
        if cur["name"] not in st["custom"]:
            raise _E(403, "PERMISSION_DENIED", "Findings of Google-owned sources are read-only; use setState/setMute/securityMarks")
        c = st["custom"][cur["name"]]
        for k in (q.get("updateMask") or ",".join(p.keys())).split(","):
            if k in ("state", "severity", "category", "resourceName", "description", "externalUri", "sourceProperties", "findingClass", "eventTime"):
                if k in p:
                    c[k] = p[k]
        _check_finding(c)
        return c
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


def _rtype(res):
    m = re.search(r"//([a-z]+)\.googleapis\.com/", res or "")
    return {"compute": "google.compute.Instance", "storage": "google.cloud.storage.Bucket", "artifactregistry": "google.cloud.artifactregistry.DockerImage"}.get(m.group(1) if m else "", "google.cloud.resource")


def _check_finding(f):
    if f.get("state") not in STATES:
        raise _bad("Finding.state must be ACTIVE or INACTIVE")
    if not f.get("category") or len(f["category"]) > 128:
        raise _bad("Finding.category is required (max 128 characters)")
    if not f.get("resourceName"):
        raise _bad("Finding.resourceName is required")
    if f.get("severity", "SEVERITY_UNSPECIFIED") not in SEVS:
        raise _bad("Invalid Finding.severity")
    if f.get("findingClass", "FINDING_CLASS_UNSPECIFIED") not in CLASSES + ("FINDING_CLASS_UNSPECIFIED",):
        raise _bad("Invalid Finding.findingClass")


def _create_finding(st, parent, sid, q, p):
    if sid == "-":
        raise _bad("A source id is required to create a finding")
    if sid in BUILTIN:
        raise _E(403, "PERMISSION_DENIED", "Findings cannot be created in Google-owned sources")
    _src_view(parent, sid, st)
    fid = q.get("findingId") or ""
    if not re.match(r"^[a-zA-Z0-9]{1,32}$", fid):
        raise _bad("findingId must be 1-32 alphanumeric characters")
    name = f"{parent}/sources/{sid}/findings/{fid}"
    if name in st["custom"]:
        raise _E(409, "ALREADY_EXISTS", f"Finding {name} already exists")
    if not p.get("eventTime"):
        raise _bad("Finding.eventTime is required")
    f = {"name": name, "canonicalName": name, "parent": f"{parent}/sources/{sid}", "resourceName": p.get("resourceName", ""),
         "state": p.get("state", ""), "category": p.get("category", ""), "externalUri": p.get("externalUri", ""),
         "sourceProperties": p.get("sourceProperties") or {}, "securityMarks": {"name": name + "/securityMarks", "marks": {}},
         "eventTime": p["eventTime"], "createTime": _now(), "severity": p.get("severity", "SEVERITY_UNSPECIFIED"), "mute": "UNDEFINED",
         "findingClass": p.get("findingClass", "FINDING_CLASS_UNSPECIFIED"), "description": p.get("description", "")}
    _check_finding(f)
    st["custom"][name] = f
    return f


def _cfg_name(parent, loc, kind, cid):
    return f"{parent}/locations/{loc or 'global'}/{kind}/{cid}"


def _mutes(st, method, parent, loc, seg, q, p):
    if not seg:
        if method == "GET":
            items = [m for k, m in sorted(st["mutes"].items()) if k.startswith(parent + "/")]
            page, nxt = _page(items, q)
            return {"muteConfigs": page, "nextPageToken": nxt}
        if method == "POST":
            cid = q.get("muteConfigId") or ""
            if not re.match(r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", cid):
                raise _bad("muteConfigId must be 1-63 characters: lowercase letters, digits, hyphens; start with a letter")
            name = _cfg_name(parent, loc, "muteConfigs", cid)
            if name in st["mutes"]:
                raise _E(409, "ALREADY_EXISTS", f"MuteConfig {name} already exists")
            compile_filter(p.get("filter"))
            if not p.get("filter"):
                raise _bad("MuteConfig.filter is required")
            t = p.get("type", "STATIC")
            if t not in ("STATIC", "DYNAMIC"):
                raise _bad("type must be STATIC or DYNAMIC")
            m = {"name": name, "displayName": p.get("displayName", ""), "description": p.get("description", ""), "filter": p["filter"], "type": t,
                 "createTime": _now(), "updateTime": _now(), "mostRecentEditor": "user@vyomi.local"}
            st["mutes"][name] = m
            return m
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    name = _cfg_name(parent, loc, "muteConfigs", seg[0])
    m = st["mutes"].get(name)
    if not m:
        raise _nf(f"MuteConfig {name} not found")
    if method == "GET":
        return m
    if method == "DELETE":
        st["mutes"].pop(name)
        return {}
    if method == "PATCH":
        if "filter" in p:
            compile_filter(p["filter"])
        for k in ("description", "filter", "displayName"):
            if k in p:
                m[k] = p[k]
        m["updateTime"] = _now()
        return m
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


def _notifs(bag, st, method, parent, loc, seg, q, p, ctx):
    if not seg:
        if method == "GET":
            items = [m for k, m in sorted(st["notifs"].items()) if k.startswith(parent + "/")]
            page, nxt = _page(items, q)
            return {"notificationConfigs": page, "nextPageToken": nxt}
        if method == "POST":
            cid = q.get("configId") or ""
            if not re.match(r"^[a-zA-Z0-9_-]{1,128}$", cid):
                raise _bad("configId must be 1-128 characters: letters, digits, '-' and '_'")
            name = _cfg_name(parent, loc, "notificationConfigs", cid)
            if name in st["notifs"]:
                raise _E(409, "ALREADY_EXISTS", f"NotificationConfig {name} already exists")
            return _put_notif(st, name, p, ctx, new=True)
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    name = _cfg_name(parent, loc, "notificationConfigs", seg[0])
    n = st["notifs"].get(name)
    if not n:
        raise _nf(f"NotificationConfig {name} not found")
    if method == "GET":
        return n
    if method == "DELETE":
        st["notifs"].pop(name)
        st["seen"].pop(name, None)
        return {}
    if method == "PATCH":
        return _put_notif(st, name, dict(n, **p), ctx, new=False)
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


def _put_notif(st, name, p, ctx, new):
    topic = p.get("pubsubTopic") or ""
    if not re.match(r"^projects/[^/]+/topics/[^/]+$", topic):
        raise _bad("pubsubTopic must be projects/{project}/topics/{topic}")
    if not ctx["topic_exists"](topic):
        raise _bad(f"Pub/Sub topic {topic} does not exist")
    flt = ((p.get("streamingConfig") or {}).get("filter"))
    if flt is None:
        raise _bad("streamingConfig.filter is required")
    compile_filter(flt)
    n = {"name": name, "description": p.get("description", ""), "pubsubTopic": topic,
         "serviceAccount": f"service-org-{_projnum(name)}@gcp-sa-scc-notification.iam.gserviceaccount.com", "streamingConfig": {"filter": flt}}
    st["notifs"][name] = n
    if new:
        # a new config only notifies about findings that appear (or change) AFTER it was created
        st["seen"][name] = {"__baseline__": True}
    return n


def sync_notifications(bag, ctx):
    """Publish every finding that is new or changed since the last sync to the Pub/Sub topic of each matching config. Returns messages sent."""
    st = _state(bag)
    if not st["notifs"]:
        return 0
    sent = 0
    for name, n in sorted(st["notifs"].items()):
        parent = name.split("/locations/")[0]
        project = _proj_of(parent, ctx["default_project"])
        rows = _all_findings(bag, project, generate(project, ctx["generated"](project)))
        fn = compile_filter(n["streamingConfig"]["filter"])
        seen = st["seen"].setdefault(name, {})
        baseline = seen.pop("__baseline__", False)
        for f in rows:
            if not fn(f):
                continue
            sig = hashlib.sha1(json.dumps([f["state"], f["mute"], f["severity"], f["eventTime"], f["securityMarks"]["marks"]], sort_keys=True).encode()).hexdigest()
            if seen.get(f["name"]) == sig:
                continue
            seen[f["name"]] = sig
            if baseline:
                continue
            msg = {"notificationConfigName": name, "finding": f, "resource": {"name": f["resourceName"], "projectDisplayName": project}}
            if ctx["publish"](n["pubsubTopic"], base64.b64encode(json.dumps(msg).encode()).decode(), {"configName": name}):
                sent += 1
                st["sent"].append({"config": name, "finding": f["name"], "at": _now()})
    del st["sent"][:-200]
    return sent
