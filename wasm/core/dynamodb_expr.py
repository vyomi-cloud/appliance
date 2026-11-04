# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""DynamoDB expression engine — substrate-free (host CPython + Pyodide).

v4 C0: the offline appliance serves the DynamoDB wire from core/dynamodb_core.py
instead of proxying DynamoDB Local, so the expression language real apps rely on
lives here, once, for every substrate.

v4 parity pass: the engine works on TYPED AttributeValues ({"S": ..}, {"N": ..},
{"SS": [..]}, {"L": [..]} ...), never on lossy Python natives, so

  * numbers are exact decimals (38 significant digits; 0.1 + 0.2 == 0.3),
  * a list of strings stays a List (L) and is never confused with a String Set,
  * Binary (B / BS) compares byte-wise, Strings by UTF-8 code point,

exactly as DynamoDB does. Every behaviour here is measured differentially against
DynamoDB Local by tests/parity/ddb_differential.py.

  * condition expressions — KeyConditionExpression, FilterExpression,
    ConditionExpression: = <> < <= > >=, BETWEEN, IN, AND / OR / NOT, parentheses,
    attribute_exists, attribute_not_exists, attribute_type, begins_with, contains,
    size();
  * update expressions — SET (incl. `a + :n`, `a - :n`, if_not_exists, list_append),
    REMOVE, ADD (number add / set union), DELETE (set difference), with DynamoDB's
    overlap / operand-type / document-path validation;
  * projection expressions;
  * attribute-value validation, canonical numbers and item-size accounting.

