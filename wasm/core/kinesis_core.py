# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Kinesis Data Streams core — substrate-independent stream data plane.

Speaks the native **Kinesis JSON 1.1 protocol** (X-Amz-Target `Kinesis_20131202.<Op>`,
JSON body) so unmodified AWS SDKs (boto3, Java v2, Go v2) and the `aws kinesis` CLI work
against it. NO fastapi / boto3 / socket imports → loads under Pyodide, so the same code
runs in the offline appliance and in Nano.

Model: a stream owns an ordered list of shards (hash-key ranges over the 128-bit MD5
space). PutRecord routes a partition key to the shard whose range contains its MD5 hash
(or an ExplicitHashKey), assigns a monotonically increasing 56-digit sequence number and
appends to the shard log. GetShardIterator/GetRecords read the log by position, sequence
number or timestamp. SplitShard / MergeShards / UpdateShardCount close parent shards and
open children exactly like the real service (parent shards stay readable until drained).

State lives on `store.streams` (plain JSON-safe dicts; record payloads are kept as the
base64 text the wire carries) so every store seam — in-memory, file-backed, the Nano
registry/IndexedDB persister — can snapshot it. After each mutation the core calls
`store.persist()` when the store has one.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass, field

REGION = "us-east-1"
DEFAULT_ACCOUNT_ID = "000000000000"
MAX_HASH = (1 << 128) - 1
SHARD_LIMIT = 500
DEFAULT_METRICS = []
ALL_METRICS = ["IncomingBytes", "IncomingRecords", "OutgoingBytes", "OutgoingRecords",
               "WriteProvisionedThroughputExceeded", "ReadProvisionedThroughputExceeded",
               "IteratorAgeMilliseconds"]
_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


