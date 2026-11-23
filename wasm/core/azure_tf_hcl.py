# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Minimal HCL2 reader/writer used by the Azure Terraform (azurerm) exporter and importer.

Writer: ``Raw`` (verbatim expression) and ``Blocks`` (repeated nested blocks) values, deterministic
formatting. Reader: blocks, attributes, strings with ``${}`` interpolation, heredocs, numbers, bools,
null, lists, objects, references (``a.b.c[0]``), function calls; anything else (operators, for
expressions, splats) is captured as ``Expr`` so the importer can report it instead of guessing.
"""
from __future__ import annotations

import re

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


# ── writer ─────────────────────────────────────────────────────────────────────────────────────
class Raw(str):
    """A verbatim HCL expression (reference, function call...)."""


class Blocks(list):
    """Repeated nested blocks: each element is a dict of attributes (which may contain further Blocks)."""


def hq(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t").replace("${", "$${").replace("%{", "%%{") + '"'


def hval(v, ind=0) -> str:
    pad, pad2 = "  " * ind, "  " * (ind + 1)
    if isinstance(v, Raw):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return repr(int(v)) if isinstance(v, float) and v == int(v) and abs(v) < 1e15 else str(v)
    if isinstance(v, str):
        return hq(v)
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        if all(isinstance(x, (str, int, float, bool)) or isinstance(x, Raw) for x in v) and len(v) <= 6:
            return "[" + ", ".join(hval(x, ind) for x in v) + "]"
        return "[\n" + "".join(f"{pad2}{hval(x, ind + 1)},\n" for x in v) + f"{pad}]"
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{\n" + "".join(f"{pad2}{k if _IDENT.match(k) else hq(k)} = {hval(x, ind + 1)}\n" for k, x in v.items()) + f"{pad}}}"
    return hq(str(v))


def attrs_text(attrs: dict, ind=1) -> str:
    pad = "  " * ind
    out = []
    # plain attributes first (in insertion order), then nested blocks
    plain = [k for k, v in attrs.items() if not isinstance(v, Blocks) and v is not None]
    width = max((len(k) for k in plain), default=0)
    for k in plain:
        out.append(f"{pad}{k.ljust(width)} = {hval(attrs[k], ind)}")
    for k, v in attrs.items():
        if isinstance(v, Blocks):
            for b in v:
                body = attrs_text(b, ind + 1)
                out.append(f"{pad}{k} {{\n{body}{pad}}}" if body else f"{pad}{k} {{}}")
    return "\n".join(out) + ("\n" if out else "")


def resource_text(tf_type: str, label: str, attrs: dict) -> str:
    return f'resource "{tf_type}" "{label}" {{\n{attrs_text(attrs)}}}\n'


# ── reader ─────────────────────────────────────────────────────────────────────────────────────
class Ref(tuple):
    """A traversal like azurerm_resource_group.rg.name / var.x / each.key (tuple of segments)."""

    def text(self):
        return ".".join(str(p) if not isinstance(p, int) else f"[{p}]" for p in self)


class Interp(list):
    """A template string with interpolations: items are str or parsed expression nodes (Ref/Call/Expr)."""


class Call:
    def __init__(self, name, args):
        self.name, self.args = name, args


class Expr(str):
    """Source text of an expression this reader does not evaluate (operators, for-expressions, splats)."""


class HclError(Exception):
    pass


class Body:
    def __init__(self):
        self.attrs = {}
        self.blocks = []     # (type, labels, Body, line)


def parse(text: str) -> Body:
    return _P(text).body(top=True)


class _P:
    def __init__(self, s):
        self.s, self.i, self.n = s, 0, len(s)

    def line(self):
        return self.s.count("\n", 0, self.i) + 1

    def err(self, msg):
        raise HclError(f"line {self.line()}: {msg}")

    def ws(self, newlines=True):
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r" or (newlines and c == "\n"):
                self.i += 1
            elif c == "#" or s.startswith("//", self.i):
                while self.i < self.n and s[self.i] != "\n":
                    self.i += 1
            elif s.startswith("/*", self.i):
                j = s.find("*/", self.i + 2)
                self.i = self.n if j < 0 else j + 2
            else:
                break

    def ident(self):
        m = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*").match(self.s, self.i)
        if not m:
            self.err(f"expected identifier, found {self.s[self.i:self.i + 12]!r}")
        self.i = m.end()
        return m.group(0)

    def body(self, top=False):
        b = Body()
        while True:
            self.ws()
            if self.i >= self.n:
                if not top:
                    self.err("unterminated block")
                return b
            if self.s[self.i] == "}":
                if top:
                    self.err("unexpected '}'")
                self.i += 1
                return b
            line = self.line()
            name = self.ident()
            self.ws(False)
            if self.i < self.n and self.s[self.i] == "=" and not self.s.startswith("==", self.i):
                self.i += 1
                self.ws(False)
                b.attrs[name] = self.expr()
                continue
            labels = []
            while self.i < self.n:
                self.ws(False)
                c = self.s[self.i]
                if c == '"':
                    labels.append(self.string_plain())
                elif c == "{":
                    break
                elif re.match(r"[A-Za-z_]", c):
                    labels.append(self.ident())
                else:
                    self.err(f"unexpected {c!r} after block type '{name}'")
            if self.i >= self.n or self.s[self.i] != "{":
                self.err(f"expected '{{' after block '{name}'")
            self.i += 1
            b.blocks.append((name, labels, self.body(), line))

    def string_plain(self):
        v = self.string()
        if isinstance(v, Interp):
            self.err("block labels cannot contain interpolation")
        return v

    def string(self):
        s = self.s
        assert s[self.i] == '"'
        self.i += 1
        parts, buf = [], ""
        while self.i < self.n:
            c = s[self.i]
            if c == '"':
                self.i += 1
                if buf or not parts:
                    parts.append(buf)
                return parts[0] if len(parts) == 1 and isinstance(parts[0], str) else Interp(parts)
            if c == "\\":
                nx = s[self.i + 1:self.i + 2]
                buf += {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}.get(nx, nx)
                self.i += 2
                continue
            if s.startswith("$${", self.i):
                buf += "${"
                self.i += 3
                continue
            if s.startswith("%%{", self.i):
                buf += "%{"
                self.i += 3
                continue
            if s.startswith("${", self.i):
                if buf:
                    parts.append(buf)
                    buf = ""
                self.i += 2
                self.ws()
                parts.append(self.expr())
                self.ws()
                if self.i >= self.n or s[self.i] != "}":
                    self.err("unterminated interpolation")
                self.i += 1
                continue
            buf += c
            self.i += 1
        self.err("unterminated string")

    def heredoc(self):
        m = re.compile(r"<<(-?)([A-Za-z_][A-Za-z0-9_]*)\r?\n").match(self.s, self.i)
        indent, tag = m.group(1) == "-", m.group(2)
        j = m.end()
        lines = []
        while True:
            k = self.s.find("\n", j)
            ln = self.s[j:] if k < 0 else self.s[j:k]
            if ln.strip() == tag:
                self.i = self.n if k < 0 else k
                break
            lines.append(ln)
            if k < 0:
                self.err("unterminated heredoc")
            j = k + 1
        if indent:
            ind = min((len(x) - len(x.lstrip()) for x in lines if x.strip()), default=0)
            lines = [x[ind:] for x in lines]
        return "\n".join(lines) + "\n"

    def expr(self):
        node = self.primary()
        # a trailing operator / conditional / splat -> capture the whole expression as source
        save = self.i
        self.ws(False)
        if self.i < self.n and (self.s[self.i] in "?+*/%<>!&|" or self.s.startswith(("==", "!=", "-", "..."), self.i) and self.s[self.i] != "\n"):
            if self.s[self.i] == "-" and self.s.startswith("->", self.i):
                pass
            depth, j = 0, save
            start = self.i
            while self.i < self.n:
                c = self.s[self.i]
                if c in "([{":
                    depth += 1
                elif c in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif c == '"':
                    self.string()
                    continue
                elif c in ",\n" and depth == 0:
                    break
                self.i += 1
            return Expr(self.s[j:self.i].strip())
        self.i = save
        return node

    def primary(self):
        s = self.s
        self.ws(False)
        if self.i >= self.n:
            self.err("expected expression")
        c = s[self.i]
        if c == '"':
            return self.string()
        if s.startswith("<<", self.i):
            return self.heredoc()
        if c == "[":
            self.i += 1
            out = []
            while True:
                self.ws()
                if s[self.i] == "]":
                    self.i += 1
                    return out
                if s.startswith("for ", self.i) or s.startswith("for\t", self.i):
                    return self.capture_to_close("[", "]", start=self.i - 1)
                out.append(self.expr())
                self.ws()
                if s[self.i] == ",":
                    self.i += 1
        if c == "{":
            self.i += 1
            out = {}
            while True:
                self.ws()
                if s[self.i] == "}":
                    self.i += 1
                    return out
                if s.startswith("for ", self.i):
                    return self.capture_to_close("{", "}", start=self.i - 1)
                if s[self.i] == '"':
                    k = self.string()
                    k = k if isinstance(k, str) else Expr("interp")
                elif s[self.i] == "(":
                    k = Expr(self.capture_to_close("(", ")", start=self.i))
                else:
                    k = self.ident()
                self.ws(False)
                if s[self.i] not in "=:":
                    self.err("expected '=' in object")
                self.i += 1
                self.ws()
                out[str(k)] = self.expr()
                self.ws()
                if s[self.i] == ",":
                    self.i += 1
        if c == "(":
            return self.capture_to_close("(", ")", start=self.i)
        m = re.compile(r"-?\d+(\.\d+)?([eE][+-]?\d+)?").match(s, self.i)
        if m and not re.match(r"[A-Za-z_]", s[self.i]):
            self.i = m.end()
            t = m.group(0)
            return float(t) if ("." in t or "e" in t.lower()) else int(t)
        if re.match(r"[A-Za-z_]", c):
            name = self.ident()
            if name in ("true", "false", "null") and not (self.i < self.n and s[self.i] in ".(["):
                return {"true": True, "false": False, "null": None}[name]
            if self.i < self.n and s[self.i] == "(":
                self.i += 1
                args = []
                while True:
                    self.ws()
                    if s[self.i] == ")":
                        self.i += 1
                        break
                    args.append(self.expr())
                    self.ws()
                    if s[self.i] == ",":
                        self.i += 1
                return Call(name, args)
            segs = [name]
            while self.i < self.n:
                if s[self.i] == ".":
                    if s.startswith(".*", self.i):
                        return Expr(".".join(map(str, segs)) + ".*")
                    self.i += 1
                    if self.i < self.n and s[self.i].isdigit():
                        m = re.compile(r"\d+").match(s, self.i)
                        segs.append(int(m.group(0)))
                        self.i = m.end()
                    else:
                        segs.append(self.ident())
                elif s[self.i] == "[":
                    j = s.index("]", self.i)
                    inner = s[self.i + 1:j].strip()
                    if inner.lstrip("-").isdigit():
                        segs.append(int(inner))
                    elif inner.startswith('"') and inner.endswith('"'):
                        segs.append(inner[1:-1])
                    else:
                        return Expr(".".join(map(str, segs)) + s[self.i:j + 1])
                    self.i = j + 1
                else:
                    break
            return Ref(segs)
        self.err(f"unexpected {c!r}")

    def capture_to_close(self, o, c, start):
        depth, j = 0, start
        self.i = start
        while self.i < self.n:
            ch = self.s[self.i]
            if ch == '"':
                self.string()
                continue
            if ch == o:
                depth += 1
            elif ch == c:
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return Expr(self.s[j:self.i])
            self.i += 1
        self.err(f"unterminated '{o}'")
