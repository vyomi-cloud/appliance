"""ElastiCache core — substrate-independent engine for the AWS ElastiCache API.

Targets the NATIVE ElastiCache wire — the **Query protocol** (form-encoded
`Action=CreateCacheCluster&Version=2015-02-02&...`, XML responses in
http://elasticache.amazonaws.com/doc/2015-02-02/) — so an unmodified boto3 /
aws-cli / aws-sdk-java-v2 / aws-sdk-go-v2 client works with only the endpoint
overridden. Request / response field names and error codes follow the botocore
model (`elasticache/2015-02-02/service-2.json`).

Pure Python (stdlib only — no fastapi / boto3 / socket), so the SAME file runs on
the offline appliance and in Nano (Pyodide). State lives in an `ElastiCacheStore`
(plain dicts, a `persist()` hook) — the seam the offline appliance backs with the
space-scoped state and Nano backs with its shared store registry.

Data plane: the engine is the API. Every cache node's endpoint points at
`store.endpoint_host:store.endpoint_port` — offline that is the ONE shared Valkey
container (`vyomi-valkey`, BSD-3-Clause; one backend for ElastiCache,
Memorystore and Azure Cache) so `redis-cli`/`valkey-cli` really talks to it; in
Nano (no sockets) the control plane runs alone and the console says so.

Operations: Create/Describe/Modify/Delete/Reboot CacheCluster, Create/Describe/
Modify/Delete ReplicationGroup, CacheSubnetGroup + CacheParameterGroup CRUD,
DescribeCacheParameters, Create/Describe/Delete Snapshot, Add/Remove/List tags,
DescribeCacheEngineVersions, DescribeEvents.

The `console_*` helpers at the bottom are the flat REST view the web consoles use
(`/api/aws/elasticache/...`), shared by the offline server and Nano.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

NS = "http://elasticache.amazonaws.com/doc/2015-02-02/"
DEFAULT_ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
DEFAULT_PORT = 6379

# Engines → supported versions (newest first) and parameter-group families.
ENGINE_VERSIONS = {
    "valkey": [("8.0", "valkey8"), ("7.2", "valkey7")],
    "redis": [("7.1", "redis7"), ("7.0", "redis7"), ("6.2", "redis6.x"), ("6.0", "redis6.x")],
    "memcached": [("1.6.22", "memcached1.6"), ("1.6.17", "memcached1.6")],
}
DEFAULT_VERSION = {"valkey": "8.0", "redis": "7.1", "memcached": "1.6.22"}
NODE_TYPES = {  # cache node type → (vCPU, memory GiB); also the price table key
    "cache.t3.micro": (2, 0.5), "cache.t3.small": (2, 1.37), "cache.t3.medium": (2, 3.09),
    "cache.t4g.micro": (2, 0.5), "cache.t4g.small": (2, 1.37), "cache.t4g.medium": (2, 3.09),
    "cache.m5.large": (2, 6.38), "cache.m6g.large": (2, 6.38), "cache.m7g.large": (2, 6.38),
    "cache.r5.large": (2, 13.07), "cache.r6g.large": (2, 13.07), "cache.r7g.large": (2, 13.07),
}
AZS = ["us-east-1a", "us-east-1b", "us-east-1c"]

# Default parameters per family (a representative slice of the real defaults).
_FAMILY_PARAMS = {
    "valkey": [("maxmemory-policy", "volatile-lru", "string", "Max memory policy.", "valkey8"),
               ("timeout", "0", "integer", "Close the connection after a client is idle for N seconds.", "valkey8"),
               ("tcp-keepalive", "300", "integer", "TCP keepalive interval (seconds).", "valkey8"),
               ("databases", "16", "integer", "Number of logical databases.", "valkey8"),
               ("notify-keyspace-events", "", "string", "Keyspace event notifications.", "valkey8")],
    "redis": [("maxmemory-policy", "volatile-lru", "string", "Max memory policy.", "redis7"),
              ("timeout", "0", "integer", "Close the connection after a client is idle for N seconds.", "redis7"),
              ("tcp-keepalive", "300", "integer", "TCP keepalive interval (seconds).", "redis7"),
              ("databases", "16", "integer", "Number of logical databases.", "redis7"),
              ("notify-keyspace-events", "", "string", "Keyspace event notifications.", "redis7")],
    "memcached": [("max_item_size", "1048576", "integer", "Largest item size (bytes).", "memcached1.6"),
                  ("chunk_size", "48", "integer", "Minimum chunk allocation (bytes).", "memcached1.6"),
                  ("maxconns_fast", "1", "boolean", "Close connections instead of queueing.", "memcached1.6")],
}

# Response list fields → the XML member element name (from the botocore model).
_MEMBER = {
    "CacheNodes": "CacheNode", "CacheSecurityGroups": "CacheSecurityGroup",
    "SecurityGroups": "member", "CacheNodeIdsToReboot": "CacheNodeId",
    "MemberClusters": "ClusterId", "NodeGroups": "NodeGroup", "NodeGroupMembers": "NodeGroupMember",
    "TagList": "Tag", "Subnets": "Subnet", "SupportedNetworkTypes": "member",
    "CacheClusters": "CacheCluster", "ReplicationGroups": "ReplicationGroup",
    "CacheSubnetGroups": "CacheSubnetGroup", "CacheParameterGroups": "CacheParameterGroup",
    "Snapshots": "Snapshot", "NodeSnapshots": "NodeSnapshot", "Parameters": "Parameter",
    "CacheNodeTypeSpecificParameters": "CacheNodeTypeSpecificParameter",
    "CacheEngineVersions": "CacheEngineVersion", "Events": "Event",
    "LogDeliveryConfigurations": "LogDeliveryConfiguration",
}
# Fields that are lists but have no value → still emitted as an empty element.
_UNWRAPPED_EMPTY_OK = {"CacheSecurityGroups", "SecurityGroups", "CacheNodes", "TagList"}


@dataclass
class ElastiCacheResponse:
    status: int = 200
    body: str = ""
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class ElastiCacheError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class ElastiCacheStore:
    """State seam: plain dicts the engine reads/writes. Subclass (or replace the
    attributes with proxies) to persist elsewhere; `persist()` is called after
    every mutation."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID, region: str = REGION,
                 endpoint_host: str | None = None, endpoint_port: int = DEFAULT_PORT) -> None:
        self.account_id = account_id
        self.region = region
        self.endpoint_host = endpoint_host      # None → real-shaped *.cache.amazonaws.com names
        self.endpoint_port = endpoint_port
        self.clusters: dict[str, dict] = {}
        self.replication_groups: dict[str, dict] = {}
        self.subnet_groups: dict[str, dict] = {}
        self.parameter_groups: dict[str, dict] = {}
        self.snapshots: dict[str, dict] = {}
        self.tags: dict[str, dict] = {}         # arn → {key: value}
        self.events: list[dict] = []

    def persist(self) -> None:
        pass


# ── helpers ────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return str(uuid.uuid4())


def _arn(store, kind: str, name: str) -> str:
    return f"arn:aws:elasticache:{store.region}:{store.account_id}:{kind}:{name}"


def _short(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:6]


def _az(i: int) -> str:
    return AZS[i % len(AZS)]


def _event(store, source_id: str, source_type: str, message: str) -> None:
    store.events.insert(0, {"SourceIdentifier": source_id, "SourceType": source_type,
                            "Message": message, "Date": _now()})
    del store.events[200:]


