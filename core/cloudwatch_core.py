"""CloudWatch core — substrate-independent metrics / alarms / dashboards on the
NATIVE Amazon CloudWatch wire, so an unmodified boto3 / aws-sdk-go-v2 / AWS SDK for
Java v2 / aws-cli works with only the endpoint changed.

All three protocols the real service speaks are served from one engine:
  * smithy-rpc-v2-cbor — POST /service/GraniteServiceVersion20100801/operation/<Op>
    (what current SDKs and aws-cli v2 use by default)
  * JSON 1.0           — X-Amz-Target: GraniteServiceVersion20100801.<Op>
  * Query              — form-encoded `Action=<Op>&...`, XML responses
    (http://monitoring.amazonaws.com/doc/2010-08-01/)

NO fastapi / boto3 / socket imports (stdlib only) → loads under Pyodide, and the very
same file is what the offline appliance and Nano run. State lives on a `CloudWatchStore`
seam (in-memory; `PersistentCloudWatchStore` in core/persistent_store.py write-throughs
to SQLite through `persist()`).

Modeled:
  * metrics — PutMetricData (Value / Values+Counts / StatisticValues, dimensions, units,
    timestamp window), GetMetricStatistics (Statistics + percentiles), GetMetricData
    (MetricStat + metric-math expressions), ListMetrics (filters, RecentlyActive).
  * alarms — metric alarms (single metric or metric math), composite alarms (AlarmRule
    grammar), state evaluation on every PutMetricData (M-of-N datapoints, TreatMissingData),
    SetAlarmState, history, enable/disable actions, tags.
  * dashboards, anomaly detectors, Contributor Insights rules, metric streams, tags.
"""
from __future__ import annotations

import ast
import base64
import json
import math
import re
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

CW_NS = "http://monitoring.amazonaws.com/doc/2010-08-01/"
TARGET_PREFIX = "GraniteServiceVersion20100801"
REGION = "us-east-1"
ACCOUNT_ID = "123456789012"

UNITS = {"Seconds", "Microseconds", "Milliseconds", "Bytes", "Kilobytes", "Megabytes", "Gigabytes", "Terabytes",
         "Bits", "Kilobits", "Megabits", "Gigabits", "Terabits", "Percent", "Count", "Bytes/Second",
         "Kilobytes/Second", "Megabytes/Second", "Gigabytes/Second", "Terabytes/Second", "Bits/Second",
         "Kilobits/Second", "Megabits/Second", "Gigabits/Second", "Terabits/Second", "Count/Second", "None"}
COMPARISONS = {"GreaterThanOrEqualToThreshold": ">=", "GreaterThanThreshold": ">", "LessThanThreshold": "<",
               "LessThanOrEqualToThreshold": "<=", "LessThanLowerOrGreaterThanUpperThreshold": "band",
               "LessThanLowerThreshold": "<", "GreaterThanUpperThreshold": ">"}
STATS = {"SampleCount", "Average", "Sum", "Minimum", "Maximum"}
ALARM_STATES = ("OK", "ALARM", "INSUFFICIENT_DATA")
MAX_ALARMS = 5000
KEEP_POINTS = 20000          # per series
GMS_MAX_DATAPOINTS = 1440    # GetMetricStatistics limit


# ── responses & errors ─────────────────────────────────────────────────────
@dataclass
class CwResponse:
    status: int = 200
    body: str = ""
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class Ts(float):
    """An epoch-seconds timestamp: ISO-8601 in Query XML, number (CBOR tag 1) elsewhere."""


class XMap(dict):
    """A map member — rendered as <entry><key/><value/></entry> in Query XML."""


# error shape -> (wire code, http status)
ERRORS = {
    "ConcurrentModificationException": ("ConcurrentModificationException", 429),
    "ConflictException": ("ConflictException", 409),
    "DashboardInvalidInputError": ("InvalidParameterInput", 400),
    "DashboardNotFoundError": ("ResourceNotFound", 404),
    "InternalServiceFault": ("InternalServiceError", 500),
    "InvalidFormatFault": ("InvalidFormat", 400),
    "InvalidNextToken": ("InvalidNextToken", 400),
    "InvalidParameterCombinationException": ("InvalidParameterCombination", 400),
    "InvalidParameterValueException": ("InvalidParameterValue", 400),
    "LimitExceededException": ("LimitExceededException", 400),
    "LimitExceededFault": ("LimitExceeded", 400),
    "MissingRequiredParameterException": ("MissingParameter", 400),
    "ResourceConflict": ("ResourceConflict", 409),
    "ResourceNotFound": ("ResourceNotFound", 404),
    "ResourceNotFoundException": ("ResourceNotFoundException", 404),
    "ValidationException": ("ValidationError", 400),
}


class CwError(Exception):
    def __init__(self, shape: str, message: str, extra: dict | None = None) -> None:
        super().__init__(f"{shape}: {message}")
        self.shape, self.message, self.extra = shape, message, extra or {}
        self.code, self.status = ERRORS[shape]


def _invalid(msg: str) -> CwError:
    return CwError("InvalidParameterValueException", msg)


def _missing(name: str) -> CwError:
    return CwError("MissingRequiredParameterException", f"The parameter {name} is required.")


def _combo(msg: str) -> CwError:
    return CwError("InvalidParameterCombinationException", msg)


def _rid() -> str:
    return str(uuid.uuid4())


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── the store seam ─────────────────────────────────────────────────────────
class CloudWatchStore:
    def __init__(self, account_id: str = ACCOUNT_ID, region: str = REGION) -> None:
        self.account_id = account_id
        self.region = region
        self.metrics: dict[str, dict] = {}        # series key -> {Namespace, MetricName, Dimensions, points, unit}
        self.alarms: dict[str, dict] = {}         # name -> metric alarm record
        self.composites: dict[str, dict] = {}     # name -> composite alarm record
        self.history: list[dict] = []             # alarm history items (oldest first)
        self.dashboards: dict[str, dict] = {}
        self.tags: dict[str, dict] = {}           # resource ARN -> {key: value}
        self.anomaly: list[dict] = []
        self.insight_rules: dict[str, dict] = {}
        self.streams: dict[str, dict] = {}
        self.action_hook = None                   # optional (arn, alarm, new_state, reason) -> None

    def persist(self) -> None:
        """Flush hook (no-op in memory)."""

    # ARNs
    def alarm_arn(self, name: str) -> str:
        return f"arn:aws:cloudwatch:{self.region}:{self.account_id}:alarm:{name}"

    def rule_arn(self, name: str) -> str:
        return f"arn:aws:cloudwatch:{self.region}:{self.account_id}:insight-rule/{name}"

    def stream_arn(self, name: str) -> str:
        return f"arn:aws:cloudwatch:{self.region}:{self.account_id}:metric-stream/{name}"

    def dashboard_arn(self, name: str) -> str:
        return f"arn:aws:cloudwatch::{self.account_id}:dashboard/{name}"


# ── value coercion (Query sends strings; JSON/CBOR send typed values) ───────
def _f(v, name="value"):
    if isinstance(v, bool):
        raise _invalid(f"The value {v} for parameter {name} is invalid.")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise _invalid(f"The value {v} for parameter {name} is invalid.")
    if math.isnan(x) or math.isinf(x):
        raise _invalid(f"The value {v} for parameter {name} is invalid.")
    return x


def _i(v, name="value"):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        raise _invalid(f"The value {v} for parameter {name} is invalid.")


def _b(v, default=False):
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() == "true"
    return bool(v)


def _list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _ts(v, name="Timestamp") -> float:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s)
        except ValueError:
            pass
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.timestamp()
        except ValueError:
            pass
    raise _invalid(f"The parameter {name} is not a valid timestamp.")


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _dims(v, name="Dimensions") -> list[dict]:
    out = []
    for d in _list(v):
        if not isinstance(d, dict) or not str(d.get("Name") or "").strip():
            raise _invalid(f"The parameter {name} has a dimension without a name.")
        out.append({"Name": str(d["Name"]), "Value": str(d.get("Value", ""))})
    if len(out) > 30:
        raise _invalid(f"The parameter {name} must contain at most 30 dimensions.")
    return sorted(out, key=lambda d: d["Name"])


def _dim_key(dims: list[dict]) -> str:
    return json.dumps([[d["Name"], d["Value"]] for d in dims], separators=(",", ":"))


def _page(items: list, token, limit: int):
    start = 0
    if token:
        try:
            start = int(base64.urlsafe_b64decode(str(token).encode()).decode().split(":", 1)[1])
            if start < 0 or start > len(items):
                raise ValueError
        except Exception:
            raise CwError("InvalidNextToken", "The next token specified is invalid.")
    chunk = items[start:start + limit]
    nxt = None
    if start + limit < len(items):
        nxt = base64.urlsafe_b64encode(f"cw:{start + limit}".encode()).decode()
    return chunk, nxt


def _tag_list(v) -> dict:
    out = {}
    for t in _list(v):
        if not isinstance(t, dict) or not str(t.get("Key") or ""):
            raise _invalid("The parameter Tags contains a tag without a key.")
        out[str(t["Key"])] = str(t.get("Value", ""))
    return out


def _tags_out(d: dict) -> list[dict]:
    return [{"Key": k, "Value": v} for k, v in sorted(d.items())]


# ── metrics ────────────────────────────────────────────────────────────────
def _series(store: CloudWatchStore, ns: str, name: str, dims: list[dict], create: bool = False):
    key = f"{ns}\x1f{name}\x1f{_dim_key(dims)}"
    s = store.metrics.get(key)
    if s is None and create:
        s = store.metrics[key] = {"Namespace": ns, "MetricName": name, "Dimensions": dims, "points": [], "unit": "None", "last": 0.0}
    return s


