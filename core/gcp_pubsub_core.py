"""GCP Pub/Sub core — substrate-independent in-memory eventing, the GCP analogue
of core/sns_core.py + core/sqs_core.py fused into one service. Speaks the native
**Pub/Sub REST API v1** (`https://pubsub.googleapis.com/v1/`, `projects/{p}/...`
resource names, JSON bodies, google.rpc-style errors) so the native
`google-cloud-pubsub` client (REST transport) works unchanged against it.

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Persists through the SAME MessagingStore seam as SNS/SQS (core/messaging_store.py):
topics live in `store.topics`, subscriptions (each with its own message backlog)
live in `store.queues` — so Pub/Sub covers BOTH the SNS topic-fanout half and the
SQS-style pull-and-ack half in a single service. Publishing to a topic fans a
message out to every subscription attached to that topic. Snapshots and schemas
(resources the SNS/SQS seam has no shape for) live in `store.pubsub`.

Scope: create/get/list/delete/patch topic (labels, CMEK, message retention,
schema settings), create/get/list/delete/patch subscription (labels, retention
+ retain-acked, expiration policy, message ordering + exactly-once flags, push
config, dead-letter policy, retry policy, subscription filter), publish (base64
data + attributes + ordering key → messageIds, validated against an attached
AVRO/JSON schema), pull (ack-deadline-based redelivery with exponential retry
backoff, per-ordering-key in-order delivery, dead-letter forwarding past
maxDeliveryAttempts, retention pruning), acknowledge, seek (to a snapshot OR,
when the topic has message retention enabled, to a point in time), and
snapshot / schema create+get+list+delete. Also modifyAckDeadline (nack / lease extension),
modifyPushConfig, subscriptions:detach, topics/{t}/subscriptions + topics/{t}/snapshots,
snapshot patch, schemas:validate / :validateMessage and get/set/testIamPermissions on all
four resource kinds (v4 C0g — what the offline appliance's pre-v4 handlers or the native
clients also use). Any other path under the four collections is a google.rpc NOT_FOUND /
INVALID_ARGUMENT JSON error.

DEPTH pass (this module): topic message retention now actually retains a
replayable backlog (seek-by-time), AVRO/JSON schema messages are validated on
publish, a subscription's ordering key is enforced in delivery order, retry
policy backoff really delays redelivery, and a subset of the subscription
filter language is evaluated at fan-out. Push delivery is recorded but never
actually dispatched over the network (no outbound HTTP from the simulator);
BigQuery/Cloud Storage subscriptions, topic ingestion and message transforms
are not modeled at all — see core/capabilities/gcp/pubsub.json.
"""
from __future__ import annotations

import base64
import fnmatch
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace

from core.messaging_store import MessagingStore


@dataclass
class PubsubResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


# ── primitives ────────────────────────────────────────────────────────────
def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _expires_rfc3339(seconds_from_now: float) -> str:
    return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + seconds_from_now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _next_message_id(store) -> str:
    seq = getattr(store, "_pubsub_msg_seq", 0) + 1
    store._pubsub_msg_seq = seq
    return str(seq)


def _json(status: int, obj: dict) -> PubsubResponse:
    return PubsubResponse(status=status, body=json.dumps(obj).encode())


def _err(code: int, status: str, message: str) -> PubsubResponse:
    body = {"error": {"code": code, "message": message, "status": status}}
    return PubsubResponse(status=code, body=json.dumps(body).encode())