def _endpoint(store, ident: str, node_id: str | None = None, shard: str | None = None,
              primary: bool = False) -> dict:
    """Real-shaped hostnames offline-resolvable via store.endpoint_host when set."""
    if store.endpoint_host:
        return {"Address": store.endpoint_host, "Port": store.endpoint_port}
    h = _short(store.account_id, ident)
    region = store.region.replace("-", "").replace("east", "e").replace("west", "w")
    if node_id:
        host = f"{ident}.{h}.{node_id}.{region}.cache.amazonaws.com"
    else:
        host = f"{ident}.{h}.ng.0001.{region}.cache.amazonaws.com" if not primary \
            else f"master.{ident}.{h}.{region}.cache.amazonaws.com"
    return {"Address": host, "Port": store.endpoint_port}


# ── request parameter parsing (Query protocol) ─────────────────────────────
def _collect(params: dict, prefix: str) -> list:
    """`Prefix.<member>.<n>[.Field]` → ordered list of str / dict."""
    rows: dict[int, dict | str] = {}
    pre = prefix + "."
    for k, v in params.items():
        if not k.startswith(pre):
            continue
        parts = k[len(pre):].split(".")
        if parts and not parts[0].isdigit():      # drop the member element name
            parts = parts[1:]
        if not parts or not parts[0].isdigit():
            continue
        n = int(parts[0])
        if len(parts) == 1:
            rows[n] = v
        else:
            d = rows.setdefault(n, {})
            if isinstance(d, dict):
                d[".".join(parts[1:])] = v
    return [rows[i] for i in sorted(rows)]


def _bool(v, default=None):
    if v is None or v == "":
        return default
    return str(v).lower() == "true"


def _int(params: dict, key: str, default=None):
    v = params.get(key)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError:
        raise ElastiCacheError("InvalidParameterValue", f"Invalid value for {key}: {v}.")


def _tags_from(params: dict, prefix: str = "Tags") -> dict:
    out = {}
    for t in _collect(params, prefix):
        if isinstance(t, dict) and t.get("Key") is not None:
            out[t["Key"]] = t.get("Value", "")
    return out


# ── XML serialization ──────────────────────────────────────────────────────
def _x(tag: str, val) -> str:
    if isinstance(val, bool):
        val = "true" if val else "false"
    return f"<{tag}>{_xml_escape(str(val))}</{tag}>"


def _ser(tag: str, val) -> str:
    if val is None:
        return ""
    if isinstance(val, dict):
        return f"<{tag}>" + "".join(_ser(k, v) for k, v in val.items()) + f"</{tag}>"
    if isinstance(val, list):
        m = _MEMBER.get(tag, "member")
        if not val and tag not in _UNWRAPPED_EMPTY_OK:
            return f"<{tag}/>"
        return f"<{tag}>" + "".join(_ser(m, i) for i in val) + f"</{tag}>"
    return _x(tag, val)


def _envelope(action: str, result_inner: str = "") -> ElastiCacheResponse:
    result = f"<{action}Result>{result_inner}</{action}Result>" if result_inner is not None else ""
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{NS}">{result}'
           f'<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata>'
           f'</{action}Response>')
    return ElastiCacheResponse(body=xml)


def _error(code: str, message: str, status: int = 400) -> ElastiCacheResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ErrorResponse xmlns="{NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(code)}</Code>'
           f'<Message>{_xml_escape(message)}</Message></Error>'
           f'<RequestId>{_req_id()}</RequestId></ErrorResponse>')
    return ElastiCacheResponse(status=status, body=xml)


def _page(items: list, params: dict, tag: str, key_of=None):
    """Marker/MaxRecords pagination → (page, marker-xml)."""
    mx = _int(params, "MaxRecords", 100)
    if mx < 20 or mx > 100:
        raise ElastiCacheError("InvalidParameterValue", "MaxRecords must be between 20 and 100.")
    start = int(params.get("Marker") or 0) if str(params.get("Marker") or "0").isdigit() else 0
    page = items[start:start + mx]
    nxt = start + mx
    return page, (_x("Marker", str(nxt)) if nxt < len(items) else "")


# ── views (record → API shape) ─────────────────────────────────────────────
def _cluster_view(store, c: dict, show_node_info: bool = False) -> dict:
    v = {k: c[k] for k in (
        "CacheClusterId", "ClientDownloadLandingPage", "CacheNodeType", "Engine", "EngineVersion",
        "CacheClusterStatus", "NumCacheNodes", "PreferredAvailabilityZone", "CacheClusterCreateTime",
        "PreferredMaintenanceWindow", "PendingModifiedValues", "CacheSecurityGroups",
        "CacheParameterGroup", "CacheSubnetGroupName", "AutoMinorVersionUpgrade", "SecurityGroups",
        "SnapshotRetentionLimit", "SnapshotWindow", "AuthTokenEnabled", "TransitEncryptionEnabled",
        "AtRestEncryptionEnabled", "ARN", "NetworkType", "IpDiscovery") if k in c}
    if c.get("ReplicationGroupId"):
        v["ReplicationGroupId"] = c["ReplicationGroupId"]
        v["ReplicationGroupLogDeliveryEnabled"] = False
    if c["Engine"] == "memcached":
        v["ConfigurationEndpoint"] = _endpoint(store, c["CacheClusterId"])
    if show_node_info or True:   # CacheNodes are always listed (the console shows them)
        v["CacheNodes"] = c["CacheNodes"]
    return v


def _rg_view(store, rg: dict) -> dict:
    members = [store.clusters[m] for m in rg["MemberClusters"] if m in store.clusters]
    nodes = []
    for i, m in enumerate(members):
        nodes.append({"CacheClusterId": m["CacheClusterId"], "CacheNodeId": "0001",
                      "ReadEndpoint": _endpoint(store, m["CacheClusterId"], "0001"),
                      "PreferredAvailabilityZone": m["PreferredAvailabilityZone"],
                      "CurrentRole": "primary" if i == 0 else "replica"})
    if nodes:
        nodes[0]["ReadEndpoint"] = _endpoint(store, rg["ReplicationGroupId"], "0001")
    ng = {"NodeGroupId": "0001", "Status": rg["Status"],
          "PrimaryEndpoint": _endpoint(store, rg["ReplicationGroupId"], primary=True),
          "ReaderEndpoint": _endpoint(store, rg["ReplicationGroupId"], "ro"),
          "NodeGroupMembers": nodes}
    if rg.get("ClusterEnabled"):
        ng["Slots"] = "0-16383"
    v = {k: rg[k] for k in (
        "ReplicationGroupId", "Description", "Status", "PendingModifiedValues", "MemberClusters",
        "AutomaticFailover", "MultiAZ", "SnapshotRetentionLimit", "SnapshotWindow", "ClusterEnabled",
        "CacheNodeType", "AuthTokenEnabled", "TransitEncryptionEnabled", "AtRestEncryptionEnabled",
        "ARN", "NetworkType", "IpDiscovery", "DataTiering") if k in rg}
    v["NodeGroups"] = [ng]
    if rg.get("ClusterEnabled"):
        v["ConfigurationEndpoint"] = _endpoint(store, rg["ReplicationGroupId"], primary=True)
    return v


def _snapshot_view(s: dict) -> dict:
    return {k: v for k, v in s.items() if not k.startswith("_")}


# ── lookups ────────────────────────────────────────────────────────────────
def _need_cluster(store, cid: str) -> dict:
    c = store.clusters.get(cid)
    if not cid or not c:
        raise ElastiCacheError("CacheClusterNotFound", f"Cache cluster not found: {cid}", 404)
    return c


