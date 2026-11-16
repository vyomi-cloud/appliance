# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""X-Ray control-plane surface beyond the trace APIs (groups, sampling rules, encryption, tags, resource policies, trace-segment
destination, indexing rules, insights, GetTraceGraph, time-series statistics, trace retrieval) over the same trace bag as core/xray_core.

Real: groups and sampling rules are stored and returned with X-Ray's validation (unique names, rule priority, Default rule is
protected); GetTraceGraph / GetTimeSeriesServiceStatistics / ListRetrievedTraces are computed from the stored traces;
UpdateTraceSegmentDestination switches XRay <-> CloudWatchLogs (what AgentCore Observability / Transaction Search enables).
Not real: no insights generation (GetInsight* answer ResourceNotFound / empty), no adaptive sampling, no KMS key use.
State: `store.xray_meta` next to `store.xray_traces`.
"""
from __future__ import annotations

import json
import secrets
import time

_ACCT, _REGION = "000000000000", "us-east-1"


def _meta(store) -> dict:
    m = getattr(store, "xray_meta", None)
    if not isinstance(m, dict):
        m = {}
        store.xray_meta = m
    m.setdefault("groups", {})
    m.setdefault("rules", {})
    m.setdefault("tags", {})
    m.setdefault("policies", {})
    m.setdefault("indexing", {"Default": {"Name": "Default", "ModifiedAt": time.time(), "Rule": {"Probabilistic": {"DesiredSamplingPercentage": 1.0}}}})
    m.setdefault("enc", {"Type": "NONE", "Status": "ACTIVE"})
    m.setdefault("dest", {"Destination": "XRay", "Status": "ACTIVE"})
    m.setdefault("retrievals", {})
    if "Default" not in m["rules"]:
        m["rules"]["Default"] = _rule_rec({"RuleName": "Default", "Priority": 10000, "FixedRate": 0.05, "ReservoirSize": 1, "ServiceName": "*",
                                           "ServiceType": "*", "Host": "*", "HTTPMethod": "*", "URLPath": "*", "ResourceARN": "*", "Version": 1})
    return m


class _E(Exception):
    def __init__(self, status, code, msg):
        self.status, self.code, self.msg = status, code, msg


def _rule_rec(r):
    r = dict(r)
    r.setdefault("RuleARN", f"arn:aws:xray:{_REGION}:{_ACCT}:sampling-rule/{r['RuleName']}")
    now = time.time()
    return {"SamplingRule": r, "CreatedAt": now, "ModifiedAt": now}


def _group_arn(n):
    return f"arn:aws:xray:{_REGION}:{_ACCT}:group/{n}/{secrets.token_hex(4)}"


def _find_group(m, b):
    n = b.get("GroupName")
    if not n and b.get("GroupARN"):
        n = next((k for k, g in m["groups"].items() if g["GroupARN"] == b["GroupARN"]), None)
    g = m["groups"].get(n or "")
    if g is None:
        raise _E(400, "InvalidRequestException", "Group not found")
    return g


def _create_group(st, m, b):
    n = b.get("GroupName")
    if not n or len(n) > 32:
        raise _E(400, "InvalidRequestException", "GroupName is required (max 32 characters)")
    if n in m["groups"]:
        raise _E(400, "InvalidRequestException", "Group already exists")
    g = {"GroupName": n, "GroupARN": _group_arn(n), "FilterExpression": b.get("FilterExpression", ""),
         "InsightsConfiguration": b.get("InsightsConfiguration") or {"InsightsEnabled": False, "NotificationsEnabled": False}}
    m["groups"][n] = g
    if b.get("Tags"):
        m["tags"][g["GroupARN"]] = {t["Key"]: t["Value"] for t in b["Tags"]}
    return {"Group": g}


def _update_group(st, m, b):
    g = _find_group(m, b)
    for k in ("FilterExpression", "InsightsConfiguration"):
        if k in b:
            g[k] = b[k]
    return {"Group": g}


def _delete_group(st, m, b):
    g = _find_group(m, b)
    m["groups"].pop(g["GroupName"])
    return {}


def _create_rule(st, m, b):
    r = dict(b.get("SamplingRule") or {})
    for k in ("RuleName", "Priority", "FixedRate", "ReservoirSize", "ServiceName", "ServiceType", "Host", "HTTPMethod", "URLPath", "ResourceARN", "Version"):
        if r.get(k) in (None, ""):
            raise _E(400, "InvalidRequestException", f"SamplingRule.{k} is required")
    if r["RuleName"] in m["rules"]:
        raise _E(400, "RuleLimitExceededException", "Rule already exists")
    if not 1 <= int(r["Priority"]) <= 9999:
        raise _E(400, "InvalidRequestException", "Priority must be between 1 and 9999")
    rec = _rule_rec(r)
    m["rules"][r["RuleName"]] = rec
    return {"SamplingRuleRecord": rec}


def _rule_key(m, b, k_name="RuleName", k_arn="RuleARN"):
    n = b.get(k_name) or next((k for k, r in m["rules"].items() if r["SamplingRule"]["RuleARN"] == b.get(k_arn)), None)
    if n not in m["rules"]:
        raise _E(400, "InvalidRequestException", "Rule not found")
    return n


def _update_rule(st, m, b):
    u = b.get("SamplingRuleUpdate") or {}
    n = _rule_key(m, u)
    rec = m["rules"][n]
    for k, v in u.items():
        if k not in ("RuleName", "RuleARN") and v is not None:
            rec["SamplingRule"][k] = v
    rec["ModifiedAt"] = time.time()
    return {"SamplingRuleRecord": rec}


def _delete_rule(st, m, b):
    n = _rule_key(m, b)
    if n == "Default":
        raise _E(400, "InvalidRequestException", "Cannot delete the Default sampling rule")
    return {"SamplingRuleRecord": m["rules"].pop(n)}


def _tid_docs(store, tids):
    from core import xray_core
    bag = xray_core._bag(store)
    return {t: list(bag[t]["segments"].values()) for t in tids if t in bag}


def _trace_graph(store, m, b):
    from core import xray_core
    tids = b.get("TraceIds") or []
    if not tids:
        raise _E(400, "InvalidRequestException", "TraceIds is required")
    keep = _tid_docs(store, tids)
    bag = xray_core._bag(store)
    saved = dict(bag)
    try:
        for t in list(bag):
            if t not in keep:
                bag.pop(t)
        r = json.loads(xray_core._service_graph(store, {"StartTime": 0, "EndTime": time.time() + 3600})["body"])
    finally:
        bag.clear()
        bag.update(saved)
    return {"Services": r["Services"]}


def _time_series(store, m, b):
    from core import xray_core
    lo, hi = float(b.get("StartTime") or 0), float(b.get("EndTime") or time.time())
    period = int(b.get("Period") or 60)
    buckets: dict = {}
    for t in xray_core._bag(store).values():
        docs = list(t["segments"].values())
        s, e = xray_core._times(docs)
        if e < lo or s > hi:
            continue
        fault, error = xray_core._flags(docs)
        k = lo + int((s - lo) // period) * period
        bk = buckets.setdefault(k, {"ok": 0, "err": 0, "fault": 0, "total": 0, "rt": 0.0})
        bk["total"] += 1
        bk["rt"] += e - s
        bk["fault" if fault else "err" if error else "ok"] += 1
    out = []
    for k, v in sorted(buckets.items()):
        out.append({"Timestamp": k, "EdgeSummaryStatistics": {"OkCount": v["ok"], "ErrorStatistics": {"TotalCount": v["err"]},
                                                              "FaultStatistics": {"TotalCount": v["fault"]}, "TotalCount": v["total"],
                                                              "TotalResponseTime": v["rt"]},
                    "ServiceSummaryStatistics": {"OkCount": v["ok"], "ErrorStatistics": {"TotalCount": v["err"]},
                                                 "FaultStatistics": {"TotalCount": v["fault"]}, "TotalCount": v["total"],
                                                 "TotalResponseTime": v["rt"]}})
    return {"TimeSeriesServiceStatistics": out, "ContainsOldGroupVersions": False}


def _start_retrieval(store, m, b):
    tok = secrets.token_urlsafe(16)
    m["retrievals"][tok] = list(b.get("TraceIds") or [])
    return {"RetrievalToken": tok}


def _list_retrieved(store, m, b):
    tids = m["retrievals"].get(b.get("RetrievalToken"))
    if tids is None:
        raise _E(400, "InvalidRequestException", "Unknown RetrievalToken")
    out = []
    for t, docs in _tid_docs(store, tids).items():
        s, e = min(d["start_time"] for d in docs), max(d.get("end_time", d["start_time"]) for d in docs)
        out.append({"Id": t, "Duration": round(e - s, 3), "Spans": [{"Id": d["id"], "Document": json.dumps(d), "Name": d["name"]} for d in docs]})
    return {"RetrievalStatus": "COMPLETE", "TraceFormat": b.get("TraceFormat") or "XRAY", "Traces": out}


def _get_retrieved_graph(store, m, b):
    tids = m["retrievals"].get(b.get("RetrievalToken"))
    if tids is None:
        raise _E(400, "InvalidRequestException", "Unknown RetrievalToken")
    return {"RetrievalStatus": "COMPLETE", "Services": _trace_graph(store, m, {"TraceIds": tids})["Services"]}


def _tag(st, m, b):
    m["tags"].setdefault(b["ResourceARN"], {}).update({t["Key"]: t["Value"] for t in b.get("Tags") or []})
    return {}


def _untag(st, m, b):
    for k in b.get("TagKeys") or []:
        m["tags"].get(b["ResourceARN"], {}).pop(k, None)
    return {}


def _put_policy(st, m, b):
    n = b.get("PolicyName")
    if not n or not b.get("PolicyDocument"):
        raise _E(400, "InvalidRequestException", "PolicyName and PolicyDocument are required")
    prev = m["policies"].get(n)
    rev = str(int(prev["PolicyRevisionId"]) + 1) if prev else "1"
    p = {"PolicyName": n, "PolicyDocument": b["PolicyDocument"], "PolicyRevisionId": rev, "LastUpdatedTime": time.time()}
    m["policies"][n] = p
    return {"ResourcePolicy": p}


def _del_policy(st, m, b):
    if b.get("PolicyName") not in m["policies"]:
        raise _E(400, "ResourcePolicyNotFound" if False else "InvalidPolicyRevisionIdException", "Policy not found")
    m["policies"].pop(b["PolicyName"])
    return {}


def _put_enc(st, m, b):
    if b.get("Type") not in ("NONE", "KMS"):
        raise _E(400, "InvalidRequestException", "Type must be NONE or KMS")
    m["enc"] = {"Type": b["Type"], "Status": "ACTIVE", **({"KeyId": b["KeyId"]} if b.get("KeyId") else {})}
    return {"EncryptionConfig": m["enc"]}


def _update_dest(st, m, b):
    d = b.get("Destination") or "XRay"
    if d not in ("XRay", "CloudWatchLogs"):
        raise _E(400, "InvalidRequestException", "Destination must be XRay or CloudWatchLogs")
    m["dest"] = {"Destination": d, "Status": "ACTIVE"}
    return dict(m["dest"])


def _update_indexing(st, m, b):
    n = b.get("Name")
    if not n or not isinstance(b.get("Rule"), dict):
        raise _E(400, "InvalidRequestException", "Name and Rule are required")
    m["indexing"][n] = {"Name": n, "ModifiedAt": time.time(), "Rule": b["Rule"]}
    return {"IndexingRule": m["indexing"][n]}


def _nf_insight(*_):
    raise _E(400, "InvalidRequestException", "Insight not found")


ROUTES = {
    "/CreateGroup": _create_group, "/UpdateGroup": _update_group, "/DeleteGroup": _delete_group,
    "/GetGroup": lambda st, m, b: {"Group": _find_group(m, b)},
    "/Groups": lambda st, m, b: {"Groups": [{k: g[k] for k in ("GroupName", "GroupARN", "FilterExpression", "InsightsConfiguration")} for g in m["groups"].values()]},
    "/CreateSamplingRule": _create_rule, "/UpdateSamplingRule": _update_rule, "/DeleteSamplingRule": _delete_rule,
    "/GetSamplingRules": lambda st, m, b: {"SamplingRuleRecords": sorted(m["rules"].values(), key=lambda r: r["SamplingRule"]["Priority"])},
    "/SamplingStatisticSummaries": lambda st, m, b: {"SamplingStatisticSummaries": []},
    "/TraceGraph": _trace_graph, "/TimeSeriesServiceStatistics": _time_series,
    "/StartTraceRetrieval": _start_retrieval, "/ListRetrievedTraces": _list_retrieved, "/GetRetrievedTracesGraph": _get_retrieved_graph,
    "/CancelTraceRetrieval": lambda st, m, b: m["retrievals"].pop(b.get("RetrievalToken"), None) and {} or {},
    "/TagResource": _tag, "/UntagResource": _untag,
    "/ListTagsForResource": lambda st, m, b: {"Tags": [{"Key": k, "Value": v} for k, v in m["tags"].get(b.get("ResourceARN"), {}).items()]},
    "/PutResourcePolicy": _put_policy, "/DeleteResourcePolicy": _del_policy,
    "/ListResourcePolicies": lambda st, m, b: {"ResourcePolicies": list(m["policies"].values())},
    "/EncryptionConfig": lambda st, m, b: {"EncryptionConfig": m["enc"]}, "/PutEncryptionConfig": _put_enc,
    "/GetTraceSegmentDestination": lambda st, m, b: dict(m["dest"]), "/UpdateTraceSegmentDestination": _update_dest,
    "/GetIndexingRules": lambda st, m, b: {"IndexingRules": list(m["indexing"].values())}, "/UpdateIndexingRule": _update_indexing,
    "/InsightSummaries": lambda st, m, b: {"InsightSummaries": []},
    "/Insight": _nf_insight, "/InsightEvents": _nf_insight, "/InsightImpactGraph": _nf_insight,
}


def call(store, path: str, body: dict):
    """-> (status, doc) or None when the path is not served here."""
    fn = ROUTES.get(path)
    if fn is None:
        return None
    try:
        return 200, fn(store, _meta(store), body)
    except _E as e:
        return e.status, {"__error": (e.code, e.msg)}
