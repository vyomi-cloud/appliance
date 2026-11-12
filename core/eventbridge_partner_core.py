"""EventBridge partner event sources (SaaS partners) — substrate-independent; ops ride the EventBridge JSON protocol.

Partner side: CreatePartnerEventSource / DeletePartnerEventSource / DescribePartnerEventSource / ListPartnerEventSources /
ListPartnerEventSourceAccounts / PutPartnerEvents.  Customer side: DescribeEventSource / ListEventSources / ActivateEventSource /
DeactivateEventSource, and CreateEventBus(EventSourceName=...) which associates the source with a same-named bus and turns it ACTIVE.
PutPartnerEvents on an ACTIVE source is REAL: the event enters the associated partner bus (source = the partner event source
name) and fans out through that bus's rules and targets exactly like PutEvents.

Honest limits: Vyomi simulates one account, so the "partner" and the "customer" are the same account (the console offers
Vyomi's own SaaS-partner simulators to play the partner role); there is no cross-account partner auth handshake; a PENDING
source expires after 14 days only when listed (no background reaper).
State: `eventbridge_core._bag(store, "partner_sources")`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

_NAME = re.compile(r"^aws\.partner(/[\.\-_A-Za-z0-9]+){2,}$")
_ACCT = re.compile(r"^\d{12}$")
PENDING_DAYS = 14


def _eb():
    try:
        from core import eventbridge_core as m
    except ImportError:  # Pyodide flat layout
        import eventbridge_core as m  # type: ignore
    return m


def _iso(dt=None) -> float:
    return round((dt or datetime.now(timezone.utc)).timestamp(), 3)


def _src(store) -> dict:
    return _eb()._bag(store, "partner_sources")


def _arn(store, name: str) -> str:
    return f"arn:aws:events:{_eb().REGION}:{store.account_id}:event-source/{name}"


def _require(store, name: str) -> dict:
    s = _src(store).get(str(name or ""))
    if not s or s["State"] == "DELETED":
        raise _eb()._E("ResourceNotFoundException", f"Event source {name} does not exist.")
    return s


def _view(s: dict) -> dict:
    return {"Arn": s["Arn"], "CreatedBy": s["CreatedBy"], "CreationTime": s["CreationTime"],
            "ExpirationTime": s["ExpirationTime"], "Name": s["Name"], "State": s["State"]}


def create_partner_event_source(store, body):
    eb = _eb()
    name, acct = str(body.get("Name") or ""), str(body.get("Account") or "")
    if not _NAME.match(name) or len(name) > 256:
        raise eb._E("ValidationException", f"Value '{name}' at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: aws\\.partner(/[\\.\\-_A-Za-z0-9]+){{2,}}")
    if not _ACCT.match(acct):
        raise eb._E("ValidationException", f"Value '{acct}' at 'account' failed to satisfy constraint: Member must satisfy regular expression pattern: \\d{{12}}")
    cur = _src(store).get(name)
    if cur and cur["State"] != "DELETED":
        raise eb._E("ResourceAlreadyExistsException", f"Partner event source {name} already exists for account {acct}.")
    now = datetime.now(timezone.utc)
    _src(store)[name] = {"Name": name, "Arn": _arn(store, name), "CreatedBy": name.split("/")[1], "Account": acct,
                         "CreationTime": _iso(now), "ExpirationTime": _iso(now + timedelta(days=PENDING_DAYS)),
                         "State": "PENDING", "bus": None}
    store.persist()
    return eb.EventsResponse(body={"EventSourceArn": _arn(store, name)})


def delete_partner_event_source(store, body):
    eb = _eb()
    name = str(body.get("Name") or "")
    s = _require(store, name)
    if str(body.get("Account") or "") != s["Account"]:
        raise eb._E("ResourceNotFoundException", f"Event source {name} does not exist for account {body.get('Account')}.")
    s["State"] = "DELETED"
    store.persist()
    return eb.EventsResponse(body={})


def describe_partner_event_source(store, body):
    s = _require(store, body.get("Name"))
    return _eb().EventsResponse(body={"Arn": s["Arn"], "Name": s["Name"]})


def list_partner_event_sources(store, body):
    eb = _eb()
    prefix = str(body.get("NamePrefix") or "")
    if not prefix:
        raise eb._E("ValidationException", "1 validation error detected: Value null at 'namePrefix' failed to satisfy constraint: Member must not be null")
    out = [{"Arn": s["Arn"], "Name": s["Name"]} for s in _src(store).values() if s["State"] != "DELETED" and s["Name"].startswith(prefix)]
    return eb.EventsResponse(body={"PartnerEventSources": sorted(out, key=lambda x: x["Name"])})


def list_partner_event_source_accounts(store, body):
    s = _require(store, body.get("EventSourceName"))
    return _eb().EventsResponse(body={"PartnerEventSourceAccounts": [
        {"Account": s["Account"], "CreationTime": s["CreationTime"], "ExpirationTime": s["ExpirationTime"], "State": s["State"]}]})


def describe_event_source(store, body):
    return _eb().EventsResponse(body=_view(_require(store, body.get("Name"))))


def list_event_sources(store, body):
    prefix = str(body.get("NamePrefix") or "")
    out = [_view(s) for s in _src(store).values() if s["State"] != "DELETED" and s["Name"].startswith(prefix)]
    return _eb().EventsResponse(body={"EventSources": sorted(out, key=lambda x: x["Name"])})


def activate_event_source(store, body):
    eb = _eb()
    s = _require(store, body.get("Name"))
    if not s.get("bus"):
        raise eb._E("InvalidStateException", f"Event source {s['Name']} has no associated event bus; create an event bus with EventSourceName first.")
    s["State"] = "ACTIVE"
    store.persist()
    return eb.EventsResponse(body={})


def deactivate_event_source(store, body):
    eb = _eb()
    s = _require(store, body.get("Name"))
    if s["State"] != "ACTIVE":
        raise eb._E("InvalidStateException", f"Event source {s['Name']} is not active.")
    s["State"] = "PENDING"
    store.persist()
    return eb.EventsResponse(body={})


def associate_bus(store, bus_name: str, source_name: str) -> None:
    """CreateEventBus(Name=<source>, EventSourceName=<source>) hook: validates and turns the source ACTIVE."""
    eb = _eb()
    if bus_name != source_name:
        raise eb._E("ValidationException", "The event bus name must be the same as the event source name.")
    s = _require(store, source_name)
    if s["State"] == "ACTIVE" and s.get("bus"):
        raise eb._E("ResourceAlreadyExistsException", f"Event source {source_name} is already associated with an event bus.")
    s["bus"], s["State"] = bus_name, "ACTIVE"


def bus_deleted(store, bus_name: str) -> None:
    for s in _src(store).values():
        if s.get("bus") == bus_name and s["State"] != "DELETED":
            s["bus"], s["State"] = None, "DELETED"


def put_partner_events(store, body, lam_store=None, kinesis_store=None, sfn_store=None):
    eb = _eb()
    entries = body.get("Entries") or []
    if not entries or len(entries) > 20:
        raise eb._E("ValidationException", "Entries must contain between 1 and 20 items.")
    out = []
    for e in entries:
        src = _src(store).get(str(e.get("Source") or ""))
        if not e.get("Source") or not e.get("DetailType") or e.get("Detail") in (None, ""):
            out.append({"ErrorCode": "InvalidArgument", "ErrorMessage": "Parameter Source, DetailType and Detail are required."})
            continue
        if not src or src["State"] == "DELETED":
            out.append({"ErrorCode": "ResourceNotFoundException", "ErrorMessage": f"Partner event source {e.get('Source')} does not exist."})
            continue
        if src["State"] != "ACTIVE" or not src.get("bus"):
            out.append({"ErrorCode": "InvalidStateException", "ErrorMessage": f"Partner event source {src['Name']} is {src['State']}; the customer has not associated it with an event bus."})
            continue
        try:
            json.loads(e["Detail"]) if isinstance(e["Detail"], str) else None
        except Exception:
            out.append({"ErrorCode": "MalformedDetail", "ErrorMessage": "Detail is not valid JSON."})
            continue
        r = eb._put_events(store, {"Entries": [{"EventBusName": src["bus"], "Source": src["Name"], "DetailType": e["DetailType"],
                                                 "Detail": e["Detail"], "Resources": e.get("Resources") or []}]},
                           lam_store, kinesis_store, sfn_store)
        out.append(r.body["Entries"][0])
    failed = sum(1 for x in out if "ErrorCode" in x)
    return eb.EventsResponse(body={"FailedEntryCount": failed, "Entries": out})


OPS = {
    "CreatePartnerEventSource": create_partner_event_source, "DeletePartnerEventSource": delete_partner_event_source,
    "DescribePartnerEventSource": describe_partner_event_source, "ListPartnerEventSources": list_partner_event_sources,
    "ListPartnerEventSourceAccounts": list_partner_event_source_accounts, "DescribeEventSource": describe_event_source,
    "ListEventSources": list_event_sources, "ActivateEventSource": activate_event_source,
    "DeactivateEventSource": deactivate_event_source,
}
