"""A real HCL2 subset parser + expression evaluator in pure Python (stdlib only, so it also runs in Pyodide / Nano).

Parses what hand-written and exported Terraform uses: resource / data / variable / locals / output / provider / terraform blocks,
attributes, nested blocks (incl. ``dynamic``), lists, maps, heredocs, ``"${...}"`` templates, references (``aws_vpc.main.id``,
``var.x``, ``local.y``, ``each.key``, ``count.index``), splats, conditionals, operators, ``for`` expressions and the common
built-in functions (``jsonencode``, ``file``, ``filebase64sha256``, ``merge``, ``format`` ...). Expressions parse to a small tuple AST
and are evaluated later against a resolver, so references to resources that do not exist yet stay symbolic until apply time.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Callable


class HclError(Exception):
    def __init__(self, msg: str, file: str = "", line: int = 0):
        super().__init__(f"{file + ':' if file else ''}{line}: {msg}" if line else msg)
        self.msg, self.file, self.line = msg, file, line


class Unknown(Exception):
    """Raised while evaluating an expression that depends on something not created yet (``refs`` = the addresses it waits on)."""

    def __init__(self, refs=()):
        super().__init__("unknown value: " + ", ".join(refs))
        self.refs = tuple(refs)


class SelfRef:
    """Stands in for a resource's reference to itself (a security group allowing its own group); the applier substitutes the real id."""
    __slots__ = ("attr",)

    def __init__(self, attr: str):
        self.attr = attr


# ------------------------------------------------------------------------------------------------------------------ lexer
_PUNCT3 = ("...",)
_PUNCT2 = ("==", "!=", "<=", ">=", "&&", "||", "=>")
_NUM = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_HEREDOC = re.compile(r"<<(-?)([A-Za-z_][A-Za-z0-9_]*)[ \t]*\r?\n")


class Tok:
    __slots__ = ("k", "v", "line")

    def __init__(self, k, v, line):
        self.k, self.v, self.line = k, v, line

    def __repr__(self):  # pragma: no cover
        return f"{self.k}:{self.v!r}"


def _match_brace(s: str, i: int) -> int:
    """``s[i]`` is the char after ``${``; return the index of the matching ``}``."""
    depth = 1
    while i < len(s):
        c = s[i]
        if c == '"':
            i = _skip_string(s, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise HclError("unterminated ${ ... } interpolation")


def _skip_string(s: str, i: int) -> int:
    """``s[i]`` is a ``"``; return the index just after its closing quote (handles escapes and nested ``${ "..." }``)."""
    i += 1
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "$" and s[i:i + 3] == "$${":
            i += 3
            continue
        if c == "%" and s[i:i + 3] == "%%{":
            i += 3
            continue
        if c == "$" and s[i + 1:i + 2] == "{":
            i = _match_brace(s, i + 2) + 1
            continue
        if c == '"':
            return i + 1
        i += 1
    raise HclError("unterminated string")


_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}


def _template(s: str, escapes: bool, line: int = 0) -> list:
    """Split template text into literal strings and ('expr', ast) interpolation parts."""
    parts: list = []
    buf: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and escapes:
            n = s[i + 1:i + 2]
            if n in _ESC:
                buf.append(_ESC[n])
                i += 2
                continue
            if n in ("u", "U"):
                w = 4 if n == "u" else 8
                buf.append(chr(int(s[i + 2:i + 2 + w], 16)))
                i += 2 + w
                continue
            raise HclError(f"invalid escape \\{n}", line=line)
        if c == "$" and s[i + 1:i + 2] == "$" and s[i + 2:i + 3] == "{":
            buf.append("${")
            i += 3
            continue
        if c == "%" and s[i + 1:i + 2] == "%" and s[i + 2:i + 3] == "{":
            buf.append("%{")
            i += 3
            continue
        if c == "$" and s[i + 1:i + 2] == "{":
            end = _match_brace(s, i + 2)
            if buf:
                parts.append("".join(buf))
                buf = []
            inner = s[i + 2:end].strip()
            if inner.startswith("~"):
                inner = inner[1:]
            parts.append(("expr", parse_expression(inner)))
            i = end + 1
            continue
        if c == "%" and s[i + 1:i + 2] == "{":
            raise HclError("template directives (%{ if/for }) are not supported", line=line)
        buf.append(c)
        i += 1
    if buf or not parts:
        parts.append("".join(buf))
    return parts


