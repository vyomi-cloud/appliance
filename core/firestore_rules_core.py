"""Firestore Security Rules language evaluator — substrate-independent (stdlib only).

A real parser + evaluator for the Firebase Security Rules language (rules_version '2')
as used by Cloud Firestore:

  * `service cloud.firestore { match <path> { ... } }` with nested matches, `{var}` and
    `{var=**}` captures, `allow get, list, create, update, delete, read, write [: if expr];`
  * `function f(a, b) { let x = ...; return ...; }` at service or match scope (closures over
    captured path variables), calls, recursion-free evaluation
  * expressions: `?:`, `||`, `&&`, `== != < <= > >=`, `in`, `is <type>`, `+ - * / %`, unary `! -`,
    member / index / slice / call, list + map literals, path literals `/databases/$(database)/documents/x/$(id)`
  * `request.auth.{uid,token.*}`, `request.method`, `request.time`, `request.path`,
    `request.resource.data`, `request.query.{limit,offset,orderBy}`, `resource.data/id/__name__`
  * built-ins: `get()`, `exists()`, `getAfter()`, `existsAfter()`, `path()`, `debug()`, `math.*`, `duration.*`,
    `timestamp.*`; string / list / set / map / MapDiff / timestamp / duration methods
  * error semantics: an expression that errors (null access, type mismatch, missing doc) makes the
    `allow` fail, with `||` / `&&` absorbing an error when the other side decides the result.

`compile_rules()` raises RulesError (with line/column) for syntax errors and undefined
functions; `evaluate()` returns {"allow", "matchedPath", "error", "trace"}.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone


class RulesError(Exception):
    def __init__(self, msg: str, line: int = 0, col: int = 0):
        super().__init__(msg)
        self.msg, self.line, self.col = msg, line, col

    def __str__(self):
        return f"{self.msg} (line {self.line}, col {self.col})" if self.line else self.msg


class _EvalError(Exception):
    """An expression evaluated to an error (not a parse problem)."""


# ── values ─────────────────────────────────────────────────────────────────
class Ts(datetime):
    pass


def _ts(dt: datetime) -> Ts:
    dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return Ts(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond, tzinfo=timezone.utc)


def parse_ts(s: str) -> Ts:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(.*?)(\.\d+)?([+-]\d\d:\d\d)?$", s)
    base, frac, tz = m.group(1), m.group(2) or "", m.group(3) or "+00:00"
    dt = datetime.fromisoformat(base + (frac[:7] if frac else "") + tz)
    return _ts(dt)


class Dur:
    def __init__(self, seconds: float):
        self.s = float(seconds)

    def __eq__(self, o):
        return isinstance(o, Dur) and o.s == self.s

    def __lt__(self, o): return self.s < o.s
    def __le__(self, o): return self.s <= o.s
    def __gt__(self, o): return self.s > o.s
    def __ge__(self, o): return self.s >= o.s
    def __hash__(self): return hash(self.s)


class Path:
    def __init__(self, segs):
        self.segs = tuple(segs)

    def __eq__(self, o):
        return isinstance(o, Path) and o.segs == self.segs

    def __hash__(self):
        return hash(self.segs)

    def __str__(self):
        return "/" + "/".join(self.segs)


class RSet:
    def __init__(self, items):
        self.items = []
        for i in items:
            if i not in self.items:
                self.items.append(i)

    def __eq__(self, o):
        return isinstance(o, RSet) and all(x in o.items for x in self.items) and len(o.items) == len(self.items)

    def __hash__(self):
        return len(self.items)


class MapDiff:
    def __init__(self, a: dict, b: dict):
        self.added = RSet([k for k in b if k not in a])
        self.removed = RSet([k for k in a if k not in b])
        self.changed = RSet([k for k in a if k in b and a[k] != b[k]])
        self.unch = RSet([k for k in a if k in b and a[k] == b[k]])


class LatLng:
    def __init__(self, lat, lng):
        self.lat, self.lng = lat, lng

    def __eq__(self, o):
        return isinstance(o, LatLng) and (o.lat, o.lng) == (self.lat, self.lng)

    def __hash__(self):
        return hash((self.lat, self.lng))


# ── lexer ──────────────────────────────────────────────────────────────────
_OPS3 = ()
_OPS2 = ("==", "!=", "&&", "||", "<=", ">=")
_OPS1 = "{}()[],;:.!<>/*=+-?%$@"


def _lex(src: str) -> list:
    toks = []
    i, n, line, ls = 0, len(src), 1, 0
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; ls = i + 1; i += 1; continue
        if c.isspace():
            i += 1; continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise RulesError("Unterminated comment", line, i - ls + 1)
            line += src.count("\n", i, j); i = j + 2; continue
        col = i - ls + 1
        if c in "'\"":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    esc = src[j + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(esc, esc)); j += 2
                else:
                    if src[j] == "\n":
                        raise RulesError("Unterminated string literal", line, col)
                    buf.append(src[j]); j += 1
            if j >= n:
                raise RulesError("Unterminated string literal", line, col)
            toks.append(("STR", "".join(buf), line, col)); i = j + 1; continue
        if c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            isf = False
            if j < n and src[j] == "." and j + 1 < n and src[j + 1].isdigit():
                isf = True; j += 1
                while j < n and src[j].isdigit():
                    j += 1
            toks.append(("NUM", float(src[i:j]) if isf else int(src[i:j]), line, col)); i = j; continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            toks.append(("ID", src[i:j], line, col)); i = j; continue
        if src[i:i + 2] in _OPS2:
            toks.append(("OP", src[i:i + 2], line, col)); i += 2; continue
        if c in _OPS1:
            toks.append(("OP", c, line, col)); i += 1; continue
        raise RulesError(f"Unexpected character {c!r}", line, col)
    toks.append(("EOF", None, line, n - ls + 1))
    return toks


# ── parser ─────────────────────────────────────────────────────────────────
_OPERATIONS = {"get", "list", "create", "update", "delete", "read", "write"}


class _Parser:
    def __init__(self, toks):
        self.t, self.p = toks, 0

    def peek(self, k=0):
        return self.t[min(self.p + k, len(self.t) - 1)]

    def next(self):
        tok = self.t[self.p]
        if tok[0] != "EOF":
            self.p += 1
        return tok

    def err(self, msg, tok=None):
        tok = tok or self.peek()
        return RulesError(msg, tok[2], tok[3])

    def expect(self, val):
        tok = self.next()
        if tok[1] != val:
            raise self.err(f"Expected '{val}' but found {tok[1]!r}" if tok[0] != "EOF" else f"Expected '{val}' but reached end of file", tok)
        return tok

    def accept(self, val):
        if self.peek()[1] == val and self.peek()[0] in ("OP", "ID"):
            self.next(); return True
        return False

    # -- top level
    def parse(self) -> dict:
        version = "1"
        if self.peek()[1] == "rules_version":
            self.next(); self.expect("=")
            version = self.next()[1]; self.expect(";")
        self.expect("service")
        svc = [self.next()[1]]
        while self.accept("."):
            svc.append(self.next()[1])
        if ".".join(map(str, svc)) != "cloud.firestore":
            raise self.err("Only `service cloud.firestore` is supported")
        self.expect("{")
        body = self.parse_body("}")
        self.expect("}")
        if self.peek()[0] != "EOF":
            raise self.err(f"Unexpected token {self.peek()[1]!r} after the service block")
        return {"version": str(version), "body": body}

    def parse_body(self, closer) -> dict:
        node = {"matches": [], "allows": [], "functions": {}}
        while self.peek()[1] != closer:
            tok = self.peek()
            if tok[0] == "EOF":
                raise self.err("Unexpected end of file; missing '}'")
            if tok[1] == "match":
                node["matches"].append(self.parse_match())
            elif tok[1] == "allow":
                node["allows"].append(self.parse_allow())
            elif tok[1] == "function":
                f = self.parse_function()
                node["functions"][f["name"]] = f
            else:
                raise self.err(f"Unexpected token {tok[1]!r}; expected match, allow or function")
        return node

    def parse_match(self) -> dict:
        self.expect("match")
        segs = []
        if self.peek()[1] != "/":
            raise self.err("A match path must start with '/'")
        while self.peek()[1] == "/":
            self.next()
            if self.peek()[1] == "{":
                self.next()
                name = self.next()[1]
                rec = False
                if self.accept("="):
                    self.expect("*"); self.expect("*"); rec = True
                self.expect("}")
                segs.append({"kind": "capture", "name": name, "recursive": rec})
            else:
                parts = []
                while self.peek()[1] not in ("/", "{") and self.peek()[0] != "EOF":
                    parts.append(str(self.next()[1]))
                if not parts:
                    raise self.err("Empty path segment")
                segs.append({"kind": "literal", "name": "".join(parts)})
        self.expect("{")
        body = self.parse_body("}")
        self.expect("}")
        return {"segs": segs, **body}

    def parse_allow(self) -> dict:
        tok = self.expect("allow")
        ops = []
        while True:
            op = self.next()
            if op[1] not in _OPERATIONS:
                raise self.err(f"Unknown operation {op[1]!r}; expected one of {sorted(_OPERATIONS)}", op)
            ops.append(op[1])
            if not self.accept(","):
                break
        cond = ("lit", True)
        if self.accept(":"):
            self.expect("if")
            cond = self.expr()
        self.expect(";")
        return {"ops": set(ops), "cond": cond, "line": tok[2]}

    def parse_function(self) -> dict:
        self.expect("function")
        name = self.next()[1]
        self.expect("(")
        params = []
        while self.peek()[1] != ")":
            params.append(self.next()[1])
            if not self.accept(","):
                break
        self.expect(")"); self.expect("{")
        lets = []
        while self.peek()[1] == "let":
            self.next()
            v = self.next()[1]; self.expect("=")
            lets.append((v, self.expr())); self.expect(";")
        self.expect("return")
        ret = self.expr()
        self.expect(";"); self.expect("}")
        return {"name": name, "params": params, "lets": lets, "ret": ret}

    # -- expressions (lowest -> highest precedence)
    def expr(self):
        c = self.or_()
        if self.accept("?"):
            a = self.expr(); self.expect(":"); b = self.expr()
            return ("cond", c, a, b)
        return c

    def or_(self):
        a = self.and_()
        while self.accept("||"):
            a = ("or", a, self.and_())
        return a

    def and_(self):
        a = self.rel()
        while self.accept("&&"):
            a = ("and", a, self.rel())
        return a

    def rel(self):
        a = self.add()
        while True:
            tok = self.peek()
            if tok[0] == "OP" and tok[1] in ("==", "!=", "<", "<=", ">", ">="):
                self.next(); a = ("bin", tok[1], a, self.add())
            elif tok[0] == "ID" and tok[1] == "in":
                self.next(); a = ("in", a, self.add())
            elif tok[0] == "ID" and tok[1] == "is":
                self.next(); a = ("is", a, self.next()[1])
            else:
                return a

    def add(self):
        a = self.mul()
        while self.peek()[0] == "OP" and self.peek()[1] in ("+", "-"):
            op = self.next()[1]; a = ("bin", op, a, self.mul())
        return a

    def mul(self):
        a = self.unary()
        while self.peek()[0] == "OP" and self.peek()[1] in ("*", "/", "%"):
            op = self.next()[1]; a = ("bin", op, a, self.unary())
        return a

    def unary(self):
        if self.peek()[0] == "OP" and self.peek()[1] in ("!", "-"):
            op = self.next()[1]
            return ("not" if op == "!" else "neg", self.unary())
        return self.postfix()

    def postfix(self):
        a = self.primary()
        while True:
            tok = self.peek()
            if tok[1] == "." and tok[0] == "OP":
                self.next(); a = ("member", a, self.next()[1])
            elif tok[1] == "[" and tok[0] == "OP":
                self.next()
                if self.peek()[1] == ":":
                    self.next(); hi = self.expr(); self.expect("]"); a = ("slice", a, None, hi)
                else:
                    idx = self.expr()
                    if self.accept(":"):
                        hi = None if self.peek()[1] == "]" else self.expr()
                        self.expect("]"); a = ("slice", a, idx, hi)
                    else:
                        self.expect("]"); a = ("index", a, idx)
            elif tok[1] == "(" and tok[0] == "OP":
                self.next()
                args = []
                while self.peek()[1] != ")":
                    args.append(self.expr())
                    if not self.accept(","):
                        break
                self.expect(")")
                a = ("call", a, args, tok[2], tok[3])
            else:
                return a

    def primary(self):
        tok = self.next()
        k, v = tok[0], tok[1]
        if k in ("NUM", "STR"):
            return ("lit", v)
        if k == "ID":
            if v == "true": return ("lit", True)
            if v == "false": return ("lit", False)
            if v == "null": return ("lit", None)
            return ("var", v, tok[2], tok[3])
        if v == "(":
            e = self.expr(); self.expect(")"); return e
        if v == "[":
            items = []
            while self.peek()[1] != "]":
                items.append(self.expr())
                if not self.accept(","):
                    break
            self.expect("]"); return ("list", items)
        if v == "{":
            pairs = []
            while self.peek()[1] != "}":
                key = self.expr(); self.expect(":"); pairs.append((key, self.expr()))
                if not self.accept(","):
                    break
            self.expect("}"); return ("map", pairs)
        if v == "/":                                    # path literal
            parts = []
            while True:
                if self.peek()[1] == "$":
                    self.next(); self.expect("("); parts.append(self.expr()); self.expect(")")
                else:
                    seg = []
                    while self.peek()[0] in ("ID", "NUM", "OP") and self.peek()[1] not in ("/", ")", ",", ";", "]", "}", "&&", "||", "==", "!=", "?", ":") \
                            and self.peek()[1] != "$" and (self.peek()[0] != "OP" or self.peek()[1] in ("-", ".")):
                        seg.append(str(self.next()[1]))
                    if not seg:
                        raise self.err("Empty path segment in path literal")
                    parts.append(("lit", "".join(seg)))
                if self.peek()[1] == "/":
                    self.next(); continue
                break
            return ("path", parts)
        raise self.err(f"Unexpected token {v!r}" if k != "EOF" else "Unexpected end of file in expression", tok)


# ── static checks ──────────────────────────────────────────────────────────
_GLOBALS = {"request", "resource", "math", "duration", "timestamp", "hashing", "latlng", "debug", "get", "exists", "getAfter",
            "existsAfter", "path", "string", "int", "float", "bool", "database"}


def _walk(node, fn):
    if isinstance(node, tuple):
        fn(node)
        for c in node[1:]:
            _walk(c, fn)
    elif isinstance(node, list):
        for c in node:
            _walk(c, fn)


def _check_scope(node: dict, funcs: set, issues: list) -> None:
    funcs = funcs | set(node["functions"])
    def chk_expr(e, local):
        def f(n):
            if n[0] == "call" and isinstance(n[1], tuple) and n[1][0] == "var":
                name = n[1][1]
                if name not in funcs and name not in _GLOBALS and name not in local:
                    issues.append(RulesError(f"Unknown function: {name}.", n[3], n[4]))
        _walk(e, f)
    for fn in node["functions"].values():
        local = set(fn["params"]) | {v for v, _ in fn["lets"]}
        for _, e in fn["lets"]:
            chk_expr(e, local)
        chk_expr(fn["ret"], local)
    for a in node["allows"]:
        chk_expr(a["cond"], set())
    for m in node["matches"]:
        _check_scope(m, funcs, issues)


def compile_rules(src: str) -> dict:
    """Parse + statically check. Raises RulesError (first issue)."""
    ast = _Parser(_lex(src)).parse()
    issues: list = []
    _check_scope(ast["body"], set(), issues)
    if issues:
        raise issues[0]
    return ast


def validate(src: str) -> list:
    """-> list of {severity,description,sourcePosition} (empty when valid)."""
    try:
        ast = _Parser(_lex(src)).parse()
    except RulesError as e:
        return [{"severity": "ERROR", "description": e.msg, "sourcePosition": {"line": e.line, "column": e.col}}]
    issues: list = []
    _check_scope(ast["body"], set(), issues)
    return [{"severity": "ERROR", "description": e.msg, "sourcePosition": {"line": e.line, "column": e.col}} for e in issues]


# ── evaluator ──────────────────────────────────────────────────────────────
class _Env:
    def __init__(self, vars_, funcs, parent=None):
        self.vars, self.funcs, self.parent = vars_, funcs, parent

    def lookup(self, name):
        e = self
        while e:
            if name in e.vars:
                return True, e.vars[name]
            e = e.parent
        return False, None

    def func(self, name):
        e = self
        while e:
            if name in e.funcs:
                return e.funcs[name], e
            e = e.parent
        return None, None


class _Ctx:
    """Per-evaluation context: callbacks for get()/exists() and a read budget."""
    def __init__(self, fetch, fetch_after=None, limit=10):
        self.fetch, self.fetch_after, self.reads, self.limit = fetch, fetch_after or fetch, 0, limit


def _type_of(v) -> str:
    if v is None: return "null"
    if isinstance(v, bool): return "bool"
    if isinstance(v, int): return "int"
    if isinstance(v, float): return "float"
    if isinstance(v, str): return "string"
    if isinstance(v, Ts): return "timestamp"
    if isinstance(v, Dur): return "duration"
    if isinstance(v, Path): return "path"
    if isinstance(v, LatLng): return "latlng"
    if isinstance(v, bytes): return "bytes"
    if isinstance(v, RSet): return "set"
    if isinstance(v, list): return "list"
    if isinstance(v, dict): return "map"
    return "other"


def _is(v, t: str) -> bool:
    ty = _type_of(v)
    if t == "number":
        return ty in ("int", "float")
    if t == "constraint":
        return False
    return ty == t or (t == "list" and ty == "set" and False)


def _truthy(v):
    if not isinstance(v, bool):
        raise _EvalError("Expected a boolean")
    return v


def _ev(n, env: _Env, cx: _Ctx):
    k = n[0]
    if k == "lit":
        return n[1]
    if k == "var":
        ok, v = env.lookup(n[1])
        if not ok:
            raise _EvalError(f"Undefined variable {n[1]}")
        return v
    if k == "list":
        return [_ev(x, env, cx) for x in n[1]]
    if k == "map":
        return {str(_ev(a, env, cx)): _ev(b, env, cx) for a, b in n[1]}
    if k == "path":
        segs = []
        for p in n[1]:
            v = _ev(p, env, cx)
            if isinstance(v, Path):
                segs += list(v.segs)
            else:
                segs += [s for s in str(v).split("/") if s]
        return Path(segs)
    if k == "not":
        return not _truthy(_ev(n[1], env, cx))
    if k == "neg":
        v = _ev(n[1], env, cx)
        if _type_of(v) not in ("int", "float"):
            raise _EvalError("Cannot negate a non-number")
        return -v
    if k == "and":
        try:
            a = _truthy(_ev(n[1], env, cx))
        except _EvalError:
            if _ev_bool_safe(n[2], env, cx) is False:
                return False
            raise
        if not a:
            return False
        return _truthy(_ev(n[2], env, cx))
    if k == "or":
        try:
            a = _truthy(_ev(n[1], env, cx))
        except _EvalError:
            if _ev_bool_safe(n[2], env, cx) is True:
                return True
            raise
        if a:
            return True
        return _truthy(_ev(n[2], env, cx))
    if k == "cond":
        return _ev(n[2], env, cx) if _truthy(_ev(n[1], env, cx)) else _ev(n[3], env, cx)
    if k == "is":
        return _is(_ev(n[1], env, cx), n[2])
    if k == "in":
        a, b = _ev(n[1], env, cx), _ev(n[2], env, cx)
        if isinstance(b, dict):
            return str(a) in b if isinstance(a, str) else False
        if isinstance(b, RSet):
            return a in b.items
        if isinstance(b, list):
            return a in b
        raise _EvalError("Right side of `in` must be a list, set or map")
    if k == "bin":
        return _binop(n[1], _ev(n[2], env, cx), _ev(n[3], env, cx))
    if k == "member":
        return _member(_ev(n[1], env, cx), n[2])
    if k == "index":
        o, i = _ev(n[1], env, cx), _ev(n[2], env, cx)
        if isinstance(o, dict):
            if str(i) not in o:
                raise _EvalError(f"Key {i!r} not found")
            return o[str(i)]
        if isinstance(o, list) and isinstance(i, int) and not isinstance(i, bool):
            if not -len(o) <= i < len(o):
                raise _EvalError("List index out of range")
            return o[i]
        raise _EvalError("Invalid index operation")
    if k == "slice":
        o = _ev(n[1], env, cx)
        lo = _ev(n[2], env, cx) if n[2] else 0
        hi = _ev(n[3], env, cx) if n[3] else None
        if isinstance(o, (list, str)):
            return o[lo:hi]
        raise _EvalError("Cannot slice this value")
    if k == "call":
        return _call(n, env, cx)
    raise _EvalError(f"Unsupported expression {k}")


def _ev_bool_safe(n, env, cx):
    try:
        return _truthy(_ev(n, env, cx))
    except _EvalError:
        return None


def _binop(op, a, b):
    ta, tb = _type_of(a), _type_of(b)
    if op == "==":
        return a == b if ta == tb or {ta, tb} <= {"int", "float"} else False
    if op == "!=":
        return not (a == b) if ta == tb or {ta, tb} <= {"int", "float"} else True
    if op in ("<", "<=", ">", ">="):
        num = {"int", "float"}
        if not (ta == tb or {ta, tb} <= num) or ta in ("null", "map", "list", "bool"):
            raise _EvalError(f"Cannot compare {ta} with {tb}")
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if op == "+":
        if ta == tb == "string" or ta == tb == "list":
            return a + b
        if ta == "timestamp" and tb == "duration":
            return _ts(a + timedelta(seconds=b.s))
        if ta == "duration" and tb == "timestamp":
            return _ts(b + timedelta(seconds=a.s))
        if ta == tb == "duration":
            return Dur(a.s + b.s)
        if ta == "path" and tb == "path":
            return Path(a.segs + b.segs)
        if ta in ("int", "float") and tb in ("int", "float"):
            return a + b
        raise _EvalError(f"Cannot add {ta} and {tb}")
    if op == "-":
        if ta == "timestamp" and tb == "timestamp":
            return Dur((a - b).total_seconds())
        if ta == "timestamp" and tb == "duration":
            return _ts(a - timedelta(seconds=b.s))
        if ta == tb == "duration":
            return Dur(a.s - b.s)
        if ta in ("int", "float") and tb in ("int", "float"):
            return a - b
        raise _EvalError(f"Cannot subtract {tb} from {ta}")
    if ta in ("int", "float") and tb in ("int", "float"):
        if op == "*":
            return a * b
        if b == 0:
            raise _EvalError("Division by zero")
        if op == "/":
            return a // b if ta == tb == "int" and (a % b == 0) else (int(a / b) if ta == tb == "int" else a / b)
        if op == "%":
            return int(math.fmod(a, b)) if ta == tb == "int" else math.fmod(a, b)
    raise _EvalError(f"Unsupported operands for {op}")


def _member(o, name):
    if isinstance(o, dict):
        if name in o:
            return o[name]
        raise _EvalError(f"Field {name!r} does not exist")
    raise _EvalError(f"Cannot read .{name} of {_type_of(o)}")


def _call(n, env, cx):
    callee, argn = n[1], n[2]
    args = [_ev(a, env, cx) for a in argn]
    if callee[0] == "var":
        name = callee[1]
        fn, fenv = env.func(name)
        if fn is not None:
            if len(args) != len(fn["params"]):
                raise _EvalError(f"Function {name} expects {len(fn['params'])} arguments")
            local = _Env(dict(zip(fn["params"], args)), {}, fenv)
            for v, e in fn["lets"]:
                local.vars[v] = _ev(e, local, cx)
            return _ev(fn["ret"], local, cx)
        return _global_call(name, args, cx)
    if callee[0] == "member":
        recv_node, mname = callee[1], callee[2]
        if recv_node[0] == "var" and recv_node[1] in ("math", "duration", "timestamp", "hashing", "latlng") \
                and not env.lookup(recv_node[1])[0]:
            return _namespace_call(recv_node[1], mname, args)
        return _method(_ev(recv_node, env, cx), mname, args)
    raise _EvalError("Not callable")


def _doc_value(d):
    if d is None:
        return None
    return d


def _path_rel(p, args_ok=True) -> str:
    if not isinstance(p, Path):
        raise _EvalError("Expected a path")
    segs = list(p.segs)
    if len(segs) >= 3 and segs[0] == "databases" and segs[2] == "documents":
        segs = segs[3:]
    return "/".join(segs)


def _global_call(name, args, cx: _Ctx):
    if name in ("get", "exists", "getAfter", "existsAfter"):
        if len(args) != 1:
            raise _EvalError(f"{name}() takes one path argument")
        cx.reads += 1
        if cx.reads > cx.limit:
            raise _EvalError("Exceeded maximum number of document reads in rules evaluation")
        rel = _path_rel(args[0])
        d = (cx.fetch_after if name.endswith("After") else cx.fetch)(rel)
        if name.startswith("exists"):
            return d is not None
        if d is None:
            raise _EvalError(f"Document {rel} does not exist")
        return d
    if name == "debug":
        return args[0] if args else None
    if name == "path":
        return Path([s for s in str(args[0]).split("/") if s])
    if name == "string":
        v = args[0]
        return v if isinstance(v, str) else ("true" if v is True else "false" if v is False else str(v))
    if name == "int":
        return int(float(args[0]))
    if name == "float":
        return float(args[0])
    if name == "bool":
        return bool(args[0])
    raise _EvalError(f"Unknown function {name}")


def _namespace_call(ns, name, args):
    if ns == "math":
        f = {"abs": abs, "ceil": math.ceil, "floor": math.floor, "round": lambda x: int(math.floor(x + .5)),
             "sqrt": math.sqrt, "pow": math.pow, "log": math.log, "isInfinite": math.isinf, "isNaN": math.isnan}.get(name)
        if not f:
            raise _EvalError(f"Unknown math.{name}")
        return f(*args)
    if ns == "duration":
        if name == "value":
            unit = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1, "ms": .001, "ns": 1e-9}.get(args[1])
            if unit is None:
                raise _EvalError("Unknown duration unit")
            return Dur(args[0] * unit)
        if name == "abs":
            return Dur(abs(args[0].s))
    if ns == "timestamp":
        if name == "date":
            return _ts(datetime(args[0], args[1], args[2]))
        if name == "value":
            return _ts(datetime.fromtimestamp(args[0] / 1000, timezone.utc))
    if ns == "hashing":
        import hashlib
        data = args[0].encode() if isinstance(args[0], str) else bytes(args[0])
        return {"md5": hashlib.md5, "sha256": hashlib.sha256}[name](data).hexdigest()
    if ns == "latlng" and name == "value":
        return LatLng(args[0], args[1])
    raise _EvalError(f"Unknown function {ns}.{name}")


def _method(o, name, a):
    t = _type_of(o)
    if t == "string":
        if name == "size": return len(o)
        if name == "matches":
            try:
                return re.fullmatch(a[0], o) is not None
            except re.error:
                raise _EvalError("Invalid regular expression")
        if name == "split": return o.split(a[0])
        if name == "lower": return o.lower()
        if name == "upper": return o.upper()
        if name == "trim": return o.strip()
        if name == "replace": return o.replace(a[0], a[1])
        if name == "toUtf8": return o.encode()
    if t in ("list", "set"):
        items = o.items if t == "set" else o
        other = lambda x: x.items if isinstance(x, RSet) else x
        if name == "size": return len(items)
        if name == "hasAll": return all(x in items for x in other(a[0]))
        if name == "hasAny": return any(x in items for x in other(a[0]))
        if name == "hasOnly": return all(x in other(a[0]) for x in items)
        if name == "concat" and t == "list": return items + list(a[0])
        if name == "join" and t == "list": return a[0].join(str(x) for x in items)
        if name == "removeAll" and t == "list": return [x for x in items if x not in other(a[0])]
        if name == "toSet": return RSet(items)
        if name == "union": return RSet(items + other(a[0]))
        if name == "intersection": return RSet([x for x in items if x in other(a[0])])
        if name == "difference": return RSet([x for x in items if x not in other(a[0])])
    if t == "map":
        if name == "size": return len(o)
        if name == "keys": return RSet(list(o.keys()))
        if name == "values": return list(o.values())
        if name == "get": return o.get(str(a[0]), a[1] if len(a) > 1 else None) if (str(a[0]) in o or len(a) > 1) else (_ for _ in ()).throw(_EvalError("Missing key"))
        if name == "diff": return MapDiff(o, a[0])
    if t == "other" and isinstance(o, MapDiff):
        if name == "addedKeys": return o.added
        if name == "removedKeys": return o.removed
        if name == "changedKeys": return o.changed
        if name == "unchangedKeys": return o.unch
        if name == "affectedKeys": return RSet(o.added.items + o.removed.items + o.changed.items)
    if t == "timestamp":
        f = {"toMillis": lambda: int(o.timestamp() * 1000), "seconds": lambda: o.second, "year": lambda: o.year,
             "month": lambda: o.month, "day": lambda: o.day, "hours": lambda: o.hour, "minutes": lambda: o.minute,
             "dayOfWeek": lambda: o.isoweekday(), "dayOfYear": lambda: o.timetuple().tm_yday,
             "date": lambda: _ts(o.replace(hour=0, minute=0, second=0, microsecond=0)),
             "time": lambda: Dur(o.hour * 3600 + o.minute * 60 + o.second)}.get(name)
        if f: return f()
    if t == "duration":
        if name == "seconds": return int(o.s)
        if name == "nanos": return int(round((o.s - int(o.s)) * 1e9))
    if t == "path" and name == "bind":
        return Path([str(a[0].get(s[1:], s)) if isinstance(s, str) and s.startswith("$") else s for s in o.segs])
    if t == "latlng":
        if name == "distance":
            return 0.0
        if name == "latitude": return o.lat
        if name == "longitude": return o.lng
    if t == "int" or t == "float":
        pass
    raise _EvalError(f"Unknown method {name} on {t}")


# ── pattern matching + driver ──────────────────────────────────────────────
_ALIASES = {"get": {"get", "read"}, "list": {"list", "read"}, "create": {"create", "write"},
            "update": {"update", "write"}, "delete": {"delete", "write"}}


def _desc(prefix):
    return "/" + "/".join(("{" + s["name"] + ("=**" if s["recursive"] else "") + "}") if s["kind"] == "capture" else s["name"] for s in prefix)


def evaluate(ast_or_src, *, method: str, rel_path: str, db: str = "(default)", request: dict, resource, fetch=None,
             fetch_after=None, limit: int = 10) -> dict:
    """Evaluate the ruleset for ONE operation on document/collection `rel_path` (relative to
    .../documents). `request` and `resource` are plain Python values (maps/lists/str/...);
    `resource` is {"data":...,"id":...,"__name__":...} or None when the doc doesn't exist."""
    try:
        ast = compile_rules(ast_or_src) if isinstance(ast_or_src, str) else ast_or_src
    except RulesError as e:
        return {"allow": False, "matchedPath": None, "error": f"Rules did not parse: {e}", "trace": []}
    path = ["databases", db, "documents"] + [s for s in rel_path.split("/") if s]
    wanted = _ALIASES.get(method, {method})
    cx = _Ctx(fetch or (lambda rel: None), fetch_after, limit)
    top = ast["body"]
    base = _Env({"request": request, "resource": resource, "database": db}, top["functions"])
    trace, best = [], None

    def walk_match(m, menv, mp, offset):
        nonlocal best
        scope = _Env({}, m["functions"], menv)
        if offset == len(path):
            for rule in m["allows"]:
                if not (rule["ops"] & wanted):
                    continue
                d = _desc(mp)
                try:
                    ok = _truthy(_ev(rule["cond"], scope, cx))
                    err = None
                except _EvalError as e:
                    ok, err = False, str(e)
                trace.append({"path": d, "line": rule["line"], "ops": sorted(rule["ops"]), "result": ok, **({"error": err} if err else {})})
                if ok:
                    return {"allow": True, "matchedPath": d, "error": None}
                best = best or {"allow": False, "matchedPath": d, "error": err}
        for sub in m["matches"]:
            caps, used = _prefix_match(sub["segs"], path[offset:])
            if caps is None:
                continue
            r = walk_match(sub, _Env(dict(caps), {}, scope), mp + sub["segs"], offset + used)
            if r:
                return r
        return None

    r = None
    for m in top["matches"]:
        caps, used = _prefix_match(m["segs"], path)
        if caps is None:
            continue
        r = walk_match(m, _Env(dict(caps), {}, base), m["segs"], used)
        if r:
            break
    out = dict(r or best or {"allow": False, "matchedPath": None, "error": None})
    out["trace"] = trace
    return out


