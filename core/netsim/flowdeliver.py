"""netsim flow-log DELIVERY (pure): turns collector rows into what each cloud's flow-log feature writes, and hands the
bytes to caller-supplied sinks (so this module imports no store, boto3 or fastapi and loads under Pyodide).

AWS   CreateFlowLogs configs (resource = VPC | subnet | ENI, TrafficType ALL|ACCEPT|REJECT, custom LogFormat) ->
      CloudWatch Logs stream `<eni>-<all|accept|reject>` or an S3 object
      AWSLogs/<acct>/vpcflowlogs/<region>/<yyyy>/<mm>/<dd>/<acct>_vpcflowlogs_<region>_<fl-id>_<ts>_<hash>.log.gz
Azure Network Watcher flowLogs (NSG target, version 1|2) -> blob PT1H.json in `insights-logs-networksecuritygroupflowevent`
      under resourceId=/SUBSCRIPTIONS/.../NETWORKSECURITYGROUPS/<nsg>/y=/m=/d=/h=/m=00/macAddress=<mac>/PT1H.json
      (v2 flow tuples incl. the real matched NSG rule name, from the shared evaluator).
The rows themselves come from REAL per-flow counters (offline Docker enforcement); nothing is invented here.
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import re

DEFAULT_AWS_FORMAT = "${version} ${account-id} ${interface-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status}"


def _fields(fmt: str) -> list:
    return re.findall(r"\$\{([a-z0-9-]+)\}", fmt or DEFAULT_AWS_FORMAT)


def aws_line(row: dict, fields: list) -> str:
    return " ".join(str(row.get(f, "-")) for f in fields)


def aws_matches(cfg: dict, row: dict) -> bool:
    if cfg.get("status", "ACTIVE") != "ACTIVE":
        return False
    rid = cfg.get("resource_id")
    if rid not in (row["interface-id"], row["subnet-id"], row["vpc-id"]):
        return False
    tt = cfg.get("traffic_type", "ALL")
    return tt == "ALL" or tt == row["action"]


def aws_deliver(configs: dict, rows: list, cw_put, s3_put, region: str = "us-east-1", now: int | None = None) -> dict:
    """configs: vpc_core m['flow_logs'] ({fl-id: cfg}); cw_put(group, stream, [(ts_ms, msg)]) -> bool;
    s3_put(bucket, key, bytes) -> bool. Mutates cfg['deliver_logs_status'] (SUCCESS|FAILED) like AWS. Returns {fl-id: n}."""
    done = {}
    now = int(now if now is not None else datetime.datetime.now(datetime.timezone.utc).timestamp())
    for fid, cfg in configs.items():
        fields = _fields(cfg.get("log_format"))
        mine = [r for r in rows if aws_matches(cfg, r)]
        if not mine:
            continue
        ok = True
        if cfg.get("log_destination_type", "cloud-watch-logs") == "cloud-watch-logs":
            by_stream = {}
            for r in mine:
                by_stream.setdefault(f"{r['interface-id']}-{cfg.get('traffic_type', 'ALL').lower()}", []).append((int(r["end"]) * 1000, aws_line(r, fields)))
            for stream, evs in by_stream.items():
                ok = cw_put(cfg.get("log_group_name", ""), stream, evs) and ok
        else:
            dest = cfg.get("log_destination", "")
            m = re.match(r"arn:aws:s3:::([^/]+)/?(.*)$", dest)
            if not m:
                ok = False
            else:
                bucket, prefix = m.group(1), m.group(2).strip("/")
                acct = mine[0]["account-id"]
                t = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
                body = "\n".join([" ".join(fields)] + [aws_line(r, fields) for r in mine]) + "\n"
                h = hashlib.sha1(body.encode()).hexdigest()[:8]
                key = (f"{prefix + '/' if prefix else ''}AWSLogs/{acct}/vpcflowlogs/{region}/{t:%Y/%m/%d}/"
                       f"{acct}_vpcflowlogs_{region}_{fid}_{t:%Y%m%dT%H%MZ}_{h}.log.gz")
                ok = s3_put(bucket, key, gzip.compress(body.encode()))
        cfg["deliver_logs_status"] = "SUCCESS" if ok else "FAILED"
        done[fid] = len(mine)
    return done


# ── Azure ──
def _mac(iface_id: str) -> str:
    return hashlib.md5(iface_id.encode()).hexdigest()[:12].upper()


def azure_blobs(nsg_rows: dict, now: int | None = None) -> dict:
    """nsg_rows: {nsg_arm_id: [ {iface, tuple_fields...} ]} -> {blob path: json bytes} (v2 records)."""
    now = int(now if now is not None else datetime.datetime.now(datetime.timezone.utc).timestamp())
    t = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    out = {}
    for nsg_id, rows in nsg_rows.items():
        by_mac = {}
        for r in rows:
            by_mac.setdefault(_mac(r["iface"]), []).append(r)
        for mac, rs in by_mac.items():
            by_rule = {}
            for r in rs:
                by_rule.setdefault(r["rule"], []).append(r["tuple"])
            rec = {"time": t.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"), "systemId": hashlib.md5(nsg_id.encode()).hexdigest(), "macAddress": mac,
                   "category": "NetworkSecurityGroupFlowEvent", "resourceId": nsg_id.upper(), "operationName": "NetworkSecurityGroupFlowEvents",
                   "properties": {"Version": 2, "flows": [{"rule": rule, "flows": [{"mac": mac, "flowTuples": tuples}]} for rule, tuples in by_rule.items()]}}
            path = f"resourceId={nsg_id.upper()}/y={t:%Y}/m={t:%m}/d={t:%d}/h={t:%H}/m=00/macAddress={mac}/PT1H.json"
            out[path] = json.dumps({"records": [rec]}).encode()
    return out
