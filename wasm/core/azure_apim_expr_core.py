# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure API Management policy EXPRESSIONS: a safe interpreter for the useful subset of the C# the gateway evaluates in
``@(expression)`` and ``@{ statements }`` (substrate-free, pure Python, no ``eval``; Pyodide-loadable).

``evaluate(text, env)`` takes the attribute text of a policy (``@(...)``, ``@{...}`` or a literal) and the ``context`` object model
built by ``core/azure_apim_gateway_core``.

Supported (everything else raises ``ExprError`` -> the gateway answers 500 "Expression evaluation failed", never a silent pass):
* literals: strings (``"a\\n"``, verbatim ``@"a""b"``), chars, ints, doubles, true/false/null; ``$"..{x}.."`` interpolation
* operators: ``! - * / % + - < > <= >= == != && || ?? ?: ?. [] ()``, casts ``(string)(int)(bool)(double)(long)``, lambdas ``x => ...``,
  ``new string[] {..}`` / ``new string[0]`` / ``new List<string>()`` as array literals
* statements (``@{ }``): ``var/string/int/bool/... x = e;``, ``x = e;``, ``return e;``, ``if/else``, ``foreach (var x in e)``, ``{ }`` blocks
* context: ``context.Request`` (Method, Url.Path/Host/Port/Scheme/Query/QueryString, Headers[...]/GetValueOrDefault/ContainsKey, Body.As<string|JObject|JArray|JToken>(),
  IpAddress, MatchedParameters), ``context.Response`` (outbound), ``context.Subscription`` (Id, Name), ``context.User`` (null without a user),
  ``context.Api``, ``context.Operation``, ``context.Deployment``, ``context.Variables`` (indexer / GetValueOrDefault / ContainsKey), ``context.LastError``
* ``string`` helpers (Contains StartsWith EndsWith Equals ToLower ToUpper Trim Split Substring Replace IndexOf Length PadLeft ...),
  ``string.IsNullOrEmpty/IsNullOrWhiteSpace/Join/Format``, ``Regex.IsMatch/Match/Replace``, ``Convert.ToInt32/ToString``, ``int.Parse``, ``Uri.EscapeDataString``,
  ``Guid.NewGuid()``, ``DateTime.UtcNow``, LINQ on arrays (First Last Any All Count Contains Select Where Skip Take Distinct ToArray ToList Sum)
* JWT: ``header.AsJwt()`` (``Claims`` dictionary of string[], ``Subject``, ``Issuer``, ``Audiences``, ``ExpirationTime``, ``Id``) - the signature is NOT verified here
  (that is validate-jwt / validate-azure-ad-token); JObject (``body.As<JObject>()["k"]``, ``Value<T>("k")``), arrays
Not supported: classes, generics beyond ``As<T>`` / ``GetValueOrDefault<T>``, other ``new`` expressions, async/await, reflection, the full BCL.
"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid


class ExprError(Exception):
    pass


class _Return(Exception):
    def __init__(self, v):
        self.v = v


# -- value model ---------------------------------------------------------------------------------------------
class Obj:
    """A context object: PascalCase attributes (values or zero-arg callables) and methods taking (args[, type-arg])."""

    def __init__(self, attrs=None, methods=None, name="Obj"):
        self.attrs, self.methods, self.name = attrs or {}, methods or {}, name


class Jwt(Obj):
    pass


class Match:
    def __init__(self, m):
        self.m = m


class CsDate:
    def __init__(self, t):
        self.t = t


def cs_str(v) -> str:
    if v is None:
        return ""
    if v is True:
        return "True"
    if v is False:
        return "False"
    if isinstance(v, float):
        return repr(int(v)) if v == int(v) else repr(v)
    if isinstance(v, (list, tuple)):
        return "System.String[]"
    if isinstance(v, dict):
        return json.dumps(v, separators=(",", ":"))
    if isinstance(v, CsDate):
        return time.strftime("%m/%d/%Y %H:%M:%S", time.gmtime(v.t))
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