def _need_rg(store, rid: str) -> dict:
    r = store.replication_groups.get(rid)
    if not rid or not r:
        raise ElastiCacheError("ReplicationGroupNotFoundFault", f"Replication group {rid} not found.", 404)
    return r


def _need_sg(store, name: str) -> dict:
    g = store.subnet_groups.get(name)
    if not name or not g:
        raise ElastiCacheError("CacheSubnetGroupNotFoundFault", f"Cache subnet group {name} not found.", 400)
    return g


def _need_pg(store, name: str) -> dict:
    g = store.parameter_groups.get(name)
    if not name or not g:
        raise ElastiCacheError("CacheParameterGroupNotFound", f"CacheParameterGroup not found: {name}", 404)
    return g


def _check_engine(engine: str, version: str | None) -> tuple[str, str]:
    engine = (engine or "redis").lower()
    if engine not in ENGINE_VERSIONS:
        raise ElastiCacheError("InvalidParameterValue", f"Invalid value for Engine: {engine}.")
    versions = [v for v, _ in ENGINE_VERSIONS[engine]]
    ver = version or DEFAULT_VERSION[engine]
    if not any(v == ver or v.startswith(ver + ".") or ver.startswith(v) for v in versions):
        raise ElastiCacheError("InvalidParameterValue",
                               f"Cannot find version {ver} for {engine}.")
    return engine, ver


def _family(engine: str, version: str) -> str:
    for v, fam in ENGINE_VERSIONS[engine]:
        if v == version or version.startswith(v) or v.startswith(version):
            return fam
    return ENGINE_VERSIONS[engine][0][1]


def _default_pg(store, engine: str, version: str) -> str:
    fam = _family(engine, version)
    name = f"default.{fam}"
    if name not in store.parameter_groups:
        store.parameter_groups[name] = {
            "CacheParameterGroupName": name, "CacheParameterGroupFamily": fam,
            "Description": f"Default parameter group for {fam}", "IsGlobal": False,
            "ARN": _arn(store, "parametergroup", name),
            "_params": _params_for(engine, fam), "_default": True}
    return name


def _params_for(engine: str, family: str) -> dict:
    out = {}
    for n, val, typ, desc, fam in _FAMILY_PARAMS[engine]:
        out[n] = {"ParameterName": n, "ParameterValue": val, "Description": desc, "Source": "system",
                  "DataType": typ, "AllowedValues": "", "IsModifiable": True,
                  "MinimumEngineVersion": "1.0.0", "ChangeType": "immediate"}
    return out


def _engine_of_family(family: str) -> str:
    for eng, vs in ENGINE_VERSIONS.items():
        if any(f == family for _, f in vs):
            return eng
    raise ElastiCacheError("InvalidParameterValue", f"Invalid CacheParameterGroupFamily: {family}")


def _validate_node_type(nt: str) -> str:
    nt = nt or "cache.t3.micro"
    if not nt.startswith("cache."):
        raise ElastiCacheError("InvalidParameterValue", f"Invalid cache node type: {nt}.")
    return nt


# ── cluster building ───────────────────────────────────────────────────────
def _build_cluster(store, params: dict, cid: str, *, engine: str, version: str, node_type: str,
                   num_nodes: int, rg_id: str | None = None, az: str | None = None,
                   index: int = 0, tags: dict | None = None) -> dict:
    sg_name = params.get("CacheSubnetGroupName") or "default"
    if params.get("CacheSubnetGroupName"):
        _need_sg(store, sg_name)
    pg = params.get("CacheParameterGroupName")
    pg = pg if pg else _default_pg(store, engine, version)
    _need_pg(store, pg)
    port = _int(params, "Port", store.endpoint_port)
    zone = az or params.get("PreferredAvailabilityZone") or _az(index)
    sec_groups = [{"SecurityGroupId": s, "Status": "active"}
                  for s in _collect(params, "SecurityGroupIds") if isinstance(s, str)]
    if not sec_groups:
        sec_groups = [{"SecurityGroupId": "sg-" + _short(store.account_id, "default-sg"),
                       "Status": "active"}]
    nodes = []
    for n in range(1, num_nodes + 1):
        nid = f"{n:04d}"
        ep = _endpoint(store, cid, nid)
        ep["Port"] = port
        nodes.append({"CacheNodeId": nid, "CacheNodeStatus": "available", "CacheNodeCreateTime": _now(),
                      "Endpoint": ep, "ParameterGroupStatus": "in-sync",
                      "CustomerAvailabilityZone": _az(index + n - 1) if engine == "memcached" and not az else zone})
    c = {
        "CacheClusterId": cid, "ClientDownloadLandingPage": "https://console.aws.amazon.com/elasticache/home#client-download:",
        "CacheNodeType": node_type, "Engine": engine, "EngineVersion": version,
        "CacheClusterStatus": "available", "NumCacheNodes": num_nodes,
        "PreferredAvailabilityZone": zone, "CacheClusterCreateTime": _now(),
        "PreferredMaintenanceWindow": params.get("PreferredMaintenanceWindow") or "sun:05:00-sun:06:00",
        "PendingModifiedValues": {}, "CacheSecurityGroups": [],
        "CacheParameterGroup": {"CacheParameterGroupName": pg, "ParameterApplyStatus": "in-sync",
                                "CacheNodeIdsToReboot": []},
        "CacheSubnetGroupName": sg_name,
        "AutoMinorVersionUpgrade": _bool(params.get("AutoMinorVersionUpgrade"), True),
        "SecurityGroups": sec_groups,
        "SnapshotRetentionLimit": _int(params, "SnapshotRetentionLimit", 0),
        "SnapshotWindow": params.get("SnapshotWindow") or "07:00-08:00",
        "AuthTokenEnabled": bool(params.get("AuthToken")),
        "TransitEncryptionEnabled": _bool(params.get("TransitEncryptionEnabled"), False),
        "AtRestEncryptionEnabled": _bool(params.get("AtRestEncryptionEnabled"), False),
        "ARN": _arn(store, "cluster", cid), "NetworkType": params.get("NetworkType") or "ipv4",
        "IpDiscovery": params.get("IpDiscovery") or "ipv4", "CacheNodes": nodes,
    }
    if rg_id:
        c["ReplicationGroupId"] = rg_id
    if tags:
        store.tags[c["ARN"]] = dict(tags)
    return c


# ── operations: cache clusters ─────────────────────────────────────────────
def _create_cache_cluster(store, params):
    cid = str(params.get("CacheClusterId", "")).strip().lower()
    if not cid:
        raise ElastiCacheError("InvalidParameterValue", "The parameter CacheClusterId must be provided.")
    if not cid[0].isalpha() or not all(ch.isalnum() or ch == "-" for ch in cid) or len(cid) > 50 \
            or "--" in cid or cid.endswith("-"):
        raise ElastiCacheError("InvalidParameterValue",
                               f"The parameter CacheClusterId is not a valid identifier: {cid}")
    if cid in store.clusters:
        raise ElastiCacheError("CacheClusterAlreadyExists", f"Cache cluster {cid} already exists.")
    rg_id = params.get("ReplicationGroupId")
    engine, version = _check_engine(params.get("Engine") or ("redis" if rg_id else "redis"),
                                    params.get("EngineVersion"))
    nodes = _int(params, "NumCacheNodes", 1)
    if nodes < 1 or nodes > 40 or (engine != "memcached" and nodes > 1 and not rg_id):
        raise ElastiCacheError("InvalidParameterValue", "Invalid value for NumCacheNodes.")
    if rg_id:
        rg = _need_rg(store, rg_id)
        c = _build_cluster(store, params, cid, engine=engine, version=version,
                           node_type=rg["CacheNodeType"], num_nodes=1, rg_id=rg_id,
                           index=len(rg["MemberClusters"]))
        rg["MemberClusters"].append(cid)
    else:
        c = _build_cluster(store, params, cid, engine=engine, version=version,
                           node_type=_validate_node_type(params.get("CacheNodeType")),
                           num_nodes=nodes, tags=_tags_from(params))
    store.clusters[cid] = c
    _event(store, cid, "cache-cluster", "Cache cluster created")
    store.persist()
    return _envelope("CreateCacheCluster", "<CacheCluster>" + "".join(
        _ser(k, v) for k, v in _cluster_view(store, c).items()) + "</CacheCluster>")


