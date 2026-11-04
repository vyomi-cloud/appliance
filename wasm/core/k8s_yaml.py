# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Minimal, dependency-free YAML reader for Kubernetes manifests (substrate-free: host CPython
and Pyodide alike — PyYAML is not part of the Nano bundle, and both substrates must parse a
manifest identically).

Supports what `kubectl apply -f` manifests use in practice: multi-document streams (`---`),
block mappings and sequences (including "- key: value" compact items), flow collections
(`{a: 1}` / `[a, b]`), single/double-quoted and plain scalars, block scalars (`|`, `|-`, `|+`,
`>`, `>-`), comments, and the YAML 1.1 scalar resolution go-yaml (and therefore kubectl)
applies to ints / floats / booleans / null. JSON documents are YAML and parse too.

Not supported — and rejected with a clear YAMLError instead of being misread: anchors and
aliases (`&a` / `*a`), tags (`!!str`), complex mapping keys (`? `) and directives (`%YAML`).

    load_all(text) -> list[object]   (empty documents are dropped, as kubectl does)
"""
from __future__ import annotations

import json
import re


class YAMLError(ValueError):
    pass


_INT = re.compile(r"^[-+]?(0|[1-9][0-9_]*)$")
_HEX = re.compile(r"^0x[0-9a-fA-F_]+$")
_OCT = re.compile(r"^0o?[0-7_]+$")
_FLOAT = re.compile(r"^[-+]?(\.[0-9]+|[0-9][0-9_]*(\.[0-9_]*)?)([eE][-+]?[0-9]+)?$")
# go-yaml v2 (what kubectl / sigs.k8s.io/yaml resolve with) treats the YAML 1.1 spellings as booleans too
_TRUE = {"true", "True", "TRUE", "y", "Y", "yes", "Yes", "YES", "on", "On", "ON"}
_FALSE = {"false", "False", "FALSE", "n", "N", "no", "No", "NO", "off", "Off", "OFF"}
_NULL = {"", "~", "null", "Null", "NULL"}


def _resolve(s: str):
    if s in _NULL:
        return None
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    if _INT.match(s):
        return int(s.replace("_", ""))
    if _HEX.match(s):
        return int(s[2:].replace("_", ""), 16)
    if len(s) > 1 and _OCT.match(s) and s.startswith("0"):
        return int(s.lstrip("0o").replace("_", "") or "0", 8)
    if _FLOAT.match(s) and any(c.isdigit() for c in s):
        try:
            return float(s.replace("_", ""))
        except ValueError:
            return s
    if s in (".inf", ".Inf", "+.inf"):
        return float("inf")
    if s in ("-.inf", "-.Inf"):
        return float("-inf")
    if s in (".nan", ".NaN"):
        return float("nan")
    return s


def _strip_comment(line: str) -> str:
    """Drop a trailing `# comment` that is not inside quotes (a '#' must follow whitespace)."""
    q, i, n = None, 0, len(line)
    while i < n:
        ch = line[i]
        if q == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                q = None
        elif q == "'":
            if ch == "'":
                if i + 1 < n and line[i + 1] == "'":
                    i += 2
                    continue
                q = None
        elif ch in "'\"" and (i == 0 or line[i - 1] in " \t:-[{,"):
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _unquote_double(s: str) -> str:
    out, i = [], 0
    esc = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "/": "/", " ": " ", "b": "\b", "f": "\f", "e": "\x1b", "a": "\x07", "v": "\x0b"}
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in esc:
                out.append(esc[n]); i += 2; continue
            if n == "x":
                out.append(chr(int(s[i + 2:i + 4], 16))); i += 4; continue
            if n == "u":
                out.append(chr(int(s[i + 2:i + 6], 16))); i += 6; continue
            if n == "U":
                out.append(chr(int(s[i + 2:i + 10], 16))); i += 10; continue
            out.append(n); i += 2; continue
        out.append(ch); i += 1
    return "".join(out)


# ── flow collections / inline scalars ────────────────────────────────────────────────────
class _Flow:
    def __init__(self, s: str):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\n":
            self.i += 1

    def value(self, stops: str):
        self.ws()
        if self.i >= len(self.s):
            return None
        ch = self.s[self.i]
        if ch == "{":
            return self.mapping()
        if ch == "[":
            return self.seq()
        if ch == '"':
            j = self.i + 1
            while j < len(self.s):
                if self.s[j] == "\\":
                    j += 2; continue
                if self.s[j] == '"':
                    break
                j += 1
            if j >= len(self.s):
                raise YAMLError("unterminated double-quoted string")
            v = _unquote_double(self.s[self.i + 1:j]); self.i = j + 1
            return v
        if ch == "'":
            j = self.i + 1
            buf = []
            while j < len(self.s):
                if self.s[j] == "'":
                    if j + 1 < len(self.s) and self.s[j + 1] == "'":
                        buf.append("'"); j += 2; continue
                    break
                buf.append(self.s[j]); j += 1
            if j >= len(self.s):
                raise YAMLError("unterminated single-quoted string")
            self.i = j + 1
            return "".join(buf)
        j = self.i
        while j < len(self.s) and self.s[j] not in stops:
            if self.s[j] == ":" and (j + 1 >= len(self.s) or self.s[j + 1] in " \t" ) and ":" in stops:
                break
            j += 1
        raw = self.s[self.i:j].strip(); self.i = j
        _reject_unsupported(raw)
        return _resolve(raw)

    def mapping(self):
        self.i += 1
        out = {}
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise YAMLError("unterminated flow mapping")
            if self.s[self.i] == "}":
                self.i += 1
                return out
            k = self.value(":,}")
            self.ws()
            v = None
            if self.i < len(self.s) and self.s[self.i] == ":":
                self.i += 1
                v = self.value(",}")
            out[k if not isinstance(k, (dict, list)) else json.dumps(k)] = v
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def seq(self):
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise YAMLError("unterminated flow sequence")
            if self.s[self.i] == "]":
                self.i += 1
                return out
            v = self.value(",]:")
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ":":   # [a: b] -> single-pair mapping
                self.i += 1
                v = {v: self.value(",]")}
                self.ws()
            out.append(v)
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1


def _reject_unsupported(raw: str):
    if raw[:1] in ("&", "*") and len(raw) > 1:
        raise YAMLError("YAML anchors and aliases are not supported by Vyomi's manifest reader")
    if raw[:1] == "!":
        raise YAMLError("YAML tags are not supported by Vyomi's manifest reader")


def _scalar(text: str):
    t = text.strip()
    if not t:
        return None
    if t[0] in "[{\"'":
        f = _Flow(t)
        v = f.value("")
        f.ws()
        if f.i < len(t):
            raise YAMLError(f"unexpected text after value: {t[f.i:]!r}")
        return v
    _reject_unsupported(t)
    return _resolve(t)


# ── block structure ──────────────────────────────────────────────────────────────────────
def _split_key(content: str):
    """'key: value' -> (key, rest) if the line is a mapping entry, else None."""
    if content[:1] in "\"'":
        f = _Flow(content)
        key = f.value("")
        rest = content[f.i:]
        if rest.startswith(":") and (len(rest) == 1 or rest[1] in " \t"):
            return key, rest[1:].strip()
        return None
    if content.startswith("? "):
        raise YAMLError("complex mapping keys are not supported by Vyomi's manifest reader")
    m = re.match(r"^([^\s#][^:]*?|[^:\s]):(?:\s+(.*)|$)", content)
    if not m or content[:1] in "[{":
        return None
    return m.group(1).strip(), (m.group(2) or "").strip()


class _Block:
    def __init__(self, lines):
        # (indent, content, raw_line) for non-blank, comment-stripped lines (raw kept for block scalars)
        self.raw = lines
        self.i = 0

    def _peek(self):
        while self.i < len(self.raw):
            raw = self.raw[self.i]
            content = _strip_comment(raw)
            if content.strip():
                return len(content) - len(content.lstrip(" ")), content.strip()
            self.i += 1
        return None

    def node(self, indent: int):
        p = self._peek()
        if p is None or p[0] < indent:
            return None
        ind, content = p
        if content == "-" or content.startswith("- "):
            return self.seq(ind)
        if _split_key(content) is not None:
            return self.mapping(ind)
        # a (possibly multi-line) plain/flow scalar
        self.i += 1
        parts = [content]
        while True:
            q = self._peek()
            if q is None or q[0] <= ind - 1 or q[0] < indent or _split_key(q[1]) is not None or q[1].startswith("- "):
                break
            parts.append(q[1]); self.i += 1
        return _scalar(" ".join(parts))

    def block_scalar(self, header: str, parent_indent: int):
        style, chomp = header[0], ""
        for c in header[1:]:
            if c in "+-":
                chomp = c
        lines, ind = [], None
        while self.i < len(self.raw):
            raw = self.raw[self.i].rstrip("\n")
            if raw.strip() == "":
                lines.append(""); self.i += 1; continue
            cur = len(raw) - len(raw.lstrip(" "))
            if ind is None:
                if cur <= parent_indent:
                    break
                ind = cur
            if cur < ind:
                break
            lines.append(raw[ind:]); self.i += 1
        # trailing blank lines belong to chomping, not to the next node
        trail = 0
        while lines and lines[-1] == "":
            lines.pop(); trail += 1
        if style == "|":
            text = "\n".join(lines)
        else:   # folded: single newlines become spaces, blank lines stay newlines
            out, prev_blank = [], False
            for ln in lines:
                if ln == "":
                    out.append("\n"); prev_blank = True
                elif out and not prev_blank and not out[-1].endswith("\n") and not ln.startswith(" "):
                    out.append(" " + ln)
                else:
                    out.append(ln); prev_blank = False
            text = "".join(out)
        if not lines:
            return ""
        if chomp == "-":
            return text
        if chomp == "+":
            return text + "\n" * (1 + trail)
        return text + "\n"

    def value_after(self, rest: str, ind: int, child_indent: int):
        if rest == "":
            nxt = self._peek()
            if nxt is not None and (nxt[0] > ind or (nxt[0] == ind and (nxt[1] == "-" or nxt[1].startswith("- ")) and child_indent == ind + 1)):
                return self.node(nxt[0] if nxt[0] > ind else ind)
            return None
        if rest[0] in "|>" and re.match(r"^[|>][-+0-9]*$", rest):
            return self.block_scalar(rest, ind)
        if rest[0] in "[{":
            # flow collections may span lines
            buf, depth = rest, _depth(rest)
            while depth > 0 and self.i < len(self.raw):
                nxt = _strip_comment(self.raw[self.i]).strip(); self.i += 1
                buf += " " + nxt; depth = _depth(buf)
            return _scalar(buf)
        # plain scalar that may continue on more-indented lines
        parts = [rest]
        while True:
            q = self._peek()
            if q is None or q[0] <= ind or _split_key(q[1]) is not None or q[1].startswith("- "):
                break
            parts.append(q[1]); self.i += 1
        return _scalar(" ".join(parts))

    def mapping(self, ind: int):
        out = {}
        while True:
            p = self._peek()
            if p is None or p[0] != ind:
                if p is not None and p[0] > ind:
                    raise YAMLError(f"bad indentation near {p[1]!r}")
                return out
            kv = _split_key(p[1])
            if kv is None:
                if p[1].startswith("- "):
                    return out
                raise YAMLError(f"expected a 'key: value' line, got {p[1]!r}")
            self.i += 1
            k, rest = kv
            k = _scalar(k) if isinstance(k, str) and k[:1] in "\"'" else k
            if k == "<<":
                raise YAMLError("YAML merge keys are not supported by Vyomi's manifest reader")
            out[k if isinstance(k, str) else str(k)] = self.value_after(rest, ind, ind + 1)

    def seq(self, ind: int):
        out = []
        while True:
            p = self._peek()
            if p is None or p[0] != ind or not (p[1] == "-" or p[1].startswith("- ")):
                return out
            raw = _strip_comment(self.raw[self.i])
            rest = p[1][1:].strip()
            item_indent = ind + 2 + (len(p[1][1:]) - len(p[1][1:].lstrip(" ")) - 1 if rest else 0)
            if rest == "":
                self.i += 1
                out.append(self.node(ind + 1))
                continue
            if rest[0] in "|>" and re.match(r"^[|>][-+0-9]*$", rest):
                self.i += 1
                out.append(self.block_scalar(rest, ind))
                continue
            kv = _split_key(rest)
            if kv is not None and rest[:1] not in "[{":
                # compact "- key: value" — rewrite this line as a mapping line at the item indent
                col = len(raw) - len(raw.lstrip(" ")) + (len(raw.lstrip(" ")) - len(raw.lstrip(" ")[1:].lstrip(" ")))
                self.raw[self.i] = " " * col + raw.lstrip(" ")[1:].lstrip(" ")
                out.append(self.mapping(col))
                continue
            if rest == "-" or rest.startswith("- "):
                col = len(raw) - len(raw.lstrip(" ")) + 2
                self.raw[self.i] = " " * col + rest
                out.append(self.seq(col))
                continue
            self.i += 1
            out.append(self.value_after(rest, ind, item_indent))


def _depth(s: str) -> int:
    d, q = 0, None
    for ch in s:
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch in "[{":
            d += 1
        elif ch in "]}":
            d -= 1
    return d


def load_all(text: str) -> list:
    if not isinstance(text, str):
        text = text.decode("utf-8")
    text = text.replace("\r\n", "\n")
    docs, cur = [], []
    for line in text.split("\n"):
        if line.startswith("%"):
            raise YAMLError("YAML directives are not supported by Vyomi's manifest reader")
        if re.match(r"^---(\s|$)", line) or re.match(r"^\.\.\.(\s|$)", line):
            docs.append(cur); cur = []
            tail = line[3:].strip()
            if tail and not tail.startswith("#") and line.startswith("---"):
                cur.append(tail)
            continue
        cur.append(line)
    docs.append(cur)
    out = []
    for lines in docs:
        if not any(_strip_comment(l).strip() for l in lines):
            continue
        b = _Block(list(lines))
        p = b._peek()
        v = b.node(p[0])
        rest = b._peek()
        if rest is not None:
            raise YAMLError(f"could not parse YAML near {rest[1]!r}")
        if v is not None:
            out.append(v)
    return out


def dump(obj, indent: int = 0) -> str:
    """Block-style YAML for `kubectl get -o yaml` output (round-trips through load_all)."""
    pad = " " * indent
    if isinstance(obj, dict):
        if not obj:
            return pad + "{}\n"
        out = []
        for k, v in obj.items():
            key = _dump_scalar(k) if not isinstance(k, str) or _needs_quote(k) else k
            if isinstance(v, dict) and v:
                out.append(f"{pad}{key}:\n" + dump(v, indent + 2))
            elif isinstance(v, list) and v:
                out.append(f"{pad}{key}:\n" + dump(v, indent))
            else:
                out.append(f"{pad}{key}: {_dump_scalar(v)}\n")
        return "".join(out)
    if isinstance(obj, list):
        if not obj:
            return pad + "[]\n"
        out = []
        for v in obj:
            if isinstance(v, (dict, list)) and v:
                inner = dump(v, indent + 2)
                out.append(f"{pad}- " + inner[indent + 2:])
            else:
                out.append(f"{pad}- {_dump_scalar(v)}\n")
        return "".join(out)
    return pad + _dump_scalar(obj) + "\n"


def _needs_quote(s: str) -> bool:
    if s == "" or s != s.strip() or "\n" in s:
        return True
    if _resolve(s) is not s and not isinstance(_resolve(s), str):
        return True
    if s[0] in "!&*-?{}[],#|>@`\"'%" or ": " in s or " #" in s or s.endswith(":"):
        return True
    return False


def _dump_scalar(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, dict):
        return "{}"
    if isinstance(v, list):
        return "[]"
    s = str(v)
    return json.dumps(s) if _needs_quote(s) else s