Paths support `#alias`, `a.b` and `a[0]`. NO fastapi / boto3 / socket imports —
vendored to Nano with the other cores.
"""
from __future__ import annotations

import base64
import copy
import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

MISSING = None          # an absent attribute is represented by None (AVs are always dicts)
_MISSING = MISSING      # back-compat alias

AV_TYPES = ("S", "N", "B", "SS", "NS", "BS", "M", "L", "NULL", "BOOL")
_TYPE_WORD = {"S": "STRING", "N": "NUMBER", "B": "BINARY", "SS": "SS", "NS": "NS", "BS": "BS",
              "M": "MAP", "L": "LIST", "NULL": "NULL", "BOOL": "BOOLEAN"}
_SET_WORD = {"SS": "string set", "NS": "number set", "BS": "binary set"}
MAX_ITEM_BYTES = 400 * 1024

# DynamoDB reserved words (https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ReservedWords.html).
# A bare attribute name in any expression that matches one is a ValidationException.
RESERVED = frozenset("""
ABORT ABSOLUTE ACTION ADD AFTER AGENT AGGREGATE ALL ALLOCATE ALTER ANALYZE AND ANY ARCHIVE ARE ARRAY AS ASC
ASCII ASENSITIVE ASSERTION ASYMMETRIC AT ATOMIC ATTACH ATTRIBUTE AUTH AUTHORIZATION AUTHORIZE AUTO AVG BACK
BACKUP BASE BATCH BEFORE BEGIN BETWEEN BIGINT BINARY BIT BLOB BLOCK BOOLEAN BOTH BREADTH BUCKET BULK BY BYTE
CALL CALLED CALLING CAPACITY CASCADE CASCADED CASE CAST CATALOG CHAR CHARACTER CHECK CLASS CLOB CLOSE CLUSTER
CLUSTERED CLUSTERING CLUSTERS COALESCE COLLATE COLLATION COLLECTION COLUMN COLUMNS COMBINE COMMENT COMMIT
COMPACT COMPILE COMPRESS CONDITION CONFLICT CONNECT CONNECTION CONSISTENCY CONSISTENT CONSTRAINT CONSTRAINTS
CONSTRUCTOR CONSUMED CONTINUE CONVERT COPY CORRESPONDING COUNT COUNTER CREATE CROSS CUBE CURRENT CURSOR CYCLE
DATA DATABASE DATE DATETIME DAY DEALLOCATE DEC DECIMAL DECLARE DEFAULT DEFERRABLE DEFERRED DEFINE DEFINED
DEFINITION DELETE DELIMITED DEPTH DEREF DESC DESCRIBE DESCRIPTOR DETACH DETERMINISTIC DIAGNOSTICS DIRECTORIES
DISABLE DISCONNECT DISTINCT DISTRIBUTE DO DOMAIN DOUBLE DROP DUMP DURATION DYNAMIC EACH ELEMENT ELSE ELSEIF
EMPTY ENABLE END EQUAL EQUALS ERROR ESCAPE ESCAPED EVAL EVALUATE EXCEEDED EXCEPT EXCEPTION EXCEPTIONS EXCLUSIVE
EXEC EXECUTE EXISTS EXIT EXPLAIN EXPLODE EXPORT EXPRESSION EXTENDED EXTERNAL EXTRACT FAIL FALSE FAMILY FETCH
FIELDS FILE FILTER FILTERING FINAL FINISH FIRST FIXED FLATTERN FLOAT FOR FORCE FOREIGN FORMAT FORWARD FOUND
FREE FROM FULL FUNCTION FUNCTIONS GENERAL GENERATE GET GLOB GLOBAL GO GOTO GRANT GREATER GROUP GROUPING
HANDLER HASH HAVE HAVING HEAP HIDDEN HOLD HOUR IDENTIFIED IDENTITY IF IGNORE IMMEDIATE IMPORT IN INCLUDING
INCLUSIVE INCREMENT INCREMENTAL INDEX INDEXED INDEXES INDICATOR INFINITE INITIALLY INLINE INNER INNTER INOUT
INPUT INSENSITIVE INSERT INSTEAD INT INTEGER INTERSECT INTERVAL INTO INVALIDATE IS ISOLATION ITEM ITEMS
ITERATE JOIN KEY KEYS LAG LANGUAGE LARGE LAST LATERAL LEAD LEADING LEAVE LEFT LENGTH LESS LEVEL LIKE LIMIT
LIMITED LINES LIST LOAD LOCAL LOCALTIME LOCALTIMESTAMP LOCATION LOCATOR LOCK LOCKS LOG LOGED LONG LOOP LOWER
MAP MATCH MATERIALIZED MAX MAXLEN MEMBER MERGE METHOD METRICS MIN MINUS MINUTE MISSING MOD MODE MODIFIES
MODIFY MODULE MONTH MULTI MULTISET NAME NAMES NATIONAL NATURAL NCHAR NCLOB NEW NEXT NO NONE NOT NULL NULLIF
NUMBER NUMERIC OBJECT OF OFFLINE OFFSET OLD ON ONLINE ONLY OPAQUE OPEN OPERATOR OPTION OR ORDER ORDINALITY
OTHER OTHERS OUT OUTER OUTPUT OVER OVERLAPS OVERRIDE OWNER PAD PARALLEL PARAMETER PARAMETERS PARTIAL PARTITION
PARTITIONED PARTITIONS PATH PERCENT PERCENTILE PERMISSION PERMISSIONS PIPE PIPELINED PLAN POOL POSITION
PRECISION PREPARE PRESERVE PRIMARY PRIOR PRIVATE PRIVILEGES PROCEDURE PROCESSED PROJECT PROJECTION PROPERTY
PROVISIONING PUBLIC PUT QUERY QUIT QUORUM RAISE RANDOM RANGE RANK RAW READ READS REAL REBUILD RECORD RECURSIVE
REDUCE REF REFERENCE REFERENCES REFERENCING REGEXP REGION REINDEX RELATIVE RELEASE REMAINDER RENAME REPEAT
REPLACE REQUEST RESET RESIGNAL RESOURCE RESPONSE RESTORE RESTRICT RESULT RETURN RETURNING RETURNS REVERSE
REVOKE RIGHT ROLE ROLES ROLLBACK ROLLUP ROUTINE ROW ROWS RULE RULES SAMPLE SATISFIES SAVE SAVEPOINT SCAN
SCHEMA SCOPE SCROLL SEARCH SECOND SECTION SEGMENT SEGMENTS SELECT SELF SEMI SENSITIVE SEPARATE SEQUENCE
SERIALIZABLE SESSION SET SETS SHARD SHARE SHARED SHORT SHOW SIGNAL SIMILAR SIZE SKEWED SMALLINT SNAPSHOT SOME
SOURCE SPACE SPACES SPARSE SPECIFIC SPECIFICTYPE SPLIT SQL SQLCODE SQLERROR SQLEXCEPTION SQLSTATE SQLWARNING
START STATE STATIC STATUS STORAGE STORE STORED STREAM STRING STRUCT STYLE SUB SUBMULTISET SUBPARTITION
SUBSTRING SUBTYPE SUM SUPER SYMMETRIC SYNONYM SYSTEM TABLE TABLESAMPLE TEMP TEMPORARY TERMINATED TEXT THAN
THEN THROUGHPUT TIME TIMESTAMP TIMEZONE TINYINT TO TOKEN TOTAL TOUCH TRAILING TRANSACTION TRANSFORM TRANSLATE
TRANSLATION TREAT TRIGGER TRIM TRUE TRUNCATE TTL TUPLE TYPE UNDER UNDO UNION UNIQUE UNIT UNKNOWN UNLOGGED
UNNEST UNPROCESSED UNSIGNED UNTIL UPDATE UPPER URL USAGE USE USER USERS USING UUID VACUUM VALUE VALUED VALUES
VARCHAR VARIABLE VARIANCE VARINT VARYING VIEW VIEWS VIRTUAL VOID WAIT WHEN WHENEVER WHERE WHILE WINDOW WITH
WITHIN WITHOUT WORK WRAPPED WRITE YEAR ZONE
""".split())


class ExprError(ValueError):
    """Malformed expression / invalid value → the caller answers ValidationException.

    `bare` errors are reported verbatim; the others get DynamoDB's
    "Invalid <Kind>Expression: " prefix from the caller."""

    def __init__(self, message: str, bare: bool = False):
        super().__init__(message)
        self.message = message
        self.bare = bare


# ── numbers ────────────────────────────────────────────────────────────────
_NUM_RE = re.compile(r"\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*")


def parse_number(text: Any) -> Decimal:
    s = str(text)
    if not _NUM_RE.fullmatch(s):
        raise ExprError("A value provided cannot be converted into a number", bare=True)
    try:
        d = Decimal(s.strip())
    except InvalidOperation:
        raise ExprError("A value provided cannot be converted into a number", bare=True)
    if d == 0:
        return Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 200
        d = d.normalize()
    if len(d.as_tuple().digits) > 38:
        raise ExprError("DynamoDB only supports precision up to 38 digits", bare=True)
    if d.adjusted() > 125:
        raise ExprError("Number overflow. Attempting to store a number with magnitude larger than supported range", bare=True)
    if d.adjusted() < -130:
        raise ExprError("Number underflow. Attempting to store a number with magnitude smaller than supported range", bare=True)
    return d


def format_number(d: Decimal) -> str:
    if d == 0:
        return "0"
    with localcontext() as ctx:
        ctx.prec = 200
        return format(d.normalize(), "f")


def canon_number(text: Any) -> str:
    return format_number(parse_number(text))


def _arith(a: str, b: str, op: str) -> str:
    with localcontext() as ctx:
        ctx.prec = 60
        x, y = Decimal(a), Decimal(b)
        r = x + y if op == "+" else x - y
    return canon_number(r)


def _b(v: str) -> bytes:
    try:
        return base64.b64decode(v, validate=False)
    except Exception:
        return str(v).encode()


# ── attribute values ───────────────────────────────────────────────────────
def av_type(v: Any) -> str:
    return next(iter(v)) if isinstance(v, dict) and len(v) == 1 else ""


def _java_list(xs: list) -> str:
    return "[" + ", ".join(str(x) for x in xs) + "]"


def validate_av(v: Any) -> dict:
    """Validate + canonicalise one AttributeValue (numbers normalised). Raises
    ExprError(bare) with DynamoDB's messages."""
    if not isinstance(v, dict) or len(v) != 1 or next(iter(v)) not in AV_TYPES:
        raise ExprError("Supplied AttributeValue is empty, must contain exactly one of the supported datatypes", bare=True)
    (t, x), = v.items()
    if t == "S":
        if not isinstance(x, str):
            raise ExprError("Supplied AttributeValue has invalid string value", bare=True)
        return {"S": x}
    if t == "N":
        return {"N": canon_number(x)}
    if t == "B":
        return {"B": str(x)}
    if t == "BOOL":
        return {"BOOL": bool(x)}
    if t == "NULL":
        if x is not True:
            raise ExprError("One or more parameter values were invalid: Null attribute value types must have the value of true", bare=True)
        return {"NULL": True}
    if t in ("SS", "NS", "BS"):
        xs = list(x or [])
        if not xs:
            raise ExprError(f"One or more parameter values were invalid: An {_SET_WORD[t]}  may not be empty", bare=True)
        vals = [canon_number(i) for i in xs] if t == "NS" else [str(i) for i in xs]
        if len(set(str(i) for i in xs)) != len(xs):
            raise ExprError(f"One or more parameter values were invalid: Input collection {_java_list(xs)} contains duplicates", bare=True)
        keys = [Decimal(i) for i in vals] if t == "NS" else (vals if t == "SS" else [_b(i) for i in vals])
        if len(set(keys)) != len(keys):
            raise ExprError("Input collection contains duplicates", bare=True)
        return {t: vals}
    if t == "L":
        return {"L": [validate_av(i) for i in (x or [])]}
    return {"M": {str(k): validate_av(i) for k, i in (x or {}).items()}}


