# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""DynamoDB expression engine — substrate-free (host CPython + Pyodide).

v4 C0: the offline appliance now serves the DynamoDB wire from core/dynamodb_core.py
instead of proxying DynamoDB Local, so the expression language real apps rely on
lives here, once, for every substrate:

  * condition expressions — KeyConditionExpression, FilterExpression,
    ConditionExpression: = <> < <= > >=, BETWEEN, IN, AND / OR / NOT, parentheses,
    attribute_exists, attribute_not_exists, attribute_type, begins_with, contains,
    size();
  * update expressions — SET (incl. `a + :n`, `a - :n`, if_not_exists, list_append),
    REMOVE, ADD (number add / set union), DELETE (set difference);
  * projection expressions.

Operands are the core's NATIVE values (S→str, N→int|float, BOOL→bool, NULL→None,
L→list, M→dict, SS/NS→list); `:values` arrive typed and are converted with the
caller-supplied `to_native`. Paths support `#alias`, `a.b` and `a[0]`.
NO fastapi / boto3 / socket imports — vendored to Nano with the other cores.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

_TOKEN = re.compile(r"""
    \s*(?:
      (?P<op><>|<=|>=|=|<|>)
    | (?P<punct>[(),+\-])
    | (?P<value>:[A-Za-z0-9_]+)
    | (?P<path>(?:\#[A-Za-z0-9_]+|[A-Za-z_][A-Za-z0-9_]*)(?:\.(?:\#[A-Za-z0-9_]+|[A-Za-z_][A-Za-z0-9_]*)|\[\d+\])*)
    )""", re.X)
_KEYWORDS = {"AND", "OR", "NOT", "BETWEEN", "IN"}
_BOOL_FUNCS = {"attribute_exists", "attribute_not_exists", "attribute_type", "begins_with", "contains"}
_MISSING = object()


class ExprError(ValueError):
    """Malformed expression → the caller answers ValidationException."""


def _tokenize(expr: str) -> list[tuple[str, str]]:
    out, pos, s = [], 0, expr or ""
    while pos < len(s):
        if s[pos:].strip() == "":
            break
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            raise ExprError(f"Invalid expression: unexpected token near '{s[pos:pos + 12]}'")
        pos = m.end()
        kind = m.lastgroup
        text = m.group(kind)
        if kind == "path" and text.upper() in _KEYWORDS:
            kind, text = "kw", text.upper()
        out.append((kind, text))
    return out


class _Ctx:
    def __init__(self, names: dict | None, values: dict | None, to_native: Callable[[Any], Any]):
        self.names = names or {}
        self.values = values or {}
        self.to_native = to_native

    def path(self, raw: str) -> list:
        parts: list = []
        for seg in re.findall(r"\#?[A-Za-z0-9_]+|\[\d+\]", raw):
            if seg.startswith("["):
                parts.append(int(seg[1:-1]))
            elif seg.startswith("#"):
                if seg not in self.names:
                    raise ExprError(f"An expression attribute name used in the document path is not defined; attribute name: {seg}")
                parts.append(str(self.names[seg]))
            else:
                parts.append(seg)
        return parts

    def value(self, token: str) -> Any:
        if token not in self.values:
            raise ExprError(f"An expression attribute value used in expression is not defined; attribute value: {token}")
        return self.to_native(self.values[token])


def get_path(item: Any, parts: list) -> Any:
    cur = item
    for p in parts:
        if isinstance(p, int):
            if not isinstance(cur, list) or p >= len(cur):
                return _MISSING
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return _MISSING
            cur = cur[p]
    return cur


def _set_path(item: dict, parts: list, value: Any) -> None:
    cur = item
    for i, p in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        if isinstance(p, int):
            while len(cur) <= p:
                cur.append({} if not isinstance(nxt, int) else [])
            cur = cur[p]
        else:
            if not isinstance(cur.get(p), (dict, list)):
                cur[p] = [] if isinstance(nxt, int) else {}
            cur = cur[p]
    last = parts[-1]
    if isinstance(last, int):
        if last >= len(cur):
            cur.append(value)
        else:
            cur[last] = value
    else:
        cur[last] = value


def _remove_path(item: dict, parts: list) -> None:
    parent = get_path(item, parts[:-1]) if len(parts) > 1 else item
    last = parts[-1]
    if isinstance(last, int) and isinstance(parent, list) and last < len(parent):
        parent.pop(last)
    elif isinstance(parent, dict):
        parent.pop(last, None)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _compare(op: str, a: Any, b: Any) -> bool:
    if a is _MISSING or b is _MISSING:
        return False
    if op == "=":
        return a == b
    if op == "<>":
        return a != b
    if _is_num(a) and _is_num(b) or (isinstance(a, str) and isinstance(b, str)):
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    return False