class PubsubError(Exception):
    def __init__(self, code: int, status: str, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.code = code
        self.status = status
        self.message = message


def _parse_rfc3339(ts: str) -> float:
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


# ── subscription filter language (a documented subset of Pub/Sub's filter
# syntax: attribute equality/inequality, hasPrefix, has-attribute, NOT/AND/OR
# and parens — see core/capabilities/gcp/pubsub.json for what's NOT covered,
# e.g. the ':' substring operator) ──────────────────────────────────────────
class _FilterError(Exception):
    pass


_FILTER_TOKEN_RE = re.compile(r'\(|\)|,|!=|=|:|"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_.]*')


def _tokenize_filter(expr: str) -> list[str]:
    tokens: list[str] = []
    pos, n = 0, len(expr)
    while pos < n:
        if expr[pos].isspace():
            pos += 1
            continue
        m = _FILTER_TOKEN_RE.match(expr, pos)
        if not m:
            raise _FilterError(f"unexpected character {expr[pos]!r}")
        tokens.append(m.group(0))
        pos = m.end()
    return tokens


def _unquote(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1].replace('\\"', '"')
    return tok


class _FilterParser:
    """Recursive-descent parser: OR < AND < NOT < atom."""

    def __init__(self, tokens: list[str]) -> None:
        self.toks = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def advance(self) -> str:
        t = self.peek()
        if t is None:
            raise _FilterError("unexpected end of filter")
        self.i += 1
        return t

    def parse(self):
        node = self._or()
        if self.peek() is not None:
            raise _FilterError(f"unexpected trailing token {self.peek()!r}")
        return node

    def _or(self):
        left = self._and()
        while self.peek() == "OR":
            self.advance()
            left = ("OR", left, self._and())
        return left

    def _and(self):
        left = self._not()
        while self.peek() == "AND":
            self.advance()
            left = ("AND", left, self._not())
        return left

    def _not(self):
        if self.peek() == "NOT":
            self.advance()
            return ("NOT", self._not())
        return self._atom()

    def _atom(self):
        t = self.peek()
        if t == "(":
            self.advance()
            node = self._or()
            if self.advance() != ")":
                raise _FilterError("expected ')'")
            return node
        if t == "hasPrefix":
            self.advance()
            if self.advance() != "(":
                raise _FilterError("expected '(' after hasPrefix")
            ref = self.advance()
            if self.advance() != ",":
                raise _FilterError("expected ',' in hasPrefix(...)")
            val = _unquote(self.advance())
            if self.advance() != ")":
                raise _FilterError("expected ')' in hasPrefix(...)")
            return ("HASPREFIX", _ref_key(ref), val)
        ref = self.advance()
        nxt = self.peek()
        if nxt == ":":
            self.advance()
            return ("HAS", _unquote(self.advance()))
        if nxt == "=":
            self.advance()
            return ("EQ", _ref_key(ref), _unquote(self.advance()))
        if nxt == "!=":
            self.advance()
            return ("NEQ", _ref_key(ref), _unquote(self.advance()))
        raise _FilterError(f"unsupported expression near {ref!r}")


def _ref_key(ref: str) -> str:
    prefix = "attributes."
    if not ref.startswith(prefix) or len(ref) <= len(prefix):
        raise _FilterError(f"unsupported attribute reference {ref!r} (expected attributes.<key>)")
    return ref[len(prefix):]


def _compile_filter(expr: str):
    if not expr or not expr.strip():
        return None
    return _FilterParser(_tokenize_filter(expr)).parse()


def _eval_filter(node, attrs: dict) -> bool:
    op = node[0]
    if op == "AND":
        return _eval_filter(node[1], attrs) and _eval_filter(node[2], attrs)
    if op == "OR":
        return _eval_filter(node[1], attrs) or _eval_filter(node[2], attrs)
    if op == "NOT":
        return not _eval_filter(node[1], attrs)
    if op == "HAS":
        return node[1] in attrs
    if op == "HASPREFIX":
        val = attrs.get(node[1])
        return isinstance(val, str) and val.startswith(node[2])
    if op in ("EQ", "NEQ"):
        eq = attrs.get(node[1]) == node[2]
        return eq if op == "EQ" else not eq
    raise _FilterError(f"unknown filter op {op}")


def _message_matches(filter_expr: str | None, attrs: dict | None) -> bool:
    """A malformed filter (shouldn't happen — validated at create time) never
    silently drops traffic: it fails open, same as having no filter."""
    if not filter_expr:
        return True
    try:
        node = _compile_filter(filter_expr)
        return node is None or _eval_filter(node, attrs or {})
    except _FilterError:
        return True


# ── message transforms: a documented SUBSET of JavaScript UDFs, REALLY parsed and
# executed (not a fixed menu of transform kinds) — const/let, property get/set, delete,
# if/else, return, object/array literals + spread, JSON.parse/stringify, a few
# string/Object/Array builtins, +, ===, !==, &&, ||, !. No loops, classes, async, or
# arbitrary globals — see core/capabilities/gcp/pubsub.json for exactly what's covered.
# A transform returning null/undefined drops the message (matching the real API); a
# transform that fails to PARSE is rejected at topic create/patch time (INVALID_ARGUMENT,
# like the real API's compile step); a transform that throws AT RUNTIME is skipped for
# that one message — fails open, same policy as the filter language above — rather than
# blocking the whole publish call. ──────────────────────────────────────────────────────
class _JsTransformError(Exception):
    pass


_JS_TOKEN_SPEC = [
    (re.compile(r"//[^\n]*"), None),
    (re.compile(r"/\*.*?\*/", re.DOTALL), None),
    (re.compile(r"\s+"), None),
    (re.compile(r'"(?:[^"\\]|\\.)*"'), "string"),
    (re.compile(r"'(?:[^'\\]|\\.)*'"), "string"),
    (re.compile(r"-?\d+(?:\.\d+)?"), "number"),
    (re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*"), "ident"),
    (re.compile(r"===|!==|&&|\|\||\.\.\.|[{}()\[\].,;=!+:]"), "punct"),
]


def _js_unescape(s: str) -> str:
    return (s.replace('\\"', '"').replace("\\'", "'").replace("\\n", "\n")
            .replace("\\t", "\t").replace("\\\\", "\\"))


def _js_tokenize(src: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    pos, n = 0, len(src)
    while pos < n:
        for pat, kind in _JS_TOKEN_SPEC:
            m = pat.match(src, pos)
            if m:
                if kind:
                    val = m.group(0)
                    toks.append((kind, _js_unescape(val[1:-1]) if kind == "string" else val))
                pos = m.end()
                break
        else:
            raise _JsTransformError(f"unexpected character {src[pos]!r}")
    return toks


class _JsParser:
    """Recursive-descent parser for the documented JS subset: a single top-level
    `function name(message, metadata) { ... }` declaration."""

    def __init__(self, toks: list[tuple[str, str]]) -> None:
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def at(self, kind, val=None) -> bool:
        k, v = self.peek()
        return k == kind and (val is None or v == val)

    def advance(self):
        t = self.peek()
        if t[0] is None:
            raise _JsTransformError("unexpected end of input")
        self.i += 1
        return t

    def expect(self, kind, val=None):
        if not self.at(kind, val):
            raise _JsTransformError(f"expected {val or kind}, got {self.peek()}")
        return self.advance()

    def parse_function(self):
        self.expect("ident", "function")
        if self.at("ident") and not self.at("punct", "("):
            self.advance()   # function name — not referenced; the topic's own entry names it
        self.expect("punct", "(")
        params = []
        while not self.at("punct", ")"):
            params.append(self.expect("ident")[1])
            if self.at("punct", ","):
                self.advance()
        self.expect("punct", ")")
        body = self.parse_block()
        if self.peek()[0] is not None:
            raise _JsTransformError("unexpected trailing input after function body")
        return params, body

    def parse_block(self):
        self.expect("punct", "{")
        stmts = []
        while not self.at("punct", "}"):
            stmts.append(self.parse_statement())
        self.expect("punct", "}")
        return stmts

    def parse_statement(self):
        if self.at("ident", "const") or self.at("ident", "let") or self.at("ident", "var"):
            self.advance()
            ident = self.expect("ident")[1]
            self.expect("punct", "=")
            value = self.parse_expr()
            self.expect("punct", ";")
            return ("decl", ident, value)
        if self.at("ident", "return"):
            self.advance()
            if self.at("punct", ";"):
                self.advance()
                return ("return", None)
            value = self.parse_expr()
            self.expect("punct", ";")
            return ("return", value)
        if self.at("ident", "if"):
            self.advance()
            self.expect("punct", "(")
            cond = self.parse_expr()
            self.expect("punct", ")")
            then = self.parse_block()
            otherwise = None
            if self.at("ident", "else"):
                self.advance()
                otherwise = self.parse_block()
            return ("if", cond, then, otherwise)
        if self.at("ident", "delete"):
            self.advance()
            target = self.parse_postfix()
            self.expect("punct", ";")
            return ("delete", target)
        expr = self.parse_postfix()
        if self.at("punct", "="):
            self.advance()
            value = self.parse_expr()
            self.expect("punct", ";")
            return ("assign", expr, value)
        self.expect("punct", ";")
        return ("expr", expr)

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.at("punct", "||"):
            self.advance()
            left = ("bin", "||", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_eq()
        while self.at("punct", "&&"):
            self.advance()
            left = ("bin", "&&", left, self.parse_eq())
        return left

    def parse_eq(self):
        left = self.parse_add()
        while self.at("punct", "===") or self.at("punct", "!=="):
            op = self.advance()[1]
            left = ("bin", op, left, self.parse_add())
        return left

    def parse_add(self):
        left = self.parse_unary()
        while self.at("punct", "+"):
            self.advance()
            left = ("bin", "+", left, self.parse_unary())
        return left

    def parse_unary(self):
        if self.at("punct", "!"):
            self.advance()
            return ("unary", "!", self.parse_unary())
        return self.parse_postfix()

    def parse_postfix(self):
        node = self.parse_primary()
        while True:
            if self.at("punct", "."):
                self.advance()
                prop = self.expect("ident")[1]
                node = ("member", node, prop)
            elif self.at("punct", "["):
                self.advance()
                idx = self.parse_expr()
                self.expect("punct", "]")
                node = ("index", node, idx)
            elif self.at("punct", "("):
                self.advance()
                args = []
                while not self.at("punct", ")"):
                    args.append(self.parse_expr())
                    if self.at("punct", ","):
                        self.advance()
                self.expect("punct", ")")
                node = ("call", node, args)
            else:
                return node

    def parse_primary(self):
        k, v = self.peek()
        if k == "string":
            self.advance()
            return ("lit", v)
        if k == "number":
            self.advance()
            return ("lit", float(v) if "." in v else int(v))
        if k == "ident" and v in ("true", "false"):
            self.advance()
            return ("lit", v == "true")
        if k == "ident" and v in ("null", "undefined"):
            self.advance()
            return ("lit", None)
        if k == "ident":
            self.advance()
            return ("ident", v)
        if k == "punct" and v == "(":
            self.advance()
            e = self.parse_expr()
            self.expect("punct", ")")
            return e
        if k == "punct" and v == "{":
            return self.parse_object()
        if k == "punct" and v == "[":
            return self.parse_array()
        raise _JsTransformError(f"unexpected token {k}:{v!r}")

    def parse_object(self):
        self.expect("punct", "{")
        entries = []
        while not self.at("punct", "}"):
            if self.at("punct", "..."):
                self.advance()
                entries.append(("spread", self.parse_expr()))
            else:
                k, v = self.peek()
                if k not in ("ident", "string"):
                    raise _JsTransformError("expected an object key")
                self.advance()
                self.expect("punct", ":")
                entries.append(("kv", v, self.parse_expr()))
            if self.at("punct", ","):
                self.advance()
        self.expect("punct", "}")
        return ("obj", entries)

    def parse_array(self):
        self.expect("punct", "[")
        items = []
        while not self.at("punct", "]"):
            items.append(self.parse_expr())
            if self.at("punct", ","):
                self.advance()
        self.expect("punct", "]")
        return ("arr", items)


_JS_STR_METHODS = {
    "toUpperCase": lambda s, a: s.upper(),
    "toLowerCase": lambda s, a: s.lower(),
    "trim": lambda s, a: s.strip(),
    "includes": lambda s, a: (a[0] in s) if a else False,
    "startsWith": lambda s, a: s.startswith(a[0]) if a else False,
    "endsWith": lambda s, a: s.endswith(a[0]) if a else False,
    "split": lambda s, a: s.split(a[0]) if a else [s],
}


def _js_truthy(v) -> bool:
    return not (v is None or v is False or v == "" or v == 0)


def _js_to_string(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def _js_get_member(obj, prop):
    if isinstance(obj, dict):
        return obj.get(prop)
    if prop == "length" and isinstance(obj, (str, list)):
        return len(obj)
    if isinstance(obj, list) and isinstance(prop, int) and 0 <= prop < len(obj):
        return obj[prop]
    return None


def _js_eval(node, env):
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "ident":
        if node[1] not in env:
            raise _JsTransformError(f"{node[1]!r} is not defined")
        return env[node[1]]
    if kind == "member":
        return _js_get_member(_js_eval(node[1], env), node[2])
    if kind == "index":
        return _js_get_member(_js_eval(node[1], env), _js_eval(node[2], env))
    if kind == "call":
        return _js_call(node[1], node[2], env)
    if kind == "obj":
        out: dict = {}
        for e in node[1]:
            if e[0] == "spread":
                v = _js_eval(e[1], env)
                if isinstance(v, dict):
                    out.update(v)
            else:
                out[e[1]] = _js_eval(e[2], env)
        return out
    if kind == "arr":
        return [_js_eval(n, env) for n in node[1]]
    if kind == "unary":
        return not _js_truthy(_js_eval(node[2], env))
    if kind == "bin":
        op = node[1]
        if op == "&&":
            left = _js_eval(node[2], env)
            return _js_eval(node[3], env) if _js_truthy(left) else left
        if op == "||":
            left = _js_eval(node[2], env)
            return left if _js_truthy(left) else _js_eval(node[3], env)
        left, right = _js_eval(node[2], env), _js_eval(node[3], env)
        if op == "===":
            return type(left) is type(right) and left == right
        if op == "!==":
            return not (type(left) is type(right) and left == right)
        if op == "+":
            if isinstance(left, str) or isinstance(right, str):
                return _js_to_string(left) + _js_to_string(right)
            return left + right
    raise _JsTransformError(f"unsupported expression {kind!r}")


def _js_call(callee, arg_nodes, env):
    args = [_js_eval(a, env) for a in arg_nodes]
    if callee[0] == "member":
        base_node, prop = callee[1], callee[2]
        if base_node[0] == "ident" and base_node[1] in ("JSON", "Object", "Array"):
            ns = base_node[1]
            if ns == "JSON" and prop == "parse":
                try:
                    return json.loads(args[0])
                except Exception:
                    raise _JsTransformError("JSON.parse: invalid JSON")
            if ns == "JSON" and prop == "stringify":
                return json.dumps(args[0] if args else None)
            if ns == "Object" and prop == "keys":
                return list(args[0].keys()) if args and isinstance(args[0], dict) else []
            if ns == "Array" and prop == "isArray":
                return bool(args) and isinstance(args[0], list)
            raise _JsTransformError(f"unsupported call {ns}.{prop}()")
        base = _js_eval(base_node, env)
        if isinstance(base, str) and prop in _JS_STR_METHODS:
            return _JS_STR_METHODS[prop](base, args)
        if isinstance(base, list) and prop == "includes":
            return bool(args) and args[0] in base
        if isinstance(base, list) and prop == "join":
            return (args[0] if args else ",").join(_js_to_string(x) for x in base)
        raise _JsTransformError(f"unsupported method call .{prop}()")
    if callee[0] == "ident":
        name = callee[1]
        if name == "String":
            return _js_to_string(args[0]) if args else ""
        if name == "Boolean":
            return _js_truthy(args[0]) if args else False
        if name == "Number":
            try:
                s = str(args[0]) if args else "0"
                return float(s) if "." in s else int(s)
            except (TypeError, ValueError):
                raise _JsTransformError("Number(): invalid value")
        raise _JsTransformError(f"unsupported call to {name}()")
    raise _JsTransformError("unsupported call expression")


def _js_assign(target, value, env) -> None:
    if target[0] == "ident":
        env[target[1]] = value
        return
    if target[0] == "member":
        obj = _js_eval(target[1], env)
        if not isinstance(obj, dict):
            raise _JsTransformError("cannot set a property on a non-object value")
        obj[target[2]] = value
        return
    if target[0] == "index":
        obj, key = _js_eval(target[1], env), _js_eval(target[2], env)
        if isinstance(obj, dict):
            obj[key] = value
        elif isinstance(obj, list) and isinstance(key, int):
            while len(obj) <= key:
                obj.append(None)
            obj[key] = value
        else:
            raise _JsTransformError("unsupported assignment target")
        return
    raise _JsTransformError("unsupported assignment target")


def _js_delete(target, env) -> None:
    if target[0] in ("member", "index"):
        obj = _js_eval(target[1], env)
        key = target[2] if target[0] == "member" else _js_eval(target[2], env)
        if isinstance(obj, dict):
            obj.pop(key, None)
        return
    raise _JsTransformError("unsupported delete target")


def _js_run_block(stmts, env):
    """Executes a block; returns (returned, value) so an explicit `return` inside a
    nested `if` short-circuits every enclosing block, same as JS control flow."""
    for s in stmts:
        kind = s[0]
        if kind == "decl":
            env[s[1]] = _js_eval(s[2], env)
        elif kind == "assign":
            _js_assign(s[1], _js_eval(s[2], env), env)
        elif kind == "delete":
            _js_delete(s[1], env)
        elif kind == "expr":
            _js_eval(s[1], env)
        elif kind == "if":
            branch = s[2] if _js_truthy(_js_eval(s[1], env)) else s[3]
            if branch is not None:
                returned, value = _js_run_block(branch, env)
                if returned:
                    return True, value
        elif kind == "return":
            return True, (_js_eval(s[1], env) if s[1] is not None else None)
        else:
            raise _JsTransformError(f"unsupported statement {kind!r}")
    return False, None


def _compile_js_transform(code: str):
    """Parse one javascriptUdf.code string into (params, body) ONCE, at topic create/patch
    time — a syntax/shape error the transform's subset doesn't cover is rejected right
    there (INVALID_ARGUMENT), matching the real API's own compile-time validation."""
    try:
        return _JsParser(_js_tokenize(code)).parse_function()
    except _JsTransformError as e:
        raise PubsubError(400, "INVALID_ARGUMENT", f"Invalid message transform: {e}")


def _compile_transforms(transforms: list[dict]) -> list[tuple]:
    compiled = []
    for t in transforms or []:
        udf = (t or {}).get("javascriptUdf") or {}
        code = str(udf.get("code") or "")
        if not code.strip():
            raise PubsubError(400, "INVALID_ARGUMENT", "messageTransforms[].javascriptUdf.code is required.")
        compiled.append(_compile_js_transform(code))
    return compiled


def _run_js_transform(params: list[str], body, message: dict, attrs: dict):
    """Runs one compiled transform against a {data, attributes} message view (`data` as
    a decoded UTF-8 string, matching the real UDF's view of the message — never base64).
    Returns the (possibly mutated) message dict, or None to DROP the message (falling off
    the end of the function, like plain JS, returns undefined — also a drop)."""
    env: dict = {}
    if params:
        env[params[0]] = message
    if len(params) > 1:
        env[params[1]] = {"attributes": dict(attrs)}
    returned, value = _js_run_block(body, env)
    return value if returned else None


def _apply_message_transforms(topic: dict, record: dict) -> dict | None:
    transforms = topic.get("_compiled_transforms")
    if not transforms:
        return record
    try:
        text = base64.b64decode(record.get("data") or "").decode("utf-8")
    except Exception:
        return record   # a non-UTF-8 payload passes through unchanged: this text-oriented subset can't view it
    view = {"data": text, "attributes": dict(record.get("attributes") or {})}
    for params, body in transforms:
        try:
            result = _run_js_transform(params, body, dict(view), view["attributes"])
        except _JsTransformError:
            continue   # fails open: a runtime error in a transform never blocks the publish call
        if result is None:
            return None   # the transform dropped the message
        if not isinstance(result, dict):
            continue
        view = {"data": _js_to_string(result.get("data", view["data"])),
                "attributes": dict(result.get("attributes") or view["attributes"])}
    out = dict(record)
    out["data"] = base64.b64encode(view["data"].encode("utf-8")).decode()
    out["attributes"] = view["attributes"]
    return out


# ── AVRO/JSON schema validation (a documented subset: scalars, unions,
# records/arrays/maps/enums by structural shape — not full Avro semantics) ──
_AVRO_SCALARS = {
    "null": type(None), "boolean": bool, "int": int, "long": int,
    "float": (int, float), "double": (int, float), "string": str, "bytes": str,
}


def _avro_matches(schema_type, value) -> bool:
    if isinstance(schema_type, list):              # union, e.g. ["null", "string"]
        return any(_avro_matches(t, value) for t in schema_type)
    if isinstance(schema_type, str):
        if schema_type == "record":
            return isinstance(value, dict)          # named-type reference Vyomi doesn't resolve
        py = _AVRO_SCALARS.get(schema_type)
        if py is None:
            return True
        if py is bool:
            return isinstance(value, bool)
        if py is int:
            return isinstance(value, int) and not isinstance(value, bool)
        return isinstance(value, py)
    if not isinstance(schema_type, dict):
        return True
    kind = schema_type.get("type")
    if kind == "record":
        if not isinstance(value, dict):
            return False
        for f in schema_type.get("fields", []):
            fname = f.get("name")
            if fname not in value:
                ftype = f.get("type")
                if "default" in f or (isinstance(ftype, list) and "null" in ftype):
                    continue
                return False
            if not _avro_matches(f.get("type"), value[fname]):
                return False
        return True
    if kind == "array":
        return isinstance(value, list) and all(_avro_matches(schema_type.get("items"), v) for v in value)
    if kind == "map":
        return isinstance(value, dict)
    if kind == "enum":
        return value in schema_type.get("symbols", [value])
    return _avro_matches(kind, value)


def _validate_schema_message(store, topic: dict, record: dict) -> None:
    settings = topic.get("schemaSettings")
    if not settings or not settings.get("schema"):
        return
    schema = _schema_store(store).get(settings["schema"])
    if not schema:
        return
    encoding = str(settings.get("encoding") or "JSON").upper()
    if schema.get("type") != "AVRO" or encoding != "JSON":
        return  # BINARY-encoded Avro and PROTOCOL_BUFFER payloads aren't decoded in Vyomi
    try:
        parsed = json.loads(base64.b64decode(record["data"] or "").decode("utf-8"))
    except Exception:
        raise PubsubError(400, "INVALID_ARGUMENT", "Message data is not valid JSON for the topic's AVRO/JSON schema.")
    try:
        avro_schema = json.loads(schema.get("definition") or "null")
    except Exception:
        avro_schema = None
    if avro_schema is not None and not _avro_matches(avro_schema, parsed):
        raise PubsubError(400, "INVALID_ARGUMENT", "Message does not match the topic's schema.")


def _snap_store(store) -> dict:
    return store.pubsub.setdefault("snapshots", {})


def _schema_store(store) -> dict:
    return store.pubsub.setdefault("schemas", {})


# ── resource views ────────────────────────────────────────────────────────
def _topic_view(topic: dict) -> dict:
    v: dict = {"name": topic["name"]}
    if topic.get("labels"):
        v["labels"] = topic["labels"]
    if topic.get("kmsKeyName"):
        v["kmsKeyName"] = topic["kmsKeyName"]
    if topic.get("messageRetentionDuration"):
        v["messageRetentionDuration"] = topic["messageRetentionDuration"]
    if topic.get("schemaSettings"):
        v["schemaSettings"] = topic["schemaSettings"]
    if topic.get("messageTransforms"):
        v["messageTransforms"] = topic["messageTransforms"]
    if topic.get("ingestionDataSourceSettings"):
        v["ingestionDataSourceSettings"] = topic["ingestionDataSourceSettings"]
    return v


def _subscription_view(sub: dict) -> dict:
    v = {
        "name": sub["name"],
        "topic": sub["topic"],
        "pushConfig": sub.get("pushConfig") or {},
        "ackDeadlineSeconds": sub.get("ackDeadlineSeconds", 10),
        "messageRetentionDuration": sub.get("messageRetentionDuration", "604800s"),
        "expirationPolicy": sub.get("expirationPolicy", {"ttl": "2678400s"}),
    }
    if sub.get("labels"):
        v["labels"] = sub["labels"]
    if sub.get("retainAckedMessages"):
        v["retainAckedMessages"] = True
    if sub.get("enableMessageOrdering"):
        v["enableMessageOrdering"] = True
    if sub.get("enableExactlyOnceDelivery"):
        v["enableExactlyOnceDelivery"] = True
    if sub.get("deadLetterPolicy"):
        v["deadLetterPolicy"] = sub["deadLetterPolicy"]
    if sub.get("retryPolicy"):
        v["retryPolicy"] = sub["retryPolicy"]
    if sub.get("filter"):
        v["filter"] = sub["filter"]
    if sub.get("cloudStorageConfig"):
        v["cloudStorageConfig"] = sub["cloudStorageConfig"]
    return v


def _snapshot_view(snap: dict) -> dict:
    v = {"name": snap["name"], "topic": snap["topic"], "expireTime": snap["expireTime"],
         # `subscription` is beyond the real Snapshot resource shape (kept for the console's
         # "Subscription" column); real SDKs ignore unknown JSON fields.
         "subscription": snap.get("subscription", "")}
    if snap.get("labels"):
        v["labels"] = snap["labels"]
    return v


def _schema_view(schema: dict, full: bool = False) -> dict:
    v = {"name": schema["name"], "type": schema.get("type", "TYPE_UNSPECIFIED"),
         "revisionId": schema.get("revisionId", ""), "revisionCreateTime": schema.get("revisionCreateTime", "")}
    if full:
        v["definition"] = schema.get("definition", "")
    return v


def _require_topic(store, name: str) -> dict:
    t = store.get_topic(name)
    if not t:
        raise PubsubError(404, "NOT_FOUND", f"Topic not found: {name}")
    return t


def _require_subscription(store, name: str) -> dict:
    s = store.get_queue(name)
    if not s:
        raise PubsubError(404, "NOT_FOUND", f"Subscription not found: {name}")
    return s


# ── Cloud Storage ingestion/delivery + Cloud Monitoring metrics: cross-core seams onto
# the SAME simulator stores every other native-wire call reaches (ADR-001 "nothing leaves
# the simulator") — wired by core/aws_wire_router.py onto the shared MessagingStore as
# `.gcs_store` / `.mon_store`, exactly like gcp_logging_core's usage-metrics mirror. ──────
def _validate_ingestion_settings(settings: dict) -> None:
    gcs = (settings or {}).get("cloudStorage")
    if gcs is None:
        # Every OTHER declared source (awsKinesis, azureEventHubs, confluentCloud,
        # platformLogsSettings/CDC, …) names an external system that has no connector
        # anywhere in Vyomi — not "out of scope for Pub/Sub", there is no such resource
        # type simulated at all to read from.
        raise PubsubError(400, "INVALID_ARGUMENT",
                           "Only ingestionDataSourceSettings.cloudStorage is supported in Vyomi: AWS Kinesis, "
                           "Azure Event Hubs, Confluent/Kafka and database CDC sources have no connector "
                           "simulated anywhere in Vyomi.")
    if not str(gcs.get("bucket", "")).strip():
        raise PubsubError(400, "INVALID_ARGUMENT", "ingestionDataSourceSettings.cloudStorage.bucket is required.")


def _sync_cloud_storage_ingestion(store, topic: dict) -> None:
    """Lazily (no background poller exists) catch up a topic's Cloud Storage ingestion:
    called from every real entry point that touches the topic (get, publish, a pull on one
    of its subscriptions), so the console sees new objects without a continuous pull of
    its own. Each object not ingested before is published as one message, keyed by its
    generation so it is never re-ingested after being overwritten with the same name."""
    settings = (topic.get("ingestionDataSourceSettings") or {}).get("cloudStorage")
    if not settings:
        return
    gcs_store = getattr(store, "gcs_store", None)
    if gcs_store is None:
        return
    bucket = settings.get("bucket", "")
    if not gcs_store.bucket_exists(bucket):
        return
    from core.gcp_storage_core import _entry_bytes
    seen = topic.setdefault("_ingested", set())
    glob = settings.get("matchGlob") or ""
    new_records = []
    for oname, entry in sorted(gcs_store.bucket_objects(bucket).items()):
        key = f"{oname}#{entry.get('generation', 1)}"
        if key in seen:
            continue
        seen.add(key)
        if glob and not fnmatch.fnmatch(oname, glob):
            continue
        data = _entry_bytes(gcs_store, bucket, oname, entry)
        new_records.append({
            "data": base64.b64encode(data).decode(),
            "attributes": {"objectId": oname, "bucket": bucket},
            "messageId": _next_message_id(store),
            "publishTime": _now_rfc3339(),
        })
    if not new_records:
        return
    retain = bool(topic.get("messageRetentionDuration"))
    for record in new_records:
        _fanout(store, topic, record)
        if retain:
            topic.setdefault("_retained", []).append({**record, "_publish_at": store.now()})
    if retain:
        _prune_topic_retention(store, topic)
    topic["_publish_count"] = topic.get("_publish_count", 0) + len(new_records)
    store.persist()


def _validate_cloud_storage_config(store, cfg: dict) -> None:
    bucket = str((cfg or {}).get("bucket", "")).strip()
    if not bucket:
        raise PubsubError(400, "INVALID_ARGUMENT", "cloudStorageConfig.bucket is required.")
    gcs_store = getattr(store, "gcs_store", None)
    if gcs_store is None or not gcs_store.bucket_exists(bucket):
        raise PubsubError(404, "NOT_FOUND", f"Cloud Storage bucket not found: {bucket}")
    if cfg.get("avroConfig"):
        raise PubsubError(400, "INVALID_ARGUMENT",
                           "cloudStorageConfig.avroConfig isn't modeled in Vyomi: messages are always "
                           "written as newline-delimited TEXT objects.")


def _deliver_to_cloud_storage(store, sub: dict, record: dict) -> None:
    """A Cloud Storage subscription writes each delivered message as a REAL object in the
    simulator's own GCS bucket (never queued on the subscription) — one object per
    message, named from the subscription's filenamePrefix/Suffix, matching
    `outputFormat: TEXT` (the only format Vyomi models; see _validate_cloud_storage_config)."""
    gcs_store = getattr(store, "gcs_store", None)
    cfg = sub.get("cloudStorageConfig")
    if gcs_store is None or not cfg or not gcs_store.bucket_exists(cfg.get("bucket", "")):
        return
    try:
        text = base64.b64decode(record.get("data") or "").decode("utf-8")
    except Exception:
        text = record.get("data", "")
    from core.gcp_storage_core import _new_entry
    bucket = cfg["bucket"]
    objs = gcs_store.bucket_objects(bucket)
    sub_id = sub["name"].rsplit("/", 1)[-1]
    key = f"{cfg.get('filenamePrefix', '')}{sub_id}-{record['messageId']}{cfg.get('filenameSuffix', '') or '.txt'}"
    objs[key] = _new_entry(objs, key, (text + "\n").encode("utf-8"), "text/plain", {})
    gcs_store.persist()


def _mon_end_iso(store) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(store.now())) + ".000000Z"


def _sync_topic_metrics(store, name: str) -> None:
    """Mirrors a topic's live cumulative publish count into the shared Cloud Monitoring
    store as pubsub.googleapis.com/topic/send_message_operation_count — a REAL metric a
    REAL alert policy or the console's own Metrics tab can read back (never fabricated)."""
    mon_store = getattr(store, "mon_store", None)
    topic = store.get_topic(name)
    if mon_store is None or topic is None:
        return
    try:
        from core import gcp_monitoring_core as mon
        project, topic_id = name.split("/")[1], name.rsplit("/", 1)[-1]
        resource = {"type": "pubsub_topic", "labels": {"project_id": project, "topic_id": topic_id}}
        mon.record_system_point(mon_store, project, "pubsub.googleapis.com/topic/send_message_operation_count",
                                 resource, topic.get("_publish_count", 0), _mon_end_iso(store), unit="1")
    except Exception:
        pass


def _sync_subscription_metrics(store, name: str) -> None:
    """Mirrors a subscription's live backlog (num_undelivered_messages) and oldest unacked
    message age into the shared Cloud Monitoring store — the same two series the real
    console's Metrics tab charts, derived from the subscription's OWN message list."""
    mon_store = getattr(store, "mon_store", None)
    sub = store.get_queue(name)
    if mon_store is None or sub is None:
        return
    try:
        from core import gcp_monitoring_core as mon
        project, sub_id = name.split("/")[1], name.rsplit("/", 1)[-1]
        now = store.now()
        backlog, oldest = 0, 0.0
        for m in sub.get("messages", []):
            if m.get("_acked"):
                continue
            backlog += 1
            oldest = max(oldest, now - m.get("_publish_at", now))
        resource = {"type": "pubsub_subscription", "labels": {"project_id": project, "subscription_id": sub_id}}
        end_iso = _mon_end_iso(store)
        mon.record_system_point(mon_store, project, "pubsub.googleapis.com/subscription/num_undelivered_messages",
                                 resource, backlog, end_iso, unit="1")
        mon.record_system_point(mon_store, project, "pubsub.googleapis.com/subscription/oldest_unacked_message_age",
                                 resource, oldest, end_iso, unit="s")
    except Exception:
        pass


# ── topic operations ──────────────────────────────────────────────────────
def _create_topic(store, name: str, body: dict) -> PubsubResponse:
    if store.get_topic(name):
        raise PubsubError(409, "ALREADY_EXISTS", f"Topic already exists: {name}")
    topic = {"name": name, "subscriptions": [], "created": _now_rfc3339(), "labels": dict(body.get("labels") or {})}
    if body.get("kmsKeyName"):
        topic["kmsKeyName"] = body["kmsKeyName"]
    if body.get("messageRetentionDuration"):
        topic["messageRetentionDuration"] = body["messageRetentionDuration"]
    if body.get("schemaSettings"):
        topic["schemaSettings"] = body["schemaSettings"]
    if body.get("messageTransforms"):
        topic["messageTransforms"] = body["messageTransforms"]
        topic["_compiled_transforms"] = _compile_transforms(topic["messageTransforms"])
    if body.get("ingestionDataSourceSettings"):
        _validate_ingestion_settings(body["ingestionDataSourceSettings"])
        topic["ingestionDataSourceSettings"] = body["ingestionDataSourceSettings"]
    store.put_topic(name, topic)
    store.persist()
    _sync_cloud_storage_ingestion(store, topic)
    _sync_topic_metrics(store, name)
    return _json(200, _topic_view(store.get_topic(name)))


def _get_topic(store, name: str) -> PubsubResponse:
    topic = _require_topic(store, name)
    _sync_cloud_storage_ingestion(store, topic)
    _sync_topic_metrics(store, name)
    return _json(200, _topic_view(topic))


_TOPIC_PATCHABLE = {"labels", "kmsKeyName", "messageRetentionDuration", "schemaSettings",
                     "messageTransforms", "ingestionDataSourceSettings"}


def _patch_topic(store, name: str, body: dict) -> PubsubResponse:
    topic = _require_topic(store, name)
    fields = body.get("topic") or body
    mask = [f.strip() for f in str(body.get("updateMask", "")).split(",") if f.strip()]
    keys = mask if mask else [k for k in fields if k in _TOPIC_PATCHABLE]
    for k in keys:
        if k not in _TOPIC_PATCHABLE:
            continue
        if k in fields:
            if k == "messageTransforms":
                topic["_compiled_transforms"] = _compile_transforms(fields[k] or [])
            elif k == "ingestionDataSourceSettings":
                _validate_ingestion_settings(fields[k] or {})
            topic[k] = fields[k]
        else:
            topic.pop(k, None)
            if k == "messageTransforms":
                topic.pop("_compiled_transforms", None)
    store.persist()
    _sync_cloud_storage_ingestion(store, topic)
    return _json(200, _topic_view(topic))


def _list_topics(store, project: str) -> PubsubResponse:
    prefix = f"projects/{project}/topics/"
    items = [_topic_view(store.get_topic(n)) for n in store.topic_arns() if n.startswith(prefix)]
    out: dict = {}
    if items:
        out["topics"] = items
    return _json(200, out)


def _delete_topic(store, name: str) -> PubsubResponse:
    topic = _require_topic(store, name)
    # Detach subscriptions (Pub/Sub keeps them but marks topic _deleted-topic_).
    for sub_name in topic.get("subscriptions", []):
        sub = store.get_queue(sub_name)
        if sub:
            sub["topic"] = "_deleted-topic_"
    store.drop_topic(name)
    store.persist()
    return _json(200, {})


def _fanout(store, topic: dict, record: dict) -> None:
    """Deliver a prepared message record into every subscription attached to `topic`
    whose filter (if any) matches the message's attributes. A Cloud Storage subscription
    writes the message straight into a real bucket object instead of queuing it."""
    for sub_name in topic.get("subscriptions", []):
        sub = store.get_queue(sub_name)
        if sub is None or not _message_matches(sub.get("filter"), record.get("attributes")):
            continue
        if sub.get("cloudStorageConfig"):
            _deliver_to_cloud_storage(store, sub, record)
            continue
        if sub.get("_eventarc_trigger"):   # push-delivered by gcp_run_core.deliver_event (on_publish), nobody pulls it
            continue
        sub.setdefault("messages", []).append({"_id": uuid.uuid4().hex, "_publish_at": store.now(), **record})


def _prune_topic_retention(store, topic: dict) -> None:
    """Topic-level message retention: an independent, replayable backlog used by
    seek-by-time (unlike subscription retention, this exists even for subscriptions
    created after the message was published)."""
    try:
        retention = int(str(topic.get("messageRetentionDuration", "0s")).rstrip("s"))
    except ValueError:
        retention = 0
    if not retention:
        topic.pop("_retained", None)
        return
    now = store.now()
    topic["_retained"] = [m for m in topic.get("_retained", []) if now - m.get("_publish_at", now) <= retention]


def _publish(store, name: str, body: dict, on_publish=None) -> PubsubResponse:
    topic = _require_topic(store, name)
    _sync_cloud_storage_ingestion(store, topic)
    messages = body.get("messages") or []
    if not messages:
        raise PubsubError(400, "INVALID_ARGUMENT", "The value for message_count is too small. You passed 0")
    # Message transforms run first, then schema validation runs against the TRANSFORMED
    # message (same order as the real API) — all BEFORE fanning any message out: a schema
    # violation anywhere in the batch fails the whole publish call, same as the real API,
    # never a partial delivery. A transform that drops a message removes it from this
    # batch entirely — it is never delivered, retained, or returned in messageIds.
    prepared: list[dict] = []
    for m in messages:
        record = {
            "data": m.get("data", ""),            # already base64 on the wire
            "attributes": dict(m.get("attributes") or {}),
            "messageId": _next_message_id(store),
            "publishTime": _now_rfc3339(),
        }
        if m.get("orderingKey"):
            record["orderingKey"] = m["orderingKey"]
        record = _apply_message_transforms(topic, record)
        if record is None:
            continue
        _validate_schema_message(store, topic, record)
        prepared.append(record)
    retain = bool(topic.get("messageRetentionDuration"))
    for record in prepared:
        _fanout(store, topic, record)
        if retain:
            topic.setdefault("_retained", []).append({**record, "_publish_at": store.now()})
    if retain:
        _prune_topic_retention(store, topic)
    topic["_publish_count"] = topic.get("_publish_count", 0) + len(prepared)
    store.persist()
    _sync_topic_metrics(store, name)
    for sub_name in topic.get("subscriptions", []):
        _sync_subscription_metrics(store, sub_name)
    if on_publish:
        on_publish(name, prepared)
    return _json(200, {"messageIds": [r["messageId"] for r in prepared]})


# ── subscription operations ───────────────────────────────────────────────
def _create_subscription(store, name: str, body: dict) -> PubsubResponse:
    if store.get_queue(name):
        raise PubsubError(409, "ALREADY_EXISTS", f"Subscription already exists: {name}")
    topic_name = str(body.get("topic", "")).strip()
    if not topic_name:
        raise PubsubError(400, "INVALID_ARGUMENT", "Subscription must specify a topic.")
    topic = _require_topic(store, topic_name)
    filter_expr = str(body.get("filter", "") or "").strip()
    if filter_expr:
        try:
            _compile_filter(filter_expr)
        except _FilterError as e:
            raise PubsubError(400, "INVALID_ARGUMENT", f"Invalid filter: {e}")
    sub = {
        "name": name,
        "topic": topic_name,
        "ackDeadlineSeconds": int(body.get("ackDeadlineSeconds", 10) or 10),
        "messages": [],
        "ackids": {},
        "created": _now_rfc3339(),
        "labels": dict(body.get("labels") or {}),
        "messageRetentionDuration": body.get("messageRetentionDuration", "604800s"),
        "retainAckedMessages": bool(body.get("retainAckedMessages", False)),
        "expirationPolicy": body.get("expirationPolicy", {"ttl": "2678400s"}),
        "enableMessageOrdering": bool(body.get("enableMessageOrdering", False)),
        "enableExactlyOnceDelivery": bool(body.get("enableExactlyOnceDelivery", False)),
        "pushConfig": body.get("pushConfig") or {},
    }
    if filter_expr:
        # Immutable after creation, matching the real API: filter is never in
        # _SUB_PATCHABLE below.
        sub["filter"] = filter_expr
    if body.get("deadLetterPolicy"):
        sub["deadLetterPolicy"] = body["deadLetterPolicy"]
    if body.get("retryPolicy"):
        sub["retryPolicy"] = body["retryPolicy"]
    if body.get("bigQueryConfig"):
        # Not "a separate product" hand-wave: there is no BigQuery dataset/table resource
        # anywhere in Vyomi to stream rows into, so this delivery type has nowhere to go.
        raise PubsubError(400, "INVALID_ARGUMENT",
                           "bigQueryConfig delivery isn't modeled in Vyomi: no BigQuery core exists anywhere "
                           "in the simulator. Use Pull, Push, or Cloud Storage delivery instead.")
    if body.get("cloudStorageConfig"):
        _validate_cloud_storage_config(store, body["cloudStorageConfig"])
        sub["cloudStorageConfig"] = body["cloudStorageConfig"]
    store.put_queue(name, sub)
    if name not in topic["subscriptions"]:
        topic["subscriptions"].append(name)
    store.persist()
    _sync_subscription_metrics(store, name)
    return _json(200, _subscription_view(sub))


def _get_subscription(store, name: str) -> PubsubResponse:
    sub = _require_subscription(store, name)
    _sync_subscription_metrics(store, name)
    return _json(200, _subscription_view(sub))


_SUB_PATCHABLE = {
    "labels", "ackDeadlineSeconds", "messageRetentionDuration", "retainAckedMessages",
    "expirationPolicy", "enableMessageOrdering", "pushConfig", "deadLetterPolicy", "retryPolicy",
    "cloudStorageConfig",
}


def _patch_subscription(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    fields = body.get("subscription") or body
    mask = [f.strip() for f in str(body.get("updateMask", "")).split(",") if f.strip()]
    keys = mask if mask else [k for k in fields if k in _SUB_PATCHABLE]
    for k in keys:
        if k not in _SUB_PATCHABLE:
            continue
        if k in fields:
            if k == "cloudStorageConfig":
                _validate_cloud_storage_config(store, fields[k] or {})
            sub[k] = fields[k]
        else:
            sub.pop(k, None)
    store.persist()
    return _json(200, _subscription_view(sub))


def _list_subscriptions(store, project: str) -> PubsubResponse:
    prefix = f"projects/{project}/subscriptions/"
    items = [_subscription_view(store.get_queue(n)) for n in store.queue_names() if n.startswith(prefix)]
    out: dict = {}
    if items:
        out["subscriptions"] = items
    return _json(200, out)


def _delete_subscription(store, name: str) -> PubsubResponse:
    sub = _require_subscription(store, name)
    topic = store.get_topic(sub.get("topic", ""))
    if topic and name in topic.get("subscriptions", []):
        topic["subscriptions"].remove(name)
    store.drop_queue(name)
    store.persist()
    return _json(200, {})


def _prune_retention(store, sub: dict) -> None:
    try:
        retention = int(str(sub.get("messageRetentionDuration", "604800s")).rstrip("s"))
    except ValueError:
        retention = 604800
    now = store.now()
    sub["messages"] = [m for m in sub.get("messages", []) if now - m.get("_publish_at", now) <= retention]


def _backoff_seconds(retry_policy: dict, attempts: int) -> float:
    def _secs(v, default):
        try:
            return float(str(v).rstrip("s"))
        except (TypeError, ValueError):
            return default
    minimum = _secs(retry_policy.get("minimumBackoff"), 10.0)
    maximum = _secs(retry_policy.get("maximumBackoff"), 600.0)
    return min(minimum * (2 ** max(0, attempts - 1)), maximum)


def _pull(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    topic = store.get_topic(sub.get("topic", ""))
    if topic:
        _sync_cloud_storage_ingestion(store, topic)
    _prune_retention(store, sub)
    max_messages = int(body.get("maxMessages", 1) or 1)
    deadline = int(sub.get("ackDeadlineSeconds", 10) or 10)
    dlp = sub.get("deadLetterPolicy")
    retry_policy = sub.get("retryPolicy")
    ordered = bool(sub.get("enableMessageOrdering"))
    now = store.now()
    kept: list[dict] = []
    received: list[dict] = []
    blocked_keys: set[str] = set()
    for msg in sub.get("messages", []):
        if msg.get("_acked"):
            kept.append(msg)
            continue
        key = msg.get("orderingKey") if ordered else None
        if key:
            if key in blocked_keys:
                kept.append(msg)   # an earlier unacked message with this ordering key exists
                continue
            blocked_keys.add(key)  # this is the head for the key: block any later one until it's acked
        if msg.get("_pending") and now < msg.get("_pending_until", 0):
            kept.append(msg)   # still out for delivery, within its ack deadline
            continue
        attempts_so_far = msg.get("_attempts", 0)
        if attempts_so_far and retry_policy and now < msg.get("_pending_until", 0) + _backoff_seconds(retry_policy, attempts_so_far):
            kept.append(msg)   # ack deadline expired, but still inside the retry policy's backoff window
            continue
        if len(received) >= max_messages:
            kept.append(msg)   # eligible, but this pull's quota is already full
            continue
        attempts = attempts_so_far + 1
        if dlp and attempts > int(dlp.get("maxDeliveryAttempts", 5) or 5):
            dlq = store.get_topic(dlp.get("deadLetterTopic", ""))
            if dlq:
                fwd = {"data": msg["data"], "attributes": dict(msg.get("attributes") or {}),
                       "messageId": _next_message_id(store), "publishTime": _now_rfc3339()}
                _fanout(store, dlq, fwd)
            continue   # exceeded max delivery attempts: forwarded (or dropped), never kept
        msg["_attempts"] = attempts
        msg["_pending"] = True
        msg["_pending_until"] = now + deadline
        ack_id = "ackid-" + uuid.uuid4().hex
        sub.setdefault("ackids", {})[ack_id] = msg["_id"]
        out_msg = {"data": msg["data"], "attributes": msg["attributes"], "messageId": msg["messageId"], "publishTime": msg["publishTime"]}
        if msg.get("orderingKey"):
            out_msg["orderingKey"] = msg["orderingKey"]
        received.append({"ackId": ack_id, "message": out_msg, "deliveryAttempt": attempts})
        kept.append(msg)
    sub["messages"] = kept
    out: dict = {}
    if received:
        out["receivedMessages"] = received
        store.persist()
    _sync_subscription_metrics(store, name)
    return _json(200, out)


def _acknowledge(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    ack_ids = body.get("ackIds") or []
    ackids = sub.setdefault("ackids", {})
    remove_ids = {ackids.pop(a) for a in ack_ids if a in ackids}
    if remove_ids:
        if sub.get("retainAckedMessages"):
            for m in sub.get("messages", []):
                if m["_id"] in remove_ids:
                    m["_acked"] = True
                    m["_pending"] = False
        else:
            sub["messages"] = [m for m in sub.get("messages", []) if m["_id"] not in remove_ids]
        store.persist()
        _sync_subscription_metrics(store, name)
    return _json(200, {})


_SEEK_COPY_DROP = ("_pending", "_pending_until", "_acked", "_attempts", "_id")


def _seek(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    snap_name = body.get("snapshot")
    time_val = body.get("time")
    if snap_name:
        snap = _snap_store(store).get(snap_name)
        if not snap:
            raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {snap_name}")
        sub["messages"] = [{**{k: v for k, v in m.items() if k not in _SEEK_COPY_DROP}, "_id": uuid.uuid4().hex}
                           for m in snap.get("_messages", [])]
        sub["ackids"] = {}
    elif time_val:
        # Seek to a point in time: only possible when the topic has message retention
        # enabled, since that's the only backlog Vyomi keeps independent of any one
        # subscription's own (shorter-lived) message list.
        topic = store.get_topic(sub.get("topic", ""))
        if not topic or not topic.get("messageRetentionDuration"):
            raise PubsubError(400, "FAILED_PRECONDITION",
                               "Seeking to a timestamp requires the topic to have message retention enabled.")
        try:
            ts = _parse_rfc3339(time_val) if isinstance(time_val, str) else float(time_val)
        except (ValueError, TypeError):
            raise PubsubError(400, "INVALID_ARGUMENT", f"Invalid seek time: {time_val!r}")
        _prune_topic_retention(store, topic)
        sub["messages"] = [{**{k: v for k, v in m.items() if k not in _SEEK_COPY_DROP}, "_id": uuid.uuid4().hex}
                           for m in topic.get("_retained", []) if m.get("_publish_at", 0) >= ts]
        sub["ackids"] = {}
    else:
        raise PubsubError(400, "INVALID_ARGUMENT", "Seek requires either a snapshot or a time.")
    store.persist()
    return _json(200, {})


# ── snapshot operations ───────────────────────────────────────────────────
def _create_snapshot(store, name: str, body: dict) -> PubsubResponse:
    snaps = _snap_store(store)
    if name in snaps:
        raise PubsubError(409, "ALREADY_EXISTS", f"Snapshot already exists: {name}")
    sub_name = str(body.get("subscription", "")).strip()
    if not sub_name:
        raise PubsubError(400, "INVALID_ARGUMENT", "Snapshot must specify a subscription.")
    sub = _require_subscription(store, sub_name)
    snap = {
        "name": name,
        "topic": sub.get("topic", ""),
        "subscription": sub_name,
        "labels": dict(body.get("labels") or {}),
        "expireTime": _expires_rfc3339(7 * 24 * 3600),
        "_messages": [dict(m) for m in sub.get("messages", [])],
    }
    snaps[name] = snap
    store.persist()
    return _json(200, _snapshot_view(snap))


def _get_snapshot(store, name: str) -> PubsubResponse:
    snap = _snap_store(store).get(name)
    if not snap:
        raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {name}")
    return _json(200, _snapshot_view(snap))


def _list_snapshots(store, project: str) -> PubsubResponse:
    prefix = f"projects/{project}/snapshots/"
    items = [_snapshot_view(s) for n, s in _snap_store(store).items() if n.startswith(prefix)]
    out: dict = {}
    if items:
        out["snapshots"] = items
    return _json(200, out)


def _delete_snapshot(store, name: str) -> PubsubResponse:
    snaps = _snap_store(store)
    if name not in snaps:
        raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {name}")
    del snaps[name]
    store.persist()
    return _json(200, {})


# ── schema operations ──────────────────────────────────────────────────────
def _create_schema(store, project: str, query: dict, body: dict) -> PubsubResponse:
    schema_id = (query or {}).get("schemaId")
    if isinstance(schema_id, list):
        schema_id = schema_id[0] if schema_id else None
    if not schema_id:
        raise PubsubError(400, "INVALID_ARGUMENT", "schemaId is required.")
    schemas = _schema_store(store)
    name = f"projects/{project}/schemas/{schema_id}"
    if name in schemas:
        raise PubsubError(409, "ALREADY_EXISTS", f"Schema already exists: {name}")
    schema = {
        "name": name,
        "type": body.get("type", "TYPE_UNSPECIFIED"),
        "definition": body.get("definition", ""),
        "revisionId": uuid.uuid4().hex[:8],
        "revisionCreateTime": _now_rfc3339(),
    }
    schemas[name] = schema
    store.persist()
    return _json(200, _schema_view(schema, full=True))


def _get_schema(store, name: str, query: dict) -> PubsubResponse:
    schema = _schema_store(store).get(name)
    if not schema:
        raise PubsubError(404, "NOT_FOUND", f"Schema not found: {name}")
    view = (query or {}).get("view", "BASIC")
    if isinstance(view, list):
        view = view[0] if view else "BASIC"
    return _json(200, _schema_view(schema, full=(view == "FULL")))


def _list_schemas(store, project: str, query: dict) -> PubsubResponse:
    prefix = f"projects/{project}/schemas/"
    view = (query or {}).get("view", "BASIC")
    if isinstance(view, list):
        view = view[0] if view else "BASIC"
    items = [_schema_view(s, full=(view == "FULL")) for n, s in _schema_store(store).items() if n.startswith(prefix)]
    out: dict = {}
    if items:
        out["schemas"] = items
    return _json(200, out)


def _delete_schema(store, name: str) -> PubsubResponse:
    schemas = _schema_store(store)
    if name not in schemas:
        raise PubsubError(404, "NOT_FOUND", f"Schema not found: {name}")
    del schemas[name]
    store.persist()
    return _json(200, {})



# ── subscription verbs the high-level clients use (modifyAckDeadline is how
# google-cloud-pubsub's streaming / flow-controlled subscribers extend or nack a
# lease; modifyPushConfig flips a subscription between push and pull; detach cuts a
# subscription from its topic) ─────────────────────────────────────────────────────
def _modify_ack_deadline(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    try:
        deadline = int(body.get("ackDeadlineSeconds", 0) or 0)
    except (TypeError, ValueError):
        raise PubsubError(400, "INVALID_ARGUMENT", "ackDeadlineSeconds must be an integer.")
    if deadline < 0 or deadline > 600:
        raise PubsubError(400, "INVALID_ARGUMENT",
                          f"Invalid ack deadline: {deadline}. It must be between 0 and 600 seconds.")
    ackids = sub.setdefault("ackids", {})
    targets = {ackids[a] for a in (body.get("ackIds") or []) if a in ackids}
    if targets:
        now = store.now()
        for m in sub.get("messages", []):
            if m.get("_id") in targets and not m.get("_acked"):
                if deadline == 0:            # a nack: redeliverable on the very next pull
                    m["_pending"] = False
                    m["_pending_until"] = now
                else:                        # extend (or shorten) the lease from now
                    m["_pending"] = True
                    m["_pending_until"] = now + deadline
        store.persist()
    return _json(200, {})


def _modify_push_config(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    sub["pushConfig"] = dict(body.get("pushConfig") or {})
    store.persist()
    return _json(200, {})


def _detach_subscription(store, name: str) -> PubsubResponse:
    sub = _require_subscription(store, name)
    topic = store.get_topic(sub.get("topic", ""))
    if topic and name in topic.get("subscriptions", []):
        topic["subscriptions"].remove(name)
    sub["topic"] = "_deleted-topic_"
    sub["detached"] = True
    sub["messages"] = []
    sub["ackids"] = {}
    store.persist()
    return _json(200, {})


def _list_topic_subscriptions(store, topic_name: str) -> PubsubResponse:
    topic = _require_topic(store, topic_name)
    subs = [n for n in topic.get("subscriptions", []) if store.get_queue(n)]
    out: dict = {}
    if subs:
        out["subscriptions"] = subs
    return _json(200, out)


def _list_topic_snapshots(store, topic_name: str) -> PubsubResponse:
    _require_topic(store, topic_name)
    snaps = sorted(n for n, s in _snap_store(store).items() if s.get("topic") == topic_name)
    out: dict = {}
    if snaps:
        out["snapshots"] = snaps
    return _json(200, out)


def _patch_snapshot(store, name: str, body: dict) -> PubsubResponse:
    snap = _snap_store(store).get(name)
    if not snap:
        raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {name}")
    fields = body.get("snapshot") or body
    mask = [f.strip() for f in str(body.get("updateMask", "")).split(",") if f.strip()]
    for k in (mask or [k for k in fields if k in ("labels", "expireTime")]):
        if k in ("labels", "expireTime"):
            if k in fields:
                snap[k] = fields[k]
            elif k == "labels":
                snap.pop(k, None)
    store.persist()
    return _json(200, _snapshot_view(snap))


# ── schema validation (schemas:validate / schemas:validateMessage) ─────────────
_SCHEMA_TYPES = ("AVRO", "PROTOCOL_BUFFER")


def _check_schema_definition(schema: dict) -> None:
    stype = str(schema.get("type") or "")
    if stype not in _SCHEMA_TYPES:
        raise PubsubError(400, "INVALID_ARGUMENT", f"Invalid schema type: {stype or 'TYPE_UNSPECIFIED'}.")
    definition = str(schema.get("definition") or "")
    if not definition.strip():
        raise PubsubError(400, "INVALID_ARGUMENT", "Schema definition is empty.")
    if stype == "AVRO":
        try:
            json.loads(definition)
        except Exception:
            raise PubsubError(400, "INVALID_ARGUMENT", "Invalid AVRO schema definition: not valid JSON.")


def _validate_schema(store, project: str, body: dict) -> PubsubResponse:
    _check_schema_definition(body.get("schema") or {})
    return _json(200, {})


def _validate_message(store, project: str, body: dict) -> PubsubResponse:
    if body.get("name"):
        name = str(body["name"])
        if "/" not in name:
            name = f"projects/{project}/schemas/{name}"
        schema = _schema_store(store).get(name)
        if not schema:
            raise PubsubError(404, "NOT_FOUND", f"Schema not found: {name}")
    elif body.get("schema"):
        schema = body["schema"]
        _check_schema_definition(schema)
    else:
        raise PubsubError(400, "INVALID_ARGUMENT", "Either name or schema must be set.")
    encoding = str(body.get("encoding") or "JSON").upper()
    record = {"data": body.get("message", "")}
    one = SimpleNamespace(pubsub={"schemas": {"_v": schema}})   # reuse the publish-time validator verbatim
    _validate_schema_message(one, {"schemaSettings": {"schema": "_v", "encoding": encoding}}, record)
    return _json(200, {})


# ── IAM on Pub/Sub resources (topics / subscriptions / snapshots / schemas) ────
def _resource_for_iam(store, collection: str, name: str) -> dict:
    if collection == "topics":
        return _require_topic(store, name)
    if collection == "subscriptions":
        return _require_subscription(store, name)
    holder = _snap_store(store) if collection == "snapshots" else _schema_store(store)
    rec = holder.get(name)
    if not rec:
        raise PubsubError(404, "NOT_FOUND", f"Resource not found: {name}")
    return rec


def _iam(store, collection: str, name: str, verb: str, body: dict) -> PubsubResponse:
    rec = _resource_for_iam(store, collection, name)
    if verb == "getIamPolicy":
        return _json(200, rec.get("_iamPolicy") or {"etag": "ACAB"})
    if verb == "setIamPolicy":
        policy = dict(body.get("policy") or {})
        policy["etag"] = uuid.uuid4().hex[:8]
        rec["_iamPolicy"] = policy
        store.persist()
        return _json(200, policy)
    # testIamPermissions: the simulator's caller holds every permission it asks about
    perms = [p for p in (body.get("permissions") or []) if isinstance(p, str)]
    return _json(200, {"permissions": perms} if perms else {})


_IAM_VERBS = ("getIamPolicy", "setIamPolicy", "testIamPermissions")


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: MessagingStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", on_publish=None) -> PubsubResponse:
    """Native GCP Pub/Sub REST v1 router. Resource names are `projects/{p}/...`;
    verbs (`:publish`, `:pull`, `:acknowledge`, `:seek`) are `:`-suffixed on the path.

    *on_publish(topic_full_name, prepared_messages)*, when given, is called after a
    successful publish — Cloud Run's Eventarc-style triggers hook in here (see
    core/aws_wire_router.py / routes/gcp_pubsub_unified.py)."""
    method = (method or "GET").upper()
    query = query or {}

    # Strip a leading /v1 prefix and any query string.
    p = path.split("?", 1)[0]
    if p.startswith("/v1/"):
        p = p[len("/v1"):]
    elif p == "/v1":
        p = "/"
    p = p.strip("/")

    # Split a trailing `:verb` (e.g. projects/p/topics/t:publish) off the resource.
    verb = ""
    if ":" in p:
        p, _, verb = p.rpartition(":")

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}

    segs = [s for s in p.split("/") if s != ""]
    # Expect: projects / {project} / (topics|subscriptions|snapshots|schemas) [ / {id...} ]
    if len(segs) < 3 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    project = segs[1]
    collection = segs[2]
    resource = p  # full resource name for a specific topic/subscription/snapshot/schema

    try:
        if collection == "topics":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_topics(store, project)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on topics")
            if len(segs) == 5 and segs[4] in ("subscriptions", "snapshots") and not verb:
                topic_name = "/".join(segs[:4])
                if method != "GET":
                    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on topic {segs[4]}")
                if segs[4] == "subscriptions":
                    return _list_topic_subscriptions(store, topic_name)
                return _list_topic_snapshots(store, topic_name)
            if len(segs) != 4:
                return _err(404, "NOT_FOUND", f"Unknown path: {path}")
            if verb in _IAM_VERBS:
                return _iam(store, collection, resource, verb, payload)
            # specific topic
            if verb == "publish" and method == "POST":
                return _publish(store, resource, payload, on_publish=on_publish)
            if method == "PUT":
                return _create_topic(store, resource, payload)
            if method == "PATCH":
                return _patch_topic(store, resource, payload)
            if method == "GET":
                return _get_topic(store, resource)
            if method == "DELETE":
                return _delete_topic(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on topic")

        if collection == "subscriptions":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_subscriptions(store, project)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on subscriptions")
            if len(segs) != 4:
                return _err(404, "NOT_FOUND", f"Unknown path: {path}")
            if verb in _IAM_VERBS:
                return _iam(store, collection, resource, verb, payload)
            if verb == "modifyAckDeadline" and method == "POST":
                return _modify_ack_deadline(store, resource, payload)
            if verb == "modifyPushConfig" and method == "POST":
                return _modify_push_config(store, resource, payload)
            if verb == "detach" and method == "POST":
                return _detach_subscription(store, resource)
            # specific subscription
            if verb == "pull" and method == "POST":
                return _pull(store, resource, payload)
            if verb == "acknowledge" and method == "POST":
                return _acknowledge(store, resource, payload)
            if verb == "seek" and method == "POST":
                return _seek(store, resource, payload)
            if method == "PUT":
                return _create_subscription(store, resource, payload)
            if method == "PATCH":
                return _patch_subscription(store, resource, payload)
            if method == "GET":
                return _get_subscription(store, resource)
            if method == "DELETE":
                return _delete_subscription(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on subscription")

        if collection == "snapshots":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_snapshots(store, project)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on snapshots")
            if len(segs) != 4:
                return _err(404, "NOT_FOUND", f"Unknown path: {path}")
            if verb in _IAM_VERBS:
                return _iam(store, collection, resource, verb, payload)
            # specific snapshot
            if method == "PUT":
                return _create_snapshot(store, resource, payload)
            if method == "PATCH":
                return _patch_snapshot(store, resource, payload)
            if method == "GET":
                return _get_snapshot(store, resource)
            if method == "DELETE":
                return _delete_snapshot(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on snapshot")

        if collection == "schemas":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_schemas(store, project, query)
                if method == "POST" and verb == "validate":
                    return _validate_schema(store, project, payload)
                if method == "POST" and verb == "validateMessage":
                    return _validate_message(store, project, payload)
                if method == "POST" and not verb:
                    return _create_schema(store, project, query, payload)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on schemas")
            if len(segs) != 4:
                return _err(404, "NOT_FOUND", f"Unknown path: {path}")
            if verb in _IAM_VERBS:
                return _iam(store, collection, resource, verb, payload)
            # specific schema
            if method == "GET":
                return _get_schema(store, resource, query)
            if method == "DELETE":
                return _delete_schema(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on schema")

        return _err(404, "NOT_FOUND", f"Unknown collection: {collection}")
    except PubsubError as e:
        return _err(e.code, e.status, e.message)