def av_eq(a: Any, b: Any) -> bool:
    ta, tb = av_type(a), av_type(b)
    if not ta or ta != tb:
        return False
    x, y = a[ta], b[tb]
    if ta == "N":
        return Decimal(x) == Decimal(y)
    if ta == "B":
        return _b(x) == _b(y)
    if ta == "NS":
        return {Decimal(i) for i in x} == {Decimal(i) for i in y}
    if ta == "BS":
        return {_b(i) for i in x} == {_b(i) for i in y}
    if ta == "SS":
        return set(x) == set(y)
    if ta == "L":
        return len(x) == len(y) and all(av_eq(i, j) for i, j in zip(x, y))
    if ta == "M":
        return set(x) == set(y) and all(av_eq(x[k], y[k]) for k in x)
    return x == y


def sort_value(v: Any) -> tuple:
    """Total order for key attributes: N numeric, S by code point (= UTF-8 byte
    order), B byte-wise. Mixed/other types order by type name (never compared
    in DynamoDB, which forbids them in keys)."""
    t = av_type(v)
    if t == "N":
        return (1, Decimal(v["N"]), b"")
    if t == "S":
        return (2, Decimal(0), v["S"].encode("utf-8"))
    if t == "B":
        return (3, Decimal(0), _b(v["B"]))
    return (9, Decimal(0), repr(v).encode())


def _ordered(op: str, a: Any, b: Any) -> bool:
    ta, tb = av_type(a), av_type(b)
    if not ta or ta != tb or ta not in ("N", "S", "B"):
        return False
    x, y = sort_value(a), sort_value(b)
    return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]