def _describe_cache_clusters(store, params):
    cid = params.get("CacheClusterId")
    items = [_need_cluster(store, cid)] if cid else [store.clusters[k] for k in sorted(store.clusters)]
    if params.get("ReplicationGroupId"):
        items = [c for c in items if c.get("ReplicationGroupId") == params["ReplicationGroupId"]]
    page, marker = _page(items, params, "CacheClusters")
    body = marker + _ser("CacheClusters", [_cluster_view(store, c) for c in page])
    return _envelope("DescribeCacheClusters", body)


def _modify_cache_cluster(store, params):
    c = _need_cluster(store, params.get("CacheClusterId", ""))
    if c["CacheClusterStatus"] not in ("available",):
        raise ElastiCacheError("InvalidCacheClusterState", f"Cache cluster {c['CacheClusterId']} is not available.")
    if params.get("CacheNodeType"):
        c["CacheNodeType"] = _validate_node_type(params["CacheNodeType"])
    if params.get("EngineVersion"):
        _, ver = _check_engine(c["Engine"], params["EngineVersion"])
        c["EngineVersion"] = ver
    if params.get("NumCacheNodes"):
        n = _int(params, "NumCacheNodes")
        if c["Engine"] != "memcached" and n != 1:
            raise ElastiCacheError("InvalidParameterCombination", "NumCacheNodes can only change for memcached.")
        cur = len(c["CacheNodes"])
        for i in range(cur + 1, n + 1):
            ep = _endpoint(store, c["CacheClusterId"], f"{i:04d}")
            c["CacheNodes"].append({"CacheNodeId": f"{i:04d}", "CacheNodeStatus": "available",
                                    "CacheNodeCreateTime": _now(), "Endpoint": ep,
                                    "ParameterGroupStatus": "in-sync",
                                    "CustomerAvailabilityZone": _az(i)})
        del c["CacheNodes"][n:]
        c["NumCacheNodes"] = n
    if params.get("CacheParameterGroupName"):
        _need_pg(store, params["CacheParameterGroupName"])
        c["CacheParameterGroup"]["CacheParameterGroupName"] = params["CacheParameterGroupName"]
    for p in ("PreferredMaintenanceWindow", "SnapshotWindow"):
        if params.get(p):
            c[p] = params[p]
    if params.get("SnapshotRetentionLimit"):
        c["SnapshotRetentionLimit"] = _int(params, "SnapshotRetentionLimit")
    if params.get("AutoMinorVersionUpgrade"):
        c["AutoMinorVersionUpgrade"] = _bool(params["AutoMinorVersionUpgrade"])
    sgs = [s for s in _collect(params, "SecurityGroupIds") if isinstance(s, str)]
    if sgs:
        c["SecurityGroups"] = [{"SecurityGroupId": s, "Status": "active"} for s in sgs]
    _event(store, c["CacheClusterId"], "cache-cluster", "Cache cluster modified")
    store.persist()
    return _envelope("ModifyCacheCluster", "<CacheCluster>" + "".join(
        _ser(k, v) for k, v in _cluster_view(store, c).items()) + "</CacheCluster>")


def _delete_cache_cluster(store, params):
    cid = params.get("CacheClusterId", "")
    c = _need_cluster(store, cid)
    if c.get("ReplicationGroupId") and len(store.replication_groups.get(c["ReplicationGroupId"], {}).get("MemberClusters", [])) <= 1:
        raise ElastiCacheError("InvalidParameterValue",
                               "Cannot delete the last cache cluster of a replication group; delete the replication group.")
    final = params.get("FinalSnapshotIdentifier")
    if final:
        _make_snapshot(store, final, c, "manual")
    view = _cluster_view(store, c)
    view["CacheClusterStatus"] = "deleting"
    rg = store.replication_groups.get(c.get("ReplicationGroupId") or "")
    if rg and cid in rg["MemberClusters"]:
        rg["MemberClusters"].remove(cid)
    store.tags.pop(c["ARN"], None)
    del store.clusters[cid]
    _event(store, cid, "cache-cluster", "Cache cluster deleted")
    store.persist()
    return _envelope("DeleteCacheCluster", "<CacheCluster>" + "".join(
        _ser(k, v) for k, v in view.items()) + "</CacheCluster>")


def _reboot_cache_cluster(store, params):
    c = _need_cluster(store, params.get("CacheClusterId", ""))
    ids = [i for i in _collect(params, "CacheNodeIdsToReboot") if isinstance(i, str)]
    if not ids:
        raise ElastiCacheError("InvalidParameterValue", "CacheNodeIdsToReboot is required.")
    known = {n["CacheNodeId"] for n in c["CacheNodes"]}
    if any(i not in known for i in ids):
        raise ElastiCacheError("InvalidParameterValue", "Unknown cache node id.")
    _event(store, c["CacheClusterId"], "cache-cluster", "Cache cluster nodes restarted")
    store.persist()
    return _envelope("RebootCacheCluster", "<CacheCluster>" + "".join(
        _ser(k, v) for k, v in _cluster_view(store, c).items()) + "</CacheCluster>")