def tokenize(src: str, file: str = "") -> list[Tok]:
    toks: list[Tok] = []
    i, line, n = 0, 1, len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            toks.append(Tok("nl", "\n", line))
            line += 1
            i += 1
        elif c in " \t\r":
            i += 1
        elif c == "#" or src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise HclError("unterminated comment", file, line)
            line += src.count("\n", i, j)
            i = j + 2
        elif c == '"':
            try:
                j = _skip_string(src, i)
            except HclError as e:
                raise HclError(e.msg, file, line) from None
            try:
                toks.append(Tok("str", _template(src[i + 1:j - 1], True, line), line))
            except HclError as e:
                raise HclError(e.msg, file, e.line or line) from None
            line += src.count("\n", i, j)
            i = j
        elif c == "<" and (m := _HEREDOC.match(src, i)):
            indent, tag = m.group(1) == "-", m.group(2)
            start = m.end()
            lines, j, found = [], start, False
            while j <= n:
                e = src.find("\n", j)
                e = n if e < 0 else e
                raw = src[j:e]
                if raw.strip() == tag:
                    found = True
                    end_pos = e
                    break
                lines.append(raw.rstrip("\r"))
                j = e + 1
                if e >= n:
                    break
            if not found:
                raise HclError(f"unterminated heredoc <<{tag}", file, line)
            if indent:
                widths = [len(x) - len(x.lstrip(" \t")) for x in lines if x.strip()]
                cut = min(widths) if widths else 0
                lines = [x[cut:] for x in lines]
            body = "\n".join(lines) + ("\n" if lines else "")
            try:
                toks.append(Tok("str", _template(body, False, line), line))
            except HclError as e:
                raise HclError(e.msg, file, e.line or line) from None
            line += src.count("\n", i, end_pos)
            i = end_pos
        elif c.isdigit():
            m = _NUM.match(src, i)
            txt = m.group(0)
            toks.append(Tok("num", float(txt) if any(x in txt for x in ".eE") else int(txt), line))
            i = m.end()
        elif c.isalpha() or c == "_":
            m = _ID.match(src, i)
            toks.append(Tok("id", m.group(0), line))
            i = m.end()
        else:
            for p in _PUNCT3 + _PUNCT2:
                if src.startswith(p, i):
                    toks.append(Tok("op", p, line))
                    i += len(p)
                    break
            else:
                if c in "{}[]()=,.:?+-*/%<>!":
                    toks.append(Tok("op", c, line))
                    i += 1
                else:
                    raise HclError(f"unexpected character {c!r}", file, line)
    toks.append(Tok("eof", None, line))
    return toks


# ----------------------------------------------------------------------------------------------------------------- parser
class Body:
    def __init__(self):
        self.attrs: dict[str, tuple] = {}
        self.blocks: list[tuple[str, list[str], "Body"]] = []