def op_put_metric_data(store, a):
    ns = str(a.get("Namespace") or "")
    if not ns:
        raise _missing("Namespace")
    if len(ns) > 255 or ns.startswith(":") or not re.fullmatch(r"[\w.\-/#:]+", ns):
        raise _invalid(f"The value {ns} for parameter Namespace is invalid.")
    if ns.startswith("AWS/"):
        raise _invalid(f"The value {ns} for parameter Namespace is invalid.")
    data = _list(a.get("MetricData"))
    if not data:
        raise _missing("MetricData")
    if len(data) > 1000:
        raise _invalid("The collection MetricData must not have a size greater than 1000.")
    now = _now()
    staged = []
    for n, m in enumerate(data, 1):
        p = f"MetricData.member.{n}"
        name = str(m.get("MetricName") or "")
        if not name:
            raise _missing(f"{p}.MetricName")
        if len(name) > 255:
            raise _invalid(f"The value {name} for parameter {p}.MetricName is invalid.")
        t = _ts(m["Timestamp"], f"{p}.Timestamp") if m.get("Timestamp") is not None else now
        if t < now - 14 * 86400 or t > now + 7200:
            raise _invalid(f"The parameter {p}.Timestamp must specify a time within the past two weeks and no more than two hours into the future.")
        unit = str(m.get("Unit") or "None")
        if unit not in UNITS:
            raise _invalid(f"The parameter {p}.Unit must be a valid unit.")
        res = m.get("StorageResolution")
        if res is not None and _i(res, f"{p}.StorageResolution") not in (1, 60):
            raise _invalid(f"The value {res} for parameter {p}.StorageResolution is invalid.")
        dims = _dims(m.get("Dimensions"), f"{p}.Dimensions")
        sv, values, counts = m.get("StatisticValues"), m.get("Values"), m.get("Counts")
        if sv is not None:
            if m.get("Value") is not None or values is not None:
                raise _combo(f"The parameters {p}.StatisticValues and {p}.Value (or Values) cannot both be specified.")
            cnt = _f(sv.get("SampleCount"), f"{p}.StatisticValues.SampleCount")
            tot = _f(sv.get("Sum"), f"{p}.StatisticValues.Sum")
            lo, hi = _f(sv.get("Minimum"), f"{p}.StatisticValues.Minimum"), _f(sv.get("Maximum"), f"{p}.StatisticValues.Maximum")
            if cnt <= 0 or lo > hi:
                raise _invalid(f"The parameter {p}.StatisticValues is invalid.")
            pt = [t, tot, cnt, lo, hi, unit, None]
        elif values is not None:
            vs = [_f(x, f"{p}.Values") for x in _list(values)]
            cs = [_f(x, f"{p}.Counts") for x in _list(counts)] if counts is not None else [1.0] * len(vs)
            if not vs or len(vs) != len(cs):
                raise _combo(f"The parameters {p}.Values and {p}.Counts must be the same length.")
            if any(c <= 0 for c in cs):
                raise _invalid(f"The parameter {p}.Counts must contain positive values.")
            pt = [t, sum(v * c for v, c in zip(vs, cs)), sum(cs), min(vs), max(vs), unit, [[v, c] for v, c in zip(vs, cs)]]
        elif m.get("Value") is not None:
            v = _f(m["Value"], f"{p}.Value")
            pt = [t, v, 1.0, v, v, unit, [[v, 1.0]]]
        else:
            raise _missing(f"{p}.Value (or Values / StatisticValues)")
        staged.append((name, dims, pt))
    touched = set()
    for name, dims, pt in staged:
        s = _series(store, ns, name, dims, create=True)
        s["points"].append(pt)
        if len(s["points"]) > KEEP_POINTS:
            del s["points"][: len(s["points"]) - KEEP_POINTS]
        s["unit"] = pt[5]
        s["last"] = max(s["last"], pt[0])
        touched.add((ns, name, _dim_key(dims)))
    _evaluate_for(store, touched, now)
    store.persist()
    return None


def _bucket_stat(pts: list, stat: str):
    """Aggregate the points of one bucket for `stat` (None when empty)."""
    if not pts:
        return None
    cnt = sum(p[2] for p in pts)
    if cnt <= 0:
        return None
    if stat == "SampleCount":
        return float(cnt)
    if stat == "Sum":
        return float(sum(p[1] for p in pts))
    if stat == "Average":
        return sum(p[1] for p in pts) / cnt
    if stat == "Minimum":
        return float(min(p[3] for p in pts))
    if stat == "Maximum":
        return float(max(p[4] for p in pts))
    m = re.fullmatch(r"[pP](\d+(?:\.\d+)?)", stat)
    if m:
        pct = float(m.group(1))
        vals = []
        for p in pts:
            vals.extend(p[6] if p[6] else [[p[1] / p[2], p[2]]])
        vals.sort()
        total = sum(c for _, c in vals)
        rank = max(1.0, math.ceil(pct / 100.0 * total))
        acc = 0.0
        for v, c in vals:
            acc += c
            if acc >= rank:
                return float(v)
        return float(vals[-1][0])
    raise _invalid(f"The value {stat} for parameter Stat is invalid.")


def _check_stat(stat: str) -> None:
    if stat not in STATS and not re.fullmatch(r"[pP]\d+(\.\d+)?", stat):
        raise _invalid(f"The value {stat} for parameter Stat is invalid.")


def _check_period(period: int, name="Period") -> None:
    if period < 1 or (period > 60 and period % 60):
        raise _invalid(f"The parameter {name} must be a multiple of 60.")


def _points_in(s: dict, unit: str | None):
    return [p for p in s["points"] if not unit or unit == "None" or p[5] == unit]


def _bucketize(pts: list, start: float, end: float, period: int) -> dict[float, list]:
    out: dict[float, list] = {}
    for p in pts:
        if start <= p[0] < end:
            out.setdefault(start + math.floor((p[0] - start) / period) * period, []).append(p)
    return out


def op_get_metric_statistics(store, a):
    ns, name = str(a.get("Namespace") or ""), str(a.get("MetricName") or "")
    if not ns:
        raise _missing("Namespace")
    if not name:
        raise _missing("MetricName")
    if a.get("StartTime") is None:
        raise _missing("StartTime")
    if a.get("EndTime") is None:
        raise _missing("EndTime")
    if a.get("Period") is None:
        raise _missing("Period")
    start, end = _ts(a["StartTime"], "StartTime"), _ts(a["EndTime"], "EndTime")
    if start >= end:
        raise _invalid("The parameter StartTime must be less than the parameter EndTime.")
    period = _i(a["Period"], "Period")
    _check_period(period)
    stats, ext = _list(a.get("Statistics")), _list(a.get("ExtendedStatistics"))
    if not stats and not ext:
        raise _combo("Must specify either Statistics or ExtendedStatistics")
    if stats and ext:
        raise _combo("Cannot specify both Statistics and ExtendedStatistics")
    for st in stats:
        if st not in STATS:
            raise _invalid(f"The value {st} for parameter Statistics is invalid.")
    for st in ext:
        _check_stat(st)
    n = math.ceil((end - start) / period)
    if n > GMS_MAX_DATAPOINTS:
        raise _combo(f"You have requested up to {n:,} datapoints, which exceeds the limit of {GMS_MAX_DATAPOINTS:,}. "
                     "You may reduce the datapoints requested by increasing Period, or decreasing the time range.")
    dims = _dims(a.get("Dimensions"))
    s = _series(store, ns, name, dims)
    unit = a.get("Unit")
    dps = []
    if s:
        for t0, pts in sorted(_bucketize(_points_in(s, unit), start, end, period).items()):
            dp = {"Timestamp": Ts(t0)}
            for st in stats:
                dp[st] = _bucket_stat(pts, st)
            if ext:
                dp["ExtendedStatistics"] = XMap({st: _bucket_stat(pts, st) for st in ext})
            dp["Unit"] = unit if unit else (pts[0][5] if len({p[5] for p in pts}) == 1 else "None")
            dps.append(dp)
    return {"Label": name, "Datapoints": dps}


# ── GetMetricData: MetricStat + metric math ────────────────────────────────
_ID_RE = re.compile(r"[a-z][a-zA-Z0-9_]*")


def _stat_series(store, metric: dict, period: int, stat: str, unit, start: float, end: float) -> dict[float, float]:
    ns, name = str(metric.get("Namespace") or ""), str(metric.get("MetricName") or "")
    if not ns:
        raise _missing("Namespace")
    if not name:
        raise _missing("MetricName")
    s = _series(store, ns, name, _dims(metric.get("Dimensions")))
    out: dict[float, float] = {}
    if s:
        for t0, pts in _bucketize(_points_in(s, unit), start, end, period).items():
            v = _bucket_stat(pts, stat)
            if v is not None:
                out[t0] = v
    return out


class _MathError(Exception):
    pass


def _binop(op, l, r):
    def ap(x, y):
        if isinstance(op, ast.Add):
            return x + y
        if isinstance(op, ast.Sub):
            return x - y
        if isinstance(op, ast.Mult):
            return x * y
        if isinstance(op, ast.Div):
            if y == 0:
                return None
            return x / y
        if isinstance(op, ast.Pow):
            return x ** y
        raise _MathError("unsupported operator")
    if isinstance(l, dict) and isinstance(r, dict):
        res = {t: ap(l[t], r[t]) for t in l if t in r}
    elif isinstance(l, dict):
        res = {t: ap(v, r) for t, v in l.items()}
    elif isinstance(r, dict):
        res = {t: ap(l, v) for t, v in r.items()}
    else:
        return ap(l, r)
    return {t: v for t, v in res.items() if v is not None}