def av_size(v: Any) -> int:
    t = av_type(v)
    x = v.get(t) if t else None
    if t == "S":
        return len(x.encode("utf-8"))
    if t == "N":
        return (len(Decimal(x).as_tuple().digits) + 1) // 2 + 1
    if t == "B":
        return len(_b(x))
    if t in ("BOOL", "NULL"):
        return 1
    if t == "SS":
        return sum(len(i.encode("utf-8")) for i in x)
    if t == "NS":
        return sum((len(Decimal(i).as_tuple().digits) + 1) // 2 + 1 for i in x)
    if t == "BS":
        return sum(len(_b(i)) for i in x)
    if t == "L":
        return 3 + sum(av_size(i) + 1 for i in x)
    if t == "M":
        return 3 + sum(len(k.encode("utf-8")) + av_size(i) + 1 for k, i in x.items())
    return 0


def item_size(item: dict) -> int:
    return sum(len(k.encode("utf-8")) + av_size(v) for k, v in (item or {}).items())


# ── paths over typed items ─────────────────────────────────────────────────
def get_path(item: dict, parts: list) -> Any:
    """Value at a document path of a typed item (top-level {name: AV}); None if absent."""
    if not parts or not isinstance(parts[0], str):
        return None
    cur = (item or {}).get(parts[0])
    for p in parts[1:]:
        if cur is None:
            return None
        if isinstance(p, int):
            lst = cur.get("L") if av_type(cur) == "L" else None
            if lst is None or p >= len(lst):
                return None
            cur = lst[p]
        else:
            m = cur.get("M") if av_type(cur) == "M" else None
            if m is None or p not in m:
                return None
            cur = m[p]
    return cur


def _container(item: dict, parts: list) -> Any:
    """The parent container AV of a path (or the item itself for top-level)."""
    if len(parts) == 1:
        return item
    return get_path(item, parts[:-1])


def _set_path(item: dict, parts: list, value: dict) -> None:
    if len(parts) == 1:
        item[parts[0]] = value
        return
    parent = _container(item, parts)
    last = parts[-1]
    if isinstance(last, int):
        if av_type(parent) != "L":
            raise ExprError("The document path provided in the update expression is invalid for update", bare=True)
        lst = parent["L"]
        if last >= len(lst):
            lst.append(value)
        else:
            lst[last] = value
    else:
        if av_type(parent) != "M":
            raise ExprError("The document path provided in the update expression is invalid for update", bare=True)
        parent["M"][last] = value


def _remove_path(item: dict, parts: list) -> None:
    if len(parts) == 1:
        item.pop(parts[0], None)
        return
    parent = _container(item, parts)
    last = parts[-1]
    if parent is None:
        raise ExprError("The document path provided in the update expression is invalid for update", bare=True)
    if isinstance(last, int):
        if av_type(parent) != "L":
            raise ExprError("The document path provided in the update expression is invalid for update", bare=True)
        if last < len(parent["L"]):
            parent["L"].pop(last)
    else:
        if av_type(parent) != "M":
            raise ExprError("The document path provided in the update expression is invalid for update", bare=True)
        parent["M"].pop(last, None)


# ── tokenizer ──────────────────────────────────────────────────────────────
_TOKEN = re.compile(r"""
    \s*(?:
      (?P<op><>|<=|>=|=|<|>)
    | (?P<punct>[(),+\-])
    | (?P<value>:[A-Za-z0-9_]+)
    | (?P<path>(?:\#[A-Za-z0-9_]+|[A-Za-z_][A-Za-z0-9_]*)(?:\s*\[\s*\d+\s*\])*(?:\.(?:\#[A-Za-z0-9_]+|[A-Za-z_][A-Za-z0-9_]*)(?:\s*\[\s*\d+\s*\])*)*)
    )""", re.X)
_KEYWORDS = {"AND", "OR", "NOT", "BETWEEN", "IN"}
_FUNCS = {"attribute_exists", "attribute_not_exists", "attribute_type", "begins_with", "contains", "size"}


def _tokenize(expr: str) -> list[tuple[str, str]]:
    out, pos, s = [], 0, expr or ""
    while pos < len(s):
        if s[pos:].strip() == "":
            break
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            bad = s[pos:].strip()[:1]
            prev = out[-1][1] if out else ""
            raise ExprError(f'Syntax error; token: "{bad}", near: "{prev}{bad}"')
        pos = m.end()
        kind = m.lastgroup
        text = m.group(kind)
        if kind == "path" and text.upper() in _KEYWORDS:
            kind, text = "kw", text.upper()
        out.append((kind, text))
    return out


class _Ctx:
    def __init__(self, names: dict | None, values: dict | None):
        self.names = names or {}
        self.values = values or {}
        self.used_names: set = set()
        self.used_values: set = set()
        self._cache: dict = {}

    def path(self, raw: str) -> list:
        parts: list = []
        for seg in re.findall(r"\#?[A-Za-z0-9_]+|\[\s*\d+\s*\]", raw):
            if seg.startswith("["):
                if not parts:
                    raise ExprError(f'Syntax error; token: "{seg}"')
                parts.append(int(seg[1:-1].strip()))
            elif seg.startswith("#"):
                if seg not in self.names:
                    raise ExprError(f"An expression attribute name used in the document path is not defined; attribute name: {seg}")
                self.used_names.add(seg)
                parts.append(str(self.names[seg]))
            else:
                if seg.upper() in RESERVED:
                    raise ExprError(f"Attribute name is a reserved keyword; reserved keyword: {seg}")
                parts.append(seg)
        return parts

    def value(self, token: str) -> dict:
        if token not in self.values:
            raise ExprError(f"An expression attribute value used in expression is not defined; attribute value: {token}")
        self.used_values.add(token)
        if token not in self._cache:
            self._cache[token] = validate_av(self.values[token])
        return self._cache[token]


# ── condition expressions → AST ────────────────────────────────────────────
class _Parser:
    def __init__(self, tokens, ctx: _Ctx):
        self.t, self.i, self.ctx = tokens, 0, ctx

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None)

    def fail(self):
        kind, text = self.peek()
        prev = self.t[self.i - 1][1] if self.i > 0 else ""
        if kind is None:
            raise ExprError(f'Syntax error; token: "<EOF>", near: "{prev}"')
        raise ExprError(f'Syntax error; token: "{text}", near: "{prev} {text}"'.replace('"" ', '"'))

    def take(self, kind=None, text=None):
        tk = self.peek()
        if tk[0] is None or (kind and tk[0] != kind) or (text and tk[1] != text):
            self.fail()
        self.i += 1
        return tk

    def cond(self):
        left = self.conj()
        while self.peek() == ("kw", "OR"):
            self.take()
            left = ("or", left, self.conj())
        return left

    def conj(self):
        left = self.neg()
        while self.peek() == ("kw", "AND"):
            self.take()
            left = ("and", left, self.neg())
        return left

    def neg(self):
        if self.peek() == ("kw", "NOT"):
            self.take()
            return ("not", self.neg())
        return self.primary()

    def primary(self):
        kind, text = self.peek()
        if (kind, text) == ("punct", "("):
            self.take()
            c = self.cond()
            self.take("punct", ")")
            return c
        if kind == "path" and self.peek(1) == ("punct", "(") and text != "size":
            return self.func()
        left = self.operand()
        kind, text = self.peek()
        if kind == "op":
            self.take()
            return ("cmp", text, left, self.operand())
        if (kind, text) == ("kw", "BETWEEN"):
            self.take()
            lo = self.operand()
            self.take("kw", "AND")
            return ("between", left, lo, self.operand())
        if (kind, text) == ("kw", "IN"):
            self.take()
            self.take("punct", "(")
            opts = [self.operand()]
            while self.peek() == ("punct", ","):
                self.take()
                opts.append(self.operand())
            self.take("punct", ")")
            if len(opts) > 100:
                raise ExprError("The IN operator is provided with too many operands; number of operands: %d" % len(opts))
            return ("in", left, opts)
        self.fail()

    def func(self):
        name = self.take("path")[1]
        if name not in _FUNCS:
            raise ExprError(f"Invalid function name; function: {name}")
        if name == "size":
            raise ExprError("The function is not allowed to be used this way in an expression; function: size")
        self.take("punct", "(")
        args = [self.operand()]
        while self.peek() == ("punct", ","):
            self.take()
            args.append(self.operand())
        self.take("punct", ")")
        want = 1 if name in ("attribute_exists", "attribute_not_exists") else 2
        if len(args) != want:
            raise ExprError(f"Incorrect number of operands for operator or function; operator or function: {name}, "
                            f"number of operands: {len(args)}")
        if args[0][0] != "path":
            raise ExprError(f"Operator or function requires a document path; operator or function: {name}")
        if name == "attribute_type":
            t = args[1][1] if args[1][0] == "val" else None
            if not t or av_type(t) != "S" or t["S"] not in AV_TYPES:
                raise ExprError("Invalid attribute type name found; type: %s, valid types: { B,NULL,SS,BOOL,L,BS,N,NS,S,M }"
                                % ((t or {}).get("S") if isinstance(t, dict) else t))
        return ("func", name, args)

    def operand(self):
        kind, text = self.peek()
        if kind == "value":
            self.take()
            return ("val", self.ctx.value(text), text)
        if kind == "path" and text == "size" and self.peek(1) == ("punct", "("):
            self.take()
            self.take("punct", "(")
            p = self.ctx.path(self.take("path")[1])
            self.take("punct", ")")
            return ("size", p)
        if kind == "path":
            self.take()
            if self.peek() == ("punct", "("):
                raise ExprError(f"The function is not allowed to be used this way in an expression; function: {text}")
            return ("path", self.ctx.path(text))
        self.fail()