# ── operations: replication groups ─────────────────────────────────────────
def _create_replication_group(store, params):
    rid = str(params.get("ReplicationGroupId", "")).strip().lower()
    if not rid:
        raise ElastiCacheError("InvalidParameterValue", "The parameter ReplicationGroupId must be provided.")
    if not rid[0].isalpha() or not all(ch.isalnum() or ch == "-" for ch in rid) or len(rid) > 40:
        raise ElastiCacheError("InvalidParameterValue",
                               f"The parameter ReplicationGroupId is not a valid identifier: {rid}")
    if rid in store.replication_groups:
        raise ElastiCacheError("ReplicationGroupAlreadyExists", f"Replication group {rid} already exists.")
    desc = params.get("ReplicationGroupDescription")
    if not desc:
        raise ElastiCacheError("InvalidParameterValue", "The parameter ReplicationGroupDescription must be provided.")
    engine, version = _check_engine(params.get("Engine") or "redis", params.get("EngineVersion"))
    if engine == "memcached":
        raise ElastiCacheError("InvalidParameterValue", "Replication groups do not support memcached.")
    node_type = _validate_node_type(params.get("CacheNodeType"))
    shards = _int(params, "NumNodeGroups", 1)
    replicas = _int(params, "ReplicasPerNodeGroup", None)
    n_clusters = _int(params, "NumCacheClusters", None)
    if n_clusters is None:
        n_clusters = (replicas + 1) * shards if replicas is not None else 2
    if n_clusters < 1 or n_clusters > 6 * max(shards, 1) + 6:
        raise ElastiCacheError("InvalidParameterValue", "Invalid value for NumCacheClusters.")
    failover = _bool(params.get("AutomaticFailoverEnabled"), False)
    multi_az = _bool(params.get("MultiAZEnabled"), False)
    if multi_az and not failover:
        raise ElastiCacheError("InvalidParameterCombination", "Multi-AZ requires AutomaticFailoverEnabled.")
    rg = {"ReplicationGroupId": rid, "Description": desc, "Status": "available",
          "PendingModifiedValues": {}, "MemberClusters": [],
          "AutomaticFailover": "enabled" if failover else "disabled",
          "MultiAZ": "enabled" if multi_az else "disabled",
          "SnapshotRetentionLimit": _int(params, "SnapshotRetentionLimit", 0),
          "SnapshotWindow": params.get("SnapshotWindow") or "07:00-08:00",
          "ClusterEnabled": shards > 1 or _bool(params.get("ClusterMode") == "enabled", False),
          "CacheNodeType": node_type, "AuthTokenEnabled": bool(params.get("AuthToken")),
          "TransitEncryptionEnabled": _bool(params.get("TransitEncryptionEnabled"), False),
          "AtRestEncryptionEnabled": _bool(params.get("AtRestEncryptionEnabled"), False),
          "ARN": _arn(store, "replicationgroup", rid), "NetworkType": params.get("NetworkType") or "ipv4",
          "IpDiscovery": params.get("IpDiscovery") or "ipv4", "DataTiering": "disabled",
          "_engine": engine, "_version": version}
    tags = _tags_from(params)
    for i in range(1, n_clusters + 1):
        cid = f"{rid}-{i:03d}"
        c = _build_cluster(store, params, cid, engine=engine, version=version, node_type=node_type,
                           num_nodes=1, rg_id=rid, index=i - 1)
        store.clusters[cid] = c
        rg["MemberClusters"].append(cid)
    store.replication_groups[rid] = rg
    if tags:
        store.tags[rg["ARN"]] = tags
    _event(store, rid, "replication-group", "Replication group created")
    store.persist()
    return _envelope("CreateReplicationGroup", "<ReplicationGroup>" + "".join(
        _ser(k, v) for k, v in _rg_view(store, rg).items()) + "</ReplicationGroup>")


def _describe_replication_groups(store, params):
    rid = params.get("ReplicationGroupId")
    items = [_need_rg(store, rid)] if rid else [store.replication_groups[k] for k in sorted(store.replication_groups)]
    page, marker = _page(items, params, "ReplicationGroups")
    return _envelope("DescribeReplicationGroups",
                     marker + _ser("ReplicationGroups", [_rg_view(store, r) for r in page]))


def _modify_replication_group(store, params):
    rg = _need_rg(store, params.get("ReplicationGroupId", ""))
    if params.get("ReplicationGroupDescription"):
        rg["Description"] = params["ReplicationGroupDescription"]
    if params.get("CacheNodeType"):
        rg["CacheNodeType"] = _validate_node_type(params["CacheNodeType"])
        for m in rg["MemberClusters"]:
            if m in store.clusters:
                store.clusters[m]["CacheNodeType"] = rg["CacheNodeType"]
    if params.get("EngineVersion"):
        _, ver = _check_engine(rg["_engine"], params["EngineVersion"])
        rg["_version"] = ver
        for m in rg["MemberClusters"]:
            if m in store.clusters:
                store.clusters[m]["EngineVersion"] = ver
    if params.get("AutomaticFailoverEnabled"):
        rg["AutomaticFailover"] = "enabled" if _bool(params["AutomaticFailoverEnabled"]) else "disabled"
    if params.get("MultiAZEnabled"):
        rg["MultiAZ"] = "enabled" if _bool(params["MultiAZEnabled"]) else "disabled"
    if params.get("SnapshotRetentionLimit"):
        rg["SnapshotRetentionLimit"] = _int(params, "SnapshotRetentionLimit")
    if params.get("SnapshotWindow"):
        rg["SnapshotWindow"] = params["SnapshotWindow"]
    _event(store, rg["ReplicationGroupId"], "replication-group", "Replication group modified")
    store.persist()
    return _envelope("ModifyReplicationGroup", "<ReplicationGroup>" + "".join(
        _ser(k, v) for k, v in _rg_view(store, rg).items()) + "</ReplicationGroup>")


def _delete_replication_group(store, params):
    rid = params.get("ReplicationGroupId", "")
    rg = _need_rg(store, rid)
    final = params.get("FinalSnapshotIdentifier")
    if final and rg["MemberClusters"]:
        _make_snapshot(store, final, store.clusters[rg["MemberClusters"][0]], "manual", rg)
    view = _rg_view(store, rg)
    view["Status"] = "deleting"
    for m in list(rg["MemberClusters"]):
        c = store.clusters.pop(m, None)
        if c:
            store.tags.pop(c["ARN"], None)
    store.tags.pop(rg["ARN"], None)
    del store.replication_groups[rid]
    _event(store, rid, "replication-group", "Replication group deleted")
    store.persist()
    return _envelope("DeleteReplicationGroup", "<ReplicationGroup>" + "".join(
        _ser(k, v) for k, v in view.items()) + "</ReplicationGroup>")


# ── operations: subnet groups ──────────────────────────────────────────────
def _sg_view(g: dict) -> dict:
    return {k: v for k, v in g.items() if not k.startswith("_")}


def _create_cache_subnet_group(store, params):
    name = str(params.get("CacheSubnetGroupName", "")).strip()
    if not name:
        raise ElastiCacheError("InvalidParameterValue", "The parameter CacheSubnetGroupName must be provided.")
    if name in store.subnet_groups:
        raise ElastiCacheError("CacheSubnetGroupAlreadyExists", f"Cache subnet group {name} already exists.")
    desc = params.get("CacheSubnetGroupDescription")
    if not desc:
        raise ElastiCacheError("InvalidParameterValue", "The parameter CacheSubnetGroupDescription must be provided.")
    ids = [s for s in _collect(params, "SubnetIds") if isinstance(s, str)]
    if not ids:
        raise ElastiCacheError("InvalidParameterValue", "The parameter SubnetIds must be provided.")
    g = {"CacheSubnetGroupName": name, "CacheSubnetGroupDescription": desc,
         "VpcId": "vpc-" + _short(store.account_id, "vpc"),
         "Subnets": [{"SubnetIdentifier": s, "SubnetAvailabilityZone": {"Name": _az(i)},
                      "SupportedNetworkTypes": ["ipv4"]} for i, s in enumerate(ids)],
         "ARN": _arn(store, "subnetgroup", name), "SupportedNetworkTypes": ["ipv4"]}
    store.subnet_groups[name] = g
    tags = _tags_from(params)
    if tags:
        store.tags[g["ARN"]] = tags
    store.persist()
    return _envelope("CreateCacheSubnetGroup", _ser("CacheSubnetGroup", _sg_view(g)))


def _describe_cache_subnet_groups(store, params):
    n = params.get("CacheSubnetGroupName")
    items = [_need_sg(store, n)] if n else [store.subnet_groups[k] for k in sorted(store.subnet_groups)]
    page, marker = _page(items, params, "CacheSubnetGroups")
    return _envelope("DescribeCacheSubnetGroups",
                     marker + _ser("CacheSubnetGroups", [_sg_view(g) for g in page]))


