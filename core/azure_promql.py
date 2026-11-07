"""A PromQL-subset evaluator over a stored sample set (substrate-free, pure Python; Pyodide-loadable).

Backs Azure Monitor Prometheus rule groups (core/azure_alerts_core.py): recording rules write new series, alert rules fire.

Series store (a plain dict, JSON-able):  {"series": {"<metric>{k=v,...}": {"labels": {...}, "samples": [[t, v], ...]}}}

Supported: instant selectors with =, !=, =~, !~ matchers (``__name__`` included); range selectors ``m[5m]``; functions rate,
irate, increase, delta, avg/sum/min/max/count_over_time, abs, ceil, floor, round, sqrt, clamp_min, clamp_max, vector, absent,
scalar, time; aggregations sum/avg/min/max/count/group/stddev with ``by(...)``/``without(...)`` (either position), topk/bottomk;
binary + - * / % ^ and == != > < >= <= (``bool`` modifier) between vector/scalar operands, vector-vector matching on the full
label set (``on(...)`` / ``ignoring(...)`` supported, one-to-one only); ``and`` / ``or`` / ``unless``; unary minus; parentheses;
offset on selectors. NOT supported: subqueries, histogram_quantile, label_replace/label_join, group_left/right, @ modifier.
Unsupported syntax raises PromError (never silently evaluates to something else).
"""
from __future__ import annotations

import math
import re

LOOKBACK = 300.0   # instant-vector staleness window (seconds), Prometheus default 5m


class PromError(Exception):
    pass


_DUR = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}


def parse_duration(s):
    s = str(s).strip()
    if not re.fullmatch(r"(\d+(ms|s|m|h|d|w|y))+", s):
        raise PromError(f"bad duration '{s}'")
    return sum(int(n) * _DUR[u] for n, u in re.findall(r"(\d+)(ms|s|m|h|d|w|y)", s))


def series_key(labels):
    return labels.get("__name__", "") + "{" + ",".join(f"{k}={v}" for k, v in sorted(labels.items()) if k != "__name__") + "}"


def add_sample(store, labels, t, v):
    s = store.setdefault("series", {})
    k = series_key(labels)
    ent = s.setdefault(k, {"labels": dict(labels), "samples": []})
    smp = ent["samples"]
    if smp and smp[-1][0] > t:                       # keep ordered
        smp.append([t, float(v)])
        smp.sort(key=lambda x: x[0])
    else:
        smp.append([t, float(v)])
    del smp[:-5000]


# ── tokenizer / parser ──────────────────────────────────────────────────────
_TOK = re.compile(r"""\s*(?:
 (?P<dur>(?:\d+(?:ms|s|m|h|d|w|y))+(?![a-zA-Z0-9_])) |
 (?P<num>(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|Inf|NaN)) |
 (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`) |
 (?P<id>[a-zA-Z_:][a-zA-Z0-9_:]*) |
 (?P<op>==|!=|>=|<=|=~|!~|[-+*/%^<>=(){}\[\],])
)""", re.X)

_AGGS = {"sum", "avg", "min", "max", "count", "group", "stddev", "stdvar", "topk", "bottomk"}
_KW = {"by", "without", "on", "ignoring", "bool", "offset", "and", "or", "unless", "group_left", "group_right"}
_PREC = {"or": 1, "and": 2, "unless": 2, "==": 3, "!=": 3, ">": 3, "<": 3, ">=": 3, "<=": 3, "+": 4, "-": 4, "*": 5, "/": 5, "%": 5, "^": 6}


def _tokens(src):
    out, i = [], 0
    src = src.strip()
    while i < len(src):
        m = _TOK.match(src, i)
        if not m or m.end() == i:
            raise PromError(f"unexpected character {src[i:i+10]!r}")
        i = m.end()
        for k in ("dur", "num", "str", "id", "op"):
            if m.group(k) is not None:
                out.append((k, m.group(k)))
                break
        while i < len(src) and src[i].isspace():
            i += 1
    return out