def parse_condition(expr: str, ctx: _Ctx):
    toks = _tokenize(expr)
    if not toks:
        raise ExprError("The expression can not be empty;")
    p = _Parser(toks, ctx)
    node = p.cond()
    if p.i != len(p.t):
        p.fail()
    return node


def _operand(node, item) -> Any:
    kind = node[0]
    if kind == "val":
        return node[1]
    if kind == "path":
        return get_path(item, node[1])
    if kind == "size":
        v = get_path(item, node[1])
        t = av_type(v)
        if t == "S":
            n = len(v["S"].encode("utf-8"))
        elif t == "B":
            n = len(_b(v["B"]))
        elif t in ("SS", "NS", "BS", "L"):
            n = len(v[t])
        elif t == "M":
            n = len(v["M"])
        else:
            return None
        return {"N": str(n)}
    return None


def evaluate(node, item: dict) -> bool:
    kind = node[0]
    if kind == "or":
        return evaluate(node[1], item) or evaluate(node[2], item)
    if kind == "and":
        return evaluate(node[1], item) and evaluate(node[2], item)
    if kind == "not":
        return not evaluate(node[1], item)
    if kind == "cmp":
        a, b = _operand(node[2], item), _operand(node[3], item)
        if a is None or b is None:
            return False
        if node[1] == "=":
            return av_eq(a, b)
        if node[1] == "<>":
            return not av_eq(a, b)
        return _ordered(node[1], a, b)
    if kind == "between":
        a, lo, hi = (_operand(n, item) for n in node[1:])
        if a is None or lo is None or hi is None:
            return False
        return _ordered(">=", a, lo) and _ordered("<=", a, hi)
    if kind == "in":
        a = _operand(node[1], item)
        return a is not None and any(av_eq(a, _operand(o, item)) for o in node[2])
    if kind == "func":
        name, args = node[1], node[2]
        v = get_path(item, args[0][1])
        if name == "attribute_exists":
            return v is not None
        if name == "attribute_not_exists":
            return v is None
        arg = _operand(args[1], item)
        if v is None or arg is None:
            return False
        if name == "attribute_type":
            return av_type(v) == arg.get("S")
        if name == "begins_with":
            tv, ta = av_type(v), av_type(arg)
            if tv == ta == "S":
                return v["S"].startswith(arg["S"])
            if tv == ta == "B":
                return _b(v["B"]).startswith(_b(arg["B"]))
            return False
        # contains
        tv, ta = av_type(v), av_type(arg)
        if tv == "S" and ta == "S":
            return arg["S"] in v["S"]
        if tv == "B" and ta == "B":
            return _b(arg["B"]) in _b(v["B"])
        if tv in ("SS", "NS", "BS") and ta == tv[0]:
            return any(av_eq({ta: e}, arg) for e in v[tv])
        if tv == "L":
            return any(av_eq(e, arg) for e in v["L"])
        return False
    raise ExprError("Invalid expression")