def _modify_cache_subnet_group(store, params):
    g = _need_sg(store, params.get("CacheSubnetGroupName", ""))
    if params.get("CacheSubnetGroupDescription"):
        g["CacheSubnetGroupDescription"] = params["CacheSubnetGroupDescription"]
    ids = [s for s in _collect(params, "SubnetIds") if isinstance(s, str)]
    if ids:
        g["Subnets"] = [{"SubnetIdentifier": s, "SubnetAvailabilityZone": {"Name": _az(i)},
                         "SupportedNetworkTypes": ["ipv4"]} for i, s in enumerate(ids)]
    store.persist()
    return _envelope("ModifyCacheSubnetGroup", _ser("CacheSubnetGroup", _sg_view(g)))


def _delete_cache_subnet_group(store, params):
    name = params.get("CacheSubnetGroupName", "")
    _need_sg(store, name)
    if name == "default":
        raise ElastiCacheError("CacheSubnetGroupInUse", "The default cache subnet group cannot be deleted.")
    if any(c.get("CacheSubnetGroupName") == name for c in store.clusters.values()):
        raise ElastiCacheError("CacheSubnetGroupInUse", f"Cache subnet group {name} is in use.")
    store.tags.pop(store.subnet_groups[name]["ARN"], None)
    del store.subnet_groups[name]
    store.persist()
    return _envelope("DeleteCacheSubnetGroup", None)


# ── operations: parameter groups ───────────────────────────────────────────
def _pg_view(g: dict) -> dict:
    return {k: v for k, v in g.items() if not k.startswith("_")}


def _create_cache_parameter_group(store, params):
    name = str(params.get("CacheParameterGroupName", "")).strip()
    fam = params.get("CacheParameterGroupFamily")
    if not name or not fam:
        raise ElastiCacheError("InvalidParameterValue",
                               "CacheParameterGroupName and CacheParameterGroupFamily are required.")
    if name in store.parameter_groups:
        raise ElastiCacheError("CacheParameterGroupAlreadyExists", f"Parameter group {name} already exists.")
    engine = _engine_of_family(fam)
    g = {"CacheParameterGroupName": name, "CacheParameterGroupFamily": fam,
         "Description": params.get("Description") or name, "IsGlobal": False,
         "ARN": _arn(store, "parametergroup", name), "_params": _params_for(engine, fam)}
    store.parameter_groups[name] = g
    tags = _tags_from(params)
    if tags:
        store.tags[g["ARN"]] = tags
    store.persist()
    return _envelope("CreateCacheParameterGroup", _ser("CacheParameterGroup", _pg_view(g)))


def _describe_cache_parameter_groups(store, params):
    n = params.get("CacheParameterGroupName")
    for eng, vs in ENGINE_VERSIONS.items():        # the defaults always exist
        for v, _ in vs:
            _default_pg(store, eng, v)
    items = [_need_pg(store, n)] if n else [store.parameter_groups[k] for k in sorted(store.parameter_groups)]
    page, marker = _page(items, params, "CacheParameterGroups")
    return _envelope("DescribeCacheParameterGroups",
                     marker + _ser("CacheParameterGroups", [_pg_view(g) for g in page]))


def _modify_cache_parameter_group(store, params):
    g = _need_pg(store, params.get("CacheParameterGroupName", ""))
    if g.get("_default"):
        raise ElastiCacheError("InvalidCacheParameterGroupState", "Default parameter groups cannot be modified.")
    for p in _collect(params, "ParameterNameValues"):
        if not isinstance(p, dict) or p.get("ParameterName") not in g["_params"]:
            raise ElastiCacheError("InvalidParameterValue",
                                   f"Invalid parameter: {p.get('ParameterName') if isinstance(p, dict) else p}")
        g["_params"][p["ParameterName"]]["ParameterValue"] = p.get("ParameterValue", "")
        g["_params"][p["ParameterName"]]["Source"] = "user"
    store.persist()
    return _envelope("ModifyCacheParameterGroup",
                     _x("CacheParameterGroupName", g["CacheParameterGroupName"]))


def _delete_cache_parameter_group(store, params):
    name = params.get("CacheParameterGroupName", "")
    g = _need_pg(store, name)
    if g.get("_default"):
        raise ElastiCacheError("InvalidCacheParameterGroupState", "Default parameter groups cannot be deleted.")
    if any(c["CacheParameterGroup"]["CacheParameterGroupName"] == name for c in store.clusters.values()):
        raise ElastiCacheError("InvalidCacheParameterGroupState", f"Parameter group {name} is in use.")
    store.tags.pop(g["ARN"], None)
    del store.parameter_groups[name]
    store.persist()
    return _envelope("DeleteCacheParameterGroup", None)


def _describe_cache_parameters(store, params):
    g = _need_pg(store, params.get("CacheParameterGroupName", ""))
    items = [g["_params"][k] for k in sorted(g["_params"])]
    page, marker = _page(items, params, "Parameters")
    return _envelope("DescribeCacheParameters", marker + _ser("Parameters", page))


# ── operations: snapshots ──────────────────────────────────────────────────
def _make_snapshot(store, name: str, c: dict, source: str, rg: dict | None = None) -> dict:
    if name in store.snapshots:
        raise ElastiCacheError("SnapshotAlreadyExistsFault", f"Snapshot {name} already exists.")
    s = {"SnapshotName": name, "ReplicationGroupId": (rg or {}).get("ReplicationGroupId") or c.get("ReplicationGroupId") or "",
         "ReplicationGroupDescription": (rg or {}).get("Description", ""),
         "CacheClusterId": c["CacheClusterId"], "SnapshotStatus": "available", "SnapshotSource": source,
         "CacheNodeType": c["CacheNodeType"], "Engine": c["Engine"], "EngineVersion": c["EngineVersion"],
         "NumCacheNodes": c["NumCacheNodes"], "PreferredAvailabilityZone": c["PreferredAvailabilityZone"],
         "CacheClusterCreateTime": c["CacheClusterCreateTime"],
         "PreferredMaintenanceWindow": c["PreferredMaintenanceWindow"],
         "CacheSubnetGroupName": c["CacheSubnetGroupName"], "VpcId": "vpc-" + _short(store.account_id, "vpc"),
         "AutoMinorVersionUpgrade": c["AutoMinorVersionUpgrade"],
         "SnapshotRetentionLimit": c["SnapshotRetentionLimit"], "SnapshotWindow": c["SnapshotWindow"],
         "Port": c["CacheNodes"][0]["Endpoint"]["Port"],
         "NodeSnapshots": [{"CacheNodeId": n["CacheNodeId"], "CacheSize": "0 MB",
                            "CacheNodeCreateTime": n["CacheNodeCreateTime"],
                            "SnapshotCreateTime": _now()} for n in c["CacheNodes"]],
         "ARN": _arn(store, "snapshot", name), "DataTiering": "disabled"}
    s = {k: v for k, v in s.items() if v != ""}
    store.snapshots[name] = s
    return s


def _create_snapshot(store, params):
    name = str(params.get("SnapshotName", "")).strip()
    if not name:
        raise ElastiCacheError("InvalidParameterValue", "The parameter SnapshotName must be provided.")
    cid, rid = params.get("CacheClusterId"), params.get("ReplicationGroupId")
    if not cid and not rid:
        raise ElastiCacheError("InvalidParameterCombination",
                               "Either CacheClusterId or ReplicationGroupId must be provided.")
    if rid:
        rg = _need_rg(store, rid)
        src = store.clusters[rg["MemberClusters"][0]]
        s = _make_snapshot(store, name, src, "manual", rg)
    else:
        s = _make_snapshot(store, name, _need_cluster(store, cid), "manual")
    tags = _tags_from(params)
    if tags:
        store.tags[s["ARN"]] = tags
    _event(store, name, "cache-snapshot", "Snapshot created")
    store.persist()
    return _envelope("CreateSnapshot", _ser("Snapshot", _snapshot_view(s)))