def headers_obj(hd: dict) -> Obj:
    low = {str(k).lower(): v for k, v in hd.items()}

    def gv(args):
        return low.get(str(args[0]).lower(), args[1] if len(args) > 1 else None)

    def idx(k):
        v = low.get(str(k).lower())
        if v is None:
            raise ExprError(f"The given key '{k}' was not present in the dictionary.")
        return [v]
    o = Obj({"Count": len(low), "Keys": list(low)}, {"GetValueOrDefault": gv, "ContainsKey": lambda a: str(a[0]).lower() in low}, "Headers")
    o.index = idx
    return o


def dict_obj(d: dict, name="Dictionary") -> Obj:
    def idx(k):
        if k not in d:
            raise ExprError(f"The given key '{k}' was not present in the dictionary.")
        return d[k]
    o = Obj({"Count": len(d), "Keys": list(d), "Values": list(d.values())},
            {"GetValueOrDefault": lambda a: d.get(a[0], a[1] if len(a) > 1 else None), "ContainsKey": lambda a: a[0] in d}, name)
    o.index = idx
    return o


def body_obj(raw: bytes) -> Obj:
    def as_(args, targ=None):
        t = (targ or "string").lower()
        if t in ("string", "system.string"):
            return raw.decode("utf-8", "replace")
        if t in ("byte[]", "bytes"):
            return raw
        try:
            return json.loads(raw.decode("utf-8") or "null")
        except ValueError as e:
            raise ExprError(f"body is not valid JSON: {e}")
    return Obj({"ContentType": ""}, {"As": as_}, "Body")


def jwt_obj(token: str):
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    try:
        h, p, _ = token.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        hdr = json.loads(base64.urlsafe_b64decode(pad(h)))
        cl = json.loads(base64.urlsafe_b64decode(pad(p)))
    except Exception:
        return None
    claims = {k: [str(x) for x in v] if isinstance(v, list) else [v if isinstance(v, str) else cs_str(v)] for k, v in cl.items()}
    aud = cl.get("aud")
    return Jwt({"Claims": dict_obj(claims, "Claims"), "Subject": cl.get("sub"), "Issuer": cl.get("iss"),
                "Audiences": aud if isinstance(aud, list) else ([aud] if aud else []), "Id": cl.get("jti"), "Type": hdr.get("typ"),
                "Algorithm": hdr.get("alg"), "ExpirationTime": CsDate(float(cl["exp"])) if "exp" in cl else None,
                "NotBefore": CsDate(float(cl["nbf"])) if "nbf" in cl else None, "IssuedAt": CsDate(float(cl["iat"])) if "iat" in cl else None}, {}, "Jwt")


# -- tokenizer -----------------------------------------------------------------------------------------------
_OPS = ["=>", "??", "?.", "&&", "||", "==", "!=", "<=", ">=", "<", ">", "+", "-", "*", "/", "%", "!", "?", ":", ".", ",", "(", ")", "[", "]", "{", "}", ";", "="]


def _tokenize(src: str):
    i, n, out = 0, len(src), []
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        interp = False
        if c == "$" and i + 1 < n and src[i + 1] == '"':
            interp, i, c = True, i + 1, '"'
        if c == "@" and i + 1 < n and src[i + 1] == '"':
            j, buf = i + 2, []
            while j < n:
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(src[j])
                j += 1
            out.append(("STR", "".join(buf)))
            i = j + 1
            continue
        if c == '"' or c == "'":
            q, j, buf = c, i + 1, []
            while j < n and src[j] != q:
                if src[j] == "\\" and j + 1 < n:
                    buf.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(src[j + 1], src[j + 1]))
                    j += 2
                else:
                    buf.append(src[j])
                    j += 1
            if j >= n:
                raise ExprError("unterminated string literal")
            out.append(("ISTR" if interp else "STR", "".join(buf)))
            i = j + 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = re.match(r"\d+\.\d+([eE][+-]?\d+)?|\d+[eE][+-]?\d+|\.\d+|\d+", src[i:])
            t = m.group(0)
            i += len(t)
            if i < n and src[i] in "LlFfDdMm":
                i += 1
            out.append(("NUM", float(t) if any(x in t for x in ".eE") else int(t)))
            continue
        if c.isalpha() or c == "_":
            m = re.match(r"[A-Za-z_][A-Za-z_0-9]*", src[i:])
            out.append(("ID", m.group(0)))
            i += len(m.group(0))
            continue
        for op in _OPS:
            if src.startswith(op, i):
                out.append(("OP", op))
                i += len(op)
                break
        else:
            raise ExprError(f"unexpected character {c!r}")
    out.append(("EOF", None))
    return out