class KinesisStore:
    """Plain-data store seam (public attrs are what nano_persist snapshots)."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.account_id = account_id
        self.streams: dict = {}
        self.policies: dict = {}      # resource ARN -> policy document (JSON text)
        self.seq: dict = {"n": 0}     # global monotonic counter (sequence numbers)

    def persist(self) -> None:      # overridden by file-backed substrates
        pass


@dataclass
class KinesisResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class _E(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now() -> float:
    return round(time.time(), 3)


def _store_streams(store) -> dict:
    if getattr(store, "streams", None) is None:
        store.streams = {}
    return store.streams


def _account(store) -> str:
    return getattr(store, "account_id", DEFAULT_ACCOUNT_ID)


def _arn(store, name: str) -> str:
    return f"arn:aws:kinesis:{REGION}:{_account(store)}:stream/{name}"


def _persist(store) -> None:
    fn = getattr(store, "persist", None)
    if callable(fn):
        fn()


def _next_seq(store, shard_num: int) -> str:
    seqd = getattr(store, "seq", None)
    if seqd is None:
        seqd = store.seq = {"n": 0}
    seqd["n"] += 1
    ts_ms = int(time.time() * 1000)
    return f"49{shard_num % 100:02d}{ts_ms:013d}{seqd['n']:039d}"[:56]


# ── stream / shard helpers ────────────────────────────────────────────────
def _resolve(store, p: dict) -> dict:
    """Find the stream a request names via StreamName and/or StreamARN."""
    streams = _store_streams(store)
    name = p.get("StreamName")
    arn = p.get("StreamARN")
    if not name and arn:
        m = re.match(r"^arn:aws[a-z-]*:kinesis:[^:]*:[^:]*:stream/(.+)$", str(arn))
        if not m:
            raise _E("InvalidArgumentException", f"Invalid StreamARN: {arn}")
        name = m.group(1)
    if not name:
        raise _E("InvalidArgumentException", "Either StreamName or StreamARN must be provided.")
    s = streams.get(name)
    if s is None:
        raise _E("ResourceNotFoundException", f"Stream {name} under account {_account(store)} not found.")
    return s


def _new_shard(stream: dict, start: int, end: int, parent=None, adjacent=None) -> dict:
    idx = stream["next_shard"]
    stream["next_shard"] = idx + 1
    sh = {"id": f"shardId-{idx:012d}", "num": idx, "start": str(start), "end": str(end),
          "seq_start": _seq_floor(idx), "seq_end": None, "parent": parent, "adjacent": adjacent,
          "closed": False, "records": []}
    stream["shards"].append(sh)
    return sh


def _seq_floor(idx: int) -> str:
    return f"49{idx % 100:02d}{int(time.time() * 1000):013d}{0:039d}"[:56]


def _ranges(n: int):
    step = (MAX_HASH + 1) // n
    for i in range(n):
        yield i * step, ((i + 1) * step - 1 if i < n - 1 else MAX_HASH)


def _open_shards(stream: dict) -> list:
    return [s for s in stream["shards"] if not s["closed"]]


def _close(shard: dict) -> None:
    shard["closed"] = True
    shard["seq_end"] = shard["records"][-1]["seq"] if shard["records"] else shard["seq_start"]


def _shard_view(sh: dict) -> dict:
    out = {"ShardId": sh["id"],
           "HashKeyRange": {"StartingHashKey": sh["start"], "EndingHashKey": sh["end"]},
           "SequenceNumberRange": {"StartingSequenceNumber": sh["seq_start"]}}
    if sh["seq_end"]:
        out["SequenceNumberRange"]["EndingSequenceNumber"] = sh["seq_end"]
    if sh.get("parent"):
        out["ParentShardId"] = sh["parent"]
    if sh.get("adjacent"):
        out["AdjacentParentShardId"] = sh["adjacent"]
    return out


def _mode(stream: dict) -> dict:
    return {"StreamMode": stream["mode"]}


def _enhanced(stream: dict) -> list:
    return [{"ShardLevelMetrics": list(stream["metrics"])}]


def _find_shard(stream: dict, shard_id: str) -> dict:
    for sh in stream["shards"]:
        if sh["id"] == shard_id:
            return sh
    raise _E("ResourceNotFoundException",
             f"Shard {shard_id} in stream {stream['name']} under account {stream['account']} does not exist.")


def _check_name(name) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise _E("InvalidArgumentException",
                 f"1 validation error detected: Value '{name}' at 'streamName' failed to satisfy constraint: "
                 "Member must satisfy regular expression pattern: [a-zA-Z0-9_.-]+")
    return name


# ── stream lifecycle ──────────────────────────────────────────────────────
def create_stream(store, p):
    name = _check_name(p.get("StreamName"))
    streams = _store_streams(store)
    if name in streams:
        raise _E("ResourceInUseException", f"Stream {name} under account {_account(store)} already exists.")
    mode = (p.get("StreamModeDetails") or {}).get("StreamMode", "PROVISIONED")
    if mode not in ("PROVISIONED", "ON_DEMAND"):
        raise _E("InvalidArgumentException", f"Invalid StreamMode: {mode}")
    n = p.get("ShardCount")
    if mode == "ON_DEMAND":
        n = 4 if n is None else n
    elif n is None:
        raise _E("InvalidArgumentException", "ShardCount must be specified for PROVISIONED streams.")
    n = int(n)
    if n < 1:
        raise _E("InvalidArgumentException", "ShardCount must be at least 1.")
    in_use = sum(len(_open_shards(s)) for s in streams.values())
    if in_use + n > SHARD_LIMIT:
        raise _E("LimitExceededException",
                 f"This request would exceed the shard limit for the account {_account(store)} in {REGION}.")
    st = {"name": name, "arn": _arn(store, name), "account": _account(store), "status": "ACTIVE",
          "mode": mode, "retention": 24, "created": _now(), "encryption": "NONE", "key_id": None,
          "shards": [], "next_shard": 0, "metrics": [], "tags": dict(p.get("Tags") or {}),
          "consumers": {}}
    for lo, hi in _ranges(n):
        _new_shard(st, lo, hi)
    streams[name] = st
    _persist(store)
    return {}


def delete_stream(store, p):
    st = _resolve(store, p)
    if st["consumers"] and not p.get("EnforceConsumerDeletion"):
        raise _E("ResourceInUseException",
                 f"Stream {st['name']} under account {st['account']} has registered consumers; "
                 "set EnforceConsumerDeletion to delete.")
    del _store_streams(store)[st["name"]]
    getattr(store, "policies", {}).pop(st["arn"], None)
    _persist(store)
    return {}


def describe_stream(store, p):
    st = _resolve(store, p)
    shards = st["shards"]
    start = p.get("ExclusiveStartShardId")
    if start:
        ids = [s["id"] for s in shards]
        shards = shards[ids.index(start) + 1:] if start in ids else []
    limit = int(p.get("Limit") or 100)
    page, more = shards[:limit], len(shards) > limit
    return {"StreamDescription": {
        "StreamName": st["name"], "StreamARN": st["arn"], "StreamStatus": st["status"],
        "StreamModeDetails": _mode(st), "Shards": [_shard_view(s) for s in page],
        "HasMoreShards": more, "RetentionPeriodHours": st["retention"],
        "StreamCreationTimestamp": st["created"], "EnhancedMonitoring": _enhanced(st),
        "EncryptionType": st["encryption"], **({"KeyId": st["key_id"]} if st["key_id"] else {})}}


def describe_stream_summary(store, p):
    st = _resolve(store, p)
    return {"StreamDescriptionSummary": {
        "StreamName": st["name"], "StreamARN": st["arn"], "StreamStatus": st["status"],
        "StreamModeDetails": _mode(st), "RetentionPeriodHours": st["retention"],
        "StreamCreationTimestamp": st["created"], "EnhancedMonitoring": _enhanced(st),
        "EncryptionType": st["encryption"], **({"KeyId": st["key_id"]} if st["key_id"] else {}),
        "OpenShardCount": len(_open_shards(st)), "ConsumerCount": len(st["consumers"])}}


def list_streams(store, p):
    names = sorted(_store_streams(store))
    start = p.get("ExclusiveStartStreamName")
    if start:
        names = [n for n in names if n > start]
    limit = int(p.get("Limit") or 100)
    page = names[:limit]
    streams = _store_streams(store)
    return {"StreamNames": page, "HasMoreStreams": len(names) > limit,
            "StreamSummaries": [{"StreamName": n, "StreamARN": streams[n]["arn"],
                                 "StreamStatus": streams[n]["status"],
                                 "StreamModeDetails": _mode(streams[n]),
                                 "StreamCreationTimestamp": streams[n]["created"]} for n in page]}


def list_shards(store, p):
    token = p.get("NextToken")
    if token:
        try:
            p = {**p, **json.loads(base64.b64decode(token).decode())}
        except Exception:
            raise _E("InvalidArgumentException", "Invalid NextToken.")
    st = _resolve(store, p)
    shards = list(st["shards"])
    flt = p.get("ShardFilter") or {}
    ftype = flt.get("Type")
    if ftype == "AT_LATEST":
        shards = _open_shards(st)
    elif ftype == "AFTER_SHARD_ID":
        ids = [s["id"] for s in shards]
        sid = flt.get("ShardId")
        shards = shards[ids.index(sid) + 1:] if sid in ids else []
    elif ftype in ("FROM_TRIM_HORIZON", "AT_TRIM_HORIZON"):
        pass
    start = p.get("ExclusiveStartShardId")
    if start:
        ids = [s["id"] for s in shards]
        shards = shards[ids.index(start) + 1:] if start in ids else []
    limit = int(p.get("MaxResults") or 1000)
    page = shards[:limit]
    out = {"Shards": [_shard_view(s) for s in page]}
    if len(shards) > limit:
        out["NextToken"] = base64.b64encode(json.dumps(
            {"StreamName": st["name"], "ExclusiveStartShardId": page[-1]["id"]}).encode()).decode()
    return out


def update_shard_count(store, p):
    st = _resolve(store, p)
    target = int(p.get("TargetShardCount") or 0)
    if p.get("ScalingType", "UNIFORM_SCALING") != "UNIFORM_SCALING":
        raise _E("InvalidArgumentException", "ScalingType must be UNIFORM_SCALING.")
    if st["mode"] == "ON_DEMAND":
        raise _E("ValidationException", "UpdateShardCount is not supported for ON_DEMAND streams.")
    cur = len(_open_shards(st))
    if target < 1:
        raise _E("InvalidArgumentException", "TargetShardCount must be at least 1.")
    if target > cur * 2 or target * 2 < cur:
        raise _E("InvalidArgumentException",
                 f"UpdateShardCount cannot scale from {cur} to {target}: the target must be between "
                 f"{(cur + 1) // 2} and {cur * 2}.")
    old = _open_shards(st)
    for sh in old:
        _close(sh)
    for lo, hi in _ranges(target):
        parents = [o for o in old if int(o["start"]) <= hi and int(o["end"]) >= lo]
        _new_shard(st, lo, hi, parents[0]["id"] if parents else None,
                   parents[1]["id"] if len(parents) > 1 else None)
    _persist(store)
    return {"StreamName": st["name"], "StreamARN": st["arn"], "CurrentShardCount": cur,
            "TargetShardCount": target}


def split_shard(store, p):
    st = _resolve(store, p)
    sh = _find_shard(st, p.get("ShardToSplit", ""))
    if sh["closed"]:
        raise _E("InvalidArgumentException", f"Shard {sh['id']} is already closed.")
    try:
        mid = int(p.get("NewStartingHashKey"))
    except (TypeError, ValueError):
        raise _E("InvalidArgumentException", "NewStartingHashKey must be a decimal integer.")
    lo, hi = int(sh["start"]), int(sh["end"])
    if not lo < mid <= hi:
        raise _E("InvalidArgumentException",
                 f"NewStartingHashKey {mid} is outside the hash key range of {sh['id']}.")
    _close(sh)
    _new_shard(st, lo, mid - 1, sh["id"])
    _new_shard(st, mid, hi, sh["id"])
    _persist(store)
    return {}


def merge_shards(store, p):
    st = _resolve(store, p)
    a = _find_shard(st, p.get("ShardToMerge", ""))
    b = _find_shard(st, p.get("AdjacentShardToMerge", ""))
    if a["closed"] or b["closed"]:
        raise _E("InvalidArgumentException", "Both shards must be open to be merged.")
    lo, hi = sorted([a, b], key=lambda s: int(s["start"]))
    if int(lo["end"]) + 1 != int(hi["start"]):
        raise _E("InvalidArgumentException", f"Shards {a['id']} and {b['id']} are not adjacent.")
    _close(a)
    _close(b)
    _new_shard(st, int(lo["start"]), int(hi["end"]), lo["id"], hi["id"])
    _persist(store)
    return {}


# ── records ───────────────────────────────────────────────────────────────
def _hash_of(pk: str) -> int:
    return int(hashlib.md5(pk.encode("utf-8")).hexdigest(), 16)


def _target_shard(st: dict, pk: str, explicit) -> dict:
    if explicit is not None:
        try:
            h = int(explicit)
        except (TypeError, ValueError):
            raise _E("InvalidArgumentException", "ExplicitHashKey must be a decimal integer.")
        if not 0 <= h <= MAX_HASH:
            raise _E("InvalidArgumentException", "ExplicitHashKey out of range.")
    else:
        h = _hash_of(pk)
    for sh in _open_shards(st):
        if int(sh["start"]) <= h <= int(sh["end"]):
            return sh
    raise _E("InternalFailure", "No open shard covers the hash key.", 500)


def _append(store, st: dict, data, pk, explicit) -> tuple[dict, dict]:
    if not isinstance(pk, str) or not 1 <= len(pk) <= 256:
        raise _E("InvalidArgumentException", "PartitionKey must be between 1 and 256 characters.")
    if data is None:
        raise _E("InvalidArgumentException", "Data is required.")
    try:
        raw = base64.b64decode(data, validate=False)
    except Exception:
        raise _E("SerializationException", "Data must be base64-encoded.")
    if len(raw) > 1024 * 1024:
        raise _E("InvalidArgumentException", "Data exceeds the 1 MiB record size limit.")
    sh = _target_shard(st, pk, explicit)
    rec = {"seq": _next_seq(store, sh["num"]), "pk": pk, "data": data, "ts": _now(), "size": len(raw)}
    sh["records"].append(rec)
    return sh, rec


def put_record(store, p):
    st = _resolve(store, p)
    sh, rec = _append(store, st, p.get("Data"), p.get("PartitionKey"), p.get("ExplicitHashKey"))
    _persist(store)
    return {"ShardId": sh["id"], "SequenceNumber": rec["seq"], "EncryptionType": st["encryption"]}


def put_records(store, p):
    st = _resolve(store, p)
    entries = p.get("Records") or []
    if not entries or len(entries) > 500:
        raise _E("InvalidArgumentException", "Records must contain between 1 and 500 entries.")
    out, failed = [], 0
    for e in entries:
        try:
            sh, rec = _append(store, st, e.get("Data"), e.get("PartitionKey"), e.get("ExplicitHashKey"))
            out.append({"ShardId": sh["id"], "SequenceNumber": rec["seq"]})
        except _E as ex:
            failed += 1
            out.append({"ErrorCode": ex.code, "ErrorMessage": ex.message})
    _persist(store)
    return {"FailedRecordCount": failed, "Records": out, "EncryptionType": st["encryption"]}


def _enc_iter(stream: str, shard: str, pos: int) -> str:
    return base64.urlsafe_b64encode(f"{stream}|{shard}|{pos}|{_now()}".encode()).decode().rstrip("=")


def _dec_iter(it: str):
    try:
        pad = "=" * (-len(it) % 4)
        stream, shard, pos, ts = base64.urlsafe_b64decode(it + pad).decode().split("|")
        return stream, shard, int(pos), float(ts)
    except Exception:
        raise _E("InvalidArgumentException", "Invalid ShardIterator.")


def get_shard_iterator(store, p):
    st = _resolve(store, p)
    sh = _find_shard(st, p.get("ShardId", ""))
    typ = p.get("ShardIteratorType")
    recs = sh["records"]
    if typ == "TRIM_HORIZON":
        pos = 0
    elif typ == "LATEST":
        pos = len(recs)
    elif typ in ("AT_SEQUENCE_NUMBER", "AFTER_SEQUENCE_NUMBER"):
        seq = p.get("StartingSequenceNumber")
        if not seq or not str(seq).isdigit():
            raise _E("InvalidArgumentException", "StartingSequenceNumber is required.")
        pos = next((i for i, r in enumerate(recs) if int(r["seq"]) >= int(seq)), len(recs))
        if typ == "AFTER_SEQUENCE_NUMBER" and pos < len(recs) and recs[pos]["seq"] == str(seq):
            pos += 1
    elif typ == "AT_TIMESTAMP":
        t = p.get("Timestamp")
        if t is None:
            raise _E("InvalidArgumentException", "Timestamp is required.")
        pos = next((i for i, r in enumerate(recs) if r["ts"] >= float(t)), len(recs))
    else:
        raise _E("InvalidArgumentException", f"Invalid ShardIteratorType: {typ}")
    return {"ShardIterator": _enc_iter(st["name"], sh["id"], pos)}


def get_records(store, p):
    it = p.get("ShardIterator")
    if not it:
        raise _E("InvalidArgumentException", "ShardIterator is required.")
    name, shard_id, pos, issued = _dec_iter(it)
    if _now() - issued > 300:
        raise _E("ExpiredIteratorException", "Iterator expired. The iterator was created at "
                 f"{issued} while it was used at {_now()}.")
    st = _store_streams(store).get(name)
    if st is None:
        raise _E("ResourceNotFoundException", f"Stream {name} under account {_account(store)} not found.")
    sh = _find_shard(st, shard_id)
    limit = int(p.get("Limit") or 10000)
    if not 1 <= limit <= 10000:
        raise _E("InvalidArgumentException", "Limit must be between 1 and 10000.")
    chunk = sh["records"][pos:pos + limit]
    npos = pos + len(chunk)
    out = {"Records": [{"SequenceNumber": r["seq"], "ApproximateArrivalTimestamp": r["ts"],
                        "Data": r["data"], "PartitionKey": r["pk"], "EncryptionType": st["encryption"]}
                       for r in chunk]}
    drained = npos >= len(sh["records"])
    if sh["closed"] and drained:
        out["NextShardIterator"] = None
        out["ChildShards"] = [
            {"ShardId": c["id"], "ParentShards": [x for x in (c.get("parent"), c.get("adjacent")) if x],
             "HashKeyRange": {"StartingHashKey": c["start"], "EndingHashKey": c["end"]}}
            for c in st["shards"] if sh["id"] in (c.get("parent"), c.get("adjacent"))]
    else:
        out["NextShardIterator"] = _enc_iter(name, shard_id, npos)
    behind = 0 if drained else int(max(0.0, (sh["records"][-1]["ts"] - chunk[-1]["ts"]) * 1000)) if chunk else 0
    out["MillisBehindLatest"] = behind
    return out


# ── retention / encryption / monitoring / mode ────────────────────────────
def increase_retention(store, p):
    st = _resolve(store, p)
    h = int(p.get("RetentionPeriodHours") or 0)
    if h <= st["retention"] or h > 8760:
        raise _E("InvalidArgumentException",
                 f"Requested retention period ({h} hours) must be greater than the current "
                 f"({st['retention']} hours) and at most 8760.")
    st["retention"] = h
    _persist(store)
    return {}


def decrease_retention(store, p):
    st = _resolve(store, p)
    h = int(p.get("RetentionPeriodHours") or 0)
    if h >= st["retention"] or h < 24:
        raise _E("InvalidArgumentException",
                 f"Requested retention period ({h} hours) must be less than the current "
                 f"({st['retention']} hours) and at least 24.")
    st["retention"] = h
    _persist(store)
    return {}


def start_encryption(store, p):
    st = _resolve(store, p)
    if p.get("EncryptionType") != "KMS" or not p.get("KeyId"):
        raise _E("InvalidArgumentException", "EncryptionType KMS and a KeyId are required.")
    st["encryption"], st["key_id"] = "KMS", p["KeyId"]
    _persist(store)
    return {}


def stop_encryption(store, p):
    st = _resolve(store, p)
    st["encryption"], st["key_id"] = "NONE", None
    _persist(store)
    return {}


def _metrics_args(p):
    ms = list(p.get("ShardLevelMetrics") or [])
    if not ms:
        raise _E("InvalidArgumentException", "ShardLevelMetrics must not be empty.")
    bad = [m for m in ms if m != "ALL" and m not in ALL_METRICS]
    if bad:
        raise _E("InvalidArgumentException", f"Invalid shard-level metric: {bad[0]}")
    return ALL_METRICS if "ALL" in ms else ms


def enable_monitoring(store, p):
    st = _resolve(store, p)
    cur, want = list(st["metrics"]), _metrics_args(p)
    st["metrics"] = sorted(set(cur) | set(want), key=ALL_METRICS.index)
    _persist(store)
    return {"StreamName": st["name"], "StreamARN": st["arn"], "CurrentShardLevelMetrics": cur,
            "DesiredShardLevelMetrics": list(st["metrics"])}


def disable_monitoring(store, p):
    st = _resolve(store, p)
    cur, drop = list(st["metrics"]), set(_metrics_args(p))
    st["metrics"] = [m for m in cur if m not in drop]
    _persist(store)
    return {"StreamName": st["name"], "StreamARN": st["arn"], "CurrentShardLevelMetrics": cur,
            "DesiredShardLevelMetrics": list(st["metrics"])}


def update_stream_mode(store, p):
    st = _resolve(store, {"StreamARN": p.get("StreamARN")})
    mode = (p.get("StreamModeDetails") or {}).get("StreamMode")
    if mode not in ("PROVISIONED", "ON_DEMAND"):
        raise _E("InvalidArgumentException", f"Invalid StreamMode: {mode}")
    st["mode"] = mode
    _persist(store)
    return {}


def describe_limits(store, p):
    streams = _store_streams(store)
    open_n = sum(len(_open_shards(s)) for s in streams.values())
    return {"ShardLimit": SHARD_LIMIT, "OpenShardCount": open_n,
            "OnDemandStreamCount": sum(1 for s in streams.values() if s["mode"] == "ON_DEMAND"),
            "OnDemandStreamCountLimit": 10}


# ── tags ──────────────────────────────────────────────────────────────────
def _tag_list(tags: dict) -> list:
    return [{"Key": k, "Value": v} for k, v in sorted(tags.items())]


def add_tags(store, p):
    st = _resolve(store, p)
    tags = p.get("Tags") or {}
    if len(st["tags"]) + len([k for k in tags if k not in st["tags"]]) > 50:
        raise _E("InvalidArgumentException", "A stream can have at most 50 tags.")
    st["tags"].update({str(k): str(v) for k, v in tags.items()})
    _persist(store)
    return {}


def remove_tags(store, p):
    st = _resolve(store, p)
    for k in p.get("TagKeys") or []:
        st["tags"].pop(k, None)
    _persist(store)
    return {}


def list_tags(store, p):
    st = _resolve(store, p)
    items = _tag_list(st["tags"])
    start = p.get("ExclusiveStartTagKey")
    if start:
        items = [t for t in items if t["Key"] > start]
    limit = int(p.get("Limit") or 50)
    return {"Tags": items[:limit], "HasMoreTags": len(items) > limit}


def _by_arn(store, arn) -> dict:
    return _resolve(store, {"StreamARN": arn})


def tag_resource(store, p):
    return add_tags(store, {"StreamName": _by_arn(store, p.get("ResourceARN"))["name"], "Tags": p.get("Tags")})


def untag_resource(store, p):
    return remove_tags(store, {"StreamName": _by_arn(store, p.get("ResourceARN"))["name"],
                               "TagKeys": p.get("TagKeys")})


def list_tags_for_resource(store, p):
    return {"Tags": _tag_list(_by_arn(store, p.get("ResourceARN"))["tags"])}


# ── enhanced fan-out consumers ────────────────────────────────────────────
def register_consumer(store, p):
    st = _by_arn(store, p.get("StreamARN"))
    name = p.get("ConsumerName")
    if not name or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", name):
        raise _E("InvalidArgumentException", "Invalid ConsumerName.")
    if name in st["consumers"]:
        raise _E("ResourceInUseException", f"Consumer {name} under stream {st['name']} already exists.")
    if len(st["consumers"]) >= 20:
        raise _E("LimitExceededException", "A stream can have at most 20 registered consumers.")
    ts = _now()
    c = {"name": name, "arn": f"{st['arn']}/consumer/{name}:{int(ts)}", "status": "ACTIVE", "created": ts}
    st["consumers"][name] = c
    _persist(store)
    return {"Consumer": _consumer_view(c)}


def _consumer_view(c: dict) -> dict:
    return {"ConsumerName": c["name"], "ConsumerARN": c["arn"], "ConsumerStatus": c["status"],
            "ConsumerCreationTimestamp": c["created"]}


def _find_consumer(store, p):
    st = None
    if p.get("StreamARN"):
        st = _by_arn(store, p["StreamARN"])
    cands = [st] if st else list(_store_streams(store).values())
    for s in cands:
        for c in s["consumers"].values():
            if c["arn"] == p.get("ConsumerARN") or (st and c["name"] == p.get("ConsumerName")):
                return s, c
    raise _E("ResourceNotFoundException", f"Consumer {p.get('ConsumerName') or p.get('ConsumerARN')} not found.")


def deregister_consumer(store, p):
    st, c = _find_consumer(store, p)
    del st["consumers"][c["name"]]
    _persist(store)
    return {}


def describe_consumer(store, p):
    st, c = _find_consumer(store, p)
    return {"ConsumerDescription": {**_consumer_view(c), "StreamARN": st["arn"]}}


def list_consumers(store, p):
    st = _by_arn(store, p.get("StreamARN"))
    cs = sorted(st["consumers"].values(), key=lambda c: c["created"])
    return {"Consumers": [_consumer_view(c) for c in cs]}


# ── resource policy ───────────────────────────────────────────────────────
def put_policy(store, p):
    st = _by_arn(store, p.get("ResourceARN"))
    try:
        json.loads(p.get("Policy") or "")
    except Exception:
        raise _E("InvalidArgumentException", "Policy must be a valid JSON document.")
    if getattr(store, "policies", None) is None:
        store.policies = {}
    store.policies[st["arn"]] = p["Policy"]
    _persist(store)
    return {}


def get_policy(store, p):
    st = _by_arn(store, p.get("ResourceARN"))
    return {"Policy": (getattr(store, "policies", None) or {}).get(st["arn"], "{}")}


def delete_policy(store, p):
    st = _by_arn(store, p.get("ResourceARN"))
    (getattr(store, "policies", None) or {}).pop(st["arn"], None)
    _persist(store)
    return {}


_OPS = {
    "CreateStream": create_stream, "DeleteStream": delete_stream,
    "DescribeStream": describe_stream, "DescribeStreamSummary": describe_stream_summary,
    "ListStreams": list_streams, "ListShards": list_shards,
    "UpdateShardCount": update_shard_count, "SplitShard": split_shard, "MergeShards": merge_shards,
    "PutRecord": put_record, "PutRecords": put_records,
    "GetShardIterator": get_shard_iterator, "GetRecords": get_records,
    "IncreaseStreamRetentionPeriod": increase_retention, "DecreaseStreamRetentionPeriod": decrease_retention,
    "StartStreamEncryption": start_encryption, "StopStreamEncryption": stop_encryption,
    "EnableEnhancedMonitoring": enable_monitoring, "DisableEnhancedMonitoring": disable_monitoring,
    "UpdateStreamMode": update_stream_mode, "DescribeLimits": describe_limits,
    "AddTagsToStream": add_tags, "RemoveTagsFromStream": remove_tags, "ListTagsForStream": list_tags,
    "TagResource": tag_resource, "UntagResource": untag_resource,
    "ListTagsForResource": list_tags_for_resource,
    "RegisterStreamConsumer": register_consumer, "DeregisterStreamConsumer": deregister_consumer,
    "DescribeStreamConsumer": describe_consumer, "ListStreamConsumers": list_consumers,
    "PutResourcePolicy": put_policy, "GetResourcePolicy": get_policy, "DeleteResourcePolicy": delete_policy,
}
OPERATIONS = sorted(_OPS)


def dispatch(store, target: str, payload: dict | None = None) -> KinesisResponse:
    """Native Kinesis JSON router. `target` is the X-Amz-Target header,
    e.g. "Kinesis_20131202.PutRecord"."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = _OPS.get(action)
    if op is None:
        return KinesisResponse(status=400, body={"__type": "UnknownOperationException",
                                                 "message": f"Unknown operation {action}."})
    try:
        return KinesisResponse(body=op(store, body))
    except _E as e:
        return KinesisResponse(status=e.status, body={"__type": e.code, "message": e.message})