def _describe_snapshots(store, params):
    items = list(store.snapshots.values())
    if params.get("SnapshotName"):
        items = [s for s in items if s["SnapshotName"] == params["SnapshotName"]]
        if not items:
            raise ElastiCacheError("SnapshotNotFoundFault", f"Snapshot {params['SnapshotName']} not found.", 404)
    if params.get("CacheClusterId"):
        items = [s for s in items if s.get("CacheClusterId") == params["CacheClusterId"]]
    if params.get("ReplicationGroupId"):
        items = [s for s in items if s.get("ReplicationGroupId") == params["ReplicationGroupId"]]
    items.sort(key=lambda s: s["SnapshotName"])
    page, marker = _page(items, params, "Snapshots")
    return _envelope("DescribeSnapshots", marker + _ser("Snapshots", [_snapshot_view(s) for s in page]))


def _delete_snapshot(store, params):
    name = params.get("SnapshotName", "")
    s = store.snapshots.get(name)
    if not s:
        raise ElastiCacheError("SnapshotNotFoundFault", f"Snapshot {name} not found.", 404)
    view = dict(_snapshot_view(s))
    view["SnapshotStatus"] = "deleting"
    store.tags.pop(s["ARN"], None)
    del store.snapshots[name]
    store.persist()
    return _envelope("DeleteSnapshot", _ser("Snapshot", view))


# ── operations: tags ───────────────────────────────────────────────────────
def _resource_exists(store, arn: str) -> bool:
    for coll in (store.clusters, store.replication_groups, store.subnet_groups,
                 store.parameter_groups, store.snapshots):
        if any(r.get("ARN") == arn for r in coll.values()):
            return True
    return False


def _need_arn(store, params) -> str:
    arn = params.get("ResourceName", "")
    if not arn.startswith("arn:aws:elasticache:"):
        raise ElastiCacheError("InvalidARN", f"Invalid ARN: {arn}")
    if not _resource_exists(store, arn):
        kind = arn.split(":")[5] if arn.count(":") >= 6 else "cluster"
        code = {"cluster": "CacheClusterNotFound", "replicationgroup": "ReplicationGroupNotFoundFault",
                "snapshot": "SnapshotNotFoundFault", "parametergroup": "CacheParameterGroupNotFound",
                "subnetgroup": "CacheSubnetGroupNotFoundFault"}.get(kind, "CacheClusterNotFound")
        raise ElastiCacheError(code, f"The resource {arn} was not found.", 404 if code != "CacheSubnetGroupNotFoundFault" else 400)
    return arn


def _taglist(store, arn: str) -> list:
    return [{"Key": k, "Value": v} for k, v in (store.tags.get(arn) or {}).items()]


def _add_tags_to_resource(store, params):
    arn = _need_arn(store, params)
    new = _tags_from(params, "Tags")
    if not new:
        raise ElastiCacheError("InvalidParameterValue", "Tags must be provided.")
    store.tags.setdefault(arn, {}).update(new)
    store.persist()
    return _envelope("AddTagsToResource", _ser("TagList", _taglist(store, arn)))


def _remove_tags_from_resource(store, params):
    arn = _need_arn(store, params)
    keys = [k for k in _collect(params, "TagKeys") if isinstance(k, str)]
    have = store.tags.get(arn) or {}
    missing = [k for k in keys if k not in have]
    if missing:
        raise ElastiCacheError("TagNotFound", f"Tag not found: {missing[0]}", 404)
    for k in keys:
        have.pop(k, None)
    store.persist()
    return _envelope("RemoveTagsFromResource", _ser("TagList", _taglist(store, arn)))


def _list_tags_for_resource(store, params):
    arn = _need_arn(store, params)
    return _envelope("ListTagsForResource", _ser("TagList", _taglist(store, arn)))


# ── operations: reference data ─────────────────────────────────────────────
def _describe_cache_engine_versions(store, params):
    eng, ver, fam = params.get("Engine"), params.get("EngineVersion"), params.get("CacheParameterGroupFamily")
    out = []
    for e, vs in ENGINE_VERSIONS.items():
        for v, f in vs:
            if (eng and e != eng) or (ver and v != ver) or (fam and f != fam):
                continue
            out.append({"Engine": e, "EngineVersion": v, "CacheParameterGroupFamily": f,
                        "CacheEngineDescription": e.capitalize(),
                        "CacheEngineVersionDescription": f"{e} version {v}"})
    page, marker = _page(out, params, "CacheEngineVersions")
    return _envelope("DescribeCacheEngineVersions", marker + _ser("CacheEngineVersions", page))


def _describe_events(store, params):
    items = list(store.events)
    if params.get("SourceIdentifier"):
        items = [e for e in items if e["SourceIdentifier"] == params["SourceIdentifier"]]
    if params.get("SourceType"):
        items = [e for e in items if e["SourceType"] == params["SourceType"]]
    page, marker = _page(items, params, "Events")
    return _envelope("DescribeEvents", marker + _ser("Events", page))


OPERATIONS = {
    "CreateCacheCluster": _create_cache_cluster, "DescribeCacheClusters": _describe_cache_clusters,
    "ModifyCacheCluster": _modify_cache_cluster, "DeleteCacheCluster": _delete_cache_cluster,
    "RebootCacheCluster": _reboot_cache_cluster,
    "CreateReplicationGroup": _create_replication_group,
    "DescribeReplicationGroups": _describe_replication_groups,
    "ModifyReplicationGroup": _modify_replication_group,
    "DeleteReplicationGroup": _delete_replication_group,
    "CreateCacheSubnetGroup": _create_cache_subnet_group,
    "DescribeCacheSubnetGroups": _describe_cache_subnet_groups,
    "ModifyCacheSubnetGroup": _modify_cache_subnet_group,
    "DeleteCacheSubnetGroup": _delete_cache_subnet_group,
    "CreateCacheParameterGroup": _create_cache_parameter_group,
    "DescribeCacheParameterGroups": _describe_cache_parameter_groups,
    "ModifyCacheParameterGroup": _modify_cache_parameter_group,
    "DeleteCacheParameterGroup": _delete_cache_parameter_group,
    "DescribeCacheParameters": _describe_cache_parameters,
    "CreateSnapshot": _create_snapshot, "DescribeSnapshots": _describe_snapshots,
    "DeleteSnapshot": _delete_snapshot,
    "AddTagsToResource": _add_tags_to_resource, "RemoveTagsFromResource": _remove_tags_from_resource,
    "ListTagsForResource": _list_tags_for_resource,
    "DescribeCacheEngineVersions": _describe_cache_engine_versions, "DescribeEvents": _describe_events,
}


def _ensure_defaults(store) -> None:
    """Every account has a `default` cache subnet group (it cannot be deleted)."""
    if "default" not in store.subnet_groups:
        store.subnet_groups["default"] = {
            "CacheSubnetGroupName": "default", "CacheSubnetGroupDescription": "Default CacheSubnetGroup",
            "VpcId": "vpc-" + _short(store.account_id, "vpc"),
            "Subnets": [{"SubnetIdentifier": "subnet-" + _short("default", i),
                         "SubnetAvailabilityZone": {"Name": _az(i)}, "SupportedNetworkTypes": ["ipv4"]}
                        for i in range(3)],
            "ARN": _arn(store, "subnetgroup", "default"), "SupportedNetworkTypes": ["ipv4"]}


