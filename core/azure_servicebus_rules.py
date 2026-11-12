"""Azure Service Bus subscription rules — SQL filter (the SQL-92 subset Service Bus documents) and
correlation filter evaluation. Substrate-free (no socket / fastapi), loads under Pyodide.

A subscription's rules live in `sub["rules"]` = {rule_name: rule}; a subscription WITHOUT the key
behaves as if it only held the default `$Default` TrueFilter (REST-created subscriptions). A rule:
    {"type": "true"|"false"|"sql"|"correlation", "sql": str, "correlation": {...}, "action": str|None}
A message is delivered to the subscription when ANY rule matches (Service Bus semantics).

`view` is the flattened message the filters see:
    {"sys": {"Label"/"Subject", "To", "MessageId", "CorrelationId", "ContentType", "ReplyTo",
             "SessionId", "ReplyToSessionId"}, "user": {application properties}}
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"""\s*(?:
    (?P<num>\d+\.\d+|\d+)|
    (?P<str>'(?:[^']|'')*')|
    (?P<br>\[[^\]]+\])|
    (?P<id>[A-Za-z_@#$][\w.@#$]*)|
    (?P<op><>|!=|<=|>=|=|<|>|\(|\)|,|\+|-|\*|/|%)
)""", re.X)

_SYS = {"label": "Label", "subject": "Label", "to": "To", "messageid": "MessageId", "correlationid": "CorrelationId",
        "contenttype": "ContentType", "replyto": "ReplyTo", "sessionid": "SessionId", "replytosessionid": "ReplyToSessionId",
        "partitionkey": "PartitionKey"}


class FilterError(ValueError):
    pass


def _tokens(s: str):
    out, pos = [], 0
    s = s.strip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            raise FilterError("Invalid SQL expression near %r" % s[pos:pos + 12])
        pos = m.end()
        k = m.lastgroup
        v = m.group(k)
        if k == "num":
            out.append(("n", float(v) if "." in v else int(v)))
        elif k == "str":
            out.append(("s", v[1:-1].replace("''", "'")))
        elif k == "br":
            out.append(("i", v[1:-1]))
        elif k == "id":
            out.append(("i", v))
        else:
            out.append(("o", v))
    return out


class _P:
    """recursive descent -> a closure tree evaluated against a view"""

    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def kw(self, w):
        k, v = self.peek()
        return k == "i" and isinstance(v, str) and v.upper() == w

    def eat_kw(self, w):
        if self.kw(w):
            self.i += 1
            return True
        return False

    def eat_op(self, o):
        k, v = self.peek()
        if k == "o" and v == o:
            self.i += 1
            return True
        return False

    def parse(self):
        e = self.or_()
        if self.i != len(self.t):
            raise FilterError("Unexpected token %r" % (self.peek()[1],))
        return e

    def or_(self):
        a = self.and_()
        while self.eat_kw("OR"):
            b = self.and_()
            a = (lambda x, y: lambda v: bool(x(v)) or bool(y(v)))(a, b)
        return a

    def and_(self):
        a = self.not_()
        while self.eat_kw("AND"):
            b = self.not_()
            a = (lambda x, y: lambda v: bool(x(v)) and bool(y(v)))(a, b)
        return a

    def not_(self):
        if self.eat_kw("NOT"):
            a = self.not_()
            return lambda v: not a(v)
        return self.cmp()

    def cmp(self):
        left = self.add()
        k, v = self.peek()
        if k == "o" and v in ("=", "<>", "!=", "<", ">", "<=", ">="):
            self.i += 1
            right = self.add()
            return lambda vw: _compare(v, left(vw), right(vw))
        if self.kw("IS"):
            self.i += 1
            neg = self.eat_kw("NOT")
            if not self.eat_kw("NULL"):
                raise FilterError("expected NULL")
            return lambda vw: (left(vw) is not None) if neg else (left(vw) is None)
        neg = False
        if self.kw("NOT"):
            self.i += 1
            neg = True
        if self.eat_kw("IN"):
            if not self.eat_op("("):
                raise FilterError("expected ( after IN")
            items = [self.add()]
            while self.eat_op(","):
                items.append(self.add())
            if not self.eat_op(")"):
                raise FilterError("expected )")
            return lambda vw: ((left(vw) in [i(vw) for i in items]) != neg)
        if self.eat_kw("LIKE"):
            pat = self.add()
            esc = self.add() if self.eat_kw("ESCAPE") else None

            def like(vw):
                lv, pv = left(vw), pat(vw)
                if lv is None or pv is None:
                    return False
                e = esc(vw) if esc else None
                rx, i = "", 0
                pv = str(pv)
                while i < len(pv):
                    c = pv[i]
                    if e and c == e and i + 1 < len(pv):
                        rx += re.escape(pv[i + 1])
                        i += 1
                    elif c == "%":
                        rx += ".*"
                    elif c == "_":
                        rx += "."
                    else:
                        rx += re.escape(c)
                    i += 1
                return (re.fullmatch(rx, str(lv), re.S) is not None) != neg
            return like
        if neg:
            raise FilterError("expected IN or LIKE after NOT")
        return left

    def add(self):
        a = self.mul()
        while True:
            k, v = self.peek()
            if k == "o" and v in ("+", "-"):
                self.i += 1
                b = self.mul()
                a = (lambda x, y, op: lambda vw: _arith(op, x(vw), y(vw)))(a, b, v)
            else:
                return a

    def mul(self):
        a = self.atom()
        while True:
            k, v = self.peek()
            if k == "o" and v in ("*", "/", "%"):
                self.i += 1
                b = self.atom()
                a = (lambda x, y, op: lambda vw: _arith(op, x(vw), y(vw)))(a, b, v)
            else:
                return a

    def atom(self):
        k, v = self.peek()
        if k is None:
            raise FilterError("Unexpected end of expression")
        self.i += 1
        if k == "n":
            return lambda vw: v
        if k == "s":
            return lambda vw: v
        if k == "o" and v == "(":
            e = self.or_()
            if not self.eat_op(")"):
                raise FilterError("expected )")
            return e
        if k == "o" and v == "-":
            e = self.atom()
            return lambda vw: -e(vw) if isinstance(e(vw), (int, float)) else None
        if k == "i":
            up = v.upper()
            if up == "TRUE":
                return lambda vw: True
            if up == "FALSE":
                return lambda vw: False
            if up == "NULL":
                return lambda vw: None
            if up == "EXISTS" and self.eat_op("("):
                kk, name = self.peek()
                self.i += 1
                self.eat_op(")")
                return lambda vw: _lookup(vw, name) is not None
            if up in ("LEN", "UPPER", "LOWER") and self.eat_op("("):
                arg = self.add()
                self.eat_op(")")
                fn = {"LEN": lambda x: len(x) if x is not None else None, "UPPER": lambda x: str(x).upper() if x is not None else None,
                      "LOWER": lambda x: str(x).lower() if x is not None else None}[up]
                return lambda vw: fn(arg(vw))
            return lambda vw: _lookup(vw, v)
        raise FilterError("Unexpected token %r" % (v,))


def _arith(op, a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return None
    try:
        return {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else None, "%": a % b if b else None}[op]
    except Exception:
        return None


def _compare(op, a, b):
    if a is None or b is None:
        return False
    try:
        if isinstance(a, bool) != isinstance(b, bool):
            return False
        if isinstance(a, str) != isinstance(b, str):
            return False
        return {"=": a == b, "<>": a != b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    except Exception:
        return False


def _lookup(view, name):
    n = str(name)
    low = n.lower()
    if low.startswith("sys."):
        key = _SYS.get(low[4:])
        return (view.get("sys") or {}).get(key) if key else None
    if low.startswith("user."):
        n = n[5:]
    user = view.get("user") or {}
    if n in user:
        return user[n]
    for k, v in user.items():
        if str(k).lower() == n.lower():
            return v
    return None


_cache: dict = {}


def compile_sql(expr: str):
    fn = _cache.get(expr)
    if fn is None:
        fn = _P(_tokens(expr)).parse()
        if len(_cache) > 256:
            _cache.clear()
        _cache[expr] = fn
    return fn


def validate_sql(expr: str) -> None:
    compile_sql(expr)


_CORR = (("correlation_id", "CorrelationId"), ("message_id", "MessageId"), ("to", "To"), ("reply_to", "ReplyTo"),
         ("subject", "Label"), ("session_id", "SessionId"), ("reply_to_session_id", "ReplyToSessionId"),
         ("content_type", "ContentType"))


def rule_matches(rule: dict, view: dict) -> bool:
    t = rule.get("type", "true")
    if t == "true":
        return True
    if t == "false":
        return False
    if t == "sql":
        try:
            return bool(compile_sql(rule.get("sql") or "1=1")(view))
        except FilterError:
            return False
    if t == "correlation":
        c = rule.get("correlation") or {}
        for field, sysk in _CORR:
            want = c.get(field)
            if want is not None and (view.get("sys") or {}).get(sysk) != want:
                return False
        for k, want in (c.get("properties") or {}).items():
            if (view.get("user") or {}).get(k) != want:
                return False
        return True
    return False


def default_rules() -> dict:
    return {"$Default": {"type": "true", "sql": "1=1", "action": None, "name": "$Default"}}


def subscription_matches(sub: dict, view: dict) -> bool:
    rules = sub.get("rules")
    if rules is None:
        return True
    return any(rule_matches(r, view) for r in rules.values())