def compile_condition(expr: str, names: dict | None, values: dict | None, to_native=None, ctx: _Ctx | None = None):
    """Compile a condition / filter / key-condition expression into item -> bool
    (items are typed {name: AV} maps)."""
    expr = (expr or "").strip()
    if not expr:
        return lambda it: True
    node = parse_condition(expr, ctx or _Ctx(names, values))
    return lambda it: evaluate(node, it)


def condition_paths(node) -> list[list]:
    """Every document path a condition AST references."""
    out: list = []

    def walk(n):
        if not isinstance(n, tuple):
            return
        if n[0] in ("path", "size"):
            out.append(n[1])
            return
        for x in n[1:]:
            if isinstance(x, tuple):
                walk(x)
            elif isinstance(x, list):
                for y in x:
                    walk(y)
    walk(node)
    return out


def key_condition_attrs(expr: str, names: dict | None) -> list[str]:
    """Top-level attribute names a KeyConditionExpression references (for validation)."""
    out = []
    for kind, text in _tokenize(expr or ""):
        if kind == "path" and text not in _FUNCS:
            out.append(str((names or {}).get(text, text)).split(".", 1)[0])
    return out


def split_key_condition(node, pk: str, sk: str) -> tuple:
    """Validate a parsed KeyConditionExpression against the (index) key schema.
    Returns (pk_value_av, sk_predicate_node|None). Raises ExprError(bare) with
    DynamoDB's messages."""
    conds: list = []

    def flat(n):
        if n[0] == "and":
            flat(n[1])
            flat(n[2])
        elif n[0] in ("or", "not"):
            raise ExprError(f"Invalid operator used in KeyConditionExpression: {n[0].upper()}")
        else:
            conds.append(n)
    flat(node)

    def attr_of(n):
        if n[0] == "func":
            a = n[2][0]
        elif n[0] == "cmp":
            a = n[2] if n[2][0] == "path" else n[3]
        else:
            a = n[1]
        if a[0] != "path":
            return None
        return a[1][0] if len(a[1]) == 1 else ".".join(str(x) for x in a[1])

    if len(conds) > 2:
        raise ExprError("Conditions can be of length 1 or 2 only", bare=True)
    pk_val, sk_node = None, None
    for c in conds:
        a = attr_of(c)
        if a not in (pk, sk) or not a:
            raise ExprError("Query condition missed key schema element", bare=True)
        if a == pk:
            if c[0] != "cmp" or c[1] != "=":
                raise ExprError("Query key condition not supported", bare=True)
            other = c[3] if c[2][0] == "path" else c[2]
            if other[0] != "val":
                raise ExprError("Query key condition not supported", bare=True)
            pk_val = other[1]
        else:
            if c[0] == "cmp" and c[1] == "<>" or c[0] == "in" or (c[0] == "func" and c[1] != "begins_with"):
                raise ExprError("Query key condition not supported", bare=True)
            if c[0] == "func":
                arg = c[2][1]
                if arg[0] == "val" and av_type(arg[1]) not in ("S", "B"):
                    raise ExprError("Incorrect operand type for operator or function; operator or function: "
                                    f"begins_with, operand type: {av_type(arg[1])}")
            if c[0] == "between":
                lo, hi = c[2], c[3]
                if lo[0] == "val" and hi[0] == "val" and _ordered(">", lo[1], hi[1]):
                    raise ExprError("Invalid KeyConditionExpression: The BETWEEN operator requires upper bound to be "
                                    "greater than or equal to lower bound; lower bound operand: AttributeValue: "
                                    f"{{{av_type(lo[1])}:{lo[1][av_type(lo[1])]}}}, upper bound operand: AttributeValue: "
                                    f"{{{av_type(hi[1])}:{hi[1][av_type(hi[1])]}}}", bare=True)
            sk_node = c
    if pk_val is None:
        raise ExprError("Query condition missed key schema element", bare=True)
    return pk_val, sk_node


# ── update expressions ─────────────────────────────────────────────────────
_CLAUSES = ("SET", "REMOVE", "ADD", "DELETE")