class Parser:
    def __init__(self, toks: list[Tok], file: str = ""):
        self.t, self.i, self.file = toks, 0, file
        self.depth = 0  # >0 inside ( or [ : newlines are insignificant

    # token helpers
    def peek(self) -> Tok:
        if self.depth:
            while self.t[self.i].k == "nl":
                self.i += 1
        return self.t[self.i]

    def next(self) -> Tok:
        t = self.peek()
        self.i += 1
        return t

    def is_op(self, v: str) -> bool:
        t = self.peek()
        return t.k == "op" and t.v == v

    def accept(self, v: str) -> bool:
        if self.is_op(v):
            self.i += 1
            return True
        return False

    def expect(self, v: str) -> Tok:
        t = self.next()
        if t.k != "op" or t.v != v:
            self.fail(f"expected {v!r}, found {t.v!r}", t)
        return t

    def fail(self, msg: str, t: Tok | None = None):
        raise HclError(msg, self.file, (t or self.t[min(self.i, len(self.t) - 1)]).line)

    def skip_nl(self):
        while self.t[self.i].k == "nl":
            self.i += 1

    # body / blocks
    def parse_body(self, closing: bool) -> Body:
        body = Body()
        while True:
            self.skip_nl()
            t = self.t[self.i]
            if t.k == "eof":
                if closing:
                    self.fail("missing closing brace", t)
                return body
            if t.k == "op" and t.v == "}":
                if not closing:
                    self.fail("unexpected }", t)
                self.i += 1
                return body
            if t.k != "id" and not (t.k == "str"):
                self.fail(f"expected an attribute or block name, found {t.v!r}", t)
            name = t.v if t.k == "id" else _literal(t.v)
            self.i += 1
            nt = self.t[self.i]
            if nt.k == "op" and nt.v in ("=", ":") and t.k == "id":
                self.i += 1
                body.attrs[name] = self.expr()
                self._end_stmt()
                continue
            labels = []
            while True:
                lt = self.t[self.i]
                if lt.k == "str":
                    labels.append(_literal(lt.v))
                    self.i += 1
                elif lt.k == "id":
                    labels.append(lt.v)
                    self.i += 1
                else:
                    break
            self.expect_raw("{")
            inner = self.parse_body(True)
            body.blocks.append((name, labels, inner))
            self._end_stmt(block=True)

    def expect_raw(self, v: str):
        self.skip_nl_if_brace()
        t = self.t[self.i]
        if t.k != "op" or t.v != v:
            self.fail(f"expected {v!r}, found {t.v!r}", t)
        self.i += 1

    def skip_nl_if_brace(self):
        pass

    def _end_stmt(self, block: bool = False):
        t = self.t[self.i]
        if t.k == "nl":
            return
        if t.k == "eof" or (t.k == "op" and t.v == "}"):
            return
        if t.k == "op" and t.v == "," and not block:
            self.i += 1
            return
        self.fail(f"unexpected {t.v!r}; expected a newline", t)

    # expressions
    def expr(self) -> tuple:
        return self.cond()

    def cond(self) -> tuple:
        c = self.binary(0)
        if self.accept("?"):
            a = self.cond()
            self.expect(":")
            b = self.cond()
            return ("cond", c, a, b)
        return c

    _LEVELS = [("||",), ("&&",), ("==", "!="), ("<", ">", "<=", ">="), ("+", "-"), ("*", "/", "%")]

    def binary(self, lvl: int) -> tuple:
        if lvl == len(self._LEVELS):
            return self.unary()
        left = self.binary(lvl + 1)
        while True:
            t = self.peek()
            if t.k == "op" and t.v in self._LEVELS[lvl]:
                self.i += 1
                left = ("bin", t.v, left, self.binary(lvl + 1))
            else:
                return left

    def unary(self) -> tuple:
        if self.is_op("-"):
            self.i += 1
            return ("un", "-", self.unary())
        if self.is_op("!"):
            self.i += 1
            return ("un", "!", self.unary())
        return self.postfix(self.primary())

    def postfix(self, e: tuple) -> tuple:
        while True:
            t = self.t[self.i] if not self.depth else self.peek()
            if t.k != "op":
                return e
            if t.v == ".":
                self.i += 1
                n = self.t[self.i]
                if n.k == "id":
                    self.i += 1
                    e = ("attr", e, n.v)
                elif n.k == "num" and isinstance(n.v, int):
                    self.i += 1
                    e = ("idx", e, ("lit", n.v))
                elif n.k == "op" and n.v == "*":
                    self.i += 1
                    e = ("splat", e, self._splat_tail())
                else:
                    self.fail("expected an attribute name after '.'", n)
            elif t.v == "[":
                self.i += 1
                self.depth += 1
                if self.is_op("*"):
                    self.i += 1
                    self.expect("]")
                    self.depth -= 1
                    e = ("splat", e, self._splat_tail())
                    continue
                k = self.expr()
                self.expect("]")
                self.depth -= 1
                e = ("idx", e, k)
            else:
                return e

    def _splat_tail(self) -> list:
        steps = []
        while True:
            t = self.t[self.i]
            if t.k == "op" and t.v == ".":
                n = self.t[self.i + 1]
                if n.k == "id":
                    steps.append(("attr", n.v))
                    self.i += 2
                    continue
            if t.k == "op" and t.v == "[":
                self.i += 1
                self.depth += 1
                k = self.expr()
                self.expect("]")
                self.depth -= 1
                steps.append(("idx", k))
                continue
            return steps

    def primary(self) -> tuple:
        t = self.next()
        if t.k == "num":
            return ("lit", t.v)
        if t.k == "str":
            return _tpl_node(t.v)
        if t.k == "id":
            if t.v == "true":
                return ("lit", True)
            if t.v == "false":
                return ("lit", False)
            if t.v == "null":
                return ("lit", None)
            if self.t[self.i].k == "op" and self.t[self.i].v == "(":
                self.i += 1
                self.depth += 1
                args = []
                while not self.is_op(")"):
                    args.append(self.expr())
                    if self.is_op("..."):
                        self.i += 1
                        args[-1] = ("expand", args[-1])
                    if not self.accept(","):
                        break
                self.expect(")")
                self.depth -= 1
                return ("call", t.v, args)
            return ("name", t.v)
        if t.k == "op":
            if t.v == "(":
                self.depth += 1
                e = self.expr()
                self.expect(")")
                self.depth -= 1
                return e
            if t.v == "[":
                self.depth += 1
                if self.peek().k == "id" and self.peek().v == "for":
                    r = self._for(False)
                    self.depth -= 1
                    return r
                items = []
                while not self.is_op("]"):
                    items.append(self.expr())
                    if not self.accept(","):
                        break
                self.expect("]")
                self.depth -= 1
                return ("list", items)
            if t.v == "{":
                return self._object()
        self.fail(f"unexpected {t.v!r} in expression", t)

    def _object(self) -> tuple:
        self.depth += 1  # newlines insignificant, commas/newlines both separate
        if self.peek().k == "id" and self.peek().v == "for":
            r = self._for(True)
            self.depth -= 1
            return r
        items = []
        while not self.is_op("}"):
            kt = self.peek()
            if kt.k == "id" and self.t[self.i + 1].k == "op" and self.t[self.i + 1].v in ("=", ":"):
                key = ("lit", kt.v)
                self.i += 1
            elif kt.k == "op" and kt.v == "(":
                self.i += 1
                key = self.expr()
                self.expect(")")
            else:
                key = self.expr()
            if not (self.accept("=") or self.accept(":")):
                self.fail("expected '=' or ':' after object key", self.peek())
            items.append((key, self.expr()))
            if not self.accept(","):
                continue
        self.expect("}")
        self.depth -= 1
        return ("obj", items)

    def _for(self, obj: bool) -> tuple:
        self.next()  # for
        v1 = self.next().v
        v2 = None
        if self.accept(","):
            v2 = self.next().v
        t = self.next()
        if t.v != "in":
            self.fail("expected 'in' in for expression", t)
        coll = self.expr()
        self.expect(":")
        k = self.expr()
        v = None
        if obj:
            self.expect("=>")
            v = self.expr()
        grp = False
        if self.is_op("..."):
            self.i += 1
            grp = True
        cond = None
        if self.peek().k == "id" and self.peek().v == "if":
            self.next()
            cond = self.expr()
        self.expect("}" if obj else "]")
        return ("for", obj, v1, v2, coll, k, v, cond, grp)