class _P:
    def __init__(self, src):
        self.t = _tokens(src)
        self.i = 0

    def peek(self, off=0):
        return self.t[self.i + off] if self.i + off < len(self.t) else (None, None)

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, v):
        k, x = self.next()
        if x != v:
            raise PromError(f"expected '{v}' got '{x}'")

    def parse(self):
        e = self.expr(0)
        if self.i != len(self.t):
            raise PromError(f"unexpected '{self.peek()[1]}'")
        return e

    def expr(self, minp):
        lhs = self.unary()
        while True:
            k, v = self.peek()
            if v not in _PREC or (k == "id" and v not in ("and", "or", "unless")):
                break
            p = _PREC[v]
            if p < minp:
                break
            self.next()
            mods = {"bool": False, "on": None, "ignoring": None}
            while self.peek()[1] in ("bool", "on", "ignoring"):
                w = self.next()[1]
                if w == "bool":
                    mods["bool"] = True
                else:
                    mods[w] = self.labels()
                    if self.peek()[1] in ("group_left", "group_right"):
                        raise PromError("group_left/group_right is not supported")
            rhs = self.expr(p if v == "^" else p + 1)
            lhs = ("bin", v, lhs, rhs, mods)
        return lhs

    def labels(self):
        self.expect("(")
        out = []
        while self.peek()[1] != ")":
            out.append(self.next()[1])
            if self.peek()[1] == ",":
                self.next()
        self.expect(")")
        return out

    def unary(self):
        k, v = self.peek()
        if v == "-":
            self.next()
            return ("neg", self.unary())
        if v == "+":
            self.next()
            return self.unary()
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            k, v = self.peek()
            if v == "[" and e[0] == "sel":
                self.next()
                d = parse_duration(self.next()[1])
                if self.peek()[1] == ":":
                    raise PromError("subqueries are not supported")
                self.expect("]")
                e = ("range", e, d)
            elif v == "offset":
                self.next()
                neg = self.peek()[1] == "-"
                if neg:
                    self.next()
                off = parse_duration(self.next()[1]) * (-1 if neg else 1)
                if e[0] == "sel":
                    e = ("sel", e[1], e[2], off)
                elif e[0] == "range":
                    s = e[1]
                    e = ("range", ("sel", s[1], s[2], off), e[2])
                else:
                    raise PromError("offset only applies to selectors")
            elif v == "@":
                raise PromError("@ modifier is not supported")
            else:
                return e

    def primary(self):
        k, v = self.next()
        if k == "num":
            return ("num", float("inf") if v == "Inf" else float("nan") if v == "NaN" else float(int(v, 16)) if v.lower().startswith("0x") else float(v))
        if k == "str":
            return ("str", v[1:-1])
        if v == "(":
            e = self.expr(0)
            self.expect(")")
            return ("paren", e)
        if k == "id" or v == "{":
            if v == "{":
                self.i -= 1
                name = None
            else:
                name = v
                if name in _AGGS:
                    return self.aggregate(name)
                if self.peek()[1] == "(":
                    return self.call(name)
            matchers = []
            if name:
                matchers.append(("__name__", "=", name))
            if self.peek()[1] == "{":
                self.next()
                while self.peek()[1] != "}":
                    ln = self.next()[1]
                    op = self.next()[1]
                    if op not in ("=", "!=", "=~", "!~"):
                        raise PromError(f"bad matcher operator '{op}'")
                    lv = self.next()[1][1:-1]
                    matchers.append((ln, op, lv))
                    if self.peek()[1] == ",":
                        self.next()
                self.expect("}")
            if not matchers:
                raise PromError("vector selector must contain at least one matcher")
            return ("sel", name, matchers, 0.0)
        raise PromError(f"unexpected '{v}'")

    def call(self, name):
        self.expect("(")
        args = []
        while self.peek()[1] != ")":
            args.append(self.expr(0))
            if self.peek()[1] == ",":
                self.next()
        self.expect(")")
        return ("call", name, args)

    def aggregate(self, name):
        by = wo = None
        if self.peek()[1] in ("by", "without"):
            w = self.next()[1]
            lab = self.labels()
            by, wo = (lab, None) if w == "by" else (None, lab)
        self.expect("(")
        args = []
        while self.peek()[1] != ")":
            args.append(self.expr(0))
            if self.peek()[1] == ",":
                self.next()
        self.expect(")")
        if self.peek()[1] in ("by", "without"):
            w = self.next()[1]
            lab = self.labels()
            by, wo = (lab, None) if w == "by" else (None, lab)
        return ("agg", name, args, by, wo)


def parse(src):
    if not str(src).strip():
        raise PromError("empty expression")
    return _P(src).parse()


# ── evaluation ──────────────────────────────────────────────────────────────
def _match(matchers, labels):
    for ln, op, lv in matchers:
        x = labels.get(ln, "")
        if op == "=" and x != lv:
            return False
        if op == "!=" and x == lv:
            return False
        if op == "=~" and not re.fullmatch(lv, x):
            return False
        if op == "!~" and re.fullmatch(lv, x):
            return False
    return True


def _inst(store, matchers, t, off):
    out = []
    for ent in (store.get("series") or {}).values():
        if not _match(matchers, ent["labels"]):
            continue
        tt = t - off
        pt = None
        for s in ent["samples"]:
            if s[0] <= tt:
                pt = s
            else:
                break
        if pt is not None and tt - pt[0] <= LOOKBACK:
            out.append((dict(ent["labels"]), pt[1]))
    return out


