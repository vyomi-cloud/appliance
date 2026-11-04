"""DynamoDB differential parity — the Vyomi core vs AWS's own engine (DynamoDB Local).

Since v4 "C0" the offline appliance AND Nano serve DynamoDB from the shared
pure-Python core (core/dynamodb_core.py + core/dynamodb_expr.py). This harness
MEASURES how close that core is to DynamoDB by running identical request
sequences against

  (a) the core, in-process: core.dynamodb_core.dispatch over an InMemoryNoSqlStore
  (b) DynamoDB Local (docker image amazon/dynamodb-local) — the oracle

and diffing every response after normalisation (request ids, timestamps, ARN
account/region, unordered collections, numeric spelling).

Two suites:
  * hand-written cases (CASES) — table shapes, expressions, query/scan paging,
    batch/transact failures, sets, number precision, item size, validation errors,
    ReturnValues, TTL, PartiQL;
  * property-based random sequences (seeded; `--seeds`) of put/update/delete/query
    over a small key space, comparing every response AND the final table state.
    A mismatching sequence is delta-minimised before it is reported.

Usage:
  docker run -d --name vyomi-parity-ddblocal -p 127.0.0.1:8123:8000 \\
      amazon/dynamodb-local:latest -jar DynamoDBLocal.jar -inMemory -sharedDb
  PYTHONPATH=. python3 tests/parity/ddb_differential.py --endpoint http://127.0.0.1:8123 \\
      --out tests/parity/reports
Exit status: 0 always unless --min-parity is given and the hand-written exact-match
rate is below it (CI gate).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
if os.environ.get("PARITY_CORE_ROOT"):      # measure another checkout's core (e.g. the pre-fix baseline)
    sys.path.insert(0, os.path.abspath(os.environ["PARITY_CORE_ROOT"]))

from core import dynamodb_core as core  # noqa: E402
from core.nosql_store import InMemoryNoSqlStore  # noqa: E402

TARGET = "DynamoDB_20120810."

# Fields that are inherently environment-specific or eventually-consistent in real
# DynamoDB (ItemCount / TableSizeBytes refresh ~every 6 h), so they are never diffed.
_VOLATILE = {
    "CreationDateTime", "LastUpdateToPayPerRequestDateTime", "LastIncreaseDateTime",
    "LastDecreaseDateTime", "TableId", "BackupCreationDateTime", "TableCreationDateTime",
    "ItemCount", "TableSizeBytes", "IndexSizeBytes", "LatestStreamArn", "LatestStreamLabel",
    "NumberOfDecreasesToday", "EarliestRestorableDateTime", "LatestRestorableDateTime",
    "BackupArn", "BackupSizeBytes",
}
# Fields DynamoDB Local is known NOT to emit although real DynamoDB does (documented
# in AWS's "DynamoDB Local usage notes"): the core returning them is not a deviation.
_ORACLE_OMITS = {"TableClassSummary", "DeletionProtectionEnabled", "SSEDescription", "WarmThroughput"}

# Error wording where DynamoDB Local is known to differ from the real service; the
# core deliberately keeps the REAL service's wording. (code, core regex, oracle regex)
# — matching pairs are reported as "alias" (accepted), never silently as exact.
ORACLE_WORDING = [
    ("ResourceNotFoundException", r"^Requested resource not found(: Table: .* not found)?$",
     r"^Cannot do operations on a non-existent table$"),
    ("ResourceInUseException", r"^Table already exists: .+$", r"^Cannot create preexisting table$"),
    ("ValidationException", r"^The provided key element does not match the schema$",
     r"^One or more parameter values were invalid: Type mismatch for key$"),
    ("ValidationException", r"^One or more parameter values were invalid: Some index key attributes are not defined in "
                            r"AttributeDefinitions\. Keys: \[.*\], AttributeDefinitions: \[.*\]$",
     r"^Hash Key not specified in Attribute Definitions\.  Type unknown\.$"),
]
# Error codes the real service spells differently from DynamoDB Local: core → oracle.
ORACLE_CODES = {"DuplicateItemException": "DuplicateItem"}
# Operations DynamoDB Local does not implement at all (the core does, like the real
# service): such steps are reported as "oracle-gap" and excluded from the parity %.
ORACLE_GAP_MARKERS = ("not currently supported in DynamoDB Local",)


# ── clients ────────────────────────────────────────────────────────────────
class OracleClient:
    """DynamoDB Local over its native JSON wire (no SDK — raw request bytes)."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint.rstrip("/")

    def call(self, op: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            self.endpoint + "/", data=json.dumps(payload).encode(), method="POST",
            headers={"X-Amz-Target": TARGET + op, "Content-Type": "application/x-amz-json-1.0",
                     "Authorization": "AWS4-HMAC-SHA256 Credential=AKIDPARITY/20261030/us-east-1/"
                                      "dynamodb/aws4_request, SignedHeaders=host, Signature=00"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"{}")
            except ValueError:
                return e.code, {"__raw": raw.decode(errors="replace")}

    def reset(self, names: list[str]) -> None:
        for n in names:
            self.call("DeleteTable", {"TableName": n})


class CoreClient:
    def __init__(self):
        self.store = InMemoryNoSqlStore()

    def call(self, op: str, payload: dict) -> tuple[int, dict]:
        try:
            r = core.dispatch(self.store, TARGET + op, copy.deepcopy(payload))
            return r.status, json.loads(r.json_bytes())
        except Exception as exc:   # a crash is a parity failure, never a harness failure
            return 599, {"__type": "CoreCrash", "message": f"{type(exc).__name__}: {exc}"}

    def reset(self, names: list[str]) -> None:
        self.store = InMemoryNoSqlStore()


# ── normalisation ──────────────────────────────────────────────────────────
def _num(s: str) -> str:
    try:
        d = Decimal(str(s))
    except InvalidOperation:
        return str(s)
    if d == 0:
        return "0"
    with localcontext() as ctx:     # never round: the default 28-digit context would hide precision loss
        ctx.prec = 200
        return format(d.normalize(), "f")


def norm_av(v: Any) -> Any:
    """Normalise one typed AttributeValue (sets unordered, numbers canonical)."""
    if not isinstance(v, dict) or len(v) != 1:
        return v
    (t, x), = v.items()
    if t == "N":
        return {"N": _num(x)}
    if t == "NS":
        return {"NS": sorted(_num(i) for i in x)}
    if t in ("SS", "BS"):
        return {t: sorted(x)}
    if t == "L":
        return {"L": [norm_av(i) for i in x]}
    if t == "M":
        return {"M": {k: norm_av(i) for k, i in x.items()}}
    return v


def norm_item(it: dict) -> dict:
    return {k: norm_av(v) for k, v in (it or {}).items()}


def _item_sort_key(it: dict) -> str:
    return json.dumps(it, sort_keys=True)


def _arn(s: str) -> str:
    parts = s.split(":", 5)
    if len(parts) == 6 and parts[0] == "arn":
        parts[3], parts[4] = "REGION", "ACCOUNT"
        return ":".join(parts)
    return s


def normalise(op: str, status: int, body: dict, unordered_items: bool = False, request: dict | None = None) -> dict:
    body = copy.deepcopy(body)
    if not (request or {}).get("ReturnConsumedCapacity"):
        body.pop("ConsumedCapacity", None)     # DynamoDB Local sometimes volunteers it
    if op == "DeleteTable" and isinstance(body.get("TableDescription"), dict):
        body["TableDescription"].pop("TableStatus", None)   # real: DELETING; DynamoDB Local: ACTIVE

    def walk(o: Any, parent: str = "") -> Any:
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k in _VOLATILE or k in _ORACLE_OMITS:
                    continue
                if k in ("Item", "Attributes") and isinstance(v, dict):
                    out[k] = norm_item(v)
                elif k in ("Items",) and isinstance(v, list):
                    items = [norm_item(i) for i in v]
                    out[k] = sorted(items, key=_item_sort_key) if unordered_items else items
                elif k in ("LastEvaluatedKey", "ExclusiveStartKey", "Key") and isinstance(v, dict):
                    out[k] = norm_item(v)
                elif k == "Responses" and isinstance(v, dict):      # BatchGetItem: unordered
                    out[k] = {t: sorted((norm_item(i) for i in rows), key=_item_sort_key) for t, rows in v.items()}
                elif k == "Responses" and isinstance(v, list):      # TransactGetItems: ordered
                    out[k] = [walk(r) for r in v]
                elif isinstance(v, str) and v.startswith("arn:"):
                    out[k] = _arn(v)
                elif k in ("AttributeDefinitions", "GlobalSecondaryIndexes", "LocalSecondaryIndexes",
                           "TableNames", "Tags") and isinstance(v, list):
                    out[k] = sorted((walk(i) for i in v), key=_item_sort_key)
                elif k == "__type" and isinstance(v, str):
                    out[k] = v.rsplit("#", 1)[-1]
                elif k == "Message":                                 # DynamoDB Local spells it "Message" sometimes
                    out["message"] = v
                else:
                    out[k] = walk(v, k)
            return out
        if isinstance(o, list):
            return [walk(i, parent) for i in o]
        return o

    out = walk(body)
    if op == "Scan" and "LastEvaluatedKey" in out:
        # Scan order / page boundaries follow the storage hash, which DynamoDB leaves
        # unspecified (and DynamoDB Local's differs from ours): compare presence only.
        out["LastEvaluatedKey"] = "<present>"
        if isinstance(out.get("Items"), list):
            out["Items"] = f"<{len(out['Items'])} items>"
    return {"status": status, "body": out}


def diff(a: Any, b: Any, path: str = "$") -> list[str]:
    """Human-readable structural differences (core=a, oracle=b)."""
    if type(a) is not type(b):
        return [f"{path}: core={json.dumps(a)[:200]} oracle={json.dumps(b)[:200]}"]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: missing in core (oracle={json.dumps(b[k])[:160]})")
            elif k not in b:
                out.append(f"{path}.{k}: extra in core (core={json.dumps(a[k])[:160]})")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: len core={len(a)} oracle={len(b)}; core={json.dumps(a)[:200]} oracle={json.dumps(b)[:200]}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: core={json.dumps(a)[:200]} oracle={json.dumps(b)[:200]}"]


def classify(c: dict, o: dict) -> str:
    """exact | alias (documented DynamoDB-Local wording) | message (same status +
    error __type, different message) | oracle-gap | mismatch."""
    import re as _re
    if c == o:
        return "exact"
    cb, ob = c["body"], o["body"]
    if any(m in str(ob.get("message", "")) for m in ORACLE_GAP_MARKERS) or o["status"] >= 500:
        return "oracle-gap"      # DynamoDB Local doesn't implement it (or fails internally)
    ctype = ORACLE_CODES.get(cb.get("__type"), cb.get("__type"))
    if c["status"] == o["status"] and "__type" in cb and ctype == ob.get("__type"):
        rest_c = {k: v for k, v in cb.items() if k not in ("__type", "message")}
        rest_o = {k: v for k, v in ob.items() if k not in ("__type", "message")}
        if rest_c == rest_o:
            if cb.get("message") == ob.get("message"):
                return "alias"
            for code, cre, ore in ORACLE_WORDING:
                if code == ctype and _re.match(cre, str(cb.get("message", ""))) and _re.match(ore, str(ob.get("message", ""))):
                    return "alias"
            return "message"
    return "mismatch"


# ── case DSL ───────────────────────────────────────────────────────────────
def S(x): return {"S": x}
def N(x): return {"N": str(x)}
def B(x): return {"B": x}


def tbl(name, pk=("pk", "S"), sk=None, gsis=(), lsis=(), extra_attrs=(), **kw) -> dict:
    attrs = {pk[0]: pk[1]}
    ks = [{"AttributeName": pk[0], "KeyType": "HASH"}]
    if sk:
        attrs[sk[0]] = sk[1]
        ks.append({"AttributeName": sk[0], "KeyType": "RANGE"})
    for a, t in extra_attrs:
        attrs[a] = t
    p = {"TableName": name, "KeySchema": ks, "BillingMode": "PAY_PER_REQUEST"}
    if gsis:
        p["GlobalSecondaryIndexes"] = list(gsis)
    if lsis:
        p["LocalSecondaryIndexes"] = list(lsis)
    p["AttributeDefinitions"] = [{"AttributeName": a, "AttributeType": t} for a, t in attrs.items()]
    p.update(kw)
    return p


def idx(name, pk, sk=None, proj="ALL", nonkey=None):
    ks = [{"AttributeName": pk, "KeyType": "HASH"}]
    if sk:
        ks.append({"AttributeName": sk, "KeyType": "RANGE"})
    pr = {"ProjectionType": proj}
    if nonkey:
        pr["NonKeyAttributes"] = nonkey
    return {"IndexName": name, "KeySchema": ks, "Projection": pr}


CASES: list[dict] = []


def case(name: str, steps: list, *, tables: tuple = (), area: str = "misc"):
    CASES.append({"name": name, "area": area, "steps": steps, "tables": list(tables)})


def st(op, p, *, unordered=False, label=""):
    return {"op": op, "p": p, "unordered": unordered, "label": label or op}


def put(t, item, **kw):
    return st("PutItem", {"TableName": t, "Item": item, **kw})


T1 = "par_t1"       # pk S
T2 = "par_t2"       # pk S + sk S
T3 = "par_t3"       # pk S + sk N
TG = "par_tg"       # with GSI + LSI


def _build_cases() -> None:
    # ── table shapes ──
    case("create_describe_hash", [st("CreateTable", tbl(T1)), st("DescribeTable", {"TableName": T1})],
         tables=(T1,), area="table")
    case("create_describe_hash_range_provisioned", [
        st("CreateTable", tbl(T2, sk=("sk", "S"), BillingMode="PROVISIONED",
                              ProvisionedThroughput={"ReadCapacityUnits": 3, "WriteCapacityUnits": 4})),
        st("DescribeTable", {"TableName": T2})], tables=(T2,), area="table")
    case("create_gsi_lsi_describe", [
        st("CreateTable", tbl(TG, sk=("sk", "S"), extra_attrs=(("g", "S"), ("gs", "N"), ("l", "S")),
                              gsis=(idx("byG", "g", "gs"), idx("byGkeys", "g", proj="KEYS_ONLY")),
                              lsis=(idx("byL", "pk", "l", proj="INCLUDE", nonkey=["x"]),))),
        st("DescribeTable", {"TableName": TG})], tables=(TG,), area="table")
    case("create_duplicate_table", [st("CreateTable", tbl(T1)), st("CreateTable", tbl(T1))], tables=(T1,), area="table")
    case("describe_missing_table", [st("DescribeTable", {"TableName": "par_nope"})], area="table")
    case("create_attrdef_mismatch", [st("CreateTable", {
        "TableName": T1, "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"},
                                 {"AttributeName": "unused", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST"})], tables=(T1,), area="validation")
    case("create_provisioned_without_throughput", [st("CreateTable", tbl(T1, BillingMode="PROVISIONED"))],
         tables=(T1,), area="validation")
    case("list_tables", [st("CreateTable", tbl(T1)), st("CreateTable", tbl(T2, sk=("sk", "S"))),
                         st("ListTables", {})], tables=(T1, T2), area="table")
    case("delete_table_then_describe", [st("CreateTable", tbl(T1)), st("DeleteTable", {"TableName": T1}),
                                        st("DescribeTable", {"TableName": T1})], tables=(T1,), area="table")
    case("update_table_billing", [st("CreateTable", tbl(T1)),
                                  st("UpdateTable", {"TableName": T1, "BillingMode": "PROVISIONED",
                                                     "ProvisionedThroughput": {"ReadCapacityUnits": 2, "WriteCapacityUnits": 2}}),
                                  st("DescribeTable", {"TableName": T1})], tables=(T1,), area="table")
    case("ttl_update_describe", [st("CreateTable", tbl(T1)), st("DescribeTimeToLive", {"TableName": T1}),
                                 st("UpdateTimeToLive", {"TableName": T1, "TimeToLiveSpecification": {"AttributeName": "exp", "Enabled": True}}),
                                 st("DescribeTimeToLive", {"TableName": T1})], tables=(T1,), area="ttl")
    case("ttl_expired_item_still_readable", [
        st("CreateTable", tbl(T1)),
        st("UpdateTimeToLive", {"TableName": T1, "TimeToLiveSpecification": {"AttributeName": "exp", "Enabled": True}}),
        put(T1, {"pk": S("a"), "exp": N(1000)}),
        st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}})], tables=(T1,), area="ttl")
    case("tags_roundtrip", [st("CreateTable", tbl(T1, Tags=[{"Key": "env", "Value": "dev"}])),
                            st("ListTagsOfResource", {"ResourceArn": "arn:aws:dynamodb:us-east-1:000000000000:table/" + T1}),
                            ], tables=(T1,), area="table")

    # ── item CRUD + conditions ──
    base = [st("CreateTable", tbl(T1))]
    case("put_get_all_types", base + [
        put(T1, {"pk": S("a"), "s": S("x"), "n": N("42"), "f": N("3.14"), "b": B("AQID"), "t": {"BOOL": True},
                 "nul": {"NULL": True}, "ss": {"SS": ["b", "a"]}, "ns": {"NS": ["3", "1", "2"]},
                 "bs": {"BS": ["AQ==", "Ag=="]}, "l": {"L": [S("a"), N("1"), {"L": []}]},
                 "m": {"M": {"in": S("y"), "deep": {"M": {"z": N("0")}}}}, "emptyl": {"L": []}, "emptym": {"M": {}},
                 "es": S("")}),
        st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}})], tables=(T1,), area="types")
    case("list_of_strings_is_not_a_set", base + [
        put(T1, {"pk": S("a"), "l": {"L": [S("x"), S("y"), S("x")]}, "ln": {"L": [N(1), N(2)]}}),
        st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}})], tables=(T1,), area="types")
    case("number_precision_38_digits", base + [
        put(T1, {"pk": S("a"), "big": N("12345678901234567890123456789012345678"),
                 "small": N("0.000000000000000000000000000000000000001"), "neg": N("-1.50")}),
        st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}})], tables=(T1,), area="numbers")
    case("number_too_many_digits", base + [
        put(T1, {"pk": S("a"), "big": N("123456789012345678901234567890123456789")})], tables=(T1,), area="numbers")
    case("add_point1_point2", base + [
        put(T1, {"pk": S("a"), "v": N("0.1")}),
        st("UpdateItem", {"TableName": T1, "Key": {"pk": S("a")}, "UpdateExpression": "ADD v :x",
                          "ExpressionAttributeValues": {":x": N("0.2")}, "ReturnValues": "ALL_NEW"})], tables=(T1,), area="numbers")
    case("set_plus_big_ints", base + [
        put(T1, {"pk": S("a"), "v": N("99999999999999999999999999999999999998")}),
        st("UpdateItem", {"TableName": T1, "Key": {"pk": S("a")}, "UpdateExpression": "SET v = v + :one",
                          "ExpressionAttributeValues": {":one": N(1)}, "ReturnValues": "UPDATED_NEW"})], tables=(T1,), area="numbers")
    case("invalid_number", base + [put(T1, {"pk": S("a"), "n": N("abc")})], tables=(T1,), area="validation")
    case("empty_string_key", base + [put(T1, {"pk": S("")})], tables=(T1,), area="validation")
    case("missing_key", base + [put(T1, {"other": S("x")})], tables=(T1,), area="validation")
    case("wrong_key_type", base + [put(T1, {"pk": N(1)})], tables=(T1,), area="validation")
    case("empty_set", base + [put(T1, {"pk": S("a"), "ss": {"SS": []}})], tables=(T1,), area="validation")
    case("duplicate_in_set", base + [put(T1, {"pk": S("a"), "ss": {"SS": ["x", "x"]}})], tables=(T1,), area="validation")
    case("get_missing_item", base + [st("GetItem", {"TableName": T1, "Key": {"pk": S("zz")}})], tables=(T1,), area="crud")
    case("get_with_projection", base + [
        put(T1, {"pk": S("a"), "x": N(1), "y": {"M": {"z": S("q"), "w": S("r")}}, "l": {"L": [S("0"), S("1")]}}),
        st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}, "ProjectionExpression": "x, y.z, l[1], #m",
                       "ExpressionAttributeNames": {"#m": "missing"}})], tables=(T1,), area="expr")
    case("get_key_extra_attr", base + [st("GetItem", {"TableName": T1, "Key": {"pk": S("a"), "x": S("y")}})],
         tables=(T1,), area="validation")
    case("put_return_all_old", base + [put(T1, {"pk": S("a"), "v": N(1)}),
                                       put(T1, {"pk": S("a"), "v": N(2)}, ReturnValues="ALL_OLD")], tables=(T1,), area="returnvalues")
    case("put_return_all_new_invalid", base + [put(T1, {"pk": S("a")}, ReturnValues="ALL_NEW")], tables=(T1,), area="returnvalues")
    case("put_condition_not_exists_fails", base + [
        put(T1, {"pk": S("a")}),
        put(T1, {"pk": S("a")}, ConditionExpression="attribute_not_exists(pk)")], tables=(T1,), area="conditions")
    case("put_condition_return_old_on_fail", base + [
        put(T1, {"pk": S("a"), "v": N(1)}),
        put(T1, {"pk": S("a")}, ConditionExpression="attribute_not_exists(pk)",
            ReturnValuesOnConditionCheckFailure="ALL_OLD")], tables=(T1,), area="conditions")
    case("condition_comparators", base + [
        put(T1, {"pk": S("a"), "n": N(5), "s": S("hello"), "ss": {"SS": ["x", "y"]}, "l": {"L": [S("q")]}}),
        put(T1, {"pk": S("a"), "n": N(6)}, ConditionExpression="n BETWEEN :lo AND :hi AND begins_with(s, :p) "
            "AND contains(ss, :x) AND size(l) = :one AND n IN (:a, :b, :c) AND attribute_type(s, :st)",
            ExpressionAttributeValues={":lo": N(1), ":hi": N(9), ":p": S("he"), ":x": S("y"), ":one": N(1),
                                       ":a": N(4), ":b": N(5), ":c": N(7), ":st": S("S")}),
        st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}})], tables=(T1,), area="conditions")
    case("condition_or_not_parens", base + [
        put(T1, {"pk": S("a"), "n": N(5)}),
        st("DeleteItem", {"TableName": T1, "Key": {"pk": S("a")},
                          "ConditionExpression": "NOT (n > :x) OR (attribute_exists(zz) AND n <> :x)",
                          "ExpressionAttributeValues": {":x": N(1)}})], tables=(T1,), area="conditions")
    case("condition_unused_value", base + [
        put(T1, {"pk": S("a")}, ConditionExpression="attribute_not_exists(pk)",
            ExpressionAttributeValues={":unused": S("x")})], tables=(T1,), area="validation")
    case("condition_undefined_value", base + [
        put(T1, {"pk": S("a")}, ConditionExpression="v = :nope")], tables=(T1,), area="validation")
    case("condition_syntax_error", base + [
        put(T1, {"pk": S("a")}, ConditionExpression="attribute_not_exists(")], tables=(T1,), area="validation")
    case("condition_type_mismatch_lt", base + [
        put(T1, {"pk": S("a"), "n": N(5)}),
        put(T1, {"pk": S("a")}, ConditionExpression="n < :s", ExpressionAttributeValues={":s": S("x")})],
         tables=(T1,), area="conditions")
    case("delete_return_all_old", base + [put(T1, {"pk": S("a"), "v": N(1)}),
                                          st("DeleteItem", {"TableName": T1, "Key": {"pk": S("a")}, "ReturnValues": "ALL_OLD"}),
                                          st("DeleteItem", {"TableName": T1, "Key": {"pk": S("a")}, "ReturnValues": "ALL_OLD"})],
         tables=(T1,), area="returnvalues")
    case("delete_condition_fails", base + [
        st("DeleteItem", {"TableName": T1, "Key": {"pk": S("a")}, "ConditionExpression": "attribute_exists(pk)"})],
         tables=(T1,), area="conditions")

    # ── update expressions ──
    upd = base + [put(T1, {"pk": S("a"), "n": N(1), "s": S("x"), "l": {"L": [N(1)]}, "ss": {"SS": ["a", "b"]},
                           "ns": {"NS": ["1", "2"]}, "m": {"M": {"k": S("v")}}})]

    def u(expr, vals=None, names=None, rv="ALL_NEW", **kw):
        p = {"TableName": T1, "Key": {"pk": S("a")}, "UpdateExpression": expr, "ReturnValues": rv, **kw}
        if vals:
            p["ExpressionAttributeValues"] = vals
        if names:
            p["ExpressionAttributeNames"] = names
        return st("UpdateItem", p)

    case("update_set_remove_add_delete", upd + [
        u("SET s = :s, m.k2 = :v, #nn = n + :inc REMOVE l[0], m.k ADD ns :ns, newn :one DELETE ss :d",
          {":s": S("y"), ":v": N(9), ":inc": N(2), ":ns": {"NS": ["3"]}, ":one": N(1), ":d": {"SS": ["a"]}},
          {"#nn": "n2"})], tables=(T1,), area="update")
    case("update_if_not_exists_list_append", upd + [
        u("SET c = if_not_exists(c, :z), n = if_not_exists(n, :z), l = list_append(l, :more), l2 = list_append(:more, l)",
          {":z": N(0), ":more": {"L": [S("x")]}})], tables=(T1,), area="update")
    case("update_add_string_set_to_missing", upd + [u("ADD newss :v", {":v": {"SS": ["q"]}})], tables=(T1,), area="update")
    case("update_delete_all_from_set", upd + [u("DELETE ss :v", {":v": {"SS": ["a", "b"]}})], tables=(T1,), area="update")
    case("update_add_to_list_invalid", upd + [u("ADD l :v", {":v": {"L": [N(2)]}})], tables=(T1,), area="update")
    case("update_creates_item", base + [u("SET v = :v", {":v": S("new")})], tables=(T1,), area="update")
    case("update_key_attribute", upd + [u("SET pk = :v", {":v": S("b")})], tables=(T1,), area="update")
    case("update_overlapping_paths", upd + [u("SET m = :v REMOVE m.k", {":v": {"M": {}}})], tables=(T1,), area="validation")
    case("update_set_missing_operand", upd + [u("SET x = nope + :one", {":one": N(1)})], tables=(T1,), area="update")
    case("update_list_index_out_of_range_set", upd + [u("SET l[5] = :v", {":v": S("z")})], tables=(T1,), area="update")
    case("update_nested_missing_parent", upd + [u("SET nomap.k = :v", {":v": S("z")})], tables=(T1,), area="update")
    case("update_return_updated_old", upd + [u("SET n = :v, z = :v", {":v": N(7)}, rv="UPDATED_OLD")], tables=(T1,), area="returnvalues")
    case("update_return_updated_new", upd + [u("SET n = :v, z = :v", {":v": N(7)}, rv="UPDATED_NEW")], tables=(T1,), area="returnvalues")
    case("update_return_all_old", upd + [u("REMOVE s", rv="ALL_OLD")], tables=(T1,), area="returnvalues")
    case("update_return_none_default", upd + [st("UpdateItem", {"TableName": T1, "Key": {"pk": S("a")},
                                                                  "UpdateExpression": "SET q = :v",
                                                                  "ExpressionAttributeValues": {":v": S("z")}})],
         tables=(T1,), area="returnvalues")
    case("update_condition_fail", upd + [u("SET n = :v", {":v": N(2), ":c": N(99)}, ConditionExpression="n = :c")],
         tables=(T1,), area="conditions")
    case("update_attribute_updates_legacy", upd + [st("UpdateItem", {
        "TableName": T1, "Key": {"pk": S("a")}, "ReturnValues": "ALL_NEW",
        "AttributeUpdates": {"n": {"Action": "ADD", "Value": N(5)}, "s": {"Action": "DELETE"},
                             "z": {"Action": "PUT", "Value": S("p")}}})], tables=(T1,), area="update")
    case("update_unused_name", upd + [u("SET n = :v", {":v": N(2)}, {"#x": "x"})], tables=(T1,), area="validation")

    # ── query ──
    q = [st("CreateTable", tbl(T2, sk=("sk", "S")))] + [
        put(T2, {"pk": S(p), "sk": S(s), "v": N(i)}) for i, (p, s) in enumerate(
            [("a", "a#1"), ("a", "a#2"), ("a", "b#1"), ("a", "c"), ("b", "a#1"), ("a", "A"), ("a", "a#10")])]

    def qq(kce, vals, **kw):
        return st("Query", {"TableName": T2, "KeyConditionExpression": kce, "ExpressionAttributeValues": vals, **kw})

    case("query_eq_order", q + [qq("pk = :p", {":p": S("a")})], tables=(T2,), area="query")
    case("query_begins_with", q + [qq("pk = :p AND begins_with(sk, :b)", {":p": S("a"), ":b": S("a#")})], tables=(T2,), area="query")
    case("query_between", q + [qq("pk = :p AND sk BETWEEN :x AND :y", {":p": S("a"), ":x": S("a#1"), ":y": S("b")})],
         tables=(T2,), area="query")
    case("query_backward_limit_paging", q + [
        qq("pk = :p", {":p": S("a")}, ScanIndexForward=False, Limit=2),
        qq("pk = :p", {":p": S("a")}, ScanIndexForward=False, Limit=2,
           ExclusiveStartKey={"pk": S("a"), "sk": S("a#2")})], tables=(T2,), area="query")
    case("query_limit_exact_last_page", q + [qq("pk = :p", {":p": S("b")}, Limit=1)], tables=(T2,), area="query")
    case("query_select_count", q + [qq("pk = :p", {":p": S("a")}, Select="COUNT")], tables=(T2,), area="query")
    case("query_filter", q + [qq("pk = :p", {":p": S("a"), ":m": N(2)}, FilterExpression="v > :m", Limit=3)],
         tables=(T2,), area="query")
    case("query_filter_on_key_invalid", q + [qq("pk = :p", {":p": S("a"), ":m": S("x")}, FilterExpression="sk = :m")],
         tables=(T2,), area="validation")
    case("query_missing_pk", q + [qq("sk = :s", {":s": S("a")})], tables=(T2,), area="validation")
    case("query_non_key_in_kce", q + [qq("pk = :p AND v = :v", {":p": S("a"), ":v": N(1)})], tables=(T2,), area="validation")
    case("query_pk_inequality", q + [qq("pk > :p", {":p": S("a")})], tables=(T2,), area="validation")
    case("query_projection", q + [qq("pk = :p AND sk = :s", {":p": S("a"), ":s": S("c")}, ProjectionExpression="v")],
         tables=(T2,), area="query")
    case("query_sk_lt_ge", q + [qq("pk = :p AND sk < :s", {":p": S("a"), ":s": S("a#2")}),
                                qq("pk = :p AND sk >= :s", {":p": S("a"), ":s": S("b")})], tables=(T2,), area="query")
    nq = [st("CreateTable", tbl(T3, sk=("n", "N")))] + [
        put(T3, {"pk": S("a"), "n": N(v)}) for v in ("10", "9", "-1", "2.5", "100", "-20")]
    case("query_numeric_sort_key_order", nq + [st("Query", {"TableName": T3, "KeyConditionExpression": "pk = :p",
                                                            "ExpressionAttributeValues": {":p": S("a")}})],
         tables=(T3,), area="query")
    case("query_numeric_between", nq + [st("Query", {"TableName": T3, "KeyConditionExpression": "pk = :p AND n BETWEEN :a AND :b",
                                                     "ExpressionAttributeValues": {":p": S("a"), ":a": N(-5), ":b": N(10)}})],
         tables=(T3,), area="query")
    bq = [st("CreateTable", tbl(T3, sk=("n", "B")))] + [
        put(T3, {"pk": S("a"), "n": B(v)}) for v in ("/w==", "AQ==", "fw==", "gA==")]
    case("query_binary_sort_key_order", bq + [st("Query", {"TableName": T3, "KeyConditionExpression": "pk = :p",
                                                           "ExpressionAttributeValues": {":p": S("a")}})],
         tables=(T3,), area="query")
    sq = [st("CreateTable", tbl(T2, sk=("sk", "S")))] + [
        put(T2, {"pk": S("a"), "sk": S(v)}) for v in ("b", "B", "a", "é", "Z", "_", "10", "9")]
    case("query_string_sort_utf8_order", sq + [qq("pk = :p", {":p": S("a")})], tables=(T2,), area="query")

    # ── GSI / LSI ──
    g = [st("CreateTable", tbl(TG, sk=("sk", "S"), extra_attrs=(("g", "S"), ("gs", "N"), ("l", "S")),
                               gsis=(idx("byG", "g", "gs"), idx("byGkeys", "g", proj="KEYS_ONLY")),
                               lsis=(idx("byL", "pk", "l", proj="INCLUDE", nonkey=["x"]),)))] + [
        put(TG, {"pk": S("p1"), "sk": S("1"), "g": S("G"), "gs": N(3), "l": S("z"), "x": S("xx"), "y": S("yy")}),
        put(TG, {"pk": S("p1"), "sk": S("2"), "g": S("G"), "gs": N(1), "l": S("a")}),
        put(TG, {"pk": S("p2"), "sk": S("1"), "g": S("H"), "gs": N(2)}),
        put(TG, {"pk": S("p3"), "sk": S("1"), "y": S("no index keys")})]
    case("gsi_query_all_projection", g + [st("Query", {"TableName": TG, "IndexName": "byG",
                                                       "KeyConditionExpression": "g = :g", "ExpressionAttributeValues": {":g": S("G")}})],
         tables=(TG,), area="index")
    case("gsi_keys_only_projection", g + [st("Query", {"TableName": TG, "IndexName": "byGkeys",   # hash-only index: order unspecified
                                                       "KeyConditionExpression": "g = :g", "ExpressionAttributeValues": {":g": S("G")}},
                                             unordered=True)],
         tables=(TG,), area="index")
    case("lsi_include_projection", g + [st("Query", {"TableName": TG, "IndexName": "byL",
                                                     "KeyConditionExpression": "pk = :p", "ExpressionAttributeValues": {":p": S("p1")}})],
         tables=(TG,), area="index")
    case("gsi_scan_sparse", g + [st("Scan", {"TableName": TG, "IndexName": "byG"}, unordered=True)], tables=(TG,), area="index")
    case("gsi_paging_lek_shape", g + [st("Query", {"TableName": TG, "IndexName": "byG", "Limit": 1,
                                                   "KeyConditionExpression": "g = :g", "ExpressionAttributeValues": {":g": S("G")}})],
         tables=(TG,), area="index")
    case("gsi_wrong_key_type_write", g + [put(TG, {"pk": S("p9"), "sk": S("1"), "gs": S("not a number")})],
         tables=(TG,), area="index")
    case("query_unknown_index", g + [st("Query", {"TableName": TG, "IndexName": "nope",
                                                  "KeyConditionExpression": "g = :g", "ExpressionAttributeValues": {":g": S("G")}})],
         tables=(TG,), area="validation")

    # ── scan ──
    sc = [st("CreateTable", tbl(T1))] + [put(T1, {"pk": S(f"k{i}"), "v": N(i)}) for i in range(7)]
    case("scan_all", sc + [st("Scan", {"TableName": T1}, unordered=True)], tables=(T1,), area="scan")
    case("scan_paged_union", sc + [st("_ScanAll", {"TableName": T1, "Limit": 3})], tables=(T1,), area="scan")
    case("scan_filter_count", sc + [st("Scan", {"TableName": T1, "FilterExpression": "v >= :x",
                                                "ExpressionAttributeValues": {":x": N(4)}, "Select": "COUNT"})], tables=(T1,), area="scan")
    case("scan_limit_zero_invalid", sc + [st("Scan", {"TableName": T1, "Limit": 0})], tables=(T1,), area="validation")
    case("scan_segments", sc + [st("_ScanAll", {"TableName": T1, "Segment": 0, "TotalSegments": 1})], tables=(T1,), area="scan")

    # ── item size limit ──
    case("item_size_400kb_ok", base + [put(T1, {"pk": S("a"), "blob": S("x" * (400 * 1024 - 10))}),
                                       st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}, "ProjectionExpression": "pk"})],
         tables=(T1,), area="limits")
    case("item_size_over_400kb", base + [put(T1, {"pk": S("a"), "blob": S("x" * (400 * 1024 + 1))})],
         tables=(T1,), area="limits")

    # ── batch ──
    bt = [st("CreateTable", tbl(T1)), st("CreateTable", tbl(T2, sk=("sk", "S")))]
    case("batch_write_get", bt + [
        st("BatchWriteItem", {"RequestItems": {T1: [{"PutRequest": {"Item": {"pk": S("a"), "v": N(1)}}},
                                                    {"PutRequest": {"Item": {"pk": S("b")}}}],
                                               T2: [{"PutRequest": {"Item": {"pk": S("a"), "sk": S("1")}}}]}}),
        st("BatchWriteItem", {"RequestItems": {T1: [{"DeleteRequest": {"Key": {"pk": S("b")}}}]}}),
        st("BatchGetItem", {"RequestItems": {T1: {"Keys": [{"pk": S("a")}, {"pk": S("b")}]},
                                             T2: {"Keys": [{"pk": S("a"), "sk": S("1")}], "ProjectionExpression": "sk"}}})],
         tables=(T1, T2), area="batch")
    case("batch_write_duplicate_keys", bt + [
        st("BatchWriteItem", {"RequestItems": {T1: [{"PutRequest": {"Item": {"pk": S("a")}}},
                                                    {"PutRequest": {"Item": {"pk": S("a")}}}]}})], tables=(T1, T2), area="batch")
    case("batch_write_missing_table", bt + [
        st("BatchWriteItem", {"RequestItems": {"par_nope": [{"PutRequest": {"Item": {"pk": S("a")}}}]}})],
         tables=(T1, T2), area="batch")
    case("batch_get_missing_table", bt + [st("BatchGetItem", {"RequestItems": {"par_nope": {"Keys": [{"pk": S("a")}]}}})],
         tables=(T1, T2), area="batch")
    case("batch_write_too_many", bt + [
        st("BatchWriteItem", {"RequestItems": {T1: [{"PutRequest": {"Item": {"pk": S(f"k{i}")}}} for i in range(26)]}})],
         tables=(T1, T2), area="batch")
    case("batch_write_bad_item_atomic", bt + [
        st("BatchWriteItem", {"RequestItems": {T1: [{"PutRequest": {"Item": {"pk": S("ok")}}},
                                                    {"PutRequest": {"Item": {"nokey": S("x")}}}]}}),
        st("GetItem", {"TableName": T1, "Key": {"pk": S("ok")}})], tables=(T1, T2), area="batch")

    # ── transactions ──
    tx = bt + [put(T1, {"pk": S("a"), "v": N(1)})]
    case("transact_write_ok", tx + [
        st("TransactWriteItems", {"TransactItems": [
            {"Put": {"TableName": T1, "Item": {"pk": S("b"), "v": N(2)}, "ConditionExpression": "attribute_not_exists(pk)"}},
            {"Update": {"TableName": T1, "Key": {"pk": S("a")}, "UpdateExpression": "ADD v :one",
                        "ExpressionAttributeValues": {":one": N(1)}}},
            {"ConditionCheck": {"TableName": T2, "Key": {"pk": S("x"), "sk": S("y")},
                                "ConditionExpression": "attribute_not_exists(pk)"}}]}),
        st("_ScanAll", {"TableName": T1})], tables=(T1, T2), area="transact")
    case("transact_write_cancel_reasons", tx + [
        st("TransactWriteItems", {"TransactItems": [
            {"Put": {"TableName": T1, "Item": {"pk": S("c")}}},
            {"Delete": {"TableName": T1, "Key": {"pk": S("a")}, "ConditionExpression": "v = :two",
                        "ExpressionAttributeValues": {":two": N(2)}, "ReturnValuesOnConditionCheckFailure": "ALL_OLD"}}]}),
        st("_ScanAll", {"TableName": T1})], tables=(T1, T2), area="transact")
    case("transact_write_same_item_twice", tx + [
        st("TransactWriteItems", {"TransactItems": [
            {"Put": {"TableName": T1, "Item": {"pk": S("a")}}},
            {"Delete": {"TableName": T1, "Key": {"pk": S("a")}}}]})], tables=(T1, T2), area="transact")
    case("transact_write_missing_table", tx + [
        st("TransactWriteItems", {"TransactItems": [{"Put": {"TableName": "par_nope", "Item": {"pk": S("a")}}}]})],
         tables=(T1, T2), area="transact")
    case("transact_get", tx + [
        st("TransactGetItems", {"TransactItems": [{"Get": {"TableName": T1, "Key": {"pk": S("a")}}},
                                                  {"Get": {"TableName": T1, "Key": {"pk": S("zz")}}},
                                                  {"Get": {"TableName": T1, "Key": {"pk": S("a")}, "ProjectionExpression": "v"}}]})],
         tables=(T1, T2), area="transact")

    case("transact_get_ok", tx + [
        st("TransactGetItems", {"TransactItems": [{"Get": {"TableName": T1, "Key": {"pk": S("a")}, "ProjectionExpression": "v"}},
                                                  {"Get": {"TableName": T1, "Key": {"pk": S("zz")}}}]})],
         tables=(T1, T2), area="transact")
    case("reserved_word_in_expression", upd + [u("SET status = :v", {":v": S("x")})], tables=(T1,), area="validation")
    case("reserved_word_via_name_ok", upd + [u("SET #s = :v", {":v": S("x")}, {"#s": "status"})], tables=(T1,), area="update")
    case("legacy_expected_and_key_conditions", q + [
        put(T2, {"pk": S("z"), "sk": S("1")}, Expected={"pk": {"Exists": False}}),
        st("Query", {"TableName": T2, "KeyConditions": {"pk": {"ComparisonOperator": "EQ", "AttributeValueList": [S("a")]},
                                                        "sk": {"ComparisonOperator": "BEGINS_WITH", "AttributeValueList": [S("a#")]}}})],
         tables=(T2,), area="legacy")
    case("update_set_multiple_list_indexes_remove", upd + [
        u("SET l = :l", {":l": {"L": [N(0), N(1), N(2), N(3)]}}),
        u("REMOVE l[1], l[3]")], tables=(T1,), area="update")
    case("update_set_rhs_uses_old_values", upd + [u("SET n = :v, n2 = n", {":v": N(100)})], tables=(T1,), area="update")
    case("list_tables_paging", [st("CreateTable", tbl(T1)), st("CreateTable", tbl(T2, sk=("sk", "S"))),
                                st("CreateTable", tbl(T3, sk=("n", "N"))), st("ListTables", {"Limit": 2}),
                                st("ListTables", {"ExclusiveStartTableName": T2})], tables=(T1, T2, T3), area="table")

    # ── more edge cases ──
    case("query_kce_type_mismatch", nq + [st("Query", {"TableName": T3, "KeyConditionExpression": "pk = :p AND n > :s",
                                                     "ExpressionAttributeValues": {":p": S("a"), ":s": S("x")}})],
         tables=(T3,), area="validation")
    case("query_begins_with_on_number_sk", nq + [st("Query", {"TableName": T3, "KeyConditionExpression": "pk = :p AND begins_with(n, :s)",
                                                            "ExpressionAttributeValues": {":p": S("a"), ":s": N(1)}})],
         tables=(T3,), area="validation")
    case("query_between_reversed", q + [qq("pk = :p AND sk BETWEEN :x AND :y", {":p": S("a"), ":x": S("z"), ":y": S("a")})],
         tables=(T2,), area="validation")
    case("query_count_with_limit", q + [qq("pk = :p", {":p": S("a")}, Select="COUNT", Limit=2)], tables=(T2,), area="query")
    case("query_gsi_consistent_read", g + [st("Query", {"TableName": TG, "IndexName": "byG", "ConsistentRead": True,
                                                        "KeyConditionExpression": "g = :g", "ExpressionAttributeValues": {":g": S("G")}})],
         tables=(TG,), area="index")
    case("gsi_paging_resume", g + [st("Query", {"TableName": TG, "IndexName": "byG", "Limit": 1,
                                                "KeyConditionExpression": "g = :g", "ExpressionAttributeValues": {":g": S("G")},
                                                "ExclusiveStartKey": {"g": S("G"), "gs": N(1), "pk": S("p1"), "sk": S("2")}})],
         tables=(TG,), area="index")
    case("scan_filter_limit_counts", sc + [st("Scan", {"TableName": T1, "Limit": 4, "FilterExpression": "v > :x",
                                                       "ExpressionAttributeValues": {":x": N(100)}})], tables=(T1,), area="scan")
    case("scan_segments_union", sc + [st("_ScanAll", {"TableName": T1, "TotalSegments": 2}),
                                      st("_ScanAll", {"TableName": T1, "TotalSegments": 3, "Limit": 2})],
         tables=(T1,), area="scan")
    case("get_key_wrong_type", base + [st("GetItem", {"TableName": T1, "Key": {"pk": N(1)}})], tables=(T1,), area="validation")
    case("get_unused_name", base + [st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}, "ExpressionAttributeNames": {"#x": "x"}})],
         tables=(T1,), area="validation")
    case("values_without_expression", base + [put(T1, {"pk": S("a")}, ExpressionAttributeValues={":x": S("x")})],
         tables=(T1,), area="validation")
    case("null_false_invalid", base + [put(T1, {"pk": S("a"), "z": {"NULL": False}})], tables=(T1,), area="validation")
    case("update_empty_expression", upd + [u("")], tables=(T1,), area="validation")
    case("update_unknown_function", upd + [u("SET n = nope(n, :v)", {":v": N(1)})], tables=(T1,), area="validation")
    case("update_string_plus", upd + [u("SET n = :a + :b", {":a": S("x"), ":b": N(1)})], tables=(T1,), area="validation")
    case("update_two_set_clauses", upd + [u("SET n = :v SET s = :v", {":v": N(1)})], tables=(T1,), area="validation")
    case("update_updated_new_nested", upd + [u("SET m.k2 = :v, l[0] = :v", {":v": N(5)}, rv="UPDATED_NEW")], tables=(T1,), area="returnvalues")
    case("update_rvoccf_all_old", upd + [u("SET n = :v", {":v": N(2), ":c": N(99)}, ConditionExpression="n = :c",
                                           ReturnValuesOnConditionCheckFailure="ALL_OLD")], tables=(T1,), area="conditions")
    case("condition_set_equality_unordered", upd + [put(T1, {"pk": S("a")}, ConditionExpression="ss = :s",
                                                        ExpressionAttributeValues={":s": {"SS": ["b", "a"]}})],
         tables=(T1,), area="conditions")
    case("condition_size_of_number", upd + [put(T1, {"pk": S("a")}, ConditionExpression="size(n) = :one",
                                                ExpressionAttributeValues={":one": N(1)})], tables=(T1,), area="conditions")
    case("condition_contains_on_number", upd + [put(T1, {"pk": S("a")}, ConditionExpression="contains(n, :one)",
                                                    ExpressionAttributeValues={":one": N(1)})], tables=(T1,), area="conditions")
    case("condition_nested_map_and_list", upd + [put(T1, {"pk": S("a")}, ConditionExpression="m.k = :v AND l[0] = :one",
                                                      ExpressionAttributeValues={":v": S("v"), ":one": N(1)})],
         tables=(T1,), area="conditions")
    case("projection_nested_list_of_maps", base + [
        put(T1, {"pk": S("a"), "l": {"L": [{"M": {"x": N(1), "y": N(2)}}, {"M": {"x": N(3)}}]}}),
        st("GetItem", {"TableName": T1, "Key": {"pk": S("a")}, "ProjectionExpression": "l[1].x, l[0].y"})],
         tables=(T1,), area="expr")
    case("batch_get_too_many", bt + [st("BatchGetItem", {"RequestItems": {T1: {"Keys": [{"pk": S(f"k{i}")} for i in range(101)]}}})],
         tables=(T1, T2), area="batch")
    case("batch_get_duplicate_keys", bt + [st("BatchGetItem", {"RequestItems": {T1: {"Keys": [{"pk": S("a")}, {"pk": S("a")}]}}})],
         tables=(T1, T2), area="batch")
    case("update_table_add_gsi_then_query", sc + [
        st("UpdateTable", {"TableName": T1, "AttributeDefinitions": [{"AttributeName": "v", "AttributeType": "N"}],
                           "GlobalSecondaryIndexUpdates": [{"Create": idx("byV", "v")}]}),
        st("Query", {"TableName": T1, "IndexName": "byV", "KeyConditionExpression": "v = :v",
                     "ExpressionAttributeValues": {":v": N(3)}})], tables=(T1,), area="index")
    case("create_table_bool_key_invalid", [st("CreateTable", {
        "TableName": T1, "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "BOOL"}], "BillingMode": "PAY_PER_REQUEST"})],
         tables=(T1,), area="validation")
    case("create_table_missing_attrdef", [st("CreateTable", {
        "TableName": T1, "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "other", "AttributeType": "S"}], "BillingMode": "PAY_PER_REQUEST"})],
         tables=(T1,), area="validation")
    case("put_number_set_canonical_dupes", base + [put(T1, {"pk": S("a"), "ns": {"NS": ["1", "1.0"]}})], tables=(T1,), area="validation")
    case("empty_attribute_name", base + [put(T1, {"pk": S("a"), "": S("x")})], tables=(T1,), area="validation")

    # ── PartiQL ──
    pq = [st("CreateTable", tbl(T2, sk=("sk", "S"))), put(T2, {"pk": S("a"), "sk": S("1"), "v": N(1)}),
          put(T2, {"pk": S("a"), "sk": S("2"), "v": N(2)})]
    case("partiql_select_where_pk", pq + [st("ExecuteStatement", {"Statement": f'SELECT * FROM "{T2}" WHERE pk = \'a\''})],
         tables=(T2,), area="partiql")
    case("partiql_select_params_projection", pq + [st("ExecuteStatement", {
        "Statement": f'SELECT v FROM "{T2}" WHERE pk = ? AND sk = ?', "Parameters": [S("a"), S("2")]})], tables=(T2,), area="partiql")
    case("partiql_insert_then_get", pq + [
        st("ExecuteStatement", {"Statement": f"INSERT INTO \"{T2}\" VALUE {{'pk': 'b', 'sk': '1', 'n': 5}}"}),
        st("GetItem", {"TableName": T2, "Key": {"pk": S("b"), "sk": S("1")}})], tables=(T2,), area="partiql")
    case("partiql_insert_duplicate", pq + [
        st("ExecuteStatement", {"Statement": f"INSERT INTO \"{T2}\" VALUE {{'pk': 'a', 'sk': '1'}}"})], tables=(T2,), area="partiql")
    case("partiql_update", pq + [
        st("ExecuteStatement", {"Statement": f"UPDATE \"{T2}\" SET v = 9 WHERE pk = 'a' AND sk = '1'"}),
        st("GetItem", {"TableName": T2, "Key": {"pk": S("a"), "sk": S("1")}})], tables=(T2,), area="partiql")
    case("partiql_delete", pq + [
        st("ExecuteStatement", {"Statement": f"DELETE FROM \"{T2}\" WHERE pk = 'a' AND sk = '2'"}),
        st("_ScanAll", {"TableName": T2})], tables=(T2,), area="partiql")
    case("partiql_select_in_begins_with", pq + [st("ExecuteStatement", {
        "Statement": f'SELECT * FROM "{T2}" WHERE pk = \'a\' AND (v IN [1, 3] OR begins_with(sk, \'2\'))'})], tables=(T2,), area="partiql")
    case("partiql_update_missing_item", pq + [st("ExecuteStatement", {"Statement": f"UPDATE \"{T2}\" SET v = 1 WHERE pk = 'zz' AND sk = '1'"})],
         tables=(T2,), area="partiql")
    case("partiql_delete_missing_item", pq + [st("ExecuteStatement", {"Statement": f"DELETE FROM \"{T2}\" WHERE pk = 'zz' AND sk = '1'"})],
         tables=(T2,), area="partiql")
    case("partiql_update_without_full_key", pq + [st("ExecuteStatement", {"Statement": f"UPDATE \"{T2}\" SET v = 1 WHERE pk = 'a'"})],
         tables=(T2,), area="partiql")
    case("partiql_param_count_mismatch", pq + [st("ExecuteStatement", {"Statement": f'SELECT * FROM "{T2}" WHERE pk = ?'})],
         tables=(T2,), area="partiql")
    case("partiql_missing_table", [st("ExecuteStatement", {"Statement": 'SELECT * FROM "par_nope"'})], area="partiql")
    case("partiql_update_remove_and_condition", pq + [
        st("ExecuteStatement", {"Statement": f"UPDATE \"{T2}\" SET w = 'x' REMOVE v WHERE pk = 'a' AND sk = '1' AND v = 1"}),
        st("ExecuteStatement", {"Statement": f"UPDATE \"{T2}\" SET w = 'y' WHERE pk = 'a' AND sk = '2' AND v = 99"}),
        st("_ScanAll", {"TableName": T2})], tables=(T2,), area="partiql")
    case("partiql_insert_types", pq + [
        st("ExecuteStatement", {"Statement": f"INSERT INTO \"{T2}\" VALUE {{'pk': 'c', 'sk': '1', 'n': 1.50, 'b': true, "
                                             f"'nul': null, 'l': [1, 'x'], 'm': {{'k': 'v'}}, 'ss': <<'a', 'b'>>, 'ns': <<1, 2>>}}"}),
        st("GetItem", {"TableName": T2, "Key": {"pk": S("c"), "sk": S("1")}})], tables=(T2,), area="partiql")
    case("create_table_short_name", [st("CreateTable", tbl("ab"))], tables=("ab",), area="validation")
    case("create_table_implicit_provisioned", [st("CreateTable", {
        "TableName": T1, "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}]})], tables=(T1,), area="validation")
    case("partiql_select_filter_nonkey", pq + [st("ExecuteStatement", {"Statement": f'SELECT * FROM "{T2}" WHERE v = 2'})],
         tables=(T2,), area="partiql")


# ── runner ─────────────────────────────────────────────────────────────────
def _scan_all(client, payload: dict) -> tuple[int, dict]:
    if "TotalSegments" in payload and "Segment" not in payload:     # union of every segment
        items = []
        for seg in range(int(payload["TotalSegments"])):
            status, body = _scan_all(client, {**payload, "Segment": seg})
            if status != 200:
                return status, body
            items += body["Items"]
        return 200, {"Items": items, "Count": len(items)}
    items, pages, esk = [], 0, None
    while True:
        p = dict(payload)
        if esk:
            p["ExclusiveStartKey"] = esk
        status, body = client.call("Scan", p)
        if status != 200:
            return status, body
        pages += 1
        items += body.get("Items", [])
        esk = body.get("LastEvaluatedKey")
        if not esk or pages > 200:
            break
    return 200, {"Items": items, "Count": len(items)}


def run_steps(client, steps: list) -> list[dict]:
    out = []
    for s in steps:
        if s["op"] == "_ScanAll":
            status, body = _scan_all(client, s["p"])
            out.append(normalise("Scan", status, body, unordered_items=True))
        else:
            status, body = client.call(s["op"], s["p"])
            out.append(normalise(s["op"], status, body, unordered_items=s.get("unordered", False), request=s["p"]))
    return out


def run_case(oracle: OracleClient, c: dict) -> dict:
    oracle.reset(c["tables"])
    corec = CoreClient()
    o = run_steps(oracle, c["steps"])
    k = run_steps(corec, c["steps"])
    oracle.reset(c["tables"])
    steps = []
    for s, a, b in zip(c["steps"], k, o):
        verdict = classify(a, b)
        steps.append({"op": s["label"], "request": s["p"], "verdict": verdict, "core": a, "oracle": b,
                      "diff": diff(a, b) if verdict != "exact" else []})
    rank = {"exact": 0, "alias": 1, "oracle-gap": 2, "message": 3, "mismatch": 4}
    worst = "exact"
    for s in steps:
        if rank[s["verdict"]] > rank[worst]:
            worst = s["verdict"]
    return {"name": c["name"], "area": c["area"], "verdict": worst, "steps": steps}


# ── property-based random sequences ────────────────────────────────────────
PT = "par_prop"
_PK = ["a", "b", "c"]
_SK = ["1", "2", "10", "x"]


def _rand_value(rng: random.Random) -> dict:
    kind = rng.choice(["S", "N", "N", "SS", "NS", "L", "M", "BOOL"])
    if kind == "S":
        return S(rng.choice(["", "x", "yy", "zz"]))[:] if False else S(rng.choice(["x", "yy", "zz", "a#1"]))
    if kind == "N":
        return N(rng.choice(["0", "1", "-3", "2.5", "0.1", "1e3", "12345678901234567890"]))
    if kind == "SS":
        return {"SS": rng.sample(["p", "q", "r"], rng.randint(1, 3))}
    if kind == "NS":
        return {"NS": rng.sample(["1", "2", "3.5"], rng.randint(1, 3))}
    if kind == "L":
        return {"L": [S("p"), N(1)][:rng.randint(0, 2)]}
    if kind == "M":
        return {"M": {"k": N(rng.randint(0, 3))}}
    return {"BOOL": rng.random() < 0.5}


_CONDS = [("attribute_exists(v)", {}), ("attribute_not_exists(w)", {}), ("v = :c", {":c": N(1)}),
          ("v < :c", {":c": N(2)}), ("size(v) > :one", {":one": N(1)}), ("contains(v, :c)", {":c": S("p")}),
          ("attribute_type(v, :t)", {":t": S("N")}), ("v BETWEEN :lo AND :hi", {":lo": N(0), ":hi": N(5)}),
          ("v IN (:a, :b)", {":a": S("x"), ":b": N("2.5")}), ("NOT begins_with(s, :p)", {":p": S("y")})]


def _rand_key(rng: random.Random) -> dict:
    return {"pk": S(rng.choice(_PK)), "sk": S(rng.choice(_SK))}


def _rand_update(rng: random.Random, key: dict) -> dict:
    attr = rng.choice(["v", "w", "s"])
    choice = rng.choice(["set", "add", "remove", "ine", "delete", "append", "arith", "nested", "multi"])
    vals: dict = {}
    if choice == "set":
        expr, vals = f"SET {attr} = :v", {":v": _rand_value(rng)}
    elif choice == "add":
        expr, vals = f"ADD {attr} :v", {":v": rng.choice([N(1), N("0.5"), {"SS": ["p"]}, {"NS": ["2"]}])}
    elif choice == "remove":
        expr = f"REMOVE {attr}"
    elif choice == "ine":
        expr, vals = f"SET {attr} = if_not_exists({attr}, :v)", {":v": N(7)}
    elif choice == "delete":
        expr, vals = f"DELETE {attr} :v", {":v": rng.choice([{"SS": ["p"]}, {"NS": ["1"]}])}
    elif choice == "append":
        expr, vals = f"SET {attr} = list_append(if_not_exists({attr}, :e), :v)", {":e": {"L": []}, ":v": {"L": [S("z")]}}
    elif choice == "arith":
        expr, vals = f"SET {attr} = {attr} {rng.choice(['+', '-'])} :n", {":n": N(rng.choice(["1", "0.1", "1e2"]))}
    elif choice == "nested":
        expr, vals = rng.choice([("SET m.k = :v", {":v": N(3)}), ("SET m = :m", {":m": {"M": {"k": S("q")}}}),
                                 ("REMOVE m.k", {}), ("SET m.k = m.k + :v", {":v": N(1)})])
    else:
        expr, vals = f"SET {attr} = :v, w2 = :v REMOVE s2 ADD c :one", {":v": _rand_value(rng), ":one": N(1)}
    p = {"TableName": PT, "Key": key, "UpdateExpression": expr,
         "ReturnValues": rng.choice(["NONE", "ALL_NEW", "ALL_OLD", "UPDATED_NEW", "UPDATED_OLD"])}
    if rng.random() < 0.3:
        cexpr, cvals = rng.choice(_CONDS)
        if not any(k in vals for k in cvals):
            p["ConditionExpression"] = cexpr
            vals = {**vals, **cvals}
    if vals:
        p["ExpressionAttributeValues"] = vals
    return p


def gen_sequence(rng: random.Random, n: int) -> list[dict]:
    seq = []
    for _ in range(n):
        key = _rand_key(rng)
        r = rng.random()
        if r < 0.25:
            item = dict(key)
            for a in rng.sample(["v", "w", "s", "m"], rng.randint(0, 3)):
                item[a] = _rand_value(rng) if a != "m" else {"M": {"k": N(rng.randint(0, 3))}}
            p = {"TableName": PT, "Item": item}
            if rng.random() < 0.3:
                p["ConditionExpression"] = rng.choice(["attribute_not_exists(pk)", "attribute_exists(pk)"])
            if rng.random() < 0.3:
                p["ReturnValues"] = "ALL_OLD"
            seq.append(st("PutItem", p))
        elif r < 0.50:
            seq.append(st("UpdateItem", _rand_update(rng, key)))
        elif r < 0.60:
            p = {"TableName": PT, "Key": key}
            if rng.random() < 0.3:
                p["ReturnValues"] = "ALL_OLD"
            if rng.random() < 0.3:
                cexpr, cvals = rng.choice(_CONDS)
                p["ConditionExpression"] = cexpr
                if cvals:
                    p["ExpressionAttributeValues"] = cvals
            seq.append(st("DeleteItem", p))
        elif r < 0.67:
            p = {"TableName": PT, "Key": key}
            if rng.random() < 0.4:
                p["ProjectionExpression"] = rng.choice(["v", "pk, w", "m.k, s", "v, #s"])
                if "#s" in p["ProjectionExpression"]:
                    p["ExpressionAttributeNames"] = {"#s": "s"}
            seq.append(st("GetItem", p))
        elif r < 0.85:
            p = {"TableName": PT, "KeyConditionExpression": "pk = :p", "ExpressionAttributeValues": {":p": key["pk"]}}
            if rng.random() < 0.5:
                p["KeyConditionExpression"] += rng.choice([" AND begins_with(sk, :s)", " AND sk > :s", " AND sk <= :s",
                                                           " AND sk BETWEEN :s AND :t"])
                p["ExpressionAttributeValues"][":s"] = S(rng.choice(["1", "x", "0", "10"]))
                if "BETWEEN" in p["KeyConditionExpression"]:
                    p["ExpressionAttributeValues"][":t"] = S("z")
            if rng.random() < 0.4:
                p["ScanIndexForward"] = False
            if rng.random() < 0.4:
                p["Limit"] = rng.randint(1, 3)
            if rng.random() < 0.3:
                cexpr, cvals = rng.choice(_CONDS)
                p["FilterExpression"] = cexpr
                p["ExpressionAttributeValues"].update(cvals)
            if rng.random() < 0.2:
                p["Select"] = "COUNT"
            seq.append(st("Query", p))
        elif r < 0.90:
            seq.append(st("_ScanAll", {"TableName": PT, "Limit": rng.randint(1, 4)}))
        elif r < 0.95:
            keys = []
            ops = []
            for _ in range(rng.randint(1, 4)):
                k = _rand_key(rng)
                if k in keys:
                    continue
                keys.append(k)
                ops.append({"PutRequest": {"Item": {**k, "v": _rand_value(rng)}}} if rng.random() < 0.6
                           else {"DeleteRequest": {"Key": k}})
            seq.append(st("BatchWriteItem", {"RequestItems": {PT: ops}}))
        else:
            k1, k2 = _rand_key(rng), _rand_key(rng)
            cexpr, cvals = rng.choice(_CONDS)
            items = [{"Put": {"TableName": PT, "Item": {**k1, "v": N(1)}}},
                     {"Update": {"TableName": PT, "Key": k2, "UpdateExpression": "ADD c :one",
                                 "ConditionExpression": cexpr, "ExpressionAttributeValues": {":one": N(1), **cvals},
                                 "ReturnValuesOnConditionCheckFailure": "ALL_OLD"}}]
            seq.append(st("TransactWriteItems", {"TransactItems": items}))
    return seq


_PROP_PRELUDE = [st("CreateTable", tbl(PT, sk=("sk", "S")))]
_PROP_FINAL = [st("_ScanAll", {"TableName": PT}, label="final-state")]


def run_sequence(oracle: OracleClient, seq: list[dict]) -> tuple[bool, list[dict]]:
    c = {"name": "prop", "area": "property", "steps": _PROP_PRELUDE + seq + _PROP_FINAL, "tables": [PT]}
    r = run_case(oracle, c)
    ok = all(s["verdict"] in ("exact", "alias") for s in r["steps"])
    return ok, r["steps"]


def minimise(oracle: OracleClient, seq: list[dict]) -> list[dict]:
    """Greedy delta-debugging: drop chunks of ops while the sequence still mismatches."""
    chunk = max(1, len(seq) // 2)
    while chunk >= 1:
        i, changed = 0, False
        while i < len(seq):
            trial = seq[:i] + seq[i + chunk:]
            if trial and not run_sequence(oracle, trial)[0]:
                seq, changed = trial, True
            else:
                i += chunk
        if not changed:
            chunk //= 2
    return seq


def run_property(oracle: OracleClient, seeds: int, length: int, max_reports: int = 10) -> dict:
    results, failures = [], []
    steps_total = steps_exact = 0
    for seed in range(seeds):
        seq = gen_sequence(random.Random(seed), length)
        ok, steps = run_sequence(oracle, seq)
        steps_total += len(steps)
        steps_exact += sum(1 for s in steps if s["verdict"] in ("exact", "alias"))
        results.append({"seed": seed, "ok": ok})
        if not ok and len(failures) < max_reports:
            small = minimise(oracle, seq)
            _, msteps = run_sequence(oracle, small)
            failures.append({"seed": seed, "minimised_ops": len(small),
                             "steps": [s for s in msteps if s["verdict"] not in ("exact", "alias")] or msteps,
                             "sequence": [{"op": s["op"], "request": s["p"]} for s in small]})
    passed = sum(1 for r in results if r["ok"])
    return {"seeds": seeds, "length": length, "sequences_matching": passed,
            "sequence_parity_pct": round(100.0 * passed / max(1, seeds), 1),
            "steps_total": steps_total, "steps_exact": steps_exact,
            "step_parity_pct": round(100.0 * steps_exact / max(1, steps_total), 1),
            "failures": failures}


# ── report ─────────────────────────────────────────────────────────────────
def _counts(verdicts: list[str]) -> dict:
    n = len(verdicts)
    c = {v: verdicts.count(v) for v in ("exact", "alias", "message", "mismatch", "oracle-gap")}
    scored = n - c["oracle-gap"]
    match = c["exact"] + c["alias"]
    return {"total": n, **c, "scored": scored,
            "parity_pct": round(100.0 * match / max(1, scored), 1),
            "semantic_parity_pct": round(100.0 * (match + c["message"]) / max(1, scored), 1)}


def summarise(case_results: list[dict]) -> dict:
    steps = [s for c in case_results for s in c["steps"]]
    areas: dict = {}
    for c in case_results:
        a = areas.setdefault(c["area"], {"cases": 0, "match": 0})
        a["cases"] += 1
        a["match"] += c["verdict"] in ("exact", "alias")
    return {"cases": _counts([c["verdict"] for c in case_results]),
            "steps": _counts([s["verdict"] for s in steps]), "by_area": areas}


def _md_json(o: Any) -> str:
    s = json.dumps(o, sort_keys=True, ensure_ascii=False)
    return s if len(s) <= 600 else s[:600] + " …"


def write_report(out_dir: str, summary: dict, cases: list[dict], prop: dict | None, meta: dict) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    jpath = os.path.join(out_dir, "ddb_parity_report.json")
    mpath = os.path.join(out_dir, "ddb_parity_report.md")
    def shrink(o: Any) -> Any:          # keep the report small: elide huge payload strings
        if isinstance(o, str) and len(o) > 512:
            return o[:64] + f"…<{len(o)} chars>"
        if isinstance(o, dict):
            return {k: shrink(v) for k, v in o.items()}
        if isinstance(o, list):
            return [shrink(v) for v in o]
        return o
    with open(jpath, "w") as f:
        compact = [{"name": c["name"], "area": c["area"], "verdict": c["verdict"], "steps_total": len(c["steps"]),
                    "steps": [{"index": i, **x} for i, x in enumerate(c["steps"]) if x["verdict"] != "exact"]}
                   for c in cases]   # every case's verdict; request + both responses only where they differ
        json.dump(shrink({"meta": meta, "summary": summary, "property": prop, "cases": compact}), f, indent=1, sort_keys=True)
    L = [f"# DynamoDB differential parity — Vyomi core vs DynamoDB Local", "",
         f"- oracle: `{meta['oracle']}`  ", f"- generated: {meta['generated']}  ",
         f"- core: `core/dynamodb_core.py` + `core/dynamodb_expr.py` (InMemoryNoSqlStore)", "",
         "## Summary", "",
         "| suite | total | exact | alias | message-only | mismatch | oracle-gap | parity % | semantic % |",
         "|---|---|---|---|---|---|---|---|---|"]
    for label, k in (("hand-written cases", "cases"), ("hand-written steps (responses)", "steps")):
        v = summary[k]
        L.append(f"| {label} | {v['total']} | {v['exact']} | {v['alias']} | {v['message']} | {v['mismatch']} | "
                 f"{v['oracle-gap']} | {v['parity_pct']} | {v['semantic_parity_pct']} |")
    if prop:
        L.append(f"| random sequences ({prop['seeds']} × {prop['length']} ops) | {prop['seeds']} | {prop['sequences_matching']} "
                 f"| – | – | {prop['seeds'] - prop['sequences_matching']} | – | {prop['sequence_parity_pct']} | – |")
        L.append(f"| random-sequence steps | {prop['steps_total']} | {prop['steps_exact']} | – | – | "
                 f"{prop['steps_total'] - prop['steps_exact']} | – | {prop['step_parity_pct']} | – |")
    L += ["", "*exact* = identical normalised status + body. *alias* = identical except an error wording/code where "
          "DynamoDB Local is known to differ from the real service and the core keeps the real wording (see "
          "`ORACLE_WORDING`). *message-only* = same status and error `__type`, different human-readable message. "
          "*oracle-gap* = DynamoDB Local does not implement the operation (excluded from %). Normalisation drops request ids, timestamps, ItemCount/TableSizeBytes "
          "(eventually consistent in real DynamoDB), ARN region/account, set/scan/batch ordering and numeric spelling "
          "(`1.50` ≡ `1.5`); it never hides a value difference.", "", "## By area", "", "| area | cases | matching |", "|---|---|---|"]
    for a, v in sorted(summary["by_area"].items()):
        L.append(f"| {a} | {v['cases']} | {v['match']} |")
    L += ["", "## Non-exact hand-written cases", ""]
    for c in cases:
        if c["verdict"] == "exact":
            continue
        L.append(f"### `{c['name']}` — {c['verdict']} ({c['area']})")
        for s in c["steps"]:
            if s["verdict"] == "exact":
                continue
            L.append(f"- **{s['op']}** ({s['verdict']})")
            L.append(f"  - request: `{_md_json(s['request'])}`")
            L.append(f"  - core:   `{_md_json(s['core'])}`")
            L.append(f"  - oracle: `{_md_json(s['oracle'])}`")
            for d in s["diff"][:6]:
                L.append(f"  - diff: {d}")
        L.append("")
    if prop and prop["failures"]:
        L += ["## Random-sequence failures (minimised)", ""]
        for f_ in prop["failures"]:
            L.append(f"### seed {f_['seed']} — minimised to {f_['minimised_ops']} op(s)")
            for o in f_["sequence"]:
                L.append(f"- `{o['op']}` `{_md_json(o['request'])}`")
            for s in f_["steps"]:
                L.append(f"- mismatch at **{s['op']}**: " + "; ".join(s["diff"][:4]))
            L.append("")
    with open(mpath, "w") as f:
        f.write("\n".join(L) + "\n")
    return mpath, jpath


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--endpoint", default=os.environ.get("DDB_ORACLE_URL", "http://127.0.0.1:8123"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "reports"))
    ap.add_argument("--seeds", type=int, default=60)
    ap.add_argument("--length", type=int, default=25)
    ap.add_argument("--only", default="", help="comma-separated case names")
    ap.add_argument("--wipe-oracle", action="store_true", help="delete every table in the oracle before running")
    ap.add_argument("--min-parity", type=float, default=None,
                    help="fail (exit 1) if the hand-written step parity %% (exact+alias) is below this")
    a = ap.parse_args(argv)
    oracle = OracleClient(a.endpoint)
    st_, body = oracle.call("ListTables", {})
    if st_ != 200:
        print(f"oracle not reachable at {a.endpoint}: {st_} {body}", file=sys.stderr)
        return 2
    if body.get("TableNames"):
        if not a.wipe_oracle:
            print(f"oracle at {a.endpoint} is not empty ({len(body['TableNames'])} tables): use a dedicated "
                  "DynamoDB Local, or pass --wipe-oracle to delete its tables first", file=sys.stderr)
            return 2
        oracle.reset(body["TableNames"])
    _build_cases()
    only = {x for x in a.only.split(",") if x}
    results = [run_case(oracle, c) for c in CASES if not only or c["name"] in only]
    summary = summarise(results)
    prop = run_property(oracle, a.seeds, a.length) if a.seeds > 0 else None
    meta = {"oracle": f"amazon/dynamodb-local @ {a.endpoint}", "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    mpath, jpath = write_report(a.out, summary, results, prop, meta)
    print(json.dumps({"summary": {k: v for k, v in summary.items() if k != "by_area"},
                      "property": {k: v for k, v in (prop or {}).items() if k != "failures"}}, indent=1))
    for c in results:
        if c["verdict"] != "exact":
            print(f"  {c['verdict']:8s} {c['name']}")
    print(f"report: {mpath}\n        {jpath}")
    if a.min_parity is not None and summary["steps"]["parity_pct"] < a.min_parity:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