# -- parser (tuples) -----------------------------------------------------------------------------------------
_TYPES = {"string", "int", "long", "double", "bool", "float", "decimal", "object", "var", "JObject", "JArray", "JToken", "DateTime", "Guid", "byte", "char", "short"}
_CASTS = ("string", "int", "long", "double", "bool", "float", "decimal", "object")


class _P:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def next(self):
        v = self.t[self.i]
        self.i += 1
        return v

    def isop(self, op, k=0):
        t = self.peek(k)
        return t[0] == "OP" and t[1] == op

    def eat(self, op):
        if self.isop(op):
            self.i += 1
            return True
        return False

    def need(self, op):
        if not self.eat(op):
            raise ExprError(f"expected {op!r} but found {self.peek()[1]!r}")

    def program(self):
        stmts = []
        while self.peek()[0] != "EOF":
            stmts.append(self.stmt())
        return ("block", stmts)

    def block_or_stmt(self):
        if self.isop("{"):
            self.next()
            stmts = []
            while not self.isop("}"):
                if self.peek()[0] == "EOF":
                    raise ExprError("missing }")
                stmts.append(self.stmt())
            self.next()
            return ("block", stmts)
        return self.stmt()

    def stmt(self):
        t = self.peek()
        if t == ("ID", "return"):
            self.next()
            e = None if self.isop(";") else self.expr()
            self.need(";")
            return ("return", e)
        if t == ("ID", "if"):
            self.next()
            self.need("(")
            c = self.expr()
            self.need(")")
            a = self.block_or_stmt()
            b = None
            if self.peek() == ("ID", "else"):
                self.next()
                b = self.block_or_stmt()
            return ("if", c, a, b)
        if t == ("ID", "foreach"):
            self.next()
            self.need("(")
            self.next()
            name = self.next()[1]
            if self.next() != ("ID", "in"):
                raise ExprError("foreach needs 'in'")
            src = self.expr()
            self.need(")")
            return ("foreach", name, src, self.block_or_stmt())
        if self.isop("{"):
            return self.block_or_stmt()
        if t[0] == "ID" and t[1] in _TYPES and (self.peek(1)[0] == "ID" or (self.isop("[", 1) and self.isop("]", 2))):
            self.next()
            if self.isop("["):
                self.next()
                self.need("]")
            name = self.next()[1]
            e = None
            if self.eat("="):
                e = self.expr()
            self.need(";")
            return ("decl", name, e)
        if t[0] == "ID" and self.isop("=", 1) and not self.isop("=", 2):
            self.next()
            self.next()
            e = self.expr()
            self.need(";")
            return ("assign", t[1], e)
        e = self.expr()
        self.eat(";")
        return ("expr", e)

    def expr(self):
        c = self.coalesce()
        if self.eat("?"):
            a = self.expr()
            self.need(":")
            return ("cond", c, a, self.expr())
        return c

    def coalesce(self):
        a = self.oror()
        if self.eat("??"):
            return ("coalesce", a, self.coalesce())
        return a

    def oror(self):
        a = self.andand()
        while self.eat("||"):
            a = ("or", a, self.andand())
        return a

    def andand(self):
        a = self.equality()
        while self.eat("&&"):
            a = ("and", a, self.equality())
        return a

    def equality(self):
        a = self.relational()
        while self.isop("==") or self.isop("!="):
            op = self.next()[1]
            a = ("bin", op, a, self.relational())
        return a

    def relational(self):
        a = self.additive()
        while any(self.isop(o) for o in ("<", ">", "<=", ">=")):
            op = self.next()[1]
            a = ("bin", op, a, self.additive())
        return a

    def additive(self):
        a = self.mult()
        while self.isop("+") or self.isop("-"):
            op = self.next()[1]
            a = ("bin", op, a, self.mult())
        return a

    def mult(self):
        a = self.unary()
        while self.isop("*") or self.isop("/") or self.isop("%"):
            op = self.next()[1]
            a = ("bin", op, a, self.unary())
        return a

    def unary(self):
        if self.eat("!"):
            return ("not", self.unary())
        if self.eat("-"):
            return ("neg", self.unary())
        if self.isop("(") and self.peek(1)[0] == "ID" and self.peek(1)[1] in _CASTS and self.isop(")", 2):
            self.next()
            ty = self.next()[1]
            self.next()
            return ("cast", ty, self.unary())
        return self.postfix(self.primary())

    def args(self):
        out = []
        self.need("(")
        while not self.isop(")"):
            if self.peek()[0] == "ID" and self.isop(":", 1) and not self.isop(":", 2):
                self.next()
                self.next()          # a named argument: the name is ignored
            out.append(self.expr())
            if not self.eat(","):
                break
        self.need(")")
        return out

    def postfix(self, e):
        while True:
            if self.isop(".") or self.isop("?."):
                nullc = self.next()[1] == "?."
                name = self.next()
                if name[0] != "ID":
                    raise ExprError("member name expected")
                targ = None
                if self.isop("<") and self.peek(1)[0] == "ID" and self.isop(">", 2) and self.isop("(", 3):
                    self.next()
                    targ = self.next()[1]
                    self.next()
                if self.isop("("):
                    e = ("call", e, name[1], self.args(), nullc, targ)
                else:
                    e = ("member", e, name[1], nullc)
            elif self.isop("["):
                self.next()
                idx = self.expr()
                self.need("]")
                e = ("index", e, idx)
            elif self.isop("?") and self.isop("[", 1):
                self.next()
                self.next()
                idx = self.expr()
                self.need("]")
                e = ("index", e, idx, True)
            else:
                return e

    def new_expr(self):
        if self.peek()[0] != "ID":
            raise ExprError("'new' needs a type")
        ty = self.next()[1]
        if ty not in ("string", "int", "long", "double", "bool", "object", "List", "String"):
            raise ExprError(f"'new {ty}' is not supported (only arrays/lists of primitives)")
        if self.isop("<"):
            while not self.isop(">"):
                self.next()
            self.next()
        items = []
        if self.isop("["):
            while not self.isop("]"):
                self.next()
            self.next()
        if self.isop("("):
            self.args()
        if self.isop("{"):
            self.next()
            while not self.isop("}"):
                items.append(self.expr())
                if not self.eat(","):
                    break
            self.need("}")
        return ("list", items)

    def primary(self):
        t = self.next()
        if t[0] in ("NUM", "STR"):
            return ("lit", t[1])
        if t[0] == "ISTR":
            return ("interp", t[1])
        if t[0] == "ID":
            if t[1] in ("true", "false"):
                return ("lit", t[1] == "true")
            if t[1] == "null":
                return ("lit", None)
            if self.isop("=>"):
                self.next()
                return ("lambda", [t[1]], self.expr())
            if t[1] == "new":
                return self.new_expr()
            return ("name", t[1])
        if t == ("OP", "("):
            j, depth = self.i, 1
            while depth and j < len(self.t):
                depth += (self.t[j] == ("OP", "(")) - (self.t[j] == ("OP", ")"))
                j += 1
            if j < len(self.t) and self.t[j] == ("OP", "=>"):
                params = [x[1] for x in self.t[self.i:j - 1] if x[0] == "ID"]
                self.i = j + 1
                return ("lambda", params, self.expr())
            e = self.expr()
            self.need(")")
            return e
        raise ExprError(f"unexpected token {t[1]!r}")