def _range(store, node, t):
    sel, d = node[1], node[2]
    off = sel[3]
    out = []
    for ent in (store.get("series") or {}).values():
        if _match(sel[2], ent["labels"]):
            pts = [s for s in ent["samples"] if t - off - d <= s[0] <= t - off]
            if pts:
                out.append((dict(ent["labels"]), pts, d))
    return out


def _is_scalar(v):
    return isinstance(v, float)


def _drop_name(labels):
    return {k: x for k, x in labels.items() if k != "__name__"}


def _extrap_rate(pts, d, counter, per_second, t=None, off=0.0):
    """Prometheus extrapolatedRate: increase over the window extrapolated to its edges (bounded by 1.1x the sample interval)."""
    if len(pts) < 2:
        return None
    first, last = pts[0], pts[-1]
    res = 0.0
    if counter:
        prev = first[1]
        for _, v in pts[1:]:
            res += v if v < prev else v - prev
            prev = v
    else:
        res = last[1] - first[1]
    span = last[0] - first[0]
    if span <= 0:
        return None
    end = (t if t is not None else last[0]) - off
    start = end - d
    avg = span / (len(pts) - 1)
    to_start, to_end = first[0] - start, end - last[0]
    thr = avg * 1.1
    if to_start >= thr:
        to_start = avg / 2
    if to_end >= thr:
        to_end = avg / 2
    if counter and res > 0 and first[1] >= 0:
        to_zero = span * (first[1] / res)
        to_start = min(to_start, to_zero)
    res = res * ((span + to_start + to_end) / span)
    return res / d if per_second else res


def ev(node, store, t):
    k = node[0]
    if k == "num":
        return float(node[1])
    if k == "str":
        return node[1]
    if k == "paren":
        return ev(node[1], store, t)
    if k == "neg":
        v = ev(node[1], store, t)
        return -v if _is_scalar(v) else [(_drop_name(l), -x) for l, x in v]
    if k == "sel":
        return _inst(store, node[2], t, node[3])
    if k == "range":
        raise PromError("range vector selector can only be used inside a function")
    if k == "call":
        return _call(node[1], node[2], store, t)
    if k == "agg":
        return _agg(node, store, t)
    if k == "bin":
        return _bin(node, store, t)
    raise PromError(f"cannot evaluate {k}")


_OPS = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
        "/": lambda a, b: (a / b) if b else (math.nan if a == 0 or a != a else math.copysign(math.inf, a)),
        "%": lambda a, b: math.fmod(a, b) if b else math.nan, "^": lambda a, b: a ** b}
_CMPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b, ">": lambda a, b: a > b, "<": lambda a, b: a < b,
         ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}


def _sig(labels, mods, drop_name=True):
    if mods.get("on") is not None:
        return tuple(sorted((k, labels.get(k, "")) for k in mods["on"]))
    ig = set(mods.get("ignoring") or []) | ({"__name__"} if drop_name else set())
    return tuple(sorted((k, v) for k, v in labels.items() if k not in ig))


def _bin(node, store, t):
    _, op, l, r, mods = node
    a, b = ev(l, store, t), ev(r, store, t)
    if op in ("and", "or", "unless"):
        if _is_scalar(a) or _is_scalar(b):
            raise PromError(f"'{op}' requires vector operands")
        bs = {_sig(x[0], mods) for x in b}
        if op == "and":
            return [x for x in a if _sig(x[0], mods) in bs]
        if op == "unless":
            return [x for x in a if _sig(x[0], mods) not in bs]
        asg = {_sig(x[0], mods) for x in a}
        return list(a) + [x for x in b if _sig(x[0], mods) not in asg]
    cmp = op in _CMPS
    fn = _CMPS[op] if cmp else _OPS[op]
    if _is_scalar(a) and _is_scalar(b):
        if cmp and not mods["bool"]:
            raise PromError("comparisons between scalars must use the bool modifier")
        return float(fn(a, b)) if cmp else fn(a, b)

    def one(la, x, y):
        if cmp:
            if mods["bool"]:
                return (_drop_name(la), 1.0 if fn(x, y) else 0.0)
            return (la, x) if fn(x, y) else None
        return (_drop_name(la), fn(x, y))
    out = []
    if _is_scalar(b):
        for la, x in a:
            o = one(la, x, b)
            if o:
                out.append(o)
    elif _is_scalar(a):
        for lb, y in b:
            o = one(lb, a, y)
            if o:
                if cmp and not mods["bool"]:
                    o = (lb, y)
                out.append(o)
    else:
        idx = {}
        for lb, y in b:
            s = _sig(lb, mods)
            if s in idx:
                raise PromError("many-to-many matching not allowed: matching labels must be unique on one side")
            idx[s] = (lb, y)
        for la, x in a:
            m = idx.get(_sig(la, mods))
            if m:
                o = one(la, x, m[1])
                if o:
                    out.append(o)
    return out


