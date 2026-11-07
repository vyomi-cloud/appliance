# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Security Command Center API v1 (securitycenter.googleapis.com/v1) over the SAME engine as v2 (core/gcp_scc_core).

v1 and v2 share the finding/source/mute/notification model; v1 differs in paths (no /locations/ for configs) and adds the
Asset API.  This module is a thin, honest translation layer, not a second store:
  * sources / findings / :group / :setState / :setMute / :bulkMute / securityMarks / muteConfigs / notificationConfigs
    are executed by gcp_scc_core.dispatch against the SAME persisted state the v2 wire reads (a finding muted through v1 is
    muted in v2), generated from real VM / firewall / bucket / image state;
  * assets (list / group / updateSecurityMarks / runAssetDiscovery) are derived from the live Compute, Cloud Storage,
    firewall and Cloud Run stores; marks persist in the SCC state;
  * `name` fields come back in v1 form (muteConfigs/notificationConfigs without /locations/global).
Everything else in v1 (custom modules, BigQuery exports, resource value configs, simulations ...) is served by
core/gcp_wire_ext's schema-driven store.
"""
from __future__ import annotations

import json
import re
import uuid

from core import gcp_scc_core as S

_PAR = r"(?:projects|folders|organizations)/[^/:]+"
_PATH = re.compile(r"^/v1/(" + _PAR + r")(?:/locations/([^/]+)/muteConfigs(?:/[^/]+)?|(/(?:sources|findings|assets|muteConfigs|notificationConfigs)(?:[/:][^?]*)?|:(?:runAssetDiscovery|groupAssets|listAssets)))$")


def handles(path):
    return bool(_PATH.match(path.split("?", 1)[0]))


class Resp:
    def __init__(self, status, obj):
        self.status, self.headers, self.media_type = status, {}, "application/json"
        self.body = json.dumps(obj).encode()


def _assets(parent, project, ctx):
    """Asset resources derived from live state: {name -> v1 Asset}."""
    out = {}
    num = S._projnum(project)
    for full, i in sorted((ctx["instances"] or {}).items()):
        if not full.startswith("projects/%s/zones/" % project):
            continue
        res = "//compute.googleapis.com/" + full
        out[res] = ("google.compute.Instance", full.split("/")[3], i.get("name", ""), i, i.get("labels") or {})
    for name, b in sorted((ctx["buckets"] or {}).items()):
        out["//storage.googleapis.com/" + name] = ("google.cloud.storage.Bucket", "", name, {"name": name, "location": b.get("location", "US"), "storageClass": b.get("storageClass", "STANDARD")}, b.get("labels") or {})
    for f in ctx["firewalls"] or []:
        out["//compute.googleapis.com/projects/%s/global/firewalls/%s" % (project, f.get("name"))] = ("google.compute.Firewall", "", f.get("name"), {k: f.get(k) for k in ("name", "direction", "priority", "allowed", "sourceRanges")}, {})
    for full, s in sorted((ctx["run_services"] or {}).items()):
        if full.startswith("projects/%s/" % project):
            out["//run.googleapis.com/" + full] = ("run.googleapis.com/Service", full.split("/")[3], full.rsplit("/", 1)[-1], {"name": full, "uri": s.get("uri")}, s.get("labels") or {})
    rows = []
    for res, (rtype, _loc, dn, props, labels) in out.items():
        aid = str(int(S.hashlib.sha1(res.encode()).hexdigest()[:15], 16) % 10 ** 18)
        rows.append({"name": "%s/assets/%s" % (parent, aid), "canonicalName": "projects/%s/assets/%s" % (num, aid),
                     "securityCenterProperties": {"resourceName": res, "resourceType": rtype, "resourceParent": "//cloudresourcemanager.googleapis.com/projects/%s" % num,
                                                  "resourceProject": "//cloudresourcemanager.googleapis.com/projects/%s" % num, "resourceDisplayName": dn,
                                                  "resourceOwners": ["user:admin@vyomi.cloud"]},
                     "resourceProperties": {k: (v if isinstance(v, (str, int, float, bool)) else json.dumps(v)) for k, v in (props or {}).items()},
                     "securityMarks": {"name": "%s/assets/%s/securityMarks" % (parent, aid), "marks": {}},
                     "createTime": (props or {}).get("creationTimestamp") or S._now(), "updateTime": S._now(), "labels": labels})
    return rows


def _asset_flat(a):
    return {"name": a["name"], "securityCenterProperties": a["securityCenterProperties"], "resourceProperties": a["resourceProperties"],
            "securityMarks": a["securityMarks"], "createTime": a["createTime"], "updateTime": a["updateTime"],
            "resourceType": a["securityCenterProperties"]["resourceType"]}


def dispatch(bag, method, path, query, body, ctx):
    """ctx = the scc ctx (generated/topic_exists/publish/default_project) + instances/buckets/firewalls/run_services."""
    method = method.upper()
    p = path.split("?", 1)[0]
    q = dict(query or {})
    m = _PATH.match(p)
    if not m:
        return Resp(404, {"error": {"code": 404, "message": "Unknown path %s" % path, "status": "NOT_FOUND"}})
    parent = m.group(1)
    project = S._proj_of(parent, ctx["default_project"])
    tail = m.group(3) or ""
    try:
        payload = json.loads(body.decode() or "{}") if body else {}
    except ValueError:
        return Resp(400, {"error": {"code": 400, "message": "Invalid JSON payload", "status": "INVALID_ARGUMENT"}})
    st = S._state(bag)
    # ── assets (v1 only) ────────────────────────────────────────────────────────────
    if tail.startswith("/assets") or tail in (":groupAssets", ":listAssets", ":runAssetDiscovery"):
        try:
            assets = _assets(parent, project, ctx)
            marks = st.setdefault("asset_marks", {})
            for a in assets:
                if a["name"] in marks:
                    a["securityMarks"]["marks"] = dict(marks[a["name"]])
            if tail in (":runAssetDiscovery", "/assets:runDiscovery") and method == "POST":
                oid = "%s/operations/asset-discovery-%s" % (parent, uuid.uuid4().hex[:12])
                return Resp(200, {"name": oid, "done": True, "metadata": {"@type": "type.googleapis.com/google.protobuf.Empty"}, "response": {"@type": "type.googleapis.com/google.protobuf.Empty"}})
            if tail in ("/assets", ":listAssets") and method in ("GET", "POST"):
                src = payload if method == "POST" else q
                fn = S.compile_filter(src.get("filter") or q.get("filter"))
                rows = [a for a in assets if fn(_asset_flat(a))]
                ob = src.get("orderBy") or q.get("orderBy") or ""
                if ob:
                    k, _, d = ob.partition(" ")
                    rows.sort(key=lambda a: str(S._field(_asset_flat(a), k)), reverse=d.lower() == "desc")
                page, nxt = S._page(rows, dict(q, **{k: v for k, v in src.items() if k in ("pageSize", "pageToken")}))
                return Resp(200, {"listAssetsResults": [{"asset": a, "stateChange": "UNUSED"} for a in page], "readTime": S._now(), "nextPageToken": nxt, "totalSize": len(rows)})
            if tail in ("/assets:group", ":groupAssets") and method == "POST":
                fn = S.compile_filter(payload.get("filter"))
                keys = [k.strip() for k in (payload.get("groupBy") or "").split(",") if k.strip()]
                if not keys:
                    raise S._bad("groupBy is required")
                groups = {}
                for a in assets:
                    flat = _asset_flat(a)
                    if not fn(flat):
                        continue
                    g = tuple((k, S._field(flat, k)) for k in keys)
                    groups[g] = groups.get(g, 0) + 1
                res = [{"properties": {k: v for k, v in g}, "count": str(n)} for g, n in sorted(groups.items(), key=lambda kv: -kv[1])]
                page, nxt = S._page(res, payload, 10)
                return Resp(200, {"groupByResults": page, "readTime": S._now(), "nextPageToken": nxt, "totalSize": len(res)})
            am = re.match(r"^/assets/([^/:]+)(?::updateSecurityMarks|/securityMarks)?$", tail)
            if am and method in ("PATCH", "POST"):
                cur = next((a for a in assets if a["name"].endswith("/assets/" + am.group(1))), None)
                if cur is None:
                    raise S._nf("Asset %s/assets/%s not found" % (parent, am.group(1)))
                new = payload.get("marks") or {}
                mk = dict(marks.get(cur["name"], {}))
                mask = (q.get("updateMask") or "").strip()
                if mask:
                    for k in mask.split(","):
                        k = k.strip().replace("marks.", "")
                        if k in new:
                            mk[k] = new[k]
                        else:
                            mk.pop(k, None)
                else:
                    mk = dict(new)
                marks[cur["name"]] = mk
                return Resp(200, {"name": cur["name"] + "/securityMarks", "marks": mk})
            if am and method == "GET":
                cur = next((a for a in assets if a["name"].endswith("/assets/" + am.group(1))), None)
                if cur is None:
                    raise S._nf("Asset not found")
                return Resp(200, cur)
        except S._E as e:
            return Resp(e.status, {"error": {"code": e.status, "message": e.msg, "status": e.code}})
        return Resp(404, {"error": {"code": 404, "message": "Unknown path %s" % path, "status": "NOT_FOUND"}})
    # ── everything else: the v2 engine ──────────────────────────────────────────────
    v2 = "/v2/" + p[len("/v1/"):]
    loc = m.group(2)
    if re.search(r"/(muteConfigs|notificationConfigs)", v2) and "/locations/" not in v2:
        v2 = re.sub(r"^(/v2/" + _PAR + r")/", r"\1/", v2)   # v2 defaults the config location to global
    r = S.dispatch(bag, method, v2, q, body, ctx)
    txt = r.body.decode()
    txt = txt.replace("/locations/global/muteConfigs/", "/muteConfigs/").replace("/locations/global/notificationConfigs/", "/notificationConfigs/") if not loc else txt
    r.body = txt.encode()
    return r