def parse_expression(src):
    p = _P(_tokenize(src))
    e = p.expr()
    if p.peek()[0] != "EOF":
        raise ExprError(f"unexpected trailing token {p.peek()[1]!r}")
    return e


# -- evaluation ----------------------------------------------------------------------------------------------
def _num(v):
    if isinstance(v, bool) or v is None or isinstance(v, str):
        raise ExprError(f"cannot use {type(v).__name__} as a number")
    return v


def _eq(a, b):
    if isinstance(a, CsDate) and isinstance(b, CsDate):
        return a.t == b.t
    return a == b


def _binary(op, a, b):
    if op == "+":
        if isinstance(a, str) or isinstance(b, str):
            return cs_str(a) + cs_str(b)
        if isinstance(a, CsDate):
            return CsDate(a.t + _num(b))
        return _num(a) + _num(b)
    if op == "==":
        return _eq(a, b)
    if op == "!=":
        return not _eq(a, b)
    if isinstance(a, CsDate) and isinstance(b, CsDate):
        a, b = a.t, b.t
    if op in ("<", ">", "<=", ">="):
        if not (isinstance(a, str) and isinstance(b, str)):
            a, b = _num(a), _num(b)
        return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    a, b = _num(a), _num(b)
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise ExprError("Attempted to divide by zero.")
        return a // b if isinstance(a, int) and isinstance(b, int) else a / b
    if op == "%":
        return a % b
    raise ExprError(f"operator {op} unsupported")