def _literal(parts) -> str:
    if len(parts) == 1 and isinstance(parts[0], str):
        return parts[0]
    raise HclError("a block label must be a plain string")


def _tpl_node(parts: list) -> tuple:
    if len(parts) == 1 and isinstance(parts[0], str):
        return ("lit", parts[0])
    if len(parts) == 1 and isinstance(parts[0], tuple):
        return parts[0][1]
    return ("tpl", [p if isinstance(p, str) else p[1] for p in parts])


def parse_expression(src: str, file: str = "") -> tuple:
    p = Parser(tokenize(src, file), file)
    p.depth = 1  # a standalone expression ignores newlines
    e = p.expr()
    if p.peek().k != "eof":
        p.fail(f"unexpected {p.peek().v!r} after expression")
    return e


def parse_body(src: str, file: str = "") -> Body:
    return Parser(tokenize(src, file), file).parse_body(False)


# ------------------------------------------------------------------------------------------------------------- reference walk
RESERVED_ROOTS = {"var", "local", "data", "each", "count", "path", "terraform", "self", "module"}


def _chain(e):
    steps = []
    while e[0] in ("attr", "idx"):
        steps.append(e)
        e = e[1]
    steps.reverse()
    return e, steps


def references(e, out: set[str] | None = None, bound: frozenset = frozenset()) -> set[str]:
    """Static references inside an expression: ``aws_vpc.main``, ``data.aws_x.y``, ``var.x``, ``local.y``, ``module.m``."""
    out = set() if out is None else out
    k = e[0]
    if k in ("attr", "idx", "name"):
        root, steps = _chain(e)
        if root[0] == "name":
            r = root[1]
            names = [s[2] for s in steps if s[0] == "attr"]
            if r in bound:
                pass
            elif r in ("var", "local", "module") and names:
                out.add(f"{r}.{names[0]}")
            elif r == "data" and len(names) >= 2 and all(s[0] == "attr" for s in steps[:2]):
                out.add(f"data.{names[0]}.{names[1]}")
            elif r not in RESERVED_ROOTS and names and steps[0][0] == "attr":
                out.add(f"{r}.{names[0]}")
        else:
            references(root, out, bound)
        for s in steps:
            if s[0] == "idx":
                references(s[2], out, bound)
        return out
    if k == "lit":
        return out
    if k == "tpl":
        for p in e[1]:
            if not isinstance(p, str):
                references(p, out, bound)
    elif k == "list":
        for x in e[1]:
            references(x, out, bound)
    elif k == "obj":
        for a, b in e[1]:
            references(a, out, bound)
            references(b, out, bound)
    elif k == "call":
        for a in e[2]:
            references(a, out, bound)
    elif k == "expand":
        references(e[1], out, bound)
    elif k == "cond":
        for x in e[1:]:
            references(x, out, bound)
    elif k == "bin":
        references(e[2], out, bound)
        references(e[3], out, bound)
    elif k == "un":
        references(e[2], out, bound)
    elif k == "splat":
        references(e[1], out, bound)
        for s in e[2]:
            if s[0] == "idx":
                references(s[1], out, bound)
    elif k == "for":
        _, _obj, v1, v2, coll, kx, vx, cond, _g = e
        references(coll, out, bound)
        b2 = bound | {v1} | ({v2} if v2 else set())
        for x in (kx, vx, cond):
            if x is not None:
                references(x, out, b2)
    return out