def dispatch(store: ElastiCacheStore, params: dict) -> ElastiCacheResponse:
    """Serve ONE Query-protocol request (`params` = merged query + form body)."""
    _ensure_defaults(store)
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "The request must contain the parameter Action.")
    fn = OPERATIONS.get(action)
    if fn is None:
        return _error("InvalidAction", f"The action {action} is not valid for this web service.")
    try:
        return fn(store, params)
    except ElastiCacheError as e:
        return _error(e.code, e.message, e.status)


# ── console REST view (flat, shared by the offline server and Nano) ────────
def _console_cluster(store, c: dict) -> dict:
    n0 = c["CacheNodes"][0]["Endpoint"] if c["CacheNodes"] else {"Address": "", "Port": store.endpoint_port}
    rg = store.replication_groups.get(c.get("ReplicationGroupId") or "")
    return {
        "name": c["CacheClusterId"], "cluster_id": c["CacheClusterId"], "arn": c["ARN"],
        "engine": c["Engine"].capitalize() if c["Engine"] != "redis" else "Redis OSS",
        "engine_version": c["EngineVersion"], "node_type": c["CacheNodeType"],
        "status": c["CacheClusterStatus"], "num_nodes": c["NumCacheNodes"],
        "mode": "Replication group" if rg else ("Memcached cluster" if c["Engine"] == "memcached" else "Node"),
        "replication_group": c.get("ReplicationGroupId") or "None",
        "endpoint": f"{n0['Address']}:{n0['Port']}", "port": n0["Port"],
        "availability_zone": c["PreferredAvailabilityZone"], "subnet_group": c["CacheSubnetGroupName"],
        "parameter_group": c["CacheParameterGroup"]["CacheParameterGroupName"],
        "security_groups": ", ".join(s["SecurityGroupId"] for s in c["SecurityGroups"]) or "None",
        "encryption_in_transit": "Enabled" if c["TransitEncryptionEnabled"] else "Disabled",
        "encryption_at_rest": "Enabled" if c["AtRestEncryptionEnabled"] else "Disabled",
        "maintenance_window": c["PreferredMaintenanceWindow"], "snapshot_window": c["SnapshotWindow"],
        "snapshot_retention": c["SnapshotRetentionLimit"],
        "created": c["CacheClusterCreateTime"], "instance_type": c["CacheNodeType"],
        "tags": dict(store.tags.get(c["ARN"]) or {}),
        "data_plane": "valkey" if store.endpoint_host else "control-plane only",
    }


def console_list(store) -> dict:
    return {"items": [_console_cluster(store, store.clusters[k]) for k in sorted(store.clusters)]}


def console_get(store, name: str) -> dict:
    return _console_cluster(store, _need_cluster(store, name))


def console_create(store, body: dict) -> dict:
    """Console 'Create cache': a single node (Valkey by default) with defaults."""
    name = str(body.get("name") or body.get("CacheClusterId") or "").strip()
    p = {"Action": "CreateCacheCluster", "CacheClusterId": name,
         "Engine": str(body.get("engine") or "valkey").lower().replace(" oss", ""),
         "CacheNodeType": body.get("node_type") or "cache.t3.micro"}
    if body.get("engine_version"):
        p["EngineVersion"] = str(body["engine_version"])
    if body.get("num_nodes"):
        p["NumCacheNodes"] = str(body["num_nodes"])
    r = dispatch(store, p)
    if r.status != 200:
        raise ElastiCacheError(*_err_parts(r))
    return console_get(store, name.lower())


def _err_parts(r: ElastiCacheResponse):
    import re
    code = re.search(r"<Code>(.*?)</Code>", r.body)
    msg = re.search(r"<Message>(.*?)</Message>", r.body)
    return (code.group(1) if code else "Error", msg.group(1) if msg else "", r.status)


def console_delete(store, name: str) -> dict:
    c = _need_cluster(store, name)
    if c.get("ReplicationGroupId"):
        r = dispatch(store, {"Action": "DeleteReplicationGroup", "ReplicationGroupId": c["ReplicationGroupId"]})
    else:
        r = dispatch(store, {"Action": "DeleteCacheCluster", "CacheClusterId": name})
    if r.status != 200:
        raise ElastiCacheError(*_err_parts(r))
    return {"deleted": name}


def console_set_tags(store, name: str, tags: dict) -> dict:
    c = _need_cluster(store, name)
    store.tags[c["ARN"]] = {str(k): str(v) for k, v in (tags or {}).items()}
    store.persist()
    return console_get(store, name)


def console_children(store, kind: str) -> dict:
    _ensure_defaults(store)
    if kind == "subnet-groups":
        return {"items": [{"name": g["CacheSubnetGroupName"], "description": g["CacheSubnetGroupDescription"],
                           "vpc_id": g["VpcId"], "subnets": len(g["Subnets"]), "arn": g["ARN"]}
                          for g in (store.subnet_groups[k] for k in sorted(store.subnet_groups))]}
    if kind == "parameter-groups":
        for eng, vs in ENGINE_VERSIONS.items():
            for v, _ in vs:
                _default_pg(store, eng, v)
        return {"items": [{"name": g["CacheParameterGroupName"], "family": g["CacheParameterGroupFamily"],
                           "description": g["Description"], "arn": g["ARN"],
                           "type": "default" if g.get("_default") else "custom"}
                          for g in (store.parameter_groups[k] for k in sorted(store.parameter_groups))]}
    if kind == "snapshots":
        return {"items": [{"name": s["SnapshotName"], "source": s.get("CacheClusterId", ""),
                           "status": s["SnapshotStatus"], "type": s["SnapshotSource"],
                           "engine": s["Engine"], "node_type": s["CacheNodeType"],
                           "created": s["NodeSnapshots"][0]["SnapshotCreateTime"] if s.get("NodeSnapshots") else "",
                           "arn": s["ARN"]}
                          for s in (store.snapshots[k] for k in sorted(store.snapshots))]}
    raise ElastiCacheError("InvalidParameterValue", f"Unknown collection {kind}.", 404)


def console_child_create(store, kind: str, body: dict) -> dict:
    name = str(body.get("name", "")).strip()
    if kind == "snapshots":
        r = dispatch(store, {"Action": "CreateSnapshot", "SnapshotName": name,
                             "CacheClusterId": body.get("source") or body.get("cluster", "")})
    elif kind == "subnet-groups":
        p = {"Action": "CreateCacheSubnetGroup", "CacheSubnetGroupName": name,
             "CacheSubnetGroupDescription": body.get("description") or name,
             "SubnetIds.member.1": body.get("subnet_id") or "subnet-" + _short(name, 1)}
        r = dispatch(store, p)
    elif kind == "parameter-groups":
        r = dispatch(store, {"Action": "CreateCacheParameterGroup", "CacheParameterGroupName": name,
                             "CacheParameterGroupFamily": body.get("family") or "valkey8",
                             "Description": body.get("description") or name})
    else:
        raise ElastiCacheError("InvalidParameterValue", f"Unknown collection {kind}.", 404)
    if r.status != 200:
        raise ElastiCacheError(*_err_parts(r))
    return {"created": name}


def console_child_delete(store, kind: str, name: str) -> dict:
    act, key = {"snapshots": ("DeleteSnapshot", "SnapshotName"),
                "subnet-groups": ("DeleteCacheSubnetGroup", "CacheSubnetGroupName"),
                "parameter-groups": ("DeleteCacheParameterGroup", "CacheParameterGroupName")}[kind]
    r = dispatch(store, {"Action": act, key: name})
    if r.status != 200:
        raise ElastiCacheError(*_err_parts(r))
    return {"deleted": name}
