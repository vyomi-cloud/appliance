"""Cloud Asset Inventory search query language (searchAllResources `query`), substrate-independent, stdlib only.

Grammar (as documented for Cloud Asset Inventory resource search):
    query  := term (( 'AND' | 'OR' )? term)*          implicit AND; AND binds tighter than OR
    term   := '-'? ( '(' query ')' | 'NOT' term | field OP value | value )
    OP     := ':' (substring / wildcard match, case-insensitive; on map fields 'labels:k' tests key presence)
            | '=' (exact, case-insensitive) | '>' '>=' '<' '<=' (numbers / ISO timestamps) | '!=' (not equal)
    value  := word | "quoted string"; '*' matches any run of characters
A bare value searches name, displayName, assetType, project, state, location, description and label keys/values.
Fields: name, displayName, assetType, project, state, location, description, labels.<k>, labels, kmsKey, parentFullResourceName.
"""
from __future__ import annotations

import fnmatch
import re

FIELDS = ("name", "displayName", "assetType", "project", "state", "location", "description", "labels", "kmsKey", "parentFullResourceName")
_TOKEN = re.compile(r'\s*(?:(\()|(\))|("(?:[^"\\]|\\.)*")|(>=|<=|!=|[:=<>])|([^\s():=<>!"]+))')


class QueryError(Exception):
    pass


def _tokens(q):
    out, pos = [], 0
    while pos < len(q):
        if q[pos:].strip() == "":
            break
        m = _TOKEN.match(q, pos)
        if not m or m.end() == pos:
            raise QueryError("Unexpected character at position %d of the query." % pos)
        pos = m.end()
        if m.group(1):
            out.append(("(", "("))
        elif m.group(2):
            out.append((")", ")"))
        elif m.group(3):
            out.append(("str", m.group(3)[1:-1].replace('\\"', '"')))
        elif m.group(4):
            out.append(("op", m.group(4)))
        else:
            out.append(("word", m.group(5)))
    return out


class _Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def eat(self):
        v = self.peek()
        self.i += 1
        return v

    def parse(self):
        node = self.or_()
        if self.i != len(self.t):
            raise QueryError("Unbalanced parentheses in the query.")
        return node

    def or_(self):
        parts = [self.and_()]
        while self.peek() == ("word", "OR"):
            self.eat()
            parts.append(self.and_())
        return parts[0] if len(parts) == 1 else ("or", parts)

    def and_(self):
        parts = [self.term()]
        while True:
            k, v = self.peek()
            if k is None or k == ")" or (k == "word" and v == "OR"):
                break
            if (k, v) == ("word", "AND"):
                self.eat()
            parts.append(self.term())
        return parts[0] if len(parts) == 1 else ("and", parts)

    def term(self):
        k, v = self.peek()
        if k is None:
            raise QueryError("The query ends where a term was expected.")
        neg = False
        if k == "word" and v == "NOT":
            self.eat(); return ("not", self.term())
        if k == "word" and v.startswith("-") and len(v) > 1:
            neg = True
            self.t[self.i] = ("word", v[1:])
            k, v = self.peek()
        if k == "(":
            self.eat()
            node = self.or_()
            if self.eat()[0] != ")":
                raise QueryError("Missing closing parenthesis.")
            return ("not", node) if neg else node
        if k in ("word", "str"):
            self.eat()
            nk, nv = self.peek()
            if k == "word" and nk == "op":
                self.eat()
                vk, vv = self.eat()
                if vk not in ("word", "str"):
                    raise QueryError("Expected a value after '%s%s'." % (v, nv))
                field = v
                base = field.split(".")[0]
                if base not in FIELDS:
                    raise QueryError("Unknown field '%s'. Searchable fields: %s." % (field, ", ".join(FIELDS)))
                node = ("cmp", field, nv, vv)
            else:
                node = ("text", v)
            return ("not", node) if neg else node
        raise QueryError("Unexpected '%s' in the query." % v)


def parse(q):
    toks = _tokens(q)
    if not toks:
        return None
    return _Parser(toks).parse()


def _vals(res, field):
    if "." in field and field.split(".")[0] == "labels":
        k = field.split(".", 1)[1]
        v = (res.get("labels") or {}).get(k)
        return [] if v is None else [str(v)]
    if field == "labels":
        return [f"{k}={v}" for k, v in (res.get("labels") or {}).items()] + list((res.get("labels") or {}).keys())
    v = res.get(field)
    return [] if v in (None, "") else [str(v)]


def _match_val(have, op, want):
    h, w = have.lower(), want.lower()
    if op == ":":
        return fnmatch.fnmatchcase(h, w) if "*" in w else w in h
    if op in ("=", "!="):
        eq = fnmatch.fnmatchcase(h, w) if "*" in w else h == w
        return eq if op == "=" else not eq
    try:
        a, b = float(have), float(want)
    except ValueError:
        a, b = have, want
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]


def evaluate(node, res):
    t = node[0]
    if t == "and":
        return all(evaluate(n, res) for n in node[1])
    if t == "or":
        return any(evaluate(n, res) for n in node[1])
    if t == "not":
        return not evaluate(node[1], res)
    if t == "text":
        w = node[1].lower()
        pool = [str(res.get(f, "")) for f in ("name", "displayName", "assetType", "project", "state", "location", "description")] + _vals(res, "labels")
        return any((fnmatch.fnmatchcase(p.lower(), w) if "*" in w else w in p.lower()) for p in pool)
    _, field, op, want = node
    have = _vals(res, field)
    if op == "!=":
        return all(_match_val(h, op, want) for h in have)
    return any(_match_val(h, op, want) for h in have)


def search(resources, query="", asset_types=None, order_by="", page_size=None, page_token=""):
    """-> (results, next_page_token). Raises QueryError."""
    node = parse(query or "")
    out = [r for r in resources if (node is None or evaluate(node, r))]
    if asset_types:
        pats = [a.lower() for a in asset_types]
        out = [r for r in out if any(fnmatch.fnmatchcase(r["assetType"].lower(), p) for p in pats)]
    if order_by:
        for spec in reversed([s.strip() for s in order_by.split(",") if s.strip()]):
            f, _, d = spec.partition(" ")
            if f.split(".")[0] not in FIELDS:
                raise QueryError("Cannot order by unknown field '%s'." % f)
            out.sort(key=lambda r: (_vals(r, f) or [""])[0].lower(), reverse=(d.strip().lower() == "desc"))
    total = len(out)
    try:
        size = int(page_size) if page_size not in (None, "") else 500
    except ValueError:
        raise QueryError("pageSize must be an integer.")
    if not 1 <= size <= 500:
        raise QueryError("pageSize must be between 1 and 500.")
    start = 0
    if page_token:
        try:
            start = int(page_token)
        except ValueError:
            raise QueryError("Invalid pageToken.")
    page = out[start:start + size]
    nxt = str(start + size) if start + size < total else ""
    return page, nxt, total