def _type_of(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "BOOL"
    if _is_num(v):
        return "N"
    if isinstance(v, str):
        return "S"
    if isinstance(v, dict):
        return "M"
    if isinstance(v, list):
        if v and all(isinstance(x, str) for x in v):
            return "SS"
        if v and all(_is_num(x) for x in v):
            return "NS"
        return "L"
    return "B"


class _Parser:
    def __init__(self, tokens, ctx: _Ctx):
        self.t, self.i, self.ctx = tokens, 0, ctx

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None)

    def take(self, kind=None, text=None):
        tk = self.peek()
        if tk[0] is None or (kind and tk[0] != kind) or (text and tk[1] != text):
            raise ExprError(f"Invalid expression: expected {text or kind}, found {tk[1]!r}")
        self.i += 1
        return tk

    # condition grammar → closures over the item
    def cond(self):
        left = self.conj()
        while self.peek() == ("kw", "OR"):
            self.take()
            right = self.conj()
            left = (lambda l, r: lambda it: l(it) or r(it))(left, right)
        return left

    def conj(self):
        left = self.neg()
        while self.peek() == ("kw", "AND"):
            self.take()
            right = self.neg()
            left = (lambda l, r: lambda it: l(it) and r(it))(left, right)
        return left

    def neg(self):
        if self.peek() == ("kw", "NOT"):
            self.take()
            inner = self.neg()
            return lambda it: not inner(it)
        return self.primary()

    def primary(self):
        kind, text = self.peek()
        if (kind, text) == ("punct", "("):
            self.take()
            c = self.cond()
            self.take("punct", ")")
            return c
        if kind == "path" and text in _BOOL_FUNCS and self.peek(1) == ("punct", "("):
            return self.bool_func()
        left = self.operand()
        kind, text = self.peek()
        if kind == "op":
            self.take()
            right = self.operand()
            return lambda it: _compare(text, left(it), right(it))
        if (kind, text) == ("kw", "BETWEEN"):
            self.take()
            lo = self.operand()
            self.take("kw", "AND")
            hi = self.operand()
            return lambda it: _compare(">=", left(it), lo(it)) and _compare("<=", left(it), hi(it))
        if (kind, text) == ("kw", "IN"):
            self.take()
            self.take("punct", "(")
            opts = [self.operand()]
            while self.peek() == ("punct", ","):
                self.take()
                opts.append(self.operand())
            self.take("punct", ")")
            return lambda it: any(_compare("=", left(it), o(it)) for o in opts)
        raise ExprError(f"Invalid expression: expected a comparison, found {text!r}")

    def bool_func(self):
        name = self.take("path")[1]
        self.take("punct", "(")
        p = self.ctx.path(self.take("path")[1])
        arg = None
        if self.peek() == ("punct", ","):
            self.take()
            arg = self.operand()
        self.take("punct", ")")
        if name == "attribute_exists":
            return lambda it: get_path(it, p) is not _MISSING
        if name == "attribute_not_exists":
            return lambda it: get_path(it, p) is _MISSING
        if arg is None:
            raise ExprError(f"Invalid function: {name} needs two operands")
        if name == "attribute_type":
            return lambda it: get_path(it, p) is not _MISSING and _type_of(get_path(it, p)) == arg(it)
        if name == "begins_with":
            return lambda it: isinstance(get_path(it, p), str) and isinstance(arg(it), str) \
                and get_path(it, p).startswith(arg(it))

        def _contains(it):
            v, a = get_path(it, p), arg(it)
            if isinstance(v, str) and isinstance(a, str):
                return a in v
            return isinstance(v, list) and a in v
        return _contains

    def operand(self):
        kind, text = self.peek()
        if kind == "value":
            self.take()
            v = self.ctx.value(text)
            return lambda it: v
        if kind == "path" and text == "size" and self.peek(1) == ("punct", "("):
            self.take()
            self.take("punct", "(")
            p = self.ctx.path(self.take("path")[1])
            self.take("punct", ")")

            def _size(it):
                v = get_path(it, p)
                return _MISSING if v is _MISSING or not hasattr(v, "__len__") else len(v)
            return _size
        if kind == "path":
            self.take()
            p = self.ctx.path(text)
            return lambda it: get_path(it, p)
        raise ExprError(f"Invalid expression: unexpected token {text!r}")


def compile_condition(expr: str, names: dict | None, values: dict | None,
                      to_native: Callable[[Any], Any]) -> Callable[[dict], bool]:
    """Compile a condition / filter / key-condition expression into item -> bool."""
    expr = (expr or "").strip()
    if not expr:
        return lambda it: True
    p = _Parser(_tokenize(expr), _Ctx(names, values, to_native))
    fn = p.cond()
    if p.i != len(p.t):
        raise ExprError(f"Invalid expression: unexpected token {p.peek()[1]!r}")
    return fn


def key_condition_attrs(expr: str, names: dict | None) -> list[str]:
    """Top-level attribute names a KeyConditionExpression references (for validation)."""
    out = []
    for kind, text in _tokenize(expr or ""):
        if kind == "path" and text not in _BOOL_FUNCS and text != "size":
            out.append(str((names or {}).get(text, text)).split(".", 1)[0])
    return out