def _eval_math(node, env: dict):
    if isinstance(node, ast.Expression):
        return _eval_math(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise _MathError(f"unknown metric id {node.id}")
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval_math(node.operand, env)
        sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
        return {t: sign * x for t, x in v.items()} if isinstance(v, dict) else sign * v
    if isinstance(node, ast.BinOp):
        return _binop(node.op, _eval_math(node.left, env), _eval_math(node.right, env))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = node.func.id.upper()
        if fn == "METRICS":
            return [v for k, v in env.items() if isinstance(v, dict) and k not in env.get("__exprs__", ())]
        args = [_eval_math(x, env) for x in node.args]
        if fn in ("SUM", "AVG", "MIN", "MAX") and args:
            ser = args[0] if isinstance(args[0], list) else [args[0]]
            agg = {"SUM": sum, "AVG": lambda xs: sum(xs) / len(xs), "MIN": min, "MAX": max}[fn]
            ts = sorted({t for s in ser for t in s})
            return {t: float(agg([s[t] for s in ser if t in s])) for t in ts}
        if fn in ("ABS", "CEIL", "FLOOR", "SQRT", "LOG", "LOG10") and args and isinstance(args[0], dict):
            f = {"ABS": abs, "CEIL": math.ceil, "FLOOR": math.floor, "SQRT": math.sqrt, "LOG": math.log, "LOG10": math.log10}[fn]
            return {t: float(f(v)) for t, v in args[0].items()}
        if fn == "FILL" and len(args) == 2 and isinstance(args[0], dict) and not isinstance(args[1], dict):
            ts = sorted(args[0])
            return {t: args[0].get(t, args[1]) for t in ts}
        raise _MathError(f"unsupported function {node.func.id}")
    raise _MathError("unsupported expression")


def run_queries(store, queries: list, start: float, end: float, default_period: int | None = None) -> dict[str, dict]:
    """Evaluate MetricDataQuery entries → {id: {"label", "series": {ts: val}, "return", "status", "messages"}}."""
    res: dict[str, dict] = {}
    pending = []
    for q in queries:
        qid = str(q.get("Id") or "")
        if not qid:
            raise _missing("MetricDataQueries.member.Id")
        if not _ID_RE.fullmatch(qid):
            raise _invalid(f"The value {qid} for parameter MetricDataQueries.Id is invalid.")
        if qid in res or any(p.get("Id") == qid for p in pending):
            raise _invalid(f"Duplicate query id {qid}")
        ms, expr = q.get("MetricStat"), q.get("Expression")
        if ms is not None and expr is not None:
            raise _combo("Only one of Expression and MetricStat can be specified.")
        if ms is None and expr is None:
            raise _combo("One of Expression or MetricStat is required.")
        if ms is not None:
            metric = ms.get("Metric") or {}
            period = _i(ms.get("Period"), "Period") if ms.get("Period") is not None else None
            if period is None:
                raise _missing("MetricDataQueries.member.MetricStat.Period")
            _check_period(period)
            stat = str(ms.get("Stat") or "")
            if not stat:
                raise _missing("MetricDataQueries.member.MetricStat.Stat")
            _check_stat(stat)
            ser = _stat_series(store, metric, period, stat, ms.get("Unit"), start, end)
            res[qid] = {"label": q.get("Label") or str(metric.get("MetricName") or qid), "series": ser,
                        "return": _b(q.get("ReturnData"), True), "status": "Complete", "messages": []}
        else:
            pending.append(q)
    env = {k: v["series"] for k, v in res.items()}
    env["__exprs__"] = {str(p.get("Id")) for p in pending}
    for _ in range(len(pending) + 1):          # expressions may reference later expressions
        left = []
        for q in pending:
            qid = str(q["Id"])
            try:
                tree = ast.parse(str(q["Expression"]).strip(), mode="eval")
                v = _eval_math(tree, env)
                if isinstance(v, list):
                    v = v[0] if v else {}
                if not isinstance(v, dict):
                    v = {}
                env[qid] = v
                res[qid] = {"label": q.get("Label") or str(q["Expression"]), "series": v,
                            "return": _b(q.get("ReturnData"), True), "status": "Complete", "messages": []}
            except _MathError as e:
                if "unknown metric id" in str(e) and any(str(p["Id"]) in str(e) for p in pending if p is not q):
                    left.append(q)
                    continue
                res[qid] = {"label": q.get("Label") or str(q["Expression"]), "series": {}, "return": _b(q.get("ReturnData"), True),
                            "status": "InternalError", "messages": [{"Code": "ArithmeticError", "Value": str(e)}]}
            except SyntaxError:
                res[qid] = {"label": q.get("Label") or str(q["Expression"]), "series": {}, "return": _b(q.get("ReturnData"), True),
                            "status": "InternalError", "messages": [{"Code": "SyntaxError", "Value": "Invalid expression"}]}
        pending = left
        if not pending:
            break
    for q in pending:
        res[str(q["Id"])] = {"label": q.get("Label") or str(q["Expression"]), "series": {}, "return": True,
                             "status": "InternalError", "messages": [{"Code": "ArithmeticError", "Value": "Unresolved reference"}]}
    return res


def op_get_metric_data(store, a):
    queries = _list(a.get("MetricDataQueries"))
    if not queries:
        raise _missing("MetricDataQueries")
    if a.get("StartTime") is None:
        raise _missing("StartTime")
    if a.get("EndTime") is None:
        raise _missing("EndTime")
    start, end = _ts(a["StartTime"], "StartTime"), _ts(a["EndTime"], "EndTime")
    if start >= end:
        raise _invalid("The parameter StartTime must be less than the parameter EndTime.")
    if a.get("NextToken"):
        raise CwError("InvalidNextToken", "The next token specified is invalid.")
    scan = str(a.get("ScanBy") or "TimestampDescending")
    if scan not in ("TimestampAscending", "TimestampDescending"):
        raise _invalid(f"The value {scan} for parameter ScanBy is invalid.")
    max_dp = _i(a["MaxDatapoints"], "MaxDatapoints") if a.get("MaxDatapoints") is not None else 100800
    res = run_queries(store, queries, start, end)
    out = []
    for q in queries:
        r = res[str(q["Id"])]
        if not r["return"]:
            continue
        ts = sorted(r["series"], reverse=(scan == "TimestampDescending"))[:max_dp]
        out.append({"Id": str(q["Id"]), "Label": r["label"], "Timestamps": [Ts(t) for t in ts],
                    "Values": [float(r["series"][t]) for t in ts], "StatusCode": r["status"], "Messages": r["messages"]})
    return {"MetricDataResults": out, "Messages": []}


def op_list_metrics(store, a):
    ns, name = a.get("Namespace"), a.get("MetricName")
    want = []
    for d in _list(a.get("Dimensions")):
        if not str(d.get("Name") or ""):
            raise _invalid("The parameter Dimensions.Name is required.")
        want.append((str(d["Name"]), d.get("Value")))
    recent = a.get("RecentlyActive")
    if recent is not None and recent != "PT3H":
        raise _invalid(f"The value {recent} for parameter RecentlyActive is invalid.")
    now = _now()
    rows = []
    for s in store.metrics.values():
        if ns and s["Namespace"] != ns:
            continue
        if name and s["MetricName"] != name:
            continue
        have = {d["Name"]: d["Value"] for d in s["Dimensions"]}
        if any(n not in have or (v is not None and have[n] != v) for n, v in want):
            continue
        if recent and s["last"] < now - 3 * 3600:
            continue
        rows.append({"Namespace": s["Namespace"], "MetricName": s["MetricName"], "Dimensions": s["Dimensions"]})
    rows.sort(key=lambda m: (m["Namespace"], m["MetricName"], _dim_key(m["Dimensions"])))
    chunk, nxt = _page(rows, a.get("NextToken"), 500)
    return _clean({"Metrics": chunk, "NextToken": nxt})


# ── alarms ─────────────────────────────────────────────────────────────────
def _hist(store, name: str, kind: str, item_type: str, summary: str, data: dict | None = None, ts: float | None = None):
    store.history.append({"AlarmName": name, "AlarmType": kind, "Timestamp": ts if ts is not None else _now(),
                          "HistoryItemType": item_type, "HistorySummary": summary,
                          "HistoryData": json.dumps(data, separators=(",", ":")) if data is not None else None})
    if len(store.history) > 10000:
        del store.history[:1000]


def _validate_alarm_name(a: dict) -> str:
    name = str(a.get("AlarmName") or "")
    if not name:
        raise _missing("AlarmName")
    if len(name) > 255:
        raise _invalid("The value for parameter AlarmName is too long (max 255).")
    return name


def _actions(a: dict, key: str) -> list[str]:
    v = [str(x) for x in _list(a.get(key))]
    if len(v) > 5:
        raise _invalid(f"The parameter {key} must not contain more than 5 actions.")
    return v


def op_put_metric_alarm(store, a):
    name = _validate_alarm_name(a)
    if name in store.composites:
        raise CwError("ResourceConflict", f"Alarm {name} already exists as a composite alarm.")
    cmp_ = a.get("ComparisonOperator")
    if not cmp_:
        raise _missing("ComparisonOperator")
    if cmp_ not in COMPARISONS:
        raise _invalid(f"The value {cmp_} for parameter ComparisonOperator is invalid.")
    if a.get("EvaluationPeriods") is None:
        raise _missing("EvaluationPeriods")
    evp = _i(a["EvaluationPeriods"], "EvaluationPeriods")
    if evp < 1:
        raise _invalid("The parameter EvaluationPeriods must be at least 1.")
    dta = _i(a["DatapointsToAlarm"], "DatapointsToAlarm") if a.get("DatapointsToAlarm") is not None else None
    if dta is not None and not 1 <= dta <= evp:
        raise _invalid("DatapointsToAlarm must be between 1 and EvaluationPeriods.")
    tmd = str(a.get("TreatMissingData") or "missing")
    if tmd not in ("breaching", "notBreaching", "ignore", "missing"):
        raise _invalid(f"The value {tmd} for parameter TreatMissingData is invalid.")
    rec = {"AlarmName": name, "AlarmDescription": a.get("AlarmDescription"),
           "ActionsEnabled": _b(a.get("ActionsEnabled"), True),
           "OKActions": _actions(a, "OKActions"), "AlarmActions": _actions(a, "AlarmActions"),
           "InsufficientDataActions": _actions(a, "InsufficientDataActions"),
           "EvaluationPeriods": evp, "DatapointsToAlarm": dta if dta is not None else evp,
           "ComparisonOperator": cmp_, "TreatMissingData": tmd}
    metrics = _list(a.get("Metrics"))
    if metrics:
        if a.get("MetricName") or a.get("Namespace") or a.get("Statistic") or a.get("ExtendedStatistic") or a.get("Dimensions") or a.get("Period"):
            raise _combo("Metrics cannot be specified together with MetricName, Namespace, Statistic, ExtendedStatistic, Dimensions, Period or Unit.")
        if not any(_b(m.get("ReturnData"), True) for m in metrics):
            raise _invalid("At least one metric query must return data.")
        run_queries(store, metrics, 0.0, 1.0)     # validates ids / shapes
        rec["Metrics"] = [_clean({k: (_b(v) if k == "ReturnData" else (_i(v) if k == "Period" else v)) for k, v in m.items()}) for m in metrics]
        if a.get("ThresholdMetricId"):
            rec["ThresholdMetricId"] = str(a["ThresholdMetricId"])
    else:
        if not a.get("MetricName"):
            raise _missing("MetricName")
        if not a.get("Namespace"):
            raise _missing("Namespace")
        if a.get("Period") is None:
            raise _missing("Period")
        period = _i(a["Period"], "Period")
        _check_period(period)
        if a.get("Statistic") and a.get("ExtendedStatistic"):
            raise _combo("Cannot specify both Statistic and ExtendedStatistic.")
        if not a.get("Statistic") and not a.get("ExtendedStatistic"):
            raise _combo("Must specify either Statistic or ExtendedStatistic.")
        if a.get("Statistic") and a["Statistic"] not in STATS:
            raise _invalid(f"The value {a['Statistic']} for parameter Statistic is invalid.")
        if a.get("ExtendedStatistic"):
            _check_stat(str(a["ExtendedStatistic"]))
        if a.get("Unit") and a["Unit"] not in UNITS:
            raise _invalid(f"The value {a['Unit']} for parameter Unit is invalid.")
        rec.update({"MetricName": str(a["MetricName"]), "Namespace": str(a["Namespace"]),
                    "Statistic": a.get("Statistic"), "ExtendedStatistic": a.get("ExtendedStatistic"),
                    "Dimensions": _dims(a.get("Dimensions")), "Period": period, "Unit": a.get("Unit")})
    if a.get("Threshold") is not None:
        rec["Threshold"] = _f(a["Threshold"], "Threshold")
    elif not a.get("ThresholdMetricId"):
        raise _missing("Threshold")
    if a.get("EvaluateLowSampleCountPercentile"):
        rec["EvaluateLowSampleCountPercentile"] = str(a["EvaluateLowSampleCountPercentile"])
    now = _now()
    old = store.alarms.get(name)
    if old is None and len(store.alarms) + len(store.composites) >= MAX_ALARMS:
        raise CwError("LimitExceededFault", "The maximum number of alarms has been reached.")
    rec["AlarmArn"] = store.alarm_arn(name)
    rec["AlarmConfigurationUpdatedTimestamp"] = now
    if old:                                   # an update keeps the alarm's state
        for k in ("StateValue", "StateReason", "StateReasonData", "StateUpdatedTimestamp", "StateTransitionedTimestamp"):
            if old.get(k) is not None:
                rec[k] = old[k]
    else:
        rec.update({"StateValue": "INSUFFICIENT_DATA", "StateReason": "Unchecked: Initial alarm creation",
                    "StateUpdatedTimestamp": now, "StateTransitionedTimestamp": now})
    store.alarms[name] = rec
    tags = _tag_list(a.get("Tags"))
    if tags:
        store.tags.setdefault(rec["AlarmArn"], {}).update(tags)
    _hist(store, name, "MetricAlarm", "ConfigurationUpdate", f'Alarm "{name}" {"updated" if old else "created"}',
          {"version": "1.0", "type": "Update" if old else "Create", "updatedAlarm": _public_alarm(rec)}, now)
    if old is None:
        _evaluate_alarm(store, rec, now, initial=True)
    _eval_composites(store, now)
    store.persist()
    return None


def _public_alarm(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if v is None or k.startswith("_"):
            continue
        out[k] = Ts(v) if k.endswith("Timestamp") else v
    return out


def _rule_names(rule: str) -> list[str]:
    return [m.group(1) or m.group(2) for m in re.finditer(r'(?:ALARM|OK|INSUFFICIENT_DATA)\(\s*(?:"([^"]+)"|([^\s")]+))\s*\)', rule)]


def _name_of_ref(ref: str) -> str:
    return ref.split(":alarm:", 1)[1] if ":alarm:" in ref else ref


class _RuleError(Exception):
    pass


def _rule_eval(rule: str, state_of) -> bool:
    toks = re.findall(r'"[^"]*"|\(|\)|[A-Za-z_]+|[^\s()"]+', rule)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take(expect=None):
        t = peek()
        if t is None or (expect and t.upper() != expect):
            raise _RuleError(f"expected {expect or 'token'} at {pos[0]}")
        pos[0] += 1
        return t

    def expr():
        v = term_and()
        while peek() and peek().upper() == "OR":
            take()
            r = term_and()
            v = v or r
        return v

    def term_and():
        v = unary()
        while peek() and peek().upper() == "AND":
            take()
            r = unary()
            v = v and r
        return v

    def unary():
        t = peek()
        if t is None:
            raise _RuleError("unexpected end")
        if t.upper() == "NOT":
            take()
            return not unary()
        if t == "(":
            take()
            v = expr()
            take(")")
            return v
        if t.upper() in ("TRUE", "FALSE"):
            take()
            return t.upper() == "TRUE"
        if t.upper() in ALARM_STATES:
            take()
            take("(")
            ref = take().strip('"')
            take(")")
            return state_of(_name_of_ref(ref)) == t.upper()
        raise _RuleError(f"unexpected {t}")

    v = expr()
    if peek() is not None:
        raise _RuleError("trailing tokens")
    return v


def op_put_composite_alarm(store, a):
    name = _validate_alarm_name(a)
    if name in store.alarms:
        raise CwError("ResourceConflict", f"Alarm {name} already exists as a metric alarm.")
    rule = str(a.get("AlarmRule") or "")
    if not rule:
        raise _missing("AlarmRule")
    for ref in _rule_names(rule):
        n = _name_of_ref(ref)
        if n not in store.alarms and n not in store.composites:
            raise CwError("ValidationException", f"Alarm '{n}' does not exist.")
        if n == name:
            raise CwError("ValidationException", "A composite alarm cannot reference itself.")
    try:
        _rule_eval(rule, lambda n: "OK")
    except _RuleError:
        raise CwError("ValidationException", "Unable to parse AlarmRule.")
    now = _now()
    old = store.composites.get(name)
    if old is None and len(store.alarms) + len(store.composites) >= MAX_ALARMS:
        raise CwError("LimitExceededFault", "The maximum number of alarms has been reached.")
    rec = {"AlarmName": name, "AlarmArn": store.alarm_arn(name), "AlarmDescription": a.get("AlarmDescription"),
           "AlarmRule": rule, "ActionsEnabled": _b(a.get("ActionsEnabled"), True),
           "OKActions": _actions(a, "OKActions"), "AlarmActions": _actions(a, "AlarmActions"),
           "InsufficientDataActions": _actions(a, "InsufficientDataActions"),
           "AlarmConfigurationUpdatedTimestamp": now}
    if old:
        for k in ("StateValue", "StateReason", "StateReasonData", "StateUpdatedTimestamp", "StateTransitionedTimestamp"):
            if old.get(k) is not None:
                rec[k] = old[k]
    else:
        rec.update({"StateValue": "INSUFFICIENT_DATA", "StateReason": "Unchecked: Initial alarm creation",
                    "StateUpdatedTimestamp": now, "StateTransitionedTimestamp": now})
    store.composites[name] = rec
    tags = _tag_list(a.get("Tags"))
    if tags:
        store.tags.setdefault(rec["AlarmArn"], {}).update(tags)
    _hist(store, name, "CompositeAlarm", "ConfigurationUpdate", f'Composite alarm "{name}" {"updated" if old else "created"}',
          {"version": "1.0", "type": "Update" if old else "Create", "updatedAlarm": _public_alarm(rec)}, now)
    _eval_composites(store, now)
    store.persist()
    return None


def _fire_actions(store, rec: dict, kind: str, new_state: str, reason: str, now: float) -> None:
    if not rec.get("ActionsEnabled"):
        return
    key = {"OK": "OKActions", "ALARM": "AlarmActions", "INSUFFICIENT_DATA": "InsufficientDataActions"}[new_state]
    for arn in rec.get(key, []):
        ok = True
        if store.action_hook:
            try:
                store.action_hook(arn, rec, new_state, reason)
            except Exception:
                ok = False
        _hist(store, rec["AlarmName"], kind, "Action",
              f"Successfully executed action {arn}" if ok else f"Failed to execute action {arn}",
              {"actionState": "Succeeded" if ok else "Failed", "notificationResource": arn, "publishedMessage": reason}, now)


def _set_state(store, rec: dict, kind: str, new_state: str, reason: str, data: str | None, now: float) -> None:
    old_state, old_reason = rec.get("StateValue"), rec.get("StateReason")
    rec.update({"StateValue": new_state, "StateReason": reason, "StateReasonData": data, "StateUpdatedTimestamp": now})
    if old_state != new_state:
        rec["StateTransitionedTimestamp"] = now
        _hist(store, rec["AlarmName"], kind, "StateUpdate", f"Alarm updated from {old_state} to {new_state}",
              {"version": "1.0", "oldState": {"stateValue": old_state, "stateReason": old_reason},
               "newState": {"stateValue": new_state, "stateReason": reason, "stateReasonData": json.loads(data) if data else None}}, now)
        _fire_actions(store, rec, kind, new_state, reason, now)


def _alarm_queries(rec: dict) -> tuple[list, str]:
    if rec.get("Metrics"):
        rid = next((m["Id"] for m in rec["Metrics"] if m.get("ReturnData", True) and m["Id"] != rec.get("ThresholdMetricId")), rec["Metrics"][0]["Id"])
        return rec["Metrics"], rid
    q = [{"Id": "m1", "MetricStat": {"Metric": {"Namespace": rec["Namespace"], "MetricName": rec["MetricName"], "Dimensions": rec.get("Dimensions", [])},
                                       "Period": rec["Period"], "Stat": rec.get("Statistic") or rec.get("ExtendedStatistic"), "Unit": rec.get("Unit")}}]
    return q, "m1"


def _alarm_period(rec: dict) -> int:
    if rec.get("Period"):
        return int(rec["Period"])
    for m in rec.get("Metrics", []):
        ms = m.get("MetricStat")
        if ms and ms.get("Period"):
            return int(ms["Period"])
    return 60


def _breach(op: str, v: float, thr: float) -> bool:
    return {">=": v >= thr, ">": v > thr, "<": v < thr, "<=": v <= thr}[op]


def _evaluate_alarm(store, rec: dict, now: float, initial: bool = False) -> None:
    period = _alarm_period(rec)
    n = rec["EvaluationPeriods"]
    end = math.ceil((now + 1e-6) / period) * period
    start = end - n * period
    queries, rid = _alarm_queries(rec)
    try:
        res = run_queries(store, queries, start, end)
    except CwError:
        return
    series = res[rid]["series"]
    cmp_ = rec["ComparisonOperator"]
    thr = rec.get("Threshold")
    if rec.get("ThresholdMetricId") and rec["ThresholdMetricId"] in res:
        pass                                   # anomaly-band alarms are not evaluated (no model)
    if thr is None or cmp_ in ("LessThanLowerOrGreaterThanUpperThreshold", "LessThanLowerThreshold", "GreaterThanUpperThreshold"):
        return
    op = COMPARISONS[cmp_]
    tmd = rec.get("TreatMissingData", "missing")
    vals = [series.get(start + i * period) for i in range(n)]
    states = []
    for v in vals:
        if v is None:
            states.append({"breaching": "B", "notBreaching": "O"}.get(tmd, "M"))
        else:
            states.append("B" if _breach(op, v, thr) else "O")
    b, o = states.count("B"), states.count("O")
    dta = rec.get("DatapointsToAlarm", n)
    seen = [(start + i * period, v) for i, v in enumerate(vals) if v is not None]
    when = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%d/%m/%y %H:%M:%S")
    shown = ", ".join(f"{v} ({when(t)})" for t, v in seen[-dta:] or [])
    word = {">=": "greater than or equal to", ">": "greater than", "<": "less than", "<=": "less than or equal to"}[op]
    if b >= dta:
        new = "ALARM"
        reason = (f"Threshold Crossed: {b} out of the last {n} datapoints [{shown}] was {word} the threshold ({thr}) "
                  f"(minimum {dta} datapoint{'s' if dta != 1 else ''} for OK -> ALARM transition).")
    elif b == 0 and o == 0:
        if tmd == "ignore" and not initial:
            return
        new = "INSUFFICIENT_DATA"
        reason = f"Insufficient Data: {n} datapoint{'s' if n != 1 else ''} were unknown."
    else:
        new = "OK"
        reason = (f"Threshold Crossed: {max(len(seen), o)} out of the last {n} datapoints [{shown}] was not {word} the threshold ({thr}) "
                  f"(minimum {dta} datapoint{'s' if dta != 1 else ''} for OK -> ALARM transition).")
    data = json.dumps({"version": "1.0", "queryDate": _iso(now), "startDate": _iso(start), "period": period,
                       "recentDatapoints": [v for _, v in seen], "threshold": thr}, separators=(",", ":"))
    if initial and rec.get("StateValue") == "INSUFFICIENT_DATA" and new == "INSUFFICIENT_DATA":
        return
    _set_state(store, rec, "MetricAlarm", new, reason, data, now)


def _evaluate_for(store, touched: set, now: float) -> None:
    changed = False
    for rec in list(store.alarms.values()):
        if rec.get("Metrics"):
            keys = {(m["MetricStat"]["Metric"].get("Namespace"), m["MetricStat"]["Metric"].get("MetricName"),
                     _dim_key(_dims(m["MetricStat"]["Metric"].get("Dimensions")))) for m in rec["Metrics"] if m.get("MetricStat")}
        else:
            keys = {(rec["Namespace"], rec["MetricName"], _dim_key(rec.get("Dimensions", [])))}
        if keys & touched:
            _evaluate_alarm(store, rec, now)
            changed = True
    if changed:
        _eval_composites(store, now)


def _eval_composites(store, now: float) -> None:
    def state_of(n):
        r = store.alarms.get(n) or store.composites.get(n)
        return r["StateValue"] if r else "INSUFFICIENT_DATA"
    for _ in range(4):
        moved = False
        for rec in store.composites.values():
            try:
                firing = _rule_eval(rec["AlarmRule"], state_of)
            except _RuleError:
                continue
            new = "ALARM" if firing else "OK"
            if rec["StateValue"] != new:
                names = ", ".join(_rule_names(rec["AlarmRule"]))
                reason = (f"arn:aws:cloudwatch:{store.region}:{store.account_id}:alarm:{rec['AlarmName']} transitioned to {new}: "
                          f"rule {'matched' if firing else 'no longer matches'} ({names})")
                _set_state(store, rec, "CompositeAlarm", new, reason, json.dumps({"triggeringAlarms": _rule_names(rec["AlarmRule"])}), now)
                moved = True
        if not moved:
            break


def op_describe_alarms(store, a):
    names, prefix = [str(x) for x in _list(a.get("AlarmNames"))], a.get("AlarmNamePrefix")
    if names and prefix:
        raise _combo("AlarmNames and AlarmNamePrefix cannot be specified together.")
    types = _list(a.get("AlarmTypes")) or ["MetricAlarm"]
    for t in types:
        if t not in ("MetricAlarm", "CompositeAlarm"):
            raise _invalid(f"The value {t} for parameter AlarmTypes is invalid.")
    state, action_prefix = a.get("StateValue"), a.get("ActionPrefix")
    if state and state not in ALARM_STATES:
        raise _invalid(f"The value {state} for parameter StateValue is invalid.")
    limit = _i(a["MaxRecords"], "MaxRecords") if a.get("MaxRecords") is not None else 50
    if not 1 <= limit <= 100:
        raise _invalid("The parameter MaxRecords must be between 1 and 100.")
    child, parent = a.get("ChildrenOfAlarmName"), a.get("ParentsOfAlarmName")
    if child and child not in store.composites:
        raise CwError("ResourceNotFound", f"Composite alarm {child} does not exist.")
    rows = []
    for kind, pool in (("MetricAlarm", store.alarms), ("CompositeAlarm", store.composites)):
        if kind not in types:
            continue
        for n, rec in pool.items():
            if names and n not in names:
                continue
            if prefix and not n.startswith(str(prefix)):
                continue
            if state and rec["StateValue"] != state:
                continue
            if action_prefix and not any(x.startswith(str(action_prefix)) for k in ("OKActions", "AlarmActions", "InsufficientDataActions") for x in rec.get(k, [])):
                continue
            if child and n not in [_name_of_ref(x) for x in _rule_names(store.composites[child]["AlarmRule"])]:
                continue
            if parent and not (n in store.composites and parent in [_name_of_ref(x) for x in _rule_names(store.composites[n]["AlarmRule"])]):
                continue
            rows.append((kind, rec))
    rows.sort(key=lambda r: r[1]["AlarmName"])
    chunk, nxt = _page(rows, a.get("NextToken"), limit)
    return _clean({"CompositeAlarms": [_public_alarm(r) for k, r in chunk if k == "CompositeAlarm"],
                   "MetricAlarms": [_public_alarm(r) for k, r in chunk if k == "MetricAlarm"], "NextToken": nxt})


def op_describe_alarms_for_metric(store, a):
    if not a.get("MetricName"):
        raise _missing("MetricName")
    if not a.get("Namespace"):
        raise _missing("Namespace")
    dims = _dims(a.get("Dimensions")) if a.get("Dimensions") else None
    out = []
    for rec in store.alarms.values():
        if rec.get("MetricName") != a["MetricName"] or rec.get("Namespace") != a["Namespace"]:
            continue
        if a.get("Statistic") and rec.get("Statistic") != a["Statistic"]:
            continue
        if a.get("ExtendedStatistic") and rec.get("ExtendedStatistic") != a["ExtendedStatistic"]:
            continue
        if dims is not None and rec.get("Dimensions") != dims:
            continue
        if a.get("Period") is not None and rec.get("Period") != _i(a["Period"], "Period"):
            continue
        if a.get("Unit") and rec.get("Unit") != a["Unit"]:
            continue
        out.append(_public_alarm(rec))
    return {"MetricAlarms": sorted(out, key=lambda r: r["AlarmName"])}


def op_delete_alarms(store, a):
    names = [str(x) for x in _list(a.get("AlarmNames"))]
    if not names:
        raise _missing("AlarmNames")
    if len(names) > 100:
        raise _invalid("The collection AlarmNames must not have a size greater than 100.")
    for n in names:
        for c in store.composites.values():
            if c["AlarmName"] not in names and n in _rule_names(c["AlarmRule"]):
                raise CwError("ResourceConflict", f"Alarm {n} is referenced by composite alarm {c['AlarmName']}.")
    for n in names:
        rec = store.alarms.pop(n, None) or store.composites.pop(n, None)
        if rec:
            store.tags.pop(rec["AlarmArn"], None)
            _hist(store, n, "MetricAlarm" if "AlarmRule" not in rec else "CompositeAlarm", "ConfigurationUpdate", f'Alarm "{n}" deleted',
                  {"version": "1.0", "type": "Delete"})
    store.persist()
    return None


def _find_alarm(store, name: str):
    rec = store.alarms.get(name)
    if rec:
        return "MetricAlarm", rec
    rec = store.composites.get(name)
    if rec:
        return "CompositeAlarm", rec
    return None, None


def op_set_alarm_state(store, a):
    name = str(a.get("AlarmName") or "")
    if not name:
        raise _missing("AlarmName")
    state = str(a.get("StateValue") or "")
    if not state:
        raise _missing("StateValue")
    if state not in ALARM_STATES:
        raise _invalid(f"The value {state} for parameter StateValue is invalid.")
    reason = a.get("StateReason")
    if not reason:
        raise _missing("StateReason")
    data = a.get("StateReasonData")
    if data:
        try:
            json.loads(data)
        except Exception:
            raise CwError("InvalidFormatFault", "StateReasonData is not valid JSON.")
    kind, rec = _find_alarm(store, name)
    if rec is None:
        raise CwError("ResourceNotFound", f"Alarm {name} does not exist.")
    now = _now()
    _set_state(store, rec, kind, state, str(reason), data, now)
    _eval_composites(store, now)
    store.persist()
    return None


def _toggle_actions(store, a, enabled: bool):
    names = [str(x) for x in _list(a.get("AlarmNames"))]
    if not names:
        raise _missing("AlarmNames")
    for n in names:
        kind, rec = _find_alarm(store, n)
        if rec is not None:
            rec["ActionsEnabled"] = enabled
            _hist(store, n, kind, "ConfigurationUpdate", f'Alarm "{n}" actions {"enabled" if enabled else "disabled"}')
    store.persist()
    return None


def op_enable_alarm_actions(store, a):
    return _toggle_actions(store, a, True)


def op_disable_alarm_actions(store, a):
    return _toggle_actions(store, a, False)


def op_describe_alarm_history(store, a):
    name = a.get("AlarmName")
    types = _list(a.get("AlarmTypes")) or ["MetricAlarm", "CompositeAlarm"]
    htype = a.get("HistoryItemType")
    if htype and htype not in ("ConfigurationUpdate", "StateUpdate", "Action"):
        raise _invalid(f"The value {htype} for parameter HistoryItemType is invalid.")
    start = _ts(a["StartDate"], "StartDate") if a.get("StartDate") is not None else None
    end = _ts(a["EndDate"], "EndDate") if a.get("EndDate") is not None else None
    limit = _i(a["MaxRecords"], "MaxRecords") if a.get("MaxRecords") is not None else 100
    if not 1 <= limit <= 100:
        raise _invalid("The parameter MaxRecords must be between 1 and 100.")
    scan = a.get("ScanBy") or "TimestampDescending"
    rows = [h for h in store.history
            if (not name or h["AlarmName"] == name) and h["AlarmType"] in types and (not htype or h["HistoryItemType"] == htype)
            and (start is None or h["Timestamp"] >= start) and (end is None or h["Timestamp"] <= end)]
    rows.sort(key=lambda h: h["Timestamp"], reverse=(scan == "TimestampDescending"))
    chunk, nxt = _page(rows, a.get("NextToken"), limit)
    return _clean({"AlarmHistoryItems": [_clean({**h, "Timestamp": Ts(h["Timestamp"])}) for h in chunk], "NextToken": nxt})


# ── dashboards ─────────────────────────────────────────────────────────────
def op_put_dashboard(store, a):
    name = str(a.get("DashboardName") or "")
    if not name:
        raise _missing("DashboardName")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,255}", name):
        raise CwError("DashboardInvalidInputError",
                      "The value for field DashboardName contains invalid characters. It can only contain alphanumerics, dash (-) and underscore (_).\n",
                      {"DashboardValidationMessages": [{"DataPath": "/DashboardName", "Message": "Invalid dashboard name"}]})
    body = a.get("DashboardBody")
    if not body:
        raise _missing("DashboardBody")
    try:
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError
    except Exception:
        raise CwError("DashboardInvalidInputError", "The dashboard body is invalid, there are 1 validation errors:\n[Error: Invalid JSON]",
                      {"DashboardValidationMessages": [{"DataPath": "/", "Message": "Invalid JSON: the body must be a JSON object"}]})
    msgs = []
    for i, w in enumerate(parsed.get("widgets") or []):
        if not isinstance(w, dict) or "type" not in w:
            msgs.append({"DataPath": f"/widgets/{i}", "Message": "Widget is missing required field: type"})
    if msgs:
        raise CwError("DashboardInvalidInputError", f"The dashboard body is invalid, there are {len(msgs)} validation errors:\n" +
                      "\n".join(f"[Error: {m['Message']}]" for m in msgs), {"DashboardValidationMessages": msgs})
    store.dashboards[name] = {"DashboardName": name, "DashboardArn": store.dashboard_arn(name), "DashboardBody": body,
                              "LastModified": _now(), "Size": len(body.encode("utf-8"))}
    store.persist()
    return {"DashboardValidationMessages": []}


def op_get_dashboard(store, a):
    name = str(a.get("DashboardName") or "")
    if not name:
        raise _missing("DashboardName")
    d = store.dashboards.get(name)
    if not d:
        raise CwError("DashboardNotFoundError", f"Dashboard {name} does not exist.")
    return {"DashboardArn": d["DashboardArn"], "DashboardBody": d["DashboardBody"], "DashboardName": name}


def op_list_dashboards(store, a):
    prefix = str(a.get("DashboardNamePrefix") or "")
    rows = [{"DashboardName": d["DashboardName"], "DashboardArn": d["DashboardArn"], "LastModified": Ts(d["LastModified"]), "Size": d["Size"]}
            for d in sorted(store.dashboards.values(), key=lambda d: d["DashboardName"]) if d["DashboardName"].startswith(prefix)]
    chunk, nxt = _page(rows, a.get("NextToken"), 500)
    return _clean({"DashboardEntries": chunk, "NextToken": nxt})


def op_delete_dashboards(store, a):
    names = [str(x) for x in _list(a.get("DashboardNames"))]
    if not names:
        raise _missing("DashboardNames")
    missing = [n for n in names if n not in store.dashboards]
    if missing:
        raise CwError("DashboardNotFoundError", f"Dashboards {missing} do not exist")
    for n in names:
        store.dashboards.pop(n)
        store.tags.pop(store.dashboard_arn(n), None)
    store.persist()
    return {}


# ── tags ───────────────────────────────────────────────────────────────────
def _arn_exists(store, arn: str) -> bool:
    return (any(r["AlarmArn"] == arn for r in list(store.alarms.values()) + list(store.composites.values()))
            or any(store.rule_arn(n) == arn for n in store.insight_rules)
            or any(store.stream_arn(n) == arn for n in store.streams)
            or any(d["DashboardArn"] == arn for d in store.dashboards.values()))


def op_tag_resource(store, a):
    arn = str(a.get("ResourceARN") or "")
    if not arn:
        raise _missing("ResourceARN")
    if not arn.startswith("arn:aws:cloudwatch:"):
        raise _invalid(f"The value {arn} for parameter ResourceARN is invalid.")
    tags = _tag_list(a.get("Tags"))
    if not _list(a.get("Tags")):
        raise _missing("Tags")
    if not _arn_exists(store, arn):
        raise CwError("ResourceNotFoundException", f"The resource {arn} does not exist.")
    cur = store.tags.setdefault(arn, {})
    if len({*cur, *tags}) > 50:
        raise _invalid("The number of tags on a resource cannot exceed 50.")
    cur.update(tags)
    store.persist()
    return {}


def op_untag_resource(store, a):
    arn = str(a.get("ResourceARN") or "")
    if not arn:
        raise _missing("ResourceARN")
    keys = [str(k) for k in _list(a.get("TagKeys"))]
    if not keys:
        raise _missing("TagKeys")
    if not _arn_exists(store, arn):
        raise CwError("ResourceNotFoundException", f"The resource {arn} does not exist.")
    for k in keys:
        store.tags.get(arn, {}).pop(k, None)
    store.persist()
    return {}


def op_list_tags_for_resource(store, a):
    arn = str(a.get("ResourceARN") or "")
    if not arn:
        raise _missing("ResourceARN")
    if not _arn_exists(store, arn):
        raise CwError("ResourceNotFoundException", f"The resource {arn} does not exist.")
    return {"Tags": _tags_out(store.tags.get(arn, {}))}


# ── anomaly detectors ──────────────────────────────────────────────────────
def _detector_from(a: dict) -> dict:
    single = a.get("SingleMetricAnomalyDetector")
    math_ = a.get("MetricMathAnomalyDetector")
    if single and math_:
        raise _combo("Only one of SingleMetricAnomalyDetector and MetricMathAnomalyDetector can be specified.")
    src = single or a
    if math_:
        qs = _list(math_.get("MetricDataQueries"))
        if not qs:
            raise _missing("MetricMathAnomalyDetector.MetricDataQueries")
        return {"MetricMathAnomalyDetector": {"MetricDataQueries": qs}}
    ns, name, stat = src.get("Namespace"), src.get("MetricName"), src.get("Stat")
    if not ns:
        raise _missing("Namespace")
    if not name:
        raise _missing("MetricName")
    if not stat:
        raise _missing("Stat")
    _check_stat(str(stat))
    dims = _dims(src.get("Dimensions"))
    return {"Namespace": ns, "MetricName": name, "Dimensions": dims, "Stat": stat}


def _same_detector(x: dict, y: dict) -> bool:
    keys = ("Namespace", "MetricName", "Dimensions", "Stat", "MetricMathAnomalyDetector")
    return all(x.get(k) == y.get(k) for k in keys)


def op_put_anomaly_detector(store, a):
    d = _detector_from(a)
    cfg = a.get("Configuration") or {}
    rec = dict(d)
    if "Namespace" in d:
        rec["SingleMetricAnomalyDetector"] = {"Namespace": d["Namespace"], "MetricName": d["MetricName"], "Dimensions": d["Dimensions"], "Stat": d["Stat"]}
    rec["Configuration"] = {"ExcludedTimeRanges": _list(cfg.get("ExcludedTimeRanges")), "MetricTimezone": cfg.get("MetricTimezone") or "UTC"}
    rec["StateValue"] = "PENDING_TRAINING"
    if a.get("MetricCharacteristics"):
        rec["MetricCharacteristics"] = {"PeriodicSpikes": _b(a["MetricCharacteristics"].get("PeriodicSpikes"))}
    for i, old in enumerate(store.anomaly):
        if _same_detector(old, rec):
            store.anomaly[i] = rec
            break
    else:
        if len(store.anomaly) >= 100:
            raise CwError("LimitExceededException", "The maximum number of anomaly detectors has been reached.")
        store.anomaly.append(rec)
    store.persist()
    return {}


def op_describe_anomaly_detectors(store, a):
    ns, name = a.get("Namespace"), a.get("MetricName")
    dims = _dims(a.get("Dimensions")) if a.get("Dimensions") else None
    kinds = _list(a.get("AnomalyDetectorTypes"))
    for k in kinds:
        if k not in ("SINGLE_METRIC", "METRIC_MATH"):
            raise _invalid(f"The value {k} for parameter AnomalyDetectorTypes is invalid.")
    limit = _i(a["MaxResults"], "MaxResults") if a.get("MaxResults") is not None else 10
    rows = []
    for d in store.anomaly:
        if ns and d.get("Namespace") != ns:
            continue
        if name and d.get("MetricName") != name:
            continue
        if dims is not None and d.get("Dimensions") != dims:
            continue
        if kinds and ("SINGLE_METRIC" if "Namespace" in d else "METRIC_MATH") not in kinds:
            continue
        rows.append(d)
    chunk, nxt = _page(rows, a.get("NextToken"), limit)
    return _clean({"AnomalyDetectors": chunk, "NextToken": nxt})


def op_delete_anomaly_detector(store, a):
    d = _detector_from(a)
    for i, old in enumerate(store.anomaly):
        if _same_detector(old, d):
            del store.anomaly[i]
            store.persist()
            return {}
    raise CwError("ResourceNotFoundException", "The anomaly detector does not exist.")


# ── Contributor Insights rules ─────────────────────────────────────────────
def op_put_insight_rule(store, a):
    name = str(a.get("RuleName") or "")
    if not name:
        raise _missing("RuleName")
    if len(name) > 128:
        raise _invalid("The value for parameter RuleName is too long (max 128).")
    definition = a.get("RuleDefinition")
    if not definition:
        raise _missing("RuleDefinition")
    try:
        parsed = json.loads(definition)
        if not isinstance(parsed, dict):
            raise ValueError
    except Exception:
        raise _invalid("The RuleDefinition is not a valid JSON document.")
    state = str(a.get("RuleState") or "ENABLED")
    if state not in ("ENABLED", "DISABLED"):
        raise _invalid(f"The value {state} for parameter RuleState is invalid.")
    if name not in store.insight_rules and len(store.insight_rules) >= 500:
        raise CwError("LimitExceededException", "The maximum number of Contributor Insights rules has been reached.")
    store.insight_rules[name] = {"Name": name, "State": state, "Schema": '{"Name": "CloudWatchLogRule", "Version": 1}',
                                 "Definition": definition, "ManagedRule": False,
                                 "ApplyOnTransformedLogs": _b(a.get("ApplyOnTransformedLogs"))}
    tags = _tag_list(a.get("Tags"))
    if tags:
        store.tags.setdefault(store.rule_arn(name), {}).update(tags)
    store.persist()
    return {}


def op_describe_insight_rules(store, a):
    limit = _i(a["MaxResults"], "MaxResults") if a.get("MaxResults") is not None else 500
    rows = [store.insight_rules[n] for n in sorted(store.insight_rules)]
    chunk, nxt = _page(rows, a.get("NextToken"), limit)
    return _clean({"InsightRules": chunk, "NextToken": nxt})


def _rule_op(store, a, action: str):
    names = [str(x) for x in _list(a.get("RuleNames"))]
    if not names:
        raise _missing("RuleNames")
    failures = []
    for n in names:
        r = store.insight_rules.get(n)
        if r is None:
            failures.append({"FailureResource": n, "ExceptionType": "ResourceNotFoundException",
                             "FailureCode": "404", "FailureDescription": f"Rule {n} does not exist"})
        elif action == "delete":
            del store.insight_rules[n]
            store.tags.pop(store.rule_arn(n), None)
        else:
            r["State"] = "ENABLED" if action == "enable" else "DISABLED"
    store.persist()
    return {"Failures": failures}


def op_delete_insight_rules(store, a):
    return _rule_op(store, a, "delete")


def op_enable_insight_rules(store, a):
    return _rule_op(store, a, "enable")


def op_disable_insight_rules(store, a):
    return _rule_op(store, a, "disable")


# ── metric streams ─────────────────────────────────────────────────────────
def _filters(v, name: str) -> list[dict]:
    out = []
    for f in _list(v):
        if not f.get("Namespace"):
            raise _missing(f"{name}.Namespace")
        out.append(_clean({"Namespace": f["Namespace"], "MetricNames": [str(x) for x in _list(f.get("MetricNames"))]}))
    return out


def op_put_metric_stream(store, a):
    name = str(a.get("Name") or "")
    if not name:
        raise _missing("Name")
    if not a.get("FirehoseArn"):
        raise _missing("FirehoseArn")
    if not a.get("RoleArn"):
        raise _missing("RoleArn")
    fmt = a.get("OutputFormat")
    if not fmt:
        raise _missing("OutputFormat")
    if fmt not in ("json", "opentelemetry0.7", "opentelemetry1.0"):
        raise _invalid(f"The value {fmt} for parameter OutputFormat is invalid.")
    inc, exc = _filters(a.get("IncludeFilters"), "IncludeFilters"), _filters(a.get("ExcludeFilters"), "ExcludeFilters")
    if inc and exc:
        raise _combo("Include and exclude filters cannot both be specified.")
    now = _now()
    old = store.streams.get(name)
    store.streams[name] = {"Arn": store.stream_arn(name), "Name": name, "IncludeFilters": inc, "ExcludeFilters": exc,
                           "FirehoseArn": a["FirehoseArn"], "RoleArn": a["RoleArn"], "State": old["State"] if old else "running",
                           "CreationDate": old["CreationDate"] if old else now, "LastUpdateDate": now, "OutputFormat": fmt,
                           "StatisticsConfigurations": _list(a.get("StatisticsConfigurations")),
                           "IncludeLinkedAccountsMetrics": _b(a.get("IncludeLinkedAccountsMetrics"))}
    tags = _tag_list(a.get("Tags"))
    if tags:
        store.tags.setdefault(store.stream_arn(name), {}).update(tags)
    store.persist()
    return {"Arn": store.stream_arn(name)}


def _stream(store, a) -> dict:
    name = str(a.get("Name") or "")
    if not name:
        raise _missing("Name")
    s = store.streams.get(name)
    if not s:
        raise CwError("ResourceNotFoundException", f"Metric stream {name} does not exist.")
    return s


def op_get_metric_stream(store, a):
    s = _stream(store, a)
    return {**s, "CreationDate": Ts(s["CreationDate"]), "LastUpdateDate": Ts(s["LastUpdateDate"])}


def op_list_metric_streams(store, a):
    limit = _i(a["MaxResults"], "MaxResults") if a.get("MaxResults") is not None else 500
    rows = [{"Arn": s["Arn"], "CreationDate": Ts(s["CreationDate"]), "LastUpdateDate": Ts(s["LastUpdateDate"]), "Name": s["Name"],
             "FirehoseArn": s["FirehoseArn"], "State": s["State"], "OutputFormat": s["OutputFormat"]}
            for s in sorted(store.streams.values(), key=lambda s: s["Name"])]
    chunk, nxt = _page(rows, a.get("NextToken"), limit)
    return _clean({"Entries": chunk, "NextToken": nxt})


def op_delete_metric_stream(store, a):
    name = str(a.get("Name") or "")
    if not name:
        raise _missing("Name")
    store.streams.pop(name, None)
    store.tags.pop(store.stream_arn(name), None)
    store.persist()
    return {}


def _stream_state(store, a, state: str):
    names = [str(x) for x in _list(a.get("Names"))]
    if not names:
        raise _missing("Names")
    for n in names:
        if n not in store.streams:
            raise CwError("ResourceNotFoundException", f"Metric stream {n} does not exist.")
    for n in names:
        store.streams[n]["State"] = state
        store.streams[n]["LastUpdateDate"] = _now()
    store.persist()
    return {}


def op_start_metric_streams(store, a):
    return _stream_state(store, a, "running")


def op_stop_metric_streams(store, a):
    return _stream_state(store, a, "stopped")


# op name -> (handler, returns a Result element in Query XML)
_OPS = {
    "PutMetricData": (op_put_metric_data, False), "GetMetricStatistics": (op_get_metric_statistics, True),
    "GetMetricData": (op_get_metric_data, True), "ListMetrics": (op_list_metrics, True),
    "PutMetricAlarm": (op_put_metric_alarm, False), "PutCompositeAlarm": (op_put_composite_alarm, False),
    "DescribeAlarms": (op_describe_alarms, True), "DescribeAlarmsForMetric": (op_describe_alarms_for_metric, True),
    "DeleteAlarms": (op_delete_alarms, False), "SetAlarmState": (op_set_alarm_state, False),
    "EnableAlarmActions": (op_enable_alarm_actions, False), "DisableAlarmActions": (op_disable_alarm_actions, False),
    "DescribeAlarmHistory": (op_describe_alarm_history, True),
    "PutDashboard": (op_put_dashboard, True), "GetDashboard": (op_get_dashboard, True),
    "ListDashboards": (op_list_dashboards, True), "DeleteDashboards": (op_delete_dashboards, True),
    "TagResource": (op_tag_resource, True), "UntagResource": (op_untag_resource, True),
    "ListTagsForResource": (op_list_tags_for_resource, True),
    "PutAnomalyDetector": (op_put_anomaly_detector, True), "DescribeAnomalyDetectors": (op_describe_anomaly_detectors, True),
    "DeleteAnomalyDetector": (op_delete_anomaly_detector, True),
    "PutInsightRule": (op_put_insight_rule, True), "DescribeInsightRules": (op_describe_insight_rules, True),
    "DeleteInsightRules": (op_delete_insight_rules, True), "EnableInsightRules": (op_enable_insight_rules, True),
    "DisableInsightRules": (op_disable_insight_rules, True),
    "PutMetricStream": (op_put_metric_stream, True), "GetMetricStream": (op_get_metric_stream, True),
    "ListMetricStreams": (op_list_metric_streams, True), "DeleteMetricStream": (op_delete_metric_stream, True),
    "StartMetricStreams": (op_start_metric_streams, True), "StopMetricStreams": (op_stop_metric_streams, True),
}
OPERATIONS = sorted(_OPS)


# ── CBOR (RFC 8949 subset: what smithy-rpc-v2-cbor needs) ───────────────────
def cbor_encode(v) -> bytes:
    out = bytearray()

    def head(major: int, n: int) -> None:
        if n < 24:
            out.append(major << 5 | n)
        elif n < 0x100:
            out.extend(bytes([major << 5 | 24, n]))
        elif n < 0x10000:
            out.extend(bytes([major << 5 | 25]) + struct.pack(">H", n))
        elif n < 0x100000000:
            out.extend(bytes([major << 5 | 26]) + struct.pack(">I", n))
        else:
            out.extend(bytes([major << 5 | 27]) + struct.pack(">Q", n))

    def enc(x) -> None:
        if x is None:
            out.append(0xF6)
        elif x is True:
            out.append(0xF5)
        elif x is False:
            out.append(0xF4)
        elif isinstance(x, Ts):
            head(6, 1)
            out.append(0xFB)
            out.extend(struct.pack(">d", float(x)))
        elif isinstance(x, float):
            out.append(0xFB)
            out.extend(struct.pack(">d", x))
        elif isinstance(x, int):
            head(0, x) if x >= 0 else head(1, -1 - x)
        elif isinstance(x, (bytes, bytearray)):
            head(2, len(x))
            out.extend(x)
        elif isinstance(x, str):
            b = x.encode("utf-8")
            head(3, len(b))
            out.extend(b)
        elif isinstance(x, (list, tuple)):
            head(4, len(x))
            for i in x:
                enc(i)
        elif isinstance(x, dict):
            items = [(k, val) for k, val in x.items() if val is not None]
            head(5, len(items))
            for k, val in items:
                enc(str(k))
                enc(val)
        else:
            enc(str(x))

    enc(v)
    return bytes(out)


def cbor_decode(data: bytes):
    pos = [0]

    def take(n: int) -> bytes:
        b = data[pos[0]:pos[0] + n]
        if len(b) != n:
            raise ValueError("truncated CBOR")
        pos[0] += n
        return b

    def arg(info: int) -> int:
        if info < 24:
            return info
        return {24: lambda: take(1)[0], 25: lambda: struct.unpack(">H", take(2))[0],
                26: lambda: struct.unpack(">I", take(4))[0], 27: lambda: struct.unpack(">Q", take(8))[0]}[info]()

    def dec():
        ib = take(1)[0]
        major, info = ib >> 5, ib & 0x1F
        if major == 7:
            if info == 20:
                return False
            if info == 21:
                return True
            if info in (22, 23):
                return None
            if info == 25:
                h = struct.unpack(">H", take(2))[0]
                return struct.unpack(">e", struct.pack(">H", h))[0]
            if info == 26:
                return struct.unpack(">f", take(4))[0]
            if info == 27:
                return struct.unpack(">d", take(8))[0]
            raise ValueError("unsupported simple value")
        if info == 31:                                   # indefinite length
            if major in (2, 3):
                parts = []
                while data[pos[0]] != 0xFF:
                    parts.append(dec())
                pos[0] += 1
                return (b"" if major == 2 else "").join(parts)
            if major == 4:
                items = []
                while data[pos[0]] != 0xFF:
                    items.append(dec())
                pos[0] += 1
                return items
            if major == 5:
                m = {}
                while data[pos[0]] != 0xFF:
                    k = dec()
                    m[k] = dec()
                pos[0] += 1
                return m
            raise ValueError("bad indefinite item")
        n = arg(info)
        if major == 0:
            return n
        if major == 1:
            return -1 - n
        if major == 2:
            return take(n)
        if major == 3:
            return take(n).decode("utf-8")
        if major == 4:
            return [dec() for _ in range(n)]
        if major == 5:
            m = {}
            for _ in range(n):
                k = dec()
                m[k] = dec()
            return m
        if major == 6:
            val = dec()
            if n == 1 and isinstance(val, (int, float)):
                return float(val)                        # epoch-seconds timestamp
            if n in (2, 3) and isinstance(val, bytes):
                x = int.from_bytes(val, "big")
                return x if n == 2 else -1 - x
            return val
        raise ValueError("bad CBOR")

    return dec()


# ── wire: Query / JSON / CBOR ───────────────────────────────────────────────
def unflatten(params: dict) -> dict:
    """`Dimensions.member.1.Name=K` → {"Dimensions": [{"Name": "K"}]}."""
    tree: dict = {}
    for k, v in params.items():
        parts = k.split(".")
        node = tree
        for p in parts[:-1]:
            node = node.setdefault(p, {})
            if not isinstance(node, dict):
                break
        else:
            node[parts[-1]] = v

    def fix(n):
        if not isinstance(n, dict):
            return n
        n = {k: fix(v) for k, v in n.items()}
        if set(n) == {"member"}:
            m = n["member"]
            return m if isinstance(m, list) else [m]
        if n and all(k.isdigit() for k in n):
            return [n[k] for k in sorted(n, key=int)]
        return n
    return fix(tree)


def _x(tag: str, v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return f"<{tag}>{'true' if v else 'false'}</{tag}>"
    if isinstance(v, Ts):
        return f"<{tag}>{_iso(float(v))}</{tag}>"
    if isinstance(v, XMap):
        return f"<{tag}>" + "".join(f"<entry><key>{_xml_escape(str(k))}</key><value>{_xml_escape(repr(x) if isinstance(x, float) else str(x))}</value></entry>"
                                    for k, x in v.items() if x is not None) + f"</{tag}>"
    if isinstance(v, dict):
        return f"<{tag}>" + "".join(_x(k, x) for k, x in v.items()) + f"</{tag}>"
    if isinstance(v, list):
        return f"<{tag}>" + "".join(_x("member", i) for i in v) + f"</{tag}>"
    if isinstance(v, float):
        return f"<{tag}>{repr(v)}</{tag}>"
    return f"<{tag}>{_xml_escape(str(v))}</{tag}>"


def _query_envelope(action: str, result, has_result: bool) -> CwResponse:
    inner = ""
    if has_result:
        inner = f"<{action}Result>" + "".join(_x(k, v) for k, v in (result or {}).items()) + f"</{action}Result>"
    xml = ('<?xml version="1.0" encoding="UTF-8"?>' f'<{action}Response xmlns="{CW_NS}">{inner}'
           f'<ResponseMetadata><RequestId>{_rid()}</RequestId></ResponseMetadata></{action}Response>')
    return CwResponse(body=xml)


def _query_error(e: CwError) -> CwResponse:
    extra = "".join(_x(k, v) for k, v in e.extra.items())
    xml = ('<?xml version="1.0" encoding="UTF-8"?>' f'<ErrorResponse xmlns="{CW_NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(e.code)}</Code><Message>{_xml_escape(e.message)}</Message>{extra}</Error>'
           f'<RequestId>{_rid()}</RequestId></ErrorResponse>')
    return CwResponse(status=e.status, body=xml)


def _run(store: CloudWatchStore, action: str, args: dict):
    entry = _OPS.get(action)
    if entry is None:
        return None, None
    return entry, entry[0](store, args)


def dispatch(store: CloudWatchStore, params: dict | None = None) -> CwResponse:
    """Query protocol: form params → XML."""
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    if action not in _OPS:
        return _query_error(CwError("InvalidParameterValueException", f"Could not find operation {action} for version {params.get('Version', '2010-08-01')}"))
    args = unflatten({k: v for k, v in params.items() if k not in ("Action", "Version")})
    try:
        entry, result = _run(store, action, args)
    except CwError as e:
        return _query_error(e)
    return _query_envelope(action, result, entry[1])


def _json_error(e: CwError, protocol: str) -> tuple[int, dict, object]:
    body = {"__type": f"com.amazonaws.cloudwatch#{e.shape}" if protocol == "cbor" else e.shape, "message": e.message, **e.extra}
    return e.status, {"x-amzn-query-error": f"{e.code};Sender", "x-amzn-requestid": _rid()}, body


def wire(store: CloudWatchStore, method: str, path: str, headers: dict, body: bytes, query: dict | None = None) -> dict:
    """Serve ONE CloudWatch request on whichever protocol it arrived in.
    Returns {"status", "headers", "body": bytes}."""
    lh = {str(k).lower(): v for k, v in (headers or {}).items()}
    body = body or b""
    p = path.split("?", 1)[0]
    m = re.fullmatch(rf"/service/{TARGET_PREFIX}/operation/([A-Za-z]+)", p)
    target = lh.get("x-amz-target", "") or ""
    if m or lh.get("smithy-protocol") == "rpc-v2-cbor":
        action = m.group(1) if m else p.rsplit("/", 1)[-1]
        proto, ct = "cbor", "application/cbor"
        try:
            args = cbor_decode(body) if body else {}
        except Exception:
            args = None
    elif target.startswith(TARGET_PREFIX + "."):
        action = target.split(".", 1)[1]
        proto, ct = "json", "application/x-amz-json-1.0"
        try:
            args = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            args = None
    else:
        from urllib.parse import parse_qsl
        params = dict(query or {})
        if body:
            params.update(dict(parse_qsl(body.decode("utf-8", "ignore"), keep_blank_values=True)))
        r = dispatch(store, params)
        h = dict(r.headers or {})
        h.setdefault("content-type", "text/xml")
        return {"status": r.status, "headers": h, "body": r.body.encode("utf-8")}

    def reply(status: int, hdrs: dict, payload) -> dict:
        h = {"content-type": ct, **hdrs}
        if proto == "cbor":
            h["smithy-protocol"] = "rpc-v2-cbor"
            data = cbor_encode(payload)
        else:
            data = json.dumps(payload, default=lambda o: float(o) if isinstance(o, Ts) else str(o)).encode("utf-8")
        return {"status": status, "headers": h, "body": data}

    if not isinstance(args, dict):
        return reply(400, {}, {"__type": "SerializationException" if proto == "json" else "com.amazonaws.cloudwatch#SerializationException",
                               "message": "Could not parse the request body."})
    if action not in _OPS:
        s, h, b = _json_error(CwError("InvalidParameterValueException", f"Could not find operation {action}"), proto)
        return reply(400, {k: v for k, v in h.items() if k != "x-amzn-query-error"},
                     {**b, "__type": "UnknownOperationException" if proto == "json" else "com.amazonaws.cloudwatch#UnknownOperationException"})
    try:
        _, result = _run(store, action, args)
    except CwError as e:
        s, h, b = _json_error(e, proto)
        return reply(s, h, b)
    return reply(200, {"x-amzn-requestid": _rid()}, result if result is not None else {})


# ── console helpers (shared by the offline REST routes and the Nano adapter) ──
DEFAULT_ALARM = {"name": "my-alarm", "namespace": "AWS/EC2", "metric_name": "CPUUtilization", "statistic": "Average",
                 "period": 300, "threshold": 80, "comparison_operator": "GreaterThanOrEqualToThreshold",
                 "evaluation_periods": 1, "dimensions": "InstanceId=i-0abcd1234efgh5678",
                 "alarm_action": "arn:aws:sns:us-east-1:123456789012:alerts"}

_OP_SYMBOL = {"GreaterThanOrEqualToThreshold": ">=", "GreaterThanThreshold": ">", "LessThanThreshold": "<",
              "LessThanOrEqualToThreshold": "<=", "LessThanLowerOrGreaterThanUpperThreshold": "outside band",
              "LessThanLowerThreshold": "< lower band", "GreaterThanUpperThreshold": "> upper band"}


def _ago(t: float) -> str:
    return _iso(t)


def _row(store: CloudWatchStore, kind: str, rec: dict) -> dict:
    if kind == "CompositeAlarm":
        metric, cond, period = "Composite alarm", rec["AlarmRule"], "n/a"
    elif rec.get("Metrics"):
        metric = "Metric math: " + next((m.get("Expression") or m["MetricStat"]["Metric"]["MetricName"] for m in rec["Metrics"] if m.get("ReturnData", True)), "expression")
        thr = rec.get("Threshold")
        cond = f"{_OP_SYMBOL[rec['ComparisonOperator']]} {thr:g} for {rec['DatapointsToAlarm']} datapoints within {rec['EvaluationPeriods'] * _alarm_period(rec) // 60} minutes"
        period = f"{_alarm_period(rec)} seconds"
    else:
        metric = f"{rec['Namespace']} / {rec['MetricName']}"
        cond = (f"{rec.get('Statistic') or rec.get('ExtendedStatistic')} {rec['MetricName']} {_OP_SYMBOL[rec['ComparisonOperator']]} {rec['Threshold']:g} "
                f"for {rec['DatapointsToAlarm']} datapoints within {rec['EvaluationPeriods'] * rec['Period'] // 60} minutes")
        period = f"{rec['Period']} seconds"
    n_actions = len(rec.get("OKActions", [])) + len(rec.get("AlarmActions", [])) + len(rec.get("InsufficientDataActions", []))
    return {"name": rec["AlarmName"], "alarm_name": rec["AlarmName"], "arn": rec["AlarmArn"], "type": kind,
            "state": rec["StateValue"], "metric": metric, "condition": cond, "period": period,
            "actions": ("Enabled" if rec.get("ActionsEnabled") else "Disabled") + f" ({n_actions} configured)",
            "updated": _ago(rec["StateUpdatedTimestamp"]), "description": rec.get("AlarmDescription") or "No description"}


def console_list(store: CloudWatchStore) -> dict:
    rows = [_row(store, "MetricAlarm", r) for r in store.alarms.values()] + [_row(store, "CompositeAlarm", r) for r in store.composites.values()]
    rows.sort(key=lambda r: r["name"])
    return {"ok": True, "items": rows, "alarms": rows}


def console_get(store: CloudWatchStore, name: str) -> dict:
    kind, rec = _find_alarm(store, name)
    if rec is None:
        return {"ok": False, "code": "ResourceNotFound", "name": name}
    row = _row(store, kind, rec)
    cfg = [("Alarm name", rec["AlarmName"]), ("Type", kind), ("ARN", rec["AlarmArn"]), ("Description", row["description"]),
           ("State", rec["StateValue"]), ("State reason", rec["StateReason"]), ("Condition", row["condition"])]
    if kind == "MetricAlarm" and not rec.get("Metrics"):
        cfg += [("Namespace", rec["Namespace"]), ("Metric name", rec["MetricName"]),
                ("Dimensions", ", ".join(f"{d['Name']}={d['Value']}" for d in rec.get("Dimensions", [])) or "None"),
                ("Statistic", rec.get("Statistic") or rec.get("ExtendedStatistic")), ("Period", row["period"]),
                ("Threshold", f"{_OP_SYMBOL[rec['ComparisonOperator']]} {rec['Threshold']:g}")]
    if kind == "MetricAlarm":
        cfg += [("Evaluation periods", rec["EvaluationPeriods"]), ("Datapoints to alarm", rec["DatapointsToAlarm"]),
                ("Missing data treatment", rec["TreatMissingData"])]
    cfg.append(("Last configuration change", _ago(rec["AlarmConfigurationUpdatedTimestamp"])))
    row["details"] = [{"key": k, "value": str(v)} for k, v in cfg]
    hist = [h for h in store.history if h["AlarmName"] == name]
    row["history"] = [{"timestamp": _ago(h["Timestamp"]), "type": h["HistoryItemType"], "summary": h["HistorySummary"]}
                      for h in sorted(hist, key=lambda h: h["Timestamp"], reverse=True)]
    acts = []
    for label, key in (("In alarm", "AlarmActions"), ("OK", "OKActions"), ("Insufficient data", "InsufficientDataActions")):
        for arn in rec.get(key, []):
            acts.append({"state": label, "action": arn, "enabled": "Yes" if rec.get("ActionsEnabled") else "No"})
    row["action_list"] = acts
    row["tags"] = dict(store.tags.get(rec["AlarmArn"], {}))
    return {"ok": True, **row}


def console_create(store: CloudWatchStore, body: dict) -> dict:
    b = {**DEFAULT_ALARM, **{k: v for k, v in (body or {}).items() if v not in (None, "")}}
    name = str(b["name"]).strip()
    dims = [{"Name": k.strip(), "Value": v.strip()} for k, _, v in (p.partition("=") for p in str(b.get("dimensions") or "").split(",")) if k.strip()]
    args = {"AlarmName": name, "Namespace": b["namespace"], "MetricName": b["metric_name"], "Statistic": b["statistic"],
            "Period": b["period"], "Threshold": b["threshold"], "ComparisonOperator": b["comparison_operator"],
            "EvaluationPeriods": b["evaluation_periods"], "Dimensions": dims,
            "AlarmActions": [b["alarm_action"]] if b.get("alarm_action") else [], "AlarmDescription": b.get("description") or None}
    try:
        op_put_metric_alarm(store, args)
    except CwError as e:
        return {"ok": False, "code": e.code, "message": e.message}
    return console_get(store, name)


def console_delete(store: CloudWatchStore, name: str) -> dict:
    try:
        op_delete_alarms(store, {"AlarmNames": [name]})
    except CwError as e:
        return {"ok": False, "code": e.code, "message": e.message, "name": name}
    return {"ok": True, "name": name}