def _cast(ty, v):
    try:
        if ty == "string":
            return v if v is None or isinstance(v, str) else cs_str(v)
        if ty in ("int", "long", "short"):
            return int(float(v))
        if ty in ("double", "float", "decimal"):
            return float(v)
        if ty == "bool":
            return bool(v) if isinstance(v, bool) else str(v).lower() == "true"
    except (TypeError, ValueError):
        raise ExprError(f"cannot cast {v!r} to {ty}")
    return v


class _Static:
    def __init__(self, name):
        self.name = name


_STATICS = {"string", "String", "Regex", "Convert", "int", "Int32", "Int64", "long", "Uri", "Guid", "DateTime", "Math", "double", "bool"}


def _lookup(name, env):
    if name in env:
        return env[name]
    if name in _STATICS:
        return _Static(name)
    raise ExprError(f"The name '{name}' does not exist in the current context.")


def _member(o, name):
    if isinstance(o, Obj):
        if name in o.attrs:
            v = o.attrs[name]
            return v() if callable(v) else v
        raise ExprError(f"'{o.name}' has no member '{name}'")
    if isinstance(o, str) and name == "Length":
        return len(o)
    if isinstance(o, (list, tuple)) and name in ("Length", "Count"):
        return len(o)
    if isinstance(o, dict) and name == "Count":
        return len(o)
    if isinstance(o, Match):
        m = o.m
        if name == "Success":
            return m is not None
        if name == "Value":
            return m.group(0) if m else ""
        if name == "Groups":
            return [m.group(0)] + list(m.groups()) if m else []
    if isinstance(o, CsDate):
        tm = time.gmtime(o.t)
        d = {"Year": tm.tm_year, "Month": tm.tm_mon, "Day": tm.tm_mday, "Hour": tm.tm_hour, "Minute": tm.tm_min, "Second": tm.tm_sec}
        if name in d:
            return d[name]
    if isinstance(o, _Static):
        if o.name == "DateTime" and name in ("UtcNow", "Now"):
            return CsDate(time.time())
        if o.name in ("string", "String") and name == "Empty":
            return ""
    raise ExprError(f"member '{name}' is not supported on {type(o).__name__}")