# ── console facade (friendly JSON for the console grid; same store, same core) ──
def _created_iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def console_row(store, st: dict) -> dict:
    open_n = len(_open_shards(st))
    return {
        "name": st["name"], "arn": st["arn"], "status": st["status"],
        "capacity_mode": "On-demand" if st["mode"] == "ON_DEMAND" else "Provisioned",
        "open_shards": open_n, "retention": f"{st['retention']} hours",
        "retention_hours": st["retention"],
        "encryption": "KMS" if st["encryption"] == "KMS" else "Disabled",
        "key_id": st["key_id"] or "alias/aws/kinesis",
        "consumers": len(st["consumers"]), "created": _created_iso(st["created"]),
        "region": REGION, "records": sum(len(s["records"]) for s in st["shards"]),
        "monitoring": ", ".join(st["metrics"]) if st["metrics"] else "Basic (stream-level)",
        "tags": dict(st["tags"]),
        "shards": [{"shard_id": s["id"], "state": "Closed" if s["closed"] else "Open",
                    "starting_hash_key": s["start"], "ending_hash_key": s["end"],
                    "records": len(s["records"])} for s in st["shards"]],
        "consumer_list": [_consumer_view(c) for c in st["consumers"].values()],
    }


def console_list(store) -> dict:
    rows = [console_row(store, s) for s in _store_streams(store).values()]
    return {"ok": True, "items": rows, "count": len(rows)}