def _parse_update(expr: str, ctx: _Ctx) -> list:
    toks = _tokenize(expr)
    p = _Parser(toks, ctx)
    actions: list = []
    seen: set = set()
    if not toks:
        raise ExprError("The expression can not be empty;")
    while p.peek()[0] is not None:
        kind, text = p.take()
        verb = text.upper() if kind == "path" else ""
        if verb not in _CLAUSES:
            raise ExprError(f'Syntax error; token: "{text}", near: "{text}"')
        if verb in seen:
            raise ExprError(f'The "{verb}" section can only be used once in an update expression;')
        seen.add(verb)
        while True:
            kind, text = p.peek()
            if kind != "path":
                p.fail()
            p.take()
            path = ctx.path(text)
            if verb == "SET":
                p.take("op", "=")
                actions.append(("SET", path, _parse_set_value(p)))
            elif verb == "REMOVE":
                actions.append(("REMOVE", path, None))
            else:
                k2, t2 = p.peek()
                if k2 != "value":
                    p.fail()
                p.take()
                val = ctx.value(t2)
                t = av_type(val)
                allowed = ("N", "SS", "NS", "BS") if verb == "ADD" else ("SS", "NS", "BS")
                if t not in allowed:
                    raise ExprError(f"Incorrect operand type for operator or function; operator: {verb}, operand type: "
                                    f"{_TYPE_WORD[t]}, typeSet: ALLOWED_FOR_{verb}_OPERAND")
                actions.append((verb, path, val))
            if p.peek() == ("punct", ","):
                p.take()
                continue
            break
    # overlapping / conflicting document paths
    paths = [a[1] for a in actions]
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            a, b = paths[i], paths[j]
            n = min(len(a), len(b))
            if a[:n] == b[:n]:
                fmt = lambda ps: "[" + ", ".join(str(x) if not isinstance(x, int) else f"[{x}]" for x in ps) + "]"
                if len(a) == len(b):
                    raise ExprError("Two document paths overlap with each other; must remove or rewrite one of these "
                                    f"paths; path one: {fmt(a)}, path two: {fmt(b)}")
                raise ExprError("Two document paths overlap with each other; must remove or rewrite one of these "
                                f"paths; path one: {fmt(a)}, path two: {fmt(b)}")
    return actions


def _parse_set_value(p: _Parser):
    left = _parse_set_operand(p)
    if p.peek() in (("punct", "+"), ("punct", "-")):
        op = p.take()[1]
        right = _parse_set_operand(p)
        for side in (left, right):
            if side[0] == "val" and av_type(side[1]) != "N":
                raise ExprError(f"Incorrect operand type for operator or function; operator or function: {op}, "
                                f"operand type: {av_type(side[1])}")
        return ("arith", op, left, right)
    return left


def _parse_set_operand(p: _Parser):
    kind, text = p.peek()
    if kind == "path" and p.peek(1) == ("punct", "("):
        name = p.take()[1]
        if name not in ("if_not_exists", "list_append"):
            if name in _FUNCS:
                raise ExprError(f"The function is not allowed in an update expression; function: {name}")
            raise ExprError(f"Invalid function name; function: {name}")
        p.take("punct", "(")
        a = _parse_set_operand(p)
        p.take("punct", ",")
        b = _parse_set_operand(p)
        p.take("punct", ")")
        if name == "if_not_exists" and a[0] != "path":
            raise ExprError("Operator or function requires a document path; operator or function: if_not_exists")
        if name == "list_append":
            for side in (a, b):
                if side[0] == "val" and av_type(side[1]) != "L":
                    raise ExprError("Incorrect operand type for operator or function; operator or function: list_append, "
                                    f"operand type: {av_type(side[1])}")
        return (name, a, b)
    if kind == "value":
        p.take()
        return ("val", p.ctx.value(text))
    if kind == "path":
        p.take()
        return ("path", p.ctx.path(text))
    p.fail()


def _eval_set(node, item: dict) -> dict:
    kind = node[0]
    if kind == "val":
        return copy.deepcopy(node[1])
    if kind == "path":
        v = get_path(item, node[1])
        if v is None:
            raise ExprError("The provided expression refers to an attribute that does not exist in the item", bare=True)
        return copy.deepcopy(v)
    if kind == "if_not_exists":
        v = get_path(item, node[1][1])
        return copy.deepcopy(v) if v is not None else _eval_set(node[2], item)
    if kind == "list_append":
        a, b = _eval_set(node[1], item), _eval_set(node[2], item)
        if av_type(a) != "L" or av_type(b) != "L":
            raise ExprError("An operand in the update expression has an incorrect data type", bare=True)
        return {"L": a["L"] + b["L"]}
    if kind == "arith":
        a, b = _eval_set(node[2], item), _eval_set(node[3], item)
        if av_type(a) != "N" or av_type(b) != "N":
            raise ExprError("An operand in the update expression has an incorrect data type", bare=True)
        try:
            return {"N": _arith(a["N"], b["N"], node[1])}
        except ExprError:
            raise
    raise ExprError("Invalid UpdateExpression")


def parse_update(expr: str, ctx: _Ctx) -> list:
    return _parse_update(expr, ctx)


