# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Amazon Redshift clusters (Query API 2012-12-01, signing name `redshift`) backed by a real SQL engine - substrate-independent.

Control plane (real, with AWS validation): CreateCluster / DescribeClusters / ModifyCluster / DeleteCluster /
RebootCluster, cluster identifiers, node types, endpoint (address:5439), MasterUsername / DBName, ManageMasterPassword
(the master credential is a Secrets Manager secret OWNED by redshift - same mechanism as RDS ManageMasterUserPassword,
via ``store.managed_secret_hook``).

Data plane (real): the Redshift Data API (core/zeroetl_core.dispatch_redshift_data) with ``ClusterIdentifier`` + ``Database``
runs ANY SQL statement - CREATE TABLE, INSERT, UPDATE, DELETE, SELECT, joins, aggregates - on that cluster's own SQL engine
(sqlite3, in memory). Writes are kept as a statement log in the persisted state and replayed when the engine is rebuilt, so
cluster data survives a restart/reload. ``run_sql(state, cluster, sql)`` is the single entry point.

Honest limits: the SQL dialect is SQLite's, not Redshift's (no distkey/sortkey semantics, columnar storage, COPY/UNLOAD, Spectrum,
stored procedures); node counts/types are metadata; the database is single-schema (``public`` accepted and ignored); no
snapshots/resize/WLM. The Redshift Data API's per-statement history lives in core/zeroetl_core.
State lives on the RDS store (``store.redshift``).
"""
from __future__ import annotations

import re
import sqlite3
import time
import uuid
from xml.sax.saxutils import escape as _esc

REGION, ACCT = "us-east-1", "123456789012"
_ID = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_NODE_TYPES = {"dc2.large", "dc2.8xlarge", "ra3.xlplus", "ra3.4xlarge", "ra3.16xlarge", "ds2.xlarge", "ds2.8xlarge"}
_WRITE = re.compile(r"^\s*(create|insert|update|delete|drop|alter|truncate|replace)\b", re.I)


class RsError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _st(store) -> dict:
    s = store.__dict__.setdefault("redshift", {})
    s.setdefault("clusters", {})
    return s


def _arn(cid):
    return f"arn:aws:redshift:{REGION}:{ACCT}:cluster:{cid}"


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _el(tag, v):
    return f"<{tag}>{_esc(str(v))}</{tag}>"


def _cluster_xml(c: dict) -> str:
    sec = ""
    if c.get("master_user_secret"):
        sec = ("<MasterPasswordSecretArn>" + _esc(c["master_user_secret"]["SecretArn"]) + "</MasterPasswordSecretArn>"
               "<MasterPasswordSecretKmsKeyId>" + _esc(c["master_user_secret"].get("KmsKeyId", "")) + "</MasterPasswordSecretKmsKeyId>")
    return ("<Cluster>" + _el("ClusterIdentifier", c["id"]) + _el("NodeType", c["node_type"]) + _el("ClusterStatus", c["status"])
            + _el("ClusterAvailabilityStatus", "Available") + _el("MasterUsername", c["master_username"]) + _el("DBName", c["db_name"])
            + "<Endpoint>" + _el("Address", c["address"]) + _el("Port", c["port"]) + "</Endpoint>"
            + _el("ClusterCreateTime", c["created"]) + _el("NumberOfNodes", c["nodes"]) + _el("PubliclyAccessible", str(c["public"]).lower())
            + _el("Encrypted", str(c["encrypted"]).lower()) + _el("ClusterNamespaceArn", _arn(c["id"])) + _el("ClusterVersion", "1.0") + sec + "</Cluster>")


def _resp(action: str, inner: str = "") -> tuple[int, str]:
    return 200, (f'<?xml version="1.0" encoding="UTF-8"?><{action}Response xmlns="http://redshift.amazonaws.com/doc/2012-12-01/">'
                 f"<{action}Result>{inner}</{action}Result><ResponseMetadata><RequestId>{uuid.uuid4()}</RequestId></ResponseMetadata></{action}Response>")


def _err(code, msg, status=400):
    return status, (f'<ErrorResponse xmlns="http://redshift.amazonaws.com/doc/2012-12-01/"><Error><Type>Sender</Type><Code>{code}</Code>'
                    f"<Message>{_esc(msg)}</Message></Error><RequestId>{uuid.uuid4()}</RequestId></ErrorResponse>")


def _get(store, cid) -> dict:
    c = _st(store)["clusters"].get(cid)
    if not c:
        raise RsError("ClusterNotFound", f"Cluster {cid} not found.", 404)
    return c


def _truthy(v) -> bool:
    return str(v).lower() == "true"


def dispatch(store, params: dict) -> tuple[int, str]:
    action = str(params.get("Action", ""))
    try:
        fn = _OPS.get(action)
        if fn is None:
            raise RsError("InvalidAction", f"Redshift operation {action} is not simulated.", 400)
        return fn(store, params)
    except RsError as e:
        return _err(e.code, e.message, e.status)


def _create(store, p):
    cid = str(p.get("ClusterIdentifier", "")).strip()
    if not _ID.match(cid):
        raise RsError("InvalidParameterValue", "ClusterIdentifier must be 1-63 lowercase letters, digits or hyphens and start with a letter.")
    st = _st(store)
    if cid in st["clusters"]:
        raise RsError("ClusterAlreadyExists", f"Cluster {cid} already exists.")
    node_type = str(p.get("NodeType", ""))
    if node_type not in _NODE_TYPES:
        raise RsError("InvalidParameterValue", f"NodeType {node_type or '(none)'} is not valid; use one of {sorted(_NODE_TYPES)}.")
    user = str(p.get("MasterUsername", "")).strip()
    if not user:
        raise RsError("InvalidParameterValue", "MasterUsername is required.")
    managed = _truthy(p.get("ManageMasterPassword"))
    pw = str(p.get("MasterUserPassword", ""))
    if managed and pw:
        raise RsError("InvalidParameterCombination", "Cannot specify both MasterUserPassword and ManageMasterPassword.")
    if not managed and not (8 <= len(pw) <= 64 and re.search(r"[A-Z]", pw) and re.search(r"[a-z]", pw) and re.search(r"\d", pw)):
        raise RsError("InvalidParameterValue", "MasterUserPassword must be 8-64 characters with an uppercase letter, a lowercase letter and a digit.")
    ctype = str(p.get("ClusterType") or "single-node")
    nodes = int(p.get("NumberOfNodes") or 1)
    if ctype == "multi-node" and nodes < 2:
        raise RsError("InvalidParameterCombination", "A multi-node cluster needs NumberOfNodes >= 2.")
    c = {"id": cid, "node_type": node_type, "status": "available", "master_username": user, "master_password": pw,
         "db_name": str(p.get("DBName") or "dev"), "address": f"{cid}.vyomi.us-east-1.redshift.amazonaws.com", "port": int(p.get("Port") or 5439),
         "created": _now(), "nodes": 1 if ctype == "single-node" else nodes, "public": _truthy(p.get("PubliclyAccessible")),
         "encrypted": _truthy(p.get("Encrypted")), "log": []}
    if managed:
        hook = getattr(store, "managed_secret_hook", None)
        if hook is None:
            raise RsError("InvalidParameterCombination", "ManageMasterPassword needs Secrets Manager, which is not wired on this substrate.")
        c["master_user_secret"] = hook("create", {"db_instance_identifier": cid, "master_username": user, "engine": "redshift",
                                                   "endpoint_address": c["address"], "endpoint_port": c["port"], "db_name": c["db_name"],
                                                   "db_instance_arn": _arn(cid), "dbi_resource_id": "redshift-" + cid}, kms_key_id=str(p.get("MasterPasswordSecretKmsKeyId") or ""), owner="redshift")
    st["clusters"][cid] = c
    store.persist()
    return _resp("CreateCluster", _cluster_xml(c))


def _describe(store, p):
    cid = str(p.get("ClusterIdentifier", "")).strip()
    cs = [_get(store, cid)] if cid else [c for _, c in sorted(_st(store)["clusters"].items())]
    return _resp("DescribeClusters", "<Clusters>" + "".join(_cluster_xml(c) for c in cs) + "</Clusters>")


def _modify(store, p):
    c = _get(store, str(p.get("ClusterIdentifier", "")).strip())
    if p.get("NodeType"):
        if str(p["NodeType"]) not in _NODE_TYPES:
            raise RsError("InvalidParameterValue", f"NodeType {p['NodeType']} is not valid.")
        c["node_type"] = str(p["NodeType"])
    if p.get("NumberOfNodes"):
        c["nodes"] = int(p["NumberOfNodes"])
    if p.get("MasterUserPassword"):
        if c.get("master_user_secret"):
            raise RsError("InvalidParameterCombination", "The master password is managed in Secrets Manager.")
        c["master_password"] = str(p["MasterUserPassword"])
    if p.get("ManageMasterPassword") is not None:
        hook = getattr(store, "managed_secret_hook", None)
        if _truthy(p["ManageMasterPassword"]) and not c.get("master_user_secret") and hook:
            c["master_user_secret"] = hook("create", {"db_instance_identifier": c["id"], "master_username": c["master_username"], "engine": "redshift",
                                                      "endpoint_address": c["address"], "endpoint_port": c["port"], "db_name": c["db_name"],
                                                      "db_instance_arn": _arn(c["id"]), "dbi_resource_id": "redshift-" + c["id"]}, kms_key_id="", owner="redshift")
        elif not _truthy(p["ManageMasterPassword"]) and c.get("master_user_secret") and hook:
            hook("delete", {"dbi_resource_id": "redshift-" + c["id"], "db_instance_identifier": c["id"]}, owner="redshift")
            c.pop("master_user_secret", None)
    if p.get("PubliclyAccessible") is not None:
        c["public"] = _truthy(p["PubliclyAccessible"])
    store.persist()
    return _resp("ModifyCluster", _cluster_xml(c))


def _delete(store, p):
    c = _get(store, str(p.get("ClusterIdentifier", "")).strip())
    if c.get("master_user_secret"):
        hook = getattr(store, "managed_secret_hook", None)
        if hook:
            hook("delete", {"dbi_resource_id": "redshift-" + c["id"], "db_instance_identifier": c["id"]}, owner="redshift")
    del _st(store)["clusters"][c["id"]]
    _ENGINES.pop(c["id"], None)
    store.persist()
    return _resp("DeleteCluster", _cluster_xml(dict(c, status="deleting")))


def _reboot(store, p):
    c = _get(store, str(p.get("ClusterIdentifier", "")).strip())
    _ENGINES.pop(c["id"], None)       # rebooting drops the live engine; it is rebuilt from the persisted statement log
    return _resp("RebootCluster", _cluster_xml(c))


_OPS = {"CreateCluster": _create, "DescribeClusters": _describe, "ModifyCluster": _modify, "DeleteCluster": _delete, "RebootCluster": _reboot}

# ── data plane ────────────────────────────────────────────────────────────────
_ENGINES: dict[str, sqlite3.Connection] = {}


def has_cluster(store, cid: str) -> bool:
    return bool(cid) and cid in _st(store)["clusters"]


def _engine(store, cid) -> sqlite3.Connection:
    conn = _ENGINES.get(cid)
    if conn is None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        for stmt in _get(store, cid)["log"]:        # replay the persisted write log
            try:
                conn.execute(stmt)
            except sqlite3.Error:
                pass
        conn.commit()
        _ENGINES[cid] = conn
    return conn


def run_sql(store, cid: str, sql: str):
    """Execute one statement on the cluster's engine. Returns (columns, rows, rowcount). Raises RsError on SQL errors."""
    c = _get(store, cid)
    sql = re.sub(r"(?i)\bpublic\.", "", sql.strip().rstrip(";"))
    conn = _engine(store, cid)
    try:
        cur = conn.execute(sql)
        conn.commit()
    except sqlite3.Error as e:
        raise RsError("ValidationException", f"ERROR: {e}")
    if _WRITE.match(sql):
        c["log"].append(sql)
        store.persist()
    cols = [d[0] for d in cur.description or []]
    return cols, [list(r) for r in (cur.fetchall() if cols else [])], max(cur.rowcount, 0)


def list_tables(store, cid: str):
    conn = _engine(store, cid)
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