def _split_top(s: str, sep: str = ",") -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


_CLAUSE = re.compile(r"\b(SET|REMOVE|ADD|DELETE)\b", re.I)


def apply_update(item: dict, expr: str, names: dict | None, values: dict | None,
                 to_native: Callable[[Any], Any]) -> tuple[dict, set]:
    """Apply an UpdateExpression to a COPY of `item`. Returns (new_item, top-level
    attribute names touched)."""
    ctx = _Ctx(names, values, to_native)
    new = copy.deepcopy(item)
    touched: set = set()
    pieces = _CLAUSE.split(expr or "")
    if pieces and pieces[0].strip():
        raise ExprError(f"Invalid UpdateExpression: syntax error near '{pieces[0].strip()[:20]}'")
    for verb, body in zip(pieces[1::2], pieces[2::2]):
        verb = verb.upper()
        for action in _split_top(body):
            if verb == "SET":
                if "=" not in action:
                    raise ExprError(f"Invalid UpdateExpression: SET action '{action}' has no '='")
                lhs, rhs = action.split("=", 1)
                parts = ctx.path(lhs.strip())
                _set_path(new, parts, _eval_set_value(rhs.strip(), new, ctx))
                touched.add(parts[0])
            elif verb == "REMOVE":
                parts = ctx.path(action)
                _remove_path(new, parts)
                touched.add(parts[0])
            else:   # ADD / DELETE: "<path> :value"
                bits = action.split()
                if len(bits) != 2:
                    raise ExprError(f"Invalid UpdateExpression: {verb} action '{action}'")
                parts = ctx.path(bits[0])
                operand = ctx.value(bits[1])
                cur = get_path(new, parts)
                if verb == "ADD":
                    if cur is _MISSING:
                        result = operand
                    elif _is_num(cur) and _is_num(operand):
                        result = cur + operand
                    elif isinstance(cur, list) and isinstance(operand, list):
                        result = cur + [x for x in operand if x not in cur]
                    else:
                        raise ExprError("An operand in the update expression has an incorrect data type")
                else:
                    if cur is _MISSING:
                        continue
                    if not isinstance(cur, list) or not isinstance(operand, list):
                        raise ExprError("An operand in the update expression has an incorrect data type")
                    result = [x for x in cur if x not in operand]
                if isinstance(result, list) and not result:
                    _remove_path(new, parts)      # an empty set is removed
                else:
                    _set_path(new, parts, result)
                touched.add(parts[0])
    return new, touched


def _eval_set_value(rhs: str, item: dict, ctx: _Ctx) -> Any:
    """SET right-hand side: operand [(+|-) operand]; operands may be functions."""
    terms = _split_arith(rhs)
    if len(terms) == 1:
        return _set_operand(terms[0], item, ctx)
    a, op, b = terms
    va, vb = _set_operand(a, item, ctx), _set_operand(b, item, ctx)
    if not (_is_num(va) and _is_num(vb)):
        raise ExprError("An operand in the update expression has an incorrect data type")
    return va + vb if op == "+" else va - vb


def _split_arith(s: str) -> list[str]:
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch in "+-" and depth == 0 and i > 0:
            return [s[:i].strip(), ch, s[i + 1:].strip()]
    return [s.strip()]


def _set_operand(tok: str, item: dict, ctx: _Ctx) -> Any:
    tok = tok.strip()
    m = re.match(r"^(if_not_exists|list_append)\s*\((.*)\)$", tok, re.S)
    if m:
        args = _split_top(m.group(2))
        if len(args) != 2:
            raise ExprError(f"Invalid UpdateExpression: {m.group(1)} takes two operands")
        if m.group(1) == "if_not_exists":
            cur = get_path(item, ctx.path(args[0]))
            return cur if cur is not _MISSING else _set_operand(args[1], item, ctx)
        a, b = _set_operand(args[0], item, ctx), _set_operand(args[1], item, ctx)
        if not isinstance(a, list) or not isinstance(b, list):
            raise ExprError("An operand in the update expression has an incorrect data type")
        return a + b
    if tok.startswith(":"):
        return ctx.value(tok)
    v = get_path(item, ctx.path(tok))
    if v is _MISSING:
        raise ExprError("The provided expression refers to an attribute that does not exist in the item")
    return copy.deepcopy(v)


def project(item: dict, expr: str, names: dict | None) -> dict:
    """ProjectionExpression → the item restricted to the listed paths."""
    if not (expr or "").strip():
        return item
    ctx = _Ctx(names, {}, lambda v: v)
    out: dict = {}
    for raw in _split_top(expr):
        parts = ctx.path(raw)
        v = get_path(item, parts)
        if v is _MISSING:
            continue
        if all(isinstance(p, str) for p in parts):
            _set_path(out, parts, copy.deepcopy(v))
        else:
            out[parts[0]] = copy.deepcopy(item.get(parts[0]))
    return out