def apply_actions(item: dict, actions: list) -> tuple[dict, list]:
    """Apply parsed update actions to a COPY of the typed `item`. Every operand is
    evaluated against the ORIGINAL item (DynamoDB semantics). Returns
    (new_item, [document paths touched])."""
    orig = item
    new = copy.deepcopy(item)
    computed = []
    # every target's parent container must already exist (checked before any operand
    # is evaluated, as DynamoDB does)
    for _verb, path, _arg in actions:
        if len(path) > 1:
            parent = get_path(orig, path[:-1])
            want = "L" if isinstance(path[-1], int) else "M"
            if av_type(parent) != want:
                raise ExprError("The document path provided in the update expression is invalid for update", bare=True)
    for verb, path, arg in actions:
        if verb == "SET":
            computed.append((verb, path, _eval_set(arg, orig)))
        elif verb in ("ADD", "DELETE"):
            cur = get_path(orig, path)
            t, ct = av_type(arg), av_type(cur)
            if verb == "ADD":
                if cur is None:
                    res = copy.deepcopy(arg)
                elif t == "N" and ct == "N":
                    res = {"N": _arith(cur["N"], arg["N"], "+")}
                elif t == ct and t in ("SS", "NS", "BS"):
                    res = {t: list(cur[t]) + [x for x in arg[t] if not any(av_eq({t[0]: x}, {t[0]: y}) for y in cur[t])]}
                else:
                    raise ExprError("An operand in the update expression has an incorrect data type", bare=True)
            else:
                if cur is None:
                    continue
                if t != ct:
                    raise ExprError("An operand in the update expression has an incorrect data type", bare=True)
                res = {t: [x for x in cur[t] if not any(av_eq({t[0]: x}, {t[0]: y}) for y in arg[t])]}
                if not res[t]:
                    computed.append(("REMOVE", path, None))
                    continue
            computed.append(("SET", path, res))
        else:
            computed.append((verb, path, None))
    # SETs first (list appends keep their original indices), then REMOVEs, list
    # indices highest-first so earlier removals don't shift later ones.
    for verb, path, val in computed:
        if verb == "SET":
            if len(path) > 1 and get_path(new, path[:-1]) is None:
                raise ExprError("The document path provided in the update expression is invalid for update", bare=True)
            _set_path(new, path, val)
    removes = [p for v, p, _ in computed if v == "REMOVE"]
    removes.sort(key=lambda p: [x if isinstance(x, int) else -1 for x in p], reverse=True)
    for path in removes:
        _remove_path(new, path)
    return new, [a[1] for a in actions]


def apply_update(item: dict, expr: str, names: dict | None, values: dict | None, to_native=None,
                 ctx: _Ctx | None = None) -> tuple[dict, list]:
    """Parse + apply an UpdateExpression to a COPY of the typed `item`."""
    ctx = ctx or _Ctx(names, values)
    return apply_actions(item, _parse_update(expr or "", ctx))


# ── projection ─────────────────────────────────────────────────────────────
def parse_projection(expr: str, ctx: _Ctx) -> list[list]:
    paths = []
    for raw in [x.strip() for x in (expr or "").split(",")]:
        if not raw:
            raise ExprError('Syntax error; token: ",", near: ","')
        toks = _tokenize(raw)
        if len(toks) != 1 or toks[0][0] != "path":
            raise ExprError(f'Syntax error; token: "{toks[-1][1] if toks else raw}", near: "{raw}"')
        paths.append(ctx.path(toks[0][1]))
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            a, b = paths[i], paths[j]
            n = min(len(a), len(b))
            if a[:n] == b[:n]:
                fmt = lambda ps: "[" + ", ".join(str(x) if not isinstance(x, int) else f"[{x}]" for x in ps) + "]"
                raise ExprError("Two document paths overlap with each other; must remove or rewrite one of these "
                                f"paths; path one: {fmt(a)}, path two: {fmt(b)}")
    return paths


def project_paths(item: dict, paths: list[list]) -> dict:
    """The typed item restricted to the given document paths (DynamoDB shapes:
    `m.k` → {"m": {"M": {"k": ..}}}, `l[1]` → {"l": {"L": [<elem 1>]}}; selected
    list elements keep their source order)."""
    tree: dict = {}
    for parts in paths:
        node = tree
        for i, p in enumerate(parts):
            if i == len(parts) - 1:
                node[p] = True
            else:
                nxt = node.get(p)
                if nxt is True:
                    break
                node = node.setdefault(p, {})

    def prune(av: Any, sel: Any) -> Any:
        if sel is True:
            return copy.deepcopy(av)
        t = av_type(av)
        if t == "M":
            out = {k: prune(av["M"][k], v) for k, v in sel.items() if isinstance(k, str) and k in av["M"]}
            out = {k: v for k, v in out.items() if v is not None}
            return {"M": out} if out else None
        if t == "L":
            out = [prune(av["L"][i], sel[i]) for i in sorted(k for k in sel if isinstance(k, int)) if i < len(av["L"])]
            out = [v for v in out if v is not None]
            return {"L": out} if out else None
        return None

    result = {}
    for name, sel in tree.items():
        if isinstance(name, str) and name in (item or {}):
            v = prune(item[name], sel)
            if v is not None:
                result[name] = v
    return result


def project(item: dict, expr: str, names: dict | None) -> dict:
    """ProjectionExpression → the typed item restricted to the listed paths."""
    if not (expr or "").strip():
        return item
    return project_paths(item, parse_projection(expr, _Ctx(names, {})))