def _linq(o, name, args):
    seq = list(o)
    fn = args[0] if args and callable(args[0]) else None
    if name in ("First", "FirstOrDefault", "Last", "LastOrDefault"):
        pool = [x for x in seq if fn(x)] if fn else seq
        if not pool:
            if name.endswith("OrDefault"):
                return None
            raise ExprError("Sequence contains no elements")
        return pool[0] if name.startswith("First") else pool[-1]
    if name == "Any":
        return any(fn(x) for x in seq) if fn else bool(seq)
    if name == "All":
        return all(fn(x) for x in seq)
    if name == "Count":
        return sum(1 for x in seq if fn(x)) if fn else len(seq)
    if name == "Select":
        return [fn(x) for x in seq]
    if name == "Where":
        return [x for x in seq if fn(x)]
    if name in ("ToArray", "ToList", "AsEnumerable"):
        return seq
    if name == "Skip":
        return seq[int(args[0]):]
    if name == "Take":
        return seq[:int(args[0])]
    if name == "Distinct":
        out = []
        for x in seq:
            if x not in out:
                out.append(x)
        return out
    if name == "Sum":
        return sum(fn(x) for x in seq) if fn else sum(seq)
    if name == "Contains":
        return args[0] in seq
    if name == "OrderBy":
        return sorted(seq, key=fn)
    raise ExprError(f"LINQ method '{name}' is not supported")


def _method(o, name, args, targ=None):
    if isinstance(o, Obj):
        if name in o.methods:
            f = o.methods[name]
            return f(args, targ) if f.__code__.co_argcount >= 2 else f(args)
        if name == "ToString":
            return o.name
        raise ExprError(f"'{o.name}' has no method '{name}'")
    if isinstance(o, str):
        s = o

        def ic(a):
            return len(a) > 1 and str(a[1]).endswith("IgnoreCase")
        table = {
            "Contains": lambda a: str(a[0]) in s,
            "StartsWith": lambda a: s.lower().startswith(str(a[0]).lower()) if ic(a) else s.startswith(str(a[0])),
            "EndsWith": lambda a: s.lower().endswith(str(a[0]).lower()) if ic(a) else s.endswith(str(a[0])),
            "Equals": lambda a: s.lower() == str(a[0]).lower() if ic(a) else s == a[0],
            "ToLower": lambda a: s.lower(), "ToLowerInvariant": lambda a: s.lower(), "ToUpper": lambda a: s.upper(), "ToUpperInvariant": lambda a: s.upper(),
            "Trim": lambda a: s.strip(), "TrimStart": lambda a: s.lstrip(), "TrimEnd": lambda a: s.rstrip(),
            "Substring": lambda a: s[int(a[0]):(int(a[0]) + int(a[1]) if len(a) > 1 else None)],
            "Replace": lambda a: s.replace(str(a[0]), str(a[1])), "IndexOf": lambda a: s.find(str(a[0])), "LastIndexOf": lambda a: s.rfind(str(a[0])),
            "Split": lambda a: re.split("|".join(re.escape(x) for x in (a[0] if isinstance(a[0], list) else [a[0]])), s) if a else s.split(),
            "PadLeft": lambda a: s.rjust(int(a[0]), str(a[1]) if len(a) > 1 else " "), "PadRight": lambda a: s.ljust(int(a[0]), str(a[1]) if len(a) > 1 else " "),
            "ToString": lambda a: s, "AsJwt": lambda a: jwt_obj(s), "ToCharArray": lambda a: list(s),
            "Insert": lambda a: s[:int(a[0])] + str(a[1]) + s[int(a[0]):], "CompareTo": lambda a: (s > a[0]) - (s < a[0]),
        }
        if name in table:
            return table[name](args)
        return _linq(list(s), name, args)
    if isinstance(o, dict):
        if name == "GetValueOrDefault":
            return o.get(args[0], args[1] if len(args) > 1 else None)
        if name == "ContainsKey":
            return args[0] in o
        if name == "Value":
            v = o.get(args[0])
            return _cast((targ or "string").lower(), v) if v is not None else None
        if name == "ToString":
            return json.dumps(o)
    if isinstance(o, (list, tuple)):
        if name == "ToString":
            return "System.String[]"
        return _linq(o, name, args)
    if isinstance(o, CsDate):
        if name == "ToString":
            f = args[0] if args else "o"
            if f in ("o", "O", "s"):
                return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(o.t)) + (".0000000Z" if f != "s" else "")
            return cs_str(o)
        if name in ("AddSeconds", "AddMinutes", "AddHours", "AddDays"):
            return CsDate(o.t + float(args[0]) * {"AddSeconds": 1, "AddMinutes": 60, "AddHours": 3600, "AddDays": 86400}[name])
    if isinstance(o, (int, float, bool)) and name == "ToString":
        return cs_str(o)
    if isinstance(o, _Static):
        return _static(o.name, name, args)
    raise ExprError(f"method '{name}' is not supported on {type(o).__name__}")