def _prefix_match(segs, path):
    """Match `segs` against the START of `path` -> (captures, segments consumed) or (None, 0).
    A `{x=**}` capture consumes zero or more segments; a trailing one consumes the rest."""
    if not segs:
        return {}, 0
    s, rest = segs[0], segs[1:]
    if s["kind"] == "capture" and s["recursive"]:
        if not rest:
            return {s["name"]: Path(path)}, len(path)
        for k in range(len(path) + 1):
            caps, used = _prefix_match(rest, path[k:])
            if caps is not None:
                return {**caps, s["name"]: Path(path[:k])}, k + used
        return None, 0
    if not path:
        return None, 0
    if s["kind"] == "literal":
        if path[0] != s["name"]:
            return None, 0
        caps = {}
    else:
        caps = {s["name"]: path[0]}
    c2, u2 = _prefix_match(rest, path[1:])
    if c2 is None:
        return None, 0
    return {**caps, **c2}, 1 + u2


# ── typed Firestore Value <-> rules value ──────────────────────────────────
def from_fs_value(v):
    if not isinstance(v, dict) or not v:
        return None
    (kind, val), = v.items()
    if kind == "nullValue": return None
    if kind == "booleanValue": return bool(val)
    if kind == "integerValue": return int(val)
    if kind == "doubleValue": return float(val)
    if kind == "stringValue": return val
    if kind == "timestampValue":
        try:
            return parse_ts(val)
        except Exception:
            return val
    if kind == "mapValue": return {k: from_fs_value(x) for k, x in (val.get("fields") or {}).items()}
    if kind == "arrayValue": return [from_fs_value(x) for x in (val.get("values") or [])]
    if kind == "geoPointValue": return LatLng(val.get("latitude", 0), val.get("longitude", 0))
    if kind == "referenceValue":
        m = re.search(r"/documents/(.*)$", str(val))
        return Path([s for s in (m.group(1) if m else str(val)).split("/") if s])
    return val


def fields_to_data(fields: dict) -> dict:
    return {k: from_fs_value(v) for k, v in (fields or {}).items()}


def from_json(v):
    """Plain JSON (as typed in the console playground) -> rules values; ISO strings stay strings."""
    return v