def body_references(body: Body, out: set[str] | None = None, bound: frozenset = frozenset()) -> set[str]:
    out = set() if out is None else out
    for e in body.attrs.values():
        references(e, out, bound)
    for btype, _labels, b in body.blocks:
        body_references(b, out, bound | ({btype} if btype == "dynamic" else frozenset()) | (frozenset(_labels[:1]) if btype == "dynamic" else frozenset()))
    return out


# --------------------------------------------------------------------------------------------------------------- evaluator
class Ns:
    """A not-yet-resolved namespace such as ``var``, ``aws_vpc`` or ``data.aws_vpc`` while walking a traversal."""

    def __init__(self, kind: str, sub: str = ""):
        self.kind, self.sub = kind, sub


def _num(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return float(v)
    return v


def _tostr(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    if isinstance(v, (dict, list)):
        raise HclError("cannot convert a collection to a string")
    return str(v)


def _canon_json(v):
    if isinstance(v, SelfRef):
        raise Unknown()
    return v


def _jsonencode(v) -> str:
    return json.dumps(v, separators=(",", ":"), sort_keys=True, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _format(fmt: str, *args) -> str:
    it = iter(args)

    def rep(m):
        spec = m.group(0)
        if spec == "%%":
            return "%"
        v = next(it)
        conv = spec[-1]
        if conv == "v":
            return _tostr(v) if not isinstance(v, (dict, list)) else _jsonencode(v)
        if conv == "s":
            return _tostr(v)
        if conv == "q":
            return json.dumps(_tostr(v))
        return ("%" + spec[1:]) % (_num(v),) if conv in "dfxXoeEgGb" else spec
    return re.sub(r"%%|%[-+ 0#]*\d*(?:\.\d+)?[a-zA-Z]", rep, fmt)


def _cidrsubnet(prefix: str, newbits: int, num: int) -> str:
    import ipaddress
    net = ipaddress.ip_network(prefix, strict=False)
    subs = list(net.subnets(prefixlen_diff=int(newbits))) if int(newbits) <= 12 else None
    if subs is not None:
        return str(subs[int(num)])
    size = 1 << (net.max_prefixlen - net.prefixlen - int(newbits))
    return str(ipaddress.ip_network((int(net.network_address) + int(num) * size, net.prefixlen + int(newbits)), strict=False))


def _lookup(m, k, *d):
    if isinstance(m, dict) and k in m:
        return m[k]
    if d:
        return d[0]
    raise HclError(f"lookup: key {k!r} not found")


def _merge(*maps):
    out: dict = {}
    for m in maps:
        if m:
            out.update(m)
    return out


def _try(*_a):
    raise HclError("try() is evaluated specially")


FUNCS: dict[str, Callable[..., Any]] = {
    "jsonencode": _jsonencode, "jsondecode": lambda s: json.loads(s), "format": _format,
    "join": lambda sep, lst: sep.join(_tostr(x) for x in lst), "split": lambda sep, s: s.split(sep),
    "lower": lambda s: s.lower(), "upper": lambda s: s.upper(), "title": lambda s: s.title(), "trimspace": lambda s: s.strip(),
    "trimprefix": lambda s, p: s[len(p):] if s.startswith(p) else s, "trimsuffix": lambda s, p: s[:-len(p)] if p and s.endswith(p) else s,
    "replace": lambda s, a, b: re.sub(a[1:-1], b, s) if len(a) > 1 and a.startswith("/") and a.endswith("/") else s.replace(a, b),
    "substr": lambda s, o, n: s[int(o):] if int(n) < 0 else s[int(o):int(o) + int(n)],
    "tostring": _tostr, "tonumber": _num, "tobool": lambda v: v if isinstance(v, bool) else str(v).lower() == "true",
    "tolist": lambda v: list(v), "toset": lambda v: sorted(set(v), key=str) if all(isinstance(x, (str, int, float)) for x in v) else list(v),
    "tomap": lambda v: dict(v), "length": lambda v: len(v), "merge": _merge, "concat": lambda *ls: [x for l in ls for x in l],
    "flatten": lambda l: [y for x in l for y in (_flat(x))], "keys": lambda m: sorted(m), "values": lambda m: [m[k] for k in sorted(m)],
    "lookup": _lookup, "element": lambda l, i: l[int(i) % len(l)], "index": lambda l, v: l.index(v), "contains": lambda l, v: v in l,
    "distinct": lambda l: [x for i, x in enumerate(l) if x not in l[:i]], "sort": lambda l: sorted(l), "reverse": lambda l: list(reversed(l)),
    "slice": lambda l, a, b: l[int(a):int(b)], "compact": lambda l: [x for x in l if x not in (None, "")],
    "coalesce": lambda *a: next((x for x in a if x not in (None, "")), None), "zipmap": lambda k, v: dict(zip(k, v)),
    "min": lambda *a: min(a), "max": lambda *a: max(a), "abs": abs, "ceil": lambda x: -int(-x // 1), "floor": lambda x: int(x // 1),
    "base64encode": lambda s: base64.b64encode(s.encode()).decode(), "base64decode": lambda s: base64.b64decode(s).decode(),
    "sha256": lambda s: hashlib.sha256(s.encode()).hexdigest(), "md5": lambda s: hashlib.md5(s.encode()).hexdigest(),
    "sha1": lambda s: hashlib.sha1(s.encode()).hexdigest(), "cidrsubnet": _cidrsubnet, "chomp": lambda s: s.rstrip("\r\n"),
    "urlencode": lambda s: __import__("urllib.parse").parse.quote(s, safe=""), "range": lambda *a: list(range(*[int(x) for x in a])),
    "regex": lambda p, s: (re.search(p, s) or (_ for _ in ()).throw(HclError("regex: no match"))).group(0),
    "startswith": lambda s, p: s.startswith(p), "endswith": lambda s, p: s.endswith(p), "one": lambda l: l[0] if l else None,
}


def _flat(x):
    if isinstance(x, list):
        for y in x:
            yield from _flat(y)
    else:
        yield x


class Evaluator:
    """Evaluates expression ASTs. ``scope`` supplies the world: ``var(name)``, ``local(name)``, ``resource(type, name)``,
    ``data(type, name)``, ``each`` ({key,value}), ``count_index``, ``file(path)`` (text), ``file_bytes(path)``."""

    def __init__(self, scope):
        self.s = scope
        self.env: dict[str, Any] = {}

    def child(self, **kv) -> "Evaluator":
        ev = Evaluator(self.s)
        ev.env = {**self.env, **kv}
        return ev

    def ev(self, e):
        k = e[0]
        m = getattr(self, "_" + k)
        return m(e)

    def _lit(self, e):
        return e[1]

    def _tpl(self, e):
        out = []
        for p in e[1]:
            if isinstance(p, str):
                out.append(p)
            else:
                v = self.ev(p)
                if isinstance(v, SelfRef):
                    raise Unknown()
                out.append(_tostr(v))
        return "".join(out)

    def _list(self, e):
        return [self.ev(x) for x in e[1]]

    def _obj(self, e):
        out = {}
        for kx, vx in e[1]:
            key = self.ev(kx)
            out[_tostr(key)] = self.ev(vx)
        return out

    def _name(self, e):
        n = e[1]
        if n in self.env:
            return self.env[n]
        if n not in RESERVED_ROOTS:
            return Ns("res", n)
        if True:
            if n == "each":
                return self.s.each()
            if n == "count":
                return {"index": self.s.count_index()}
            if n == "path":
                return {"module": ".", "root": ".", "cwd": "."}
            if n == "terraform":
                return {"workspace": "default"}
            return Ns(n)

    def _attr(self, e):
        base = self.ev(e[1])
        return self._step(base, e[2])

    def _step(self, base, name):
        if isinstance(base, Ns):
            if base.kind == "var":
                return self.s.var(name)
            if base.kind == "local":
                return self.s.local(name)
            if base.kind == "module":
                raise HclError("modules are not supported")
            if base.kind == "data" and not base.sub:
                return Ns("data", name)
            if base.kind == "data":
                return self.s.data(base.sub, name)
            if base.kind == "res":
                return self.s.resource(base.sub, name)
            if base.kind == "self":
                return self.s.self_attr(name)
            raise HclError(f"unsupported reference {base.kind}.{name}")
        if isinstance(base, SelfRef):
            raise Unknown()
        if isinstance(base, dict):
            if name in base:
                return base[name]
            raise HclError(f"object has no attribute {name!r}")
        if isinstance(base, list):  # attribute on a list of objects = splat
            return [self._step(x, name) for x in base]
        if base is None:
            raise HclError(f"cannot read .{name} of null")
        raise HclError(f"cannot read .{name} of a {type(base).__name__}")

    def _idx(self, e):
        base, k = self.ev(e[1]), self.ev(e[2])
        if isinstance(base, Ns):
            if base.kind == "data" and not base.sub:
                return Ns("data", _tostr(k))
            raise HclError("cannot index a namespace")
        if isinstance(base, SelfRef):
            raise Unknown()
        if isinstance(base, list):
            return base[int(k)]
        if isinstance(base, dict):
            return base[_tostr(k)]
        raise HclError(f"cannot index a {type(base).__name__}")

    def _splat(self, e):
        base = self.ev(e[1])
        items = base if isinstance(base, list) else list(base.values()) if isinstance(base, dict) and "id" not in base and False else ([] if base is None else [base])
        out = []
        for it in items:
            v = it
            for st in e[2]:
                v = self._step(v, st[1]) if st[0] == "attr" else (v[int(self.ev(st[1]))] if isinstance(v, list) else v[_tostr(self.ev(st[1]))])
            out.append(v)
        return out

    def _cond(self, e):
        return self.ev(e[2]) if self.ev(e[1]) else self.ev(e[3])

    def _un(self, e):
        v = self.ev(e[2])
        return (not v) if e[1] == "!" else -_num(v)

    def _bin(self, e):
        op = e[1]
        if op == "&&":
            return bool(self.ev(e[2])) and bool(self.ev(e[3]))
        if op == "||":
            return bool(self.ev(e[2])) or bool(self.ev(e[3]))
        a, b = self.ev(e[2]), self.ev(e[3])
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        a, b = _num(a), _num(b)
        r = {"<": lambda: a < b, ">": lambda: a > b, "<=": lambda: a <= b, ">=": lambda: a >= b, "+": lambda: a + b, "-": lambda: a - b,
             "*": lambda: a * b, "/": lambda: a / b, "%": lambda: a % b}[op]()
        return int(r) if isinstance(r, float) and r == int(r) and op != "/" else r

    def _call(self, e):
        name, args = e[1], e[2]
        if name == "try":
            for a in args:
                try:
                    return self.ev(a)
                except Unknown:
                    raise
                except (HclError, KeyError, IndexError, TypeError):
                    continue
            raise HclError("try(): all expressions failed")
        if name == "can":
            try:
                self.ev(args[0])
                return True
            except Unknown:
                raise
            except (HclError, KeyError, IndexError, TypeError):
                return False
        if name == "file":
            return self.s.file(self.ev(args[0]))
        if name in ("filebase64", "filebase64sha256", "filesha256", "filemd5"):
            data = self.s.file_bytes(self.ev(args[0]))
            if name == "filebase64":
                return base64.b64encode(data).decode()
            if name == "filebase64sha256":
                return base64.b64encode(hashlib.sha256(data).digest()).decode()
            if name == "filesha256":
                return hashlib.sha256(data).hexdigest()
            return hashlib.md5(data).hexdigest()
        if name == "templatefile":
            raise HclError("templatefile() is not supported")
        if name == "timestamp":
            return "2024-01-01T00:00:00Z"
        if name == "uuid":
            return "00000000-0000-0000-0000-000000000000"
        fn = FUNCS.get(name)
        if fn is None:
            raise HclError(f"unsupported function {name}()")
        vals = []
        for a in args:
            if a[0] == "expand":
                vals.extend(self.ev(a[1]))
            else:
                vals.append(self.ev(a))
        if any(isinstance(v, SelfRef) for v in vals):
            raise Unknown()
        return fn(*vals)

    def _for(self, e):
        _, is_obj, v1, v2, coll, kx, vx, cond, grp = e
        c = self.ev(coll)
        pairs = list(c.items()) if isinstance(c, dict) else list(enumerate(c))
        out_l, out_d = [], {}
        for key, val in pairs:
            env = {v1: val} if v2 is None else {v1: key, v2: val}
            ch = self.child(**env)
            if cond is not None and not ch.ev(cond):
                continue
            if is_obj:
                kk = _tostr(ch.ev(kx))
                if grp:
                    out_d.setdefault(kk, []).append(ch.ev(vx))
                else:
                    out_d[kk] = ch.ev(vx)
            else:
                out_l.append(ch.ev(kx))
        return out_d if is_obj else out_l

    def _expand(self, e):  # pragma: no cover
        return self.ev(e[1])


def eval_body(body: Body, ev: Evaluator, skip: frozenset = frozenset()) -> tuple[dict[str, Any], list[tuple]]:
    """(attributes, blocks) with blocks shaped like the exporter's: (type, attrs, [children]). ``dynamic`` blocks are expanded."""
    attrs = {k: ev.ev(e) for k, e in body.attrs.items() if k not in skip}
    return attrs, eval_blocks(body, ev, skip)


def eval_blocks(body: Body, ev: Evaluator, skip: frozenset = frozenset()) -> list[tuple]:
    out: list[tuple] = []
    for btype, labels, b in body.blocks:
        if btype in skip:
            continue
        if btype == "dynamic":
            name = labels[0]
            coll = ev.ev(b.attrs["for_each"])
            it = (b.attrs.get("iterator") and b.attrs["iterator"][1]) or name
            content = next((x for t, _l, x in b.blocks if t == "content"), None)
            if content is None:
                continue
            pairs = list(coll.items()) if isinstance(coll, dict) else list(enumerate(coll))
            for k, v in pairs:
                child = ev.child(**{it: {"key": k, "value": v}})
                a, kids = eval_body(content, child)
                out.append((name, a, kids))
            continue
        a, kids = eval_body(b, ev)
        out.append((btype, a, kids))
    return out


# --------------------------------------------------------------------------------------------------------------- config model
class ResourceDef:
    def __init__(self, kind: str, rtype: str, name: str, body: Body, file: str):
        self.kind, self.type, self.name, self.body, self.file = kind, rtype, name, body, file
        self.addr = f"{rtype}.{name}" if kind == "resource" else f"data.{rtype}.{name}"


class Config:
    def __init__(self):
        self.resources: dict[str, ResourceDef] = {}
        self.data: dict[str, ResourceDef] = {}
        self.variables: dict[str, Body] = {}
        self.locals: dict[str, tuple] = {}
        self.outputs: dict[str, Body] = {}
        self.providers: list[tuple[list[str], Body]] = []
        self.tfvars: dict[str, Any] = {}
        self.errors: list[dict[str, Any]] = []


def parse_config(files: dict[str, str]) -> Config:
    """Parse every ``*.tf`` / ``*.tfvars`` text. Syntax errors are collected per file (the rest still loads)."""
    cfg = Config()
    var_files = sorted(n for n in files if n.endswith(".tfvars"))
    # terraform.tfvars first, then *.auto.tfvars in lexical order (later wins)
    var_files.sort(key=lambda n: (0 if n.rsplit("/", 1)[-1] == "terraform.tfvars" else 1, n))
    for name in sorted(n for n in files if n.endswith(".tf")):
        try:
            body = parse_body(files[name], name)
        except HclError as exc:
            cfg.errors.append({"file": name, "line": exc.line, "error": exc.msg})
            continue
        for a, e in body.attrs.items():
            cfg.errors.append({"file": name, "line": 0, "error": f"unexpected top-level attribute {a!r}"})
        for btype, labels, b in body.blocks:
            try:
                if btype in ("resource", "data") and len(labels) == 2:
                    d = ResourceDef(btype, labels[0], labels[1], b, name)
                    (cfg.resources if btype == "resource" else cfg.data)[d.addr if btype == "resource" else d.addr] = d
                elif btype == "variable" and len(labels) == 1:
                    cfg.variables[labels[0]] = b
                elif btype == "locals":
                    cfg.locals.update(b.attrs)
                elif btype == "output" and len(labels) == 1:
                    cfg.outputs[labels[0]] = b
                elif btype == "provider":
                    cfg.providers.append((labels, b))
            except HclError as exc:
                cfg.errors.append({"file": name, "line": exc.line, "error": exc.msg})
    for name in var_files:
        try:
            b = parse_body(files[name], name)
        except HclError as exc:
            cfg.errors.append({"file": name, "line": exc.line, "error": exc.msg})
            continue
        ev = Evaluator(_ConstScope())
        for k, e in b.attrs.items():
            try:
                cfg.tfvars[k] = ev.ev(e)
            except (HclError, Unknown) as exc:
                cfg.errors.append({"file": name, "line": 0, "error": f"{k}: {exc}"})
    return cfg


class _ConstScope:
    def each(self):
        raise HclError("each is not available here")

    def count_index(self):
        raise HclError("count.index is not available here")

    def var(self, n):
        raise HclError(f"var.{n} is not available in a tfvars file")

    local = var

    def resource(self, t, n):
        raise HclError("references are not available in a tfvars file")

    data = resource

    def file(self, p):
        raise HclError("file() is not available here")

    file_bytes = file

    def self_attr(self, n):
        raise HclError("self is not available here")