def _static(cls, name, a):
    if cls in ("string", "String"):
        if name == "IsNullOrEmpty":
            return a[0] is None or a[0] == ""
        if name == "IsNullOrWhiteSpace":
            return a[0] is None or str(a[0]).strip() == ""
        if name == "Join":
            seq = a[1] if len(a) == 2 and isinstance(a[1], (list, tuple)) else a[1:]
            return cs_str(a[0]).join(cs_str(x) for x in seq)
        if name == "Format":
            return re.sub(r"\{(\d+)(?::[^}]*)?\}", lambda m: cs_str(a[1 + int(m.group(1))]), str(a[0]))
        if name == "Concat":
            return "".join(cs_str(x) for x in a)
        if name == "Equals":
            return a[0] == a[1]
    if cls == "Regex":
        flags = re.I if len(a) > 2 and "IgnoreCase" in str(a[2]) else 0
        if name == "IsMatch":
            return re.search(str(a[1]), str(a[0]), flags) is not None
        if name == "Match":
            return Match(re.search(str(a[1]), str(a[0]), flags))
        if name == "Replace":
            return re.sub(str(a[1]), re.sub(r"\$(\d)", r"\\\1", str(a[2])), str(a[0]))
    if cls == "Convert":
        if name in ("ToInt32", "ToInt64"):
            return int(float(a[0]))
        if name == "ToString":
            return cs_str(a[0])
        if name == "ToDouble":
            return float(a[0])
        if name == "ToBoolean":
            return str(a[0]).lower() == "true"
        if name == "ToBase64String":
            return base64.b64encode(a[0] if isinstance(a[0], bytes) else str(a[0]).encode()).decode()
        if name == "FromBase64String":
            return base64.b64decode(a[0])
    if cls in ("int", "Int32", "Int64", "long", "double") and name == "Parse":
        return int(a[0]) if cls != "double" else float(a[0])
    if cls == "bool" and name == "Parse":
        return str(a[0]).lower() == "true"
    if cls == "Uri" and name in ("EscapeDataString", "EscapeUriString"):
        from urllib.parse import quote
        return quote(str(a[0]), safe="")
    if cls == "Guid" and name == "NewGuid":
        return str(uuid.uuid4())
    if cls == "Math":
        import math
        f = {"Min": min, "Max": max, "Abs": abs, "Floor": math.floor, "Ceiling": math.ceil, "Round": round, "Pow": math.pow, "Sqrt": math.sqrt}.get(name)
        if f:
            return f(*a)
    raise ExprError(f"{cls}.{name} is not supported")


