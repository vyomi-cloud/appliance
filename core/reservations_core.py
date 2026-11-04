"""DynamoDB reserved capacity + RDS capacity reservations (Vyomi-only service `vyomi-reservations`, rest-json POST /<Operation>).

Neither exists as a public AWS API (DynamoDB reserved capacity is bought through the console / account team; RDS capacity
reservations are console-managed), so this is an honest Vyomi extension: a reservation is a RECORD of a commitment - there is no
billing or payment - but its UTILISATION is real arithmetic against what is actually running:

  * DynamoDB: reserved read / write capacity units (term 1 or 3 years, minimum 100 units) are compared with the provisioned
    RCU / WCU summed over every PROVISIONED table and global secondary index in the account. Unused reserved units, units billed
    at the normal rate (provisioned above the reservation) and a utilisation percentage are computed on every read.
  * RDS: a capacity reservation (instance class, count, Availability Zone, optional engine) is matched against the
    available DB instances of the same class (and AZ / engine when given): used = min(matching, count), unused = the rest.

State lives in ``s3_store.account["reservations"]``. Pure Python (Pyodide-loadable).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone

ACCT = "123456789012"
REGION = "us-east-1"
MIN_UNITS = 100
_CLASS = re.compile(r"^db\.[a-z0-9]+\.[a-z0-9]+$")
_AZ = re.compile(r"^[a-z]{2}-[a-z]+-\d[a-z]$")


class _Err(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _bad(msg):
    return _Err("ValidationException", msg, 400)


def _iso(t=None):
    return datetime.fromtimestamp(t if t is not None else time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(s3_store) -> dict:
    st = s3_store.account.setdefault("reservations", {})
    st.setdefault("ddb", {})
    st.setdefault("rds", {})
    return st


# ── DynamoDB reserved capacity ────────────────────────────────────────────────────────────────
def _provisioned_totals(ddb_store) -> dict:
    rcu = wcu = tables = 0
    for t in list((getattr(ddb_store, "tables", None) or {}).values()):
        if not isinstance(t, dict) or str(t.get("billing_mode", "PAY_PER_REQUEST")).upper() == "PAY_PER_REQUEST":
            continue
        tables += 1
        pt = t.get("provisioned_throughput") or {}
        rcu += int(pt.get("ReadCapacityUnits", 5) or 5)
        wcu += int(pt.get("WriteCapacityUnits", 5) or 5)
        for g in t.get("global_secondary_indexes") or []:
            gp = (g.get("provisioned_throughput") or pt) if isinstance(g, dict) else pt
            rcu += int(gp.get("ReadCapacityUnits", 5) or 5)
            wcu += int(gp.get("WriteCapacityUnits", 5) or 5)
    return {"tables": tables, "read": rcu, "write": wcu}


def _active(r, now):
    return r["endTime"] > now


def _ddb_view(st, ddb_store):
    now = time.time()
    totals = _provisioned_totals(ddb_store)
    rows = []
    for r in st["ddb"].values():
        rows.append({"ReservationId": r["id"], "ReservationArn": r["arn"], "CapacityType": r["type"], "Units": r["units"], "TermYears": r["term"],
                     "State": "active" if _active(r, now) else "expired", "StartTime": _iso(r["start"]), "EndTime": _iso(r["endTime"])})
    util = {}
    for ty in ("read", "write"):
        reserved = sum(r["units"] for r in st["ddb"].values() if r["type"] == ty and _active(r, now))
        prov = totals[ty]
        used = min(reserved, prov)
        util[ty] = {"ReservedUnits": reserved, "ProvisionedUnits": prov, "UsedReservedUnits": used, "UnusedReservedUnits": reserved - used,
                    "UnreservedProvisionedUnits": max(0, prov - reserved),
                    "UtilizationPercent": round(100.0 * used / reserved, 1) if reserved else None}
    return {"Reservations": sorted(rows, key=lambda x: x["StartTime"]), "Utilization": util, "ProvisionedTables": totals["tables"]}


def op_PurchaseDynamoDBReservedCapacity(st, p, stores):
    ty = str(p.get("CapacityType", "")).lower()
    if ty not in ("read", "write"):
        raise _bad("CapacityType must be 'read' or 'write'.")
    units = p.get("Units")
    if not isinstance(units, int) or isinstance(units, bool) or units < MIN_UNITS:
        raise _bad(f"Units must be an integer of at least {MIN_UNITS}.")
    if units % 100:
        raise _bad("Units must be a multiple of 100.")
    term = p.get("TermYears", 1)
    if term not in (1, 3):
        raise _bad("TermYears must be 1 or 3.")
    rid = "ddb-rc-" + uuid.uuid4().hex[:12]
    now = time.time()
    st["ddb"][rid] = {"id": rid, "arn": f"arn:aws:dynamodb::{ACCT}:reserved-capacity/{rid}", "type": ty, "units": units, "term": term, "start": now,
                      "endTime": now + term * 365 * 86400}
    return {"ReservationId": rid, "ReservationArn": st["ddb"][rid]["arn"]}


def op_DescribeDynamoDBReservedCapacity(st, p, stores):
    return _ddb_view(st, stores["ddb"])


def op_DeleteDynamoDBReservedCapacity(st, p, stores):
    rid = p.get("ReservationId")
    if rid not in st["ddb"]:
        raise _Err("ResourceNotFoundException", f"Reservation {rid} not found.", 404)
    del st["ddb"][rid]
    return {"ReservationId": rid}


# ── RDS capacity reservations ─────────────────────────────────────────────────────────────────
def _rds_match(rds_store, r):
    n = 0
    for iid in rds_store.instance_ids():
        d = rds_store.get_instance(iid) or {}
        if d.get("db_instance_status", "available") != "available" or d.get("db_instance_class") != r["class"]:
            continue
        if r.get("az") and d.get("availability_zone", "us-east-1a") != r["az"]:
            continue
        if r.get("engine") and d.get("engine") != r["engine"]:
            continue
        n += 1
    return n


def _rds_view(st, rds_store):
    out = []
    now = time.time()
    for r in st["rds"].values():
        matching = _rds_match(rds_store, r)
        used = min(matching, r["count"])
        active = r["state"] == "active" and (not r.get("endTime") or r["endTime"] > now)
        out.append({"ReservationId": r["id"], "ReservationArn": r["arn"], "Name": r.get("name", ""), "DBInstanceClass": r["class"], "InstanceCount": r["count"],
                    "AvailabilityZone": r.get("az", ""), "Engine": r.get("engine", ""), "State": "active" if active else ("expired" if r["state"] == "active" else r["state"]),
                    "CreateTime": _iso(r["created"]), "EndDate": _iso(r["endTime"]) if r.get("endTime") else None,
                    "MatchingInstances": matching, "UsedInstances": used, "UnusedInstances": r["count"] - used,
                    "UtilizationPercent": round(100.0 * used / r["count"], 1), "UnreservedMatchingInstances": max(0, matching - r["count"])})
    return {"CapacityReservations": sorted(out, key=lambda x: x["CreateTime"])}


def op_CreateRDSCapacityReservation(st, p, stores):
    cls = str(p.get("DBInstanceClass", ""))
    if not _CLASS.match(cls):
        raise _bad("DBInstanceClass must look like db.m5.large.")
    cnt = p.get("InstanceCount")
    if not isinstance(cnt, int) or isinstance(cnt, bool) or not 1 <= cnt <= 100:
        raise _bad("InstanceCount must be an integer between 1 and 100.")
    az = p.get("AvailabilityZone") or ""
    if az and not _AZ.match(az):
        raise _bad(f"Invalid AvailabilityZone '{az}'.")
    if az and not az.startswith(REGION):
        raise _bad(f"AvailabilityZone must be in {REGION}.")
    end = None
    if p.get("EndDate"):
        try:
            end = datetime.fromisoformat(str(p["EndDate"]).replace("Z", "+00:00")).timestamp()
        except ValueError:
            raise _bad("EndDate must be an ISO-8601 timestamp.")
        if end <= time.time():
            raise _bad("EndDate must be in the future.")
    name = str(p.get("Name") or "")
    if name and not re.match(r"^[A-Za-z][A-Za-z0-9-]{0,62}$", name):
        raise _bad("Name must start with a letter and contain only letters, digits and hyphens (max 63).")
    if any(r.get("name") == name for r in st["rds"].values() if name):
        raise _Err("ReservationAlreadyExists", f"A capacity reservation named {name} already exists.", 400)
    rid = "rds-cr-" + uuid.uuid4().hex[:12]
    st["rds"][rid] = {"id": rid, "arn": f"arn:aws:rds:{REGION}:{ACCT}:capacity-reservation:{rid}", "name": name, "class": cls, "count": cnt, "az": az,
                      "engine": str(p.get("Engine") or ""), "state": "active", "created": time.time(), "endTime": end}
    return _rds_view({"rds": {rid: st["rds"][rid]}}, stores["rds"])["CapacityReservations"][0]


def op_DescribeRDSCapacityReservations(st, p, stores):
    v = _rds_view(st, stores["rds"])
    if p.get("ReservationId"):
        v["CapacityReservations"] = [r for r in v["CapacityReservations"] if r["ReservationId"] == p["ReservationId"]]
        if not v["CapacityReservations"]:
            raise _Err("ResourceNotFoundException", f"Reservation {p['ReservationId']} not found.", 404)
    return v


def op_CancelRDSCapacityReservation(st, p, stores):
    rid = p.get("ReservationId")
    r = st["rds"].get(rid)
    if not r:
        raise _Err("ResourceNotFoundException", f"Reservation {rid} not found.", 404)
    if r["state"] == "cancelled":
        raise _Err("InvalidReservationState", "The reservation is already cancelled.", 400)
    r["state"] = "cancelled"
    return _rds_view({"rds": {rid: r}}, stores["rds"])["CapacityReservations"][0]


_OPS = {f.__name__[3:]: f for f in (op_PurchaseDynamoDBReservedCapacity, op_DescribeDynamoDBReservedCapacity, op_DeleteDynamoDBReservedCapacity,
                                     op_CreateRDSCapacityReservation, op_DescribeRDSCapacityReservations, op_CancelRDSCapacityReservation)}


def dispatch(s3_store, ddb_store, rds_store, method, path, body):
    def resp(status, doc, err=None):
        h = {"content-type": "application/json"}
        if err:
            h["x-amzn-errortype"] = err
        return {"status": status, "headers": h, "body": json.dumps(doc).encode()}
    op = (path or "").strip("/")
    fn = _OPS.get(op)
    if fn is None or method.upper() != "POST":
        return resp(404, {"__type": "UnknownOperationException", "message": f"Unknown operation {method} /{op}"}, "UnknownOperationException")
    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return resp(400, {"__type": "ValidationException", "message": "The request body must be a JSON object."}, "ValidationException")
    st = _state(s3_store)
    try:
        out = fn(st, p, {"ddb": ddb_store, "rds": rds_store})
        try:
            s3_store.persist()
        except Exception:
            pass
        return resp(200, out)
    except _Err as e:
        return resp(e.status, {"__type": e.code, "message": e.message}, e.code)