def console_create(store, body: dict) -> dict:
    name = str(body.get("name") or body.get("StreamName") or "").strip()
    mode = "ON_DEMAND" if str(body.get("capacity_mode") or body.get("mode") or "").lower().replace("-", "_") in (
        "on_demand", "ondemand") else "PROVISIONED"
    req = {"StreamName": name, "StreamModeDetails": {"StreamMode": mode}}
    if mode == "PROVISIONED":
        req["ShardCount"] = int(body.get("shard_count") or body.get("shards") or 1)
    r = dispatch(store, "Kinesis_20131202.CreateStream", req)
    if r.status >= 400:
        return {"ok": False, "code": r.body.get("__type"), "detail": r.body.get("message"), "status": r.status}
    st = _store_streams(store)[name]
    hours = int(body.get("retention_hours") or 24)
    if hours != 24:
        dispatch(store, "Kinesis_20131202.IncreaseStreamRetentionPeriod",
                 {"StreamName": name, "RetentionPeriodHours": hours})
    return {"ok": True, **console_row(store, st)}


def console_get(store, name: str) -> dict:
    st = _store_streams(store).get(name)
    return {"ok": True, **console_row(store, st)} if st else \
        {"ok": False, "code": "ResourceNotFoundException", "status": 404}


def console_update(store, name: str, body: dict) -> dict:
    """Console Save actions: tags (replace the set) and retention period."""
    st = _store_streams(store).get(name)
    if st is None:
        return {"ok": False, "code": "ResourceNotFoundException", "status": 404}
    if isinstance(body.get("tags"), dict):
        st["tags"] = {str(k): str(v) for k, v in body["tags"].items() if k}
    if body.get("retention_hours") is not None:
        h = int(body["retention_hours"])
        op = "IncreaseStreamRetentionPeriod" if h > st["retention"] else "DecreaseStreamRetentionPeriod"
        if h != st["retention"]:
            r = dispatch(store, "Kinesis_20131202." + op, {"StreamName": name, "RetentionPeriodHours": h})
            if r.status >= 400:
                return {"ok": False, "code": r.body.get("__type"), "detail": r.body.get("message"), "status": r.status}
    _persist(store)
    return console_get(store, name)


def console_delete(store, name: str) -> dict:
    r = dispatch(store, "Kinesis_20131202.DeleteStream", {"StreamName": name, "EnforceConsumerDeletion": True})
    return {"ok": r.status < 400, "name": name, "code": r.body.get("__type"), "status": r.status}