class _Interp:
    def __init__(self):
        self.steps = 0

    def tick(self):
        self.steps += 1
        if self.steps > 200000:
            raise ExprError("expression exceeded the evaluation limit")

    def ev(self, n, env):
        self.tick()
        k = n[0]
        if k == "lit":
            return n[1]
        if k == "name":
            return _lookup(n[1], env)
        if k == "list":
            return [self.ev(x, env) for x in n[1]]
        if k == "interp":
            return re.sub(r"\{([^{}]+)\}", lambda m: cs_str(self.ev(parse_expression(m.group(1).split(":")[0]), env)), n[1])
        if k == "member":
            o = self.ev(n[1], env)
            if o is None:
                if n[3]:
                    return None
                raise ExprError(f"Object reference not set to an instance of an object ('{n[2]}').")
            return _member(o, n[2])
        if k == "call":
            o = self.ev(n[1], env)
            if o is None:
                if n[4]:
                    return None
                raise ExprError(f"Object reference not set to an instance of an object ('{n[2]}()').")
            return _method(o, n[2], [self.ev(a, env) for a in n[3]], n[5])
        if k == "index":
            o = self.ev(n[1], env)
            i = self.ev(n[2], env)
            if o is None:
                if len(n) > 3:
                    return None
                raise ExprError("Object reference not set to an instance of an object (indexer).")
            if isinstance(o, Obj) and hasattr(o, "index"):
                return o.index(i)
            if isinstance(o, dict):
                if i not in o:
                    raise ExprError(f"The given key '{i}' was not present in the dictionary.")
                return o[i]
            if isinstance(o, (list, tuple, str)):
                try:
                    return o[int(i)]
                except IndexError:
                    raise ExprError("Index was out of range.")
            raise ExprError(f"indexer is not supported on {type(o).__name__}")
        if k == "not":
            v = self.ev(n[1], env)
            if not isinstance(v, bool):
                raise ExprError("Operator '!' needs a bool.")
            return not v
        if k == "neg":
            return -_num(self.ev(n[1], env))
        if k == "cast":
            return _cast(n[1], self.ev(n[2], env))
        if k == "and":
            return bool(self.ev(n[1], env)) and bool(self.ev(n[2], env))
        if k == "or":
            return bool(self.ev(n[1], env)) or bool(self.ev(n[2], env))
        if k == "coalesce":
            v = self.ev(n[1], env)
            return v if v is not None else self.ev(n[2], env)
        if k == "cond":
            return self.ev(n[2], env) if self.ev(n[1], env) else self.ev(n[3], env)
        if k == "bin":
            return _binary(n[1], self.ev(n[2], env), self.ev(n[3], env))
        if k == "lambda":
            params, body = n[1], n[2]

            def f(*a):
                e = dict(env)
                e.update(zip(params, a))
                return self.ev(body, e)
            return f
        raise ExprError(f"unsupported syntax: {k}")

    def run(self, n, env):
        self.tick()
        k = n[0]
        if k == "block":
            for s in n[1]:
                self.run(s, env)
        elif k == "return":
            raise _Return(self.ev(n[1], env) if n[1] is not None else None)
        elif k == "if":
            if self.ev(n[1], env):
                self.run(n[2], env)
            elif n[3] is not None:
                self.run(n[3], env)
        elif k == "foreach":
            for x in list(self.ev(n[2], env)):
                env[n[1]] = x
                self.run(n[3], env)
        elif k in ("decl", "assign"):
            env[n[1]] = self.ev(n[2], env) if n[2] is not None else None
        elif k == "expr":
            self.ev(n[1], env)
        else:
            raise ExprError(f"unsupported statement: {k}")


_CACHE: dict = {}


def is_expression(text) -> bool:
    t = (text or "").strip()
    return (t.startswith("@(") and t.endswith(")")) or (t.startswith("@{") and t.endswith("}"))


def evaluate(text, env):
    """-> the C# value of an ``@(...)`` / ``@{...}`` attribute; any other text is returned unchanged. Raises ExprError."""
    t = (text or "").strip()
    if not is_expression(t):
        return text
    ip = _Interp()
    try:
        if t.startswith("@("):
            ast = _CACHE.get(t) or _CACHE.setdefault(t, parse_expression(t[2:-1]))
            return ip.ev(ast, dict(env))
        ast = _CACHE.get(t) or _CACHE.setdefault(t, _P(_tokenize(t[2:-1])).program())
        try:
            ip.run(ast, dict(env))
        except _Return as r:
            return r.v
        return None
    except RecursionError:
        raise ExprError("expression is too deeply nested")
    except ExprError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ExprError(f"{type(e).__name__}: {e}")