def _agg(node, store, t):
    _, name, args, by, wo = node
    if name in ("topk", "bottomk"):
        kk = int(ev(args[0], store, t))
        vec = ev(args[1], store, t)
        groups = {}
        for l, v in vec:
            g = _group(l, by, wo)
            groups.setdefault(g, []).append((l, v))
        out = []
        for g in groups.values():
            g.sort(key=lambda x: x[1], reverse=(name == "topk"))
            out += g[:kk]
        return out
    vec = ev(args[0], store, t)
    if _is_scalar(vec):
        raise PromError(f"{name} requires an instant vector")
    groups = {}
    for l, v in vec:
        groups.setdefault(_group(l, by, wo), []).append(v)
    out = []
    for g, vals in groups.items():
        n = len(vals)
        if name == "sum":
            r = sum(vals)
        elif name == "avg":
            r = sum(vals) / n
        elif name == "min":
            r = min(vals)
        elif name == "max":
            r = max(vals)
        elif name == "count":
            r = float(n)
        elif name == "group":
            r = 1.0
        else:
            m = sum(vals) / n
            var = sum((x - m) ** 2 for x in vals) / n
            r = math.sqrt(var) if name == "stddev" else var
        out.append((dict(g), r))
    return out


def _group(l, by, wo):
    if by is not None:
        return tuple(sorted((k, l.get(k, "")) for k in by if k in l))
    if wo is not None:
        return tuple(sorted((k, v) for k, v in l.items() if k not in wo and k != "__name__"))
    return ()


def _call(name, args, store, t):
    if name in ("rate", "irate", "increase", "delta", "avg_over_time", "sum_over_time", "min_over_time", "max_over_time",
                "count_over_time", "last_over_time", "idelta", "deriv"):
        if len(args) != 1 or args[0][0] != "range":
            raise PromError(f"{name}() requires a range vector argument")
        out = []
        for labels, pts, d in _range(store, args[0], t):
            vals = [p[1] for p in pts]
            if name in ("rate", "increase"):
                r = _extrap_rate(pts, d, True, name == "rate", t, args[0][1][3])
            elif name == "delta":
                r = _extrap_rate(pts, d, False, False, t, args[0][1][3])
            elif name == "irate":
                if len(pts) < 2:
                    continue
                dv = pts[-1][1] - pts[-2][1]
                dv = pts[-1][1] if dv < 0 else dv
                r = dv / (pts[-1][0] - pts[-2][0])
            elif name == "idelta":
                r = pts[-1][1] - pts[-2][1] if len(pts) > 1 else None
            elif name == "deriv":
                r = (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]) if len(pts) > 1 and pts[-1][0] > pts[0][0] else None
            else:
                r = {"avg_over_time": lambda: sum(vals) / len(vals), "sum_over_time": lambda: sum(vals), "min_over_time": lambda: min(vals),
                     "max_over_time": lambda: max(vals), "count_over_time": lambda: float(len(vals)), "last_over_time": lambda: vals[-1]}[name]()
            if r is not None:
                out.append((_drop_name(labels) if name != "last_over_time" else labels, r))
        return out
    if name == "time":
        return float(t)
    if name == "vector":
        return [({}, ev(args[0], store, t))]
    if name == "scalar":
        v = ev(args[0], store, t)
        return v if _is_scalar(v) else (v[0][1] if len(v) == 1 else math.nan)
    if name == "absent":
        v = ev(args[0], store, t)
        return [] if v else [({}, 1.0)]
    if name in ("abs", "ceil", "floor", "sqrt", "exp", "ln", "round", "clamp_min", "clamp_max", "clamp"):
        v = ev(args[0], store, t)
        extra = [ev(a, store, t) for a in args[1:]]
        fn = {"abs": abs, "ceil": math.ceil, "floor": math.floor, "sqrt": math.sqrt, "exp": math.exp, "ln": math.log,
              "round": (lambda x: math.floor(x / (extra[0] if extra else 1) + 0.5) * (extra[0] if extra else 1)),
              "clamp_min": lambda x: max(x, extra[0]), "clamp_max": lambda x: min(x, extra[0]),
              "clamp": lambda x: min(max(x, extra[0]), extra[1])}[name]
        if _is_scalar(v):
            return float(fn(v))
        return [(_drop_name(l), float(fn(x))) for l, x in v]
    raise PromError(f"function '{name}' is not supported")


def query(store, expr, t):
    """Evaluate ``expr`` at time ``t``. Returns a list of (labels, value) for vectors, or a float for a scalar."""
    return ev(parse(expr), store, t)
