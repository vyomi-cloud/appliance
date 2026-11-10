"""Azure Service Bus AMQP 1.0 data plane — the dialect the NATIVE Service Bus SDKs speak.

`ServiceBusAmqp` is a core/amqp10.Container: it sits on the protocol engine and binds the Service Bus
semantics to the SAME `MessagingStore` the REST surface (core/azure_servicebus_core.py) uses, so the
console's Service Bus Explorer and stock `azure-servicebus` / `@azure/service-bus` clients see ONE state.
Substrate-free (no sockets, no asyncio): offline it is driven by core/amqp_server.py (TCP + WebSocket),
on Nano by the relay's WebSocket bridge into the tab's Pyodide. Loads under Pyodide.

Dialect implemented
  * `$cbs` put-token (token accepted + recorded on the connection, never verified)
  * entity addressing: queue, topic/Subscriptions/sub, either with /$DeadLetterQueue, plus
    <entity>/$management (peek, receive-by-sequence-number, update-disposition, schedule / cancel,
    renew-lock, renew-session-lock, get/set-session-state, get-message-sessions, add/remove/enumerate rules)
  * sender links (accepted / rejected dispositions, batch message format 0x80013700, scheduled enqueue,
    duplicate detection, session enforcement) and receiver links (peek-lock + receive-and-delete,
    session filter incl. next-available, lock tokens as delivery tags, x-opt-* annotations)
  * settlement: accepted=complete, released/modified(delivery-failed)=abandon, modified(undeliverable)=defer,
    rejected=dead-letter, lock expiry, MaxDeliveryCount and TTL dead-lettering
Entity state shape (extends the REST core's): owner = topic/queue dict or subscription dict with
`messages`, `dead_letter`, `scheduled` lists, optional `rules`, `_slocks`, `_sstate`, and options
`lock_duration`, `max_delivery_count`, `requires_session`, `requires_duplicate_detection`,
`dead_lettering_on_expiration`, `default_ttl`.
"""
from __future__ import annotations

import json
import threading
import uuid as _uuid
from datetime import datetime, timezone

try:
    from core import amqp10 as A
    from core import azure_servicebus_rules as R
except ImportError:  # pragma: no cover - Pyodide flat layout
    import amqp10 as A  # type: ignore
    import azure_servicebus_rules as R  # type: ignore

VENDOR = "com.microsoft:"
SESSION_FILTER = VENDOR + "session-filter"
BATCH_FORMAT = 0x80013700
DEFAULT_LOCK_S = 60
DEFAULT_MAX_DELIVERY = 10
_TICKS_EPOCH = 621355968000000000


class SbError(Exception):
    def __init__(self, condition, description, status=400):
        super().__init__(description)
        self.condition, self.description, self.status = condition, description, status


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(t: float) -> int:
    return int(t * 1000)


def _plain(v):
    """JSON-persistable view of an AMQP value (the REST core's `properties` map is persisted as JSON)"""
    if v is None or isinstance(v, (bool, int, float)):
        return int(v) if isinstance(v, A.Timestamp) else v
    if isinstance(v, (bytes, bytearray)):
        try:
            return bytes(v).decode("utf-8")
        except Exception:
            return bytes(v).hex()
    if isinstance(v, _uuid.UUID):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return str(v)


def _idstr(v):
    if v is None:
        return None
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return str(v)


# ── addressing ──────────────────────────────────────────────────────────────
class Node:
    __slots__ = ("kind", "entity", "ename", "sub", "dlq", "owner", "topic", "raw")

    def __init__(self):
        self.kind = "entity"        # entity | mgmt | cbs
        self.entity = self.ename = self.sub = self.owner = self.topic = None
        self.dlq = False
        self.raw = ""

    @property
    def box_name(self):
        return "dead_letter" if self.dlq else "messages"

    def box(self):
        return self.owner.setdefault(self.box_name, [])


def parse_address(store, address) -> Node:
    n = Node()
    a = str(address or "").strip()
    for pre in ("sb://", "amqp://", "amqps://", "ws://", "wss://", "http://", "https://"):
        if a.lower().startswith(pre):
            a = a[len(pre):].split("/", 1)[1] if "/" in a[len(pre):] else ""
    a = a.strip("/")
    n.raw = a.lower()
    if a.lower() == "$cbs":
        n.kind = "cbs"
        return n
    segs = [s for s in a.split("/") if s]
    if not segs:
        raise SbError("amqp:not-found", "The messaging entity '' could not be found.", 404)
    if segs[-1].lower() == "$management":
        n.kind = "mgmt"
        segs = segs[:-1]
    if segs and segs[-1].lower() == "$deadletterqueue":
        n.dlq = True
        segs = segs[:-1]
    if len(segs) >= 2 and segs[-2].lower() == "$transfer":
        segs = segs[:-2]
    if not segs:
        raise SbError("amqp:not-found", "The messaging entity '%s' could not be found." % a, 404)
    topics = store.topics
    name = segs[0]
    if name not in topics:
        for k in topics:
            if k.lower() == name.lower():
                name = k
                break
    ent = topics.get(name)
    if not isinstance(ent, dict):
        raise SbError("amqp:not-found", "The messaging entity '%s' could not be found." % ("/".join(segs)), 404)
    n.entity, n.ename, n.owner, n.topic = ent, name, ent, ent
    if len(segs) >= 3 and segs[1].lower() == "subscriptions":
        sname = segs[2]
        subs = ent.get("subscriptions") or {}
        if sname not in subs:
            for k in subs:
                if k.lower() == sname.lower():
                    sname = k
                    break
        if sname not in subs:
            raise SbError("amqp:not-found", "The messaging entity '%s' could not be found." % ("/".join(segs)), 404)
        n.sub, n.owner = sname, subs[sname]
    elif len(segs) > 1:
        raise SbError("amqp:not-found", "The messaging entity '%s' could not be found." % ("/".join(segs)), 404)
    return n


def _opt(owner, node_topic, key, default):
    v = owner.get(key)
    if v is None and node_topic is not None and node_topic is not owner:
        v = node_topic.get(key)
    return default if v is None else v


# ── sequence numbers ────────────────────────────────────────────────────────
def alloc_seq(store) -> int:
    cur = getattr(store, "_sb_seq", None)
    if cur is None:
        cur = 0
        for t in store.topics.values():
            for lst in _all_lists(t):
                for m in lst:
                    cur = max(cur, int(m.get("SequenceNumber") or 0))
    cur += 1
    store._sb_seq = cur
    return cur


def _all_lists(entity):
    yield entity.get("messages", [])
    yield entity.get("dead_letter", [])
    yield entity.get("scheduled", [])
    for s in (entity.get("subscriptions") or {}).values():
        yield s.get("messages", [])
        yield s.get("dead_letter", [])
        yield s.get("scheduled", [])


def _all_owners(store):
    for t in store.topics.values():
        if not isinstance(t, dict):
            continue
        yield t
        for s in (t.get("subscriptions") or {}).values():
            yield s


# ── message <-> wire ────────────────────────────────────────────────────────
def message_from_amqp(store, parsed: dict, now: float) -> dict:
    props, app = parsed["properties"], parsed["application_properties"]
    body = b""
    kind = parsed["body_kind"]
    if kind == "data":
        body = b"".join(bytes(x) for x in parsed["body"] if isinstance(x, (bytes, bytearray)))
    elif parsed["body"]:
        v = parsed["body"][0]
        body = bytes(v) if isinstance(v, (bytes, bytearray)) else (v.encode("utf-8") if isinstance(v, str)
                                                                     else json.dumps(_plain(v)).encode())
    mid = _idstr(props.get("message_id")) or str(_uuid.uuid4())
    anns = {k: v for k, v in parsed["message_annotations"].items()
            if str(k) not in ("x-opt-sequence-number", "x-opt-enqueued-time", "x-opt-locked-until",
                              "x-opt-enqueue-sequence-number")}
    uprops = {str(k): _plain(v) for k, v in app.items()}
    if props.get("subject"):
        uprops["Label"] = props["subject"]
    ttl = (parsed["header"] or {}).get("ttl")
    m = {
        "_id": _uuid.uuid4().hex, "SequenceNumber": None, "MessageId": mid, "body": body,
        "content_type": props.get("content_type") or "application/octet-stream",
        "properties": uprops, "EnqueuedTimeUtc": _iso(now), "DeliveryCount": 0, "_locked": None, "_deferred": False,
        "_wire": parsed["rest"], "_anns": A.encode(anns) if anns else b"", "_enq": now,
        "_session": props.get("group_id"),
    }
    if ttl:
        m["_expires"] = now + int(ttl) / 1000.0
    elif props.get("absolute_expiry_time"):
        m["_expires"] = int(props["absolute_expiry_time"]) / 1000.0
    return m


def _wire_of(m: dict) -> bytes:
    w = m.get("_wire")
    if w:
        return w
    props = {"message_id": m.get("MessageId"), "content_type": m.get("content_type") or None}
    app = {}
    for k, v in (m.get("properties") or {}).items():
        if k == "Label":
            props["subject"] = str(v)
        else:
            app[str(k)] = v if isinstance(v, (str, int, float, bool)) or v is None else str(v)
    return A.build_message(properties=props, application_properties=app or None,
                           raw_body=A.data_section(m.get("body") or b""))


def encode_message(m: dict, locked_until: float | None = None, with_header=True) -> bytes:
    anns = {}
    if m.get("_anns"):
        try:
            anns.update(A.decode(m["_anns"])[0])
        except Exception:
            pass
    anns[A.Symbol("x-opt-sequence-number")] = int(m["SequenceNumber"])
    anns[A.Symbol("x-opt-enqueued-time")] = A.Timestamp(_ms(m.get("_enq") or 0))
    if locked_until:
        anns[A.Symbol("x-opt-locked-until")] = A.Timestamp(_ms(locked_until))
    header = None
    if with_header:
        header = {"durable": True, "delivery_count": max(int(m.get("DeliveryCount") or 0) - 1, 0)}
        if m.get("_expires") and m.get("_enq"):
            header["ttl"] = max(int((m["_expires"] - m["_enq"]) * 1000), 0)
    return A.build_message(header=header, message_annotations=anns, raw_body=_wire_of(m))


def view_of(m: dict) -> dict:
    sysv = {"MessageId": m.get("MessageId"), "ContentType": m.get("content_type"), "SessionId": m.get("_session"),
            "Label": (m.get("properties") or {}).get("Label")}
    w = m.get("_wire")
    user = {}
    if w:
        try:
            p = A.parse_message(w)
            pr = p["properties"]
            sysv.update(To=pr.get("to"), CorrelationId=_idstr(pr.get("correlation_id")), ReplyTo=pr.get("reply_to"),
                        ReplyToSessionId=pr.get("reply_to_group_id"), Label=pr.get("subject"))
            user = {str(k): v for k, v in p["application_properties"].items()}
        except Exception:
            pass
    else:
        user = dict(m.get("properties") or {})
    return {"sys": sysv, "user": user}


# ── broker operations over the store ────────────────────────────────────────
class Broker:
    """Service Bus semantics over MessagingStore.topics. All methods take the store explicitly."""

    def __init__(self, now=None):
        self._now = now

    def now(self, store):
        return self._now() if self._now else store.now()

    # -- enqueue
    def enqueue(self, store, node: Node, m: dict, scheduled_at: float | None = None):
        owner = node.owner
        if node.dlq:
            raise SbError("amqp:not-allowed", "Cannot send to a dead-letter queue.")
        ent = node.entity
        if node.sub is not None:
            raise SbError("amqp:not-allowed", "Cannot send to a subscription.")
        if _opt(ent, None, "requires_session", False) and not m.get("_session"):
            raise SbError("amqp:invalid-field", "The SessionId property must be set for entities that require sessions.")
        if _opt(ent, None, "requires_duplicate_detection", False):
            dd = ent.setdefault("_dedupe", {})
            now = self.now(store)
            for k in [k for k, t in dd.items() if now - t > 600]:
                dd.pop(k, None)
            if m["MessageId"] in dd:
                return None
            dd[m["MessageId"]] = now
        dttl = _opt(ent, None, "default_ttl", None)
        if dttl and not m.get("_expires"):
            m["_expires"] = m["_enq"] + float(dttl)
        m["SequenceNumber"] = alloc_seq(store)
        if scheduled_at:
            m["_sched_at"] = scheduled_at
            ent.setdefault("scheduled", []).append(m)
            return m["SequenceNumber"]
        self._deliver_to_boxes(store, ent, m)
        return m["SequenceNumber"]

    def _deliver_to_boxes(self, store, ent, m):
        subs = ent.get("subscriptions") or {}
        if subs:
            view = view_of(m)
            first = True
            for s in subs.values():
                if not R.subscription_matches(s, view):
                    continue
                c = dict(m)
                c["_id"] = _uuid.uuid4().hex
                c["SequenceNumber"] = m["SequenceNumber"] if first else alloc_seq(store)
                first = False
                s.setdefault("messages", []).append(c)
        else:
            ent.setdefault("messages", []).append(m)

    # -- settlement
    def find_locked(self, store, token):
        for o in _all_owners(store):
            for name in ("messages", "dead_letter"):
                for m in o.get(name, []):
                    if m.get("_locked") == token:
                        return o, name, m
        return None

    def complete(self, store, owner, boxname, m):
        owner[boxname] = [x for x in owner.get(boxname, []) if x["_id"] != m["_id"]]

    def abandon(self, store, owner, boxname, m, props=None):
        m["_locked"] = None
        m.pop("_lock_until", None)
        m.pop("_lock_link", None)
        if props:
            self._modify_props(m, props)
        topic = self._topic_of(store, owner)
        mx = int(_opt(owner, topic, "max_delivery_count", DEFAULT_MAX_DELIVERY))
        if boxname == "messages" and int(m.get("DeliveryCount") or 0) >= mx:
            self.deadletter(store, owner, boxname, m, "MaxDeliveryCountExceeded",
                            "Message could not be consumed after %d delivery attempts." % mx)

    def defer(self, store, owner, boxname, m, props=None):
        m["_locked"] = None
        m["_deferred"] = True
        m.pop("_lock_until", None)
        m.pop("_lock_link", None)
        if props:
            self._modify_props(m, props)

    def deadletter(self, store, owner, boxname, m, reason=None, desc=None, props=None):
        owner[boxname] = [x for x in owner.get(boxname, []) if x["_id"] != m["_id"]]
        if boxname == "dead_letter":
            return
        m["_locked"] = None
        m["_deferred"] = False
        m.pop("_lock_until", None)
        m.pop("_lock_link", None)
        if props:
            self._modify_props(m, props)
        extra = {}
        if reason:
            extra["DeadLetterReason"] = str(reason)
        if desc:
            extra["DeadLetterErrorDescription"] = str(desc)
        self._modify_props(m, extra)
        m["DeadLetterReason"] = reason
        owner.setdefault("dead_letter", []).append(m)

    def _modify_props(self, m, props):
        if not props:
            return
        try:
            p = A.parse_message(_wire_of(m))
        except Exception:
            return
        app = dict(p["application_properties"])
        for k, v in props.items():
            app[A.Symbol(str(k)) if False else str(k)] = v
        m["_wire"] = A.build_message(properties=p["properties"], application_properties=app,
                                     raw_body=p["raw_body"], footer=p["footer"] or None)
        m["properties"] = {**(m.get("properties") or {}), **{str(k): _plain(v) for k, v in props.items()}}

    def _topic_of(self, store, owner):
        for t in store.topics.values():
            if isinstance(t, dict) and any(s is owner for s in (t.get("subscriptions") or {}).values()):
                return t
        return None

    # -- timers
    def tick(self, store):
        now = self.now(store)
        changed = False
        for ent in [e for e in store.topics.values() if isinstance(e, dict)]:
            for sc in list(ent.get("scheduled", [])):
                if sc.get("_sched_at", 0) <= now:
                    ent["scheduled"] = [x for x in ent["scheduled"] if x["_id"] != sc["_id"]]
                    sc.pop("_sched_at", None)
                    sc["_enq"] = now
                    sc["EnqueuedTimeUtc"] = _iso(now)
                    self._deliver_to_boxes(store, ent, sc)
                    changed = True
        for o in _all_owners(store):
            topic = self._topic_of(store, o) if o.get("subscriptions") is None and o.get("name") else None
            for m in list(o.get("messages", [])):
                if m.get("_locked") and m.get("_lock_until") and m["_lock_until"] <= now:
                    self.abandon(store, o, "messages", m)
                    changed = True
            for m in list(o.get("messages", [])):
                if m.get("_expires") and m["_expires"] <= now and not m.get("_locked"):
                    if _opt(o, topic, "dead_lettering_on_expiration", False):
                        self.deadletter(store, o, "messages", m, "TTLExpiredException",
                                        "The message expired and was dead lettered.")
                    else:
                        self.complete(store, o, "messages", m)
                    changed = True
        return changed

    # -- lookups by sequence number
    def find_seq(self, owner, boxname, seq):
        for m in owner.get(boxname, []):
            if int(m.get("SequenceNumber") or -1) == int(seq):
                return m
        return None


# ── the Container ───────────────────────────────────────────────────────────
class ServiceBusAmqp(A.Container):
    def __init__(self, get_store, persist=None, now=None):
        self.get_store = get_store
        self.persist = persist or (lambda: None)
        self.broker = Broker(now)
        self.lock = threading.RLock()
        self.consumers = set()
        self.dirty = False
        self.stats = {"connections": 0, "sent": 0, "delivered": 0}

    # -- engine callbacks -----------------------------------------------------
    def on_open(self, conn):
        self.stats["connections"] += 1

    def on_close(self, conn):
        pass

    def _s(self):
        return self.get_store()

    def on_attach(self, link):
        with self.lock:
            store = self._s()
            try:
                node = parse_address(store, link.address)
                if node.kind == "mgmt" or node.kind == "cbs":
                    link.ctx["node"] = node
                    if node.kind == "mgmt" and node.entity is None:
                        raise SbError("amqp:not-found", "not found")
                    return None
                link.ctx["node"] = node
                if link.sender:
                    return self._attach_consumer(store, link, node)
                if node.dlq:
                    raise SbError("amqp:not-allowed", "Cannot send to a dead-letter queue.")
                return None
            except SbError as e:
                return (e.condition, e.description)

    def _attach_consumer(self, store, link, node):
        fields = A.terminus_fields(link.source)
        flt = fields.get("filter") or {}
        sid, want_session = None, False
        for k, v in flt.items():
            if str(k) == SESSION_FILTER:
                want_session = True
                v = v.value if isinstance(v, A.Described) else v
                sid = v.decode() if isinstance(v, (bytes, bytearray)) else (str(v) if v is not None else None)
        link.ctx["peek"] = link.snd_settle_mode != 1
        link.ctx["sess"] = None
        requires = bool(_opt(node.owner, node.topic, "requires_session", False))
        if requires and not want_session:
            raise SbError("amqp:not-allowed", "It is not possible for an entity that requires sessions to create a non-sessionful message receiver.")
        if want_session and not requires and node.kind == "entity":
            raise SbError("amqp:not-allowed", "It is not possible for an entity that does not require sessions to create a sessionful message receiver.")
        if want_session:
            now = self.broker.now(store)
            locks = node.owner.setdefault("_slocks", {})
            me = "%x" % id(link)
            live = {s: l for s, l in locks.items() if self._lock_alive(l)}
            node.owner["_slocks"] = locks = live
            if sid is None:
                cands = sorted({m.get("_session") for m in node.box() if m.get("_session")
                                and not m.get("_deferred")}, key=lambda s: min(
                    int(x["SequenceNumber"]) for x in node.box() if x.get("_session") == s))
                cands = [s for s in cands if s not in locks]
                if not cands:
                    raise SbError(VENDOR + "timeout", "No unlocked sessions were available")
                sid = cands[0]
            elif sid in locks and locks[sid]["link"] != me:
                raise SbError(VENDOR + "session-cannot-be-locked", "The requested session '%s' cannot be accepted. It may be locked by another receiver." % sid, 409)
            until = now + float(_opt(node.owner, node.topic, "lock_duration", DEFAULT_LOCK_S))
            locks[sid] = {"link": me, "until": until}
            link.ctx["sess"] = sid
            link.ctx["sess_lock"] = (node.owner, sid, me)
            link.source = A.terminus(A.D_SOURCE, fields.get("address"), durable=fields.get("durable"),
                                     expiry_policy=fields.get("expiry_policy"), timeout=fields.get("timeout"),
                                     dynamic=fields.get("dynamic"), filter={A.Symbol(SESSION_FILTER): sid},
                                     default_outcome=fields.get("default_outcome"), outcomes=fields.get("outcomes"))
            link.attach_props = {A.Symbol(VENDOR + "locked-until-utc"): int(until * 10_000_000) + _TICKS_EPOCH}
        self.consumers.add(link)
        return None

    def _lock_alive(self, l):
        return l and l.get("link") in self._live_links

    @property
    def _live_links(self):
        return {"%x" % id(lk) for lk in self.consumers if not lk.closed}

    def on_detach(self, link):
        with self.lock:
            self.consumers.discard(link)
            store = self._s()
            sl = link.ctx.get("sess_lock")
            if sl:
                owner, sid, me = sl
                (owner.get("_slocks") or {}).pop(sid, None)
            lid = "%x" % id(link)
            for o in _all_owners(store):
                for m in list(o.get("messages", [])):
                    if m.get("_lock_link") == lid and m.get("_locked"):
                        self.broker.abandon(store, o, "messages", m)
                for m in list(o.get("dead_letter", [])):
                    if m.get("_lock_link") == lid:
                        m["_locked"] = None
                        m.pop("_lock_link", None)
            self.dirty = True

    # -- inbound transfers ----------------------------------------------------
    def on_transfer(self, link, delivery):
        with self.lock:
            store = self._s()
            node = link.ctx.get("node")
            try:
                if node.kind == "cbs":
                    self._cbs(link, delivery)
                    return A.delivery_state(A.D_ACCEPTED)
                if node.kind == "mgmt":
                    self._mgmt(store, link, node, delivery)
                    self.dirty = True
                    return A.delivery_state(A.D_ACCEPTED)
                now = self.broker.now(store)
                if delivery.format == BATCH_FORMAT:
                    msgs = []
                    outer = A.parse_message(delivery.payload)
                    for part in outer["body"]:
                        msgs.append(A.parse_message(bytes(part)))
                else:
                    msgs = [A.parse_message(delivery.payload)]
                for parsed in msgs:
                    m = message_from_amqp(store, parsed, now)
                    sched = parsed["message_annotations"].get(A.Symbol("x-opt-scheduled-enqueue-time")) \
                        or parsed["message_annotations"].get("x-opt-scheduled-enqueue-time")
                    at = int(sched) / 1000.0 if sched else None
                    self.broker.enqueue(store, node, m, at if at and at > now else None)
                self.stats["sent"] += len(msgs)
                self.dirty = True
                return A.delivery_state(A.D_ACCEPTED)
            except SbError as e:
                return A.delivery_state(A.D_REJECTED, A.error(e.condition, e.description))
            except Exception as e:  # malformed message
                if A.TRACE:
                    import traceback
                    traceback.print_exc()
                return A.delivery_state(A.D_REJECTED, A.error("amqp:decode-error", "invalid message: %s" % e))

    # -- credit / settlement for consumers -----------------------------------
    def on_flow(self, link):
        with self.lock:
            self._pump_link(self._s(), link)

    def on_disposition(self, link, delivery, state, settled):
        with self.lock:
            token = delivery.data
            if not token:
                return
            store = self._s()
            found = self.broker.find_locked(store, token)
            if not found:
                return
            owner, boxname, m = found
            self._apply_state(store, owner, boxname, m, state)
            self.dirty = True
            self._pump_all(store)

    def _apply_state(self, store, owner, boxname, m, state):
        k = A.state_kind(state)
        v = state.value if isinstance(state, A.Described) and isinstance(state.value, list) else []
        if k == A.D_ACCEPTED or state is None:
            self.broker.complete(store, owner, boxname, m)
        elif k == A.D_RELEASED:
            self.broker.abandon(store, owner, boxname, m)
        elif k == A.D_MODIFIED:
            failed = bool(v[0]) if len(v) > 0 else False
            undeliv = bool(v[1]) if len(v) > 1 else False
            anns = v[2] if len(v) > 2 and isinstance(v[2], dict) else None
            if undeliv and not failed:
                self.broker.defer(store, owner, boxname, m, anns)
            else:
                self.broker.abandon(store, owner, boxname, m, anns)
        elif k == A.D_REJECTED:
            err = v[0] if v else None
            info, reason, desc = {}, None, None
            if isinstance(err, A.Described) and isinstance(err.value, list):
                desc = err.value[1] if len(err.value) > 1 else None
                info = err.value[2] if len(err.value) > 2 and isinstance(err.value[2], dict) else {}
            for kk, vv in info.items():
                if str(kk) == "DeadLetterReason":
                    reason = vv
                elif str(kk) == "DeadLetterErrorDescription":
                    desc = vv
            self.broker.deadletter(store, owner, boxname, m, reason or "DeadLetterReasonNotSpecified", desc,
                                   {str(kk): vv for kk, vv in info.items() if str(kk) not in
                                    ("DeadLetterReason", "DeadLetterErrorDescription")} or None)

    # -- the pump -------------------------------------------------------------
    def pump(self):
        """periodic: expire locks / TTL, release scheduled, push to credit-holding consumers. True if state changed."""
        with self.lock:
            store = self._s()
            changed = self.broker.tick(store)
            self._pump_all(store)
            if changed:
                self.dirty = True
            return changed

    def push(self):
        """after any inbound I/O: hand freshly enqueued messages to consumers that hold credit"""
        with self.lock:
            self._pump_all(self._s())

    def _pump_all(self, store):
        for lk in list(self.consumers):
            if lk.closed:
                self.consumers.discard(lk)
                continue
            self._pump_link(store, lk)

    def _pump_link(self, store, link):
        if link.closed or not link.attached or link.credit <= 0:
            return
        node = link.ctx.get("node")
        if node is None or node.kind != "entity":
            return
        try:
            node = parse_address(store, link.address)     # entity may have been deleted / replaced
        except SbError:
            link.detach(A.error("amqp:not-found", "entity deleted"))
            self.consumers.discard(link)
            return
        link.ctx["node"] = node
        presettled = not link.ctx.get("peek", True)
        topic = node.topic
        lock_s = float(_opt(node.owner, topic, "lock_duration", DEFAULT_LOCK_S))
        now = self.broker.now(store)
        sid = link.ctx.get("sess")
        moved = False
        while link.credit > 0 and link.window_open():
            m = None
            for x in node.box():
                if x.get("_locked") or x.get("_deferred"):
                    continue
                if x.get("_expires") and x["_expires"] <= now:
                    continue
                if sid is not None and x.get("_session") != sid:
                    continue
                m = x
                break
            if m is None:
                break
            m["DeliveryCount"] = int(m.get("DeliveryCount") or 0) + 1
            if presettled:
                node.owner[node.box_name] = [x for x in node.box() if x["_id"] != m["_id"]]
                payload = encode_message(m)
                link.send_transfer(payload, _uuid.uuid4().bytes, settled=True)
            else:
                token = str(_uuid.uuid4())
                m["_locked"] = token
                m["_lock_until"] = now + lock_s
                m["_lock_link"] = "%x" % id(link)
                payload = encode_message(m, locked_until=m["_lock_until"])
                d = link.send_transfer(payload, _uuid.UUID(token).bytes_le, settled=False)
                d.data = token
            self.stats["delivered"] += 1
            moved = True
        if moved:
            self.dirty = True
            link.conn.kick()

    # -- $cbs -----------------------------------------------------------------
    def _reply_link(self, link, reply_to):
        node = link.ctx["node"]
        best = None
        for sess in link.conn.sessions.values():
            for lk in sess.links.values():
                if lk.sender and not lk.closed and lk.ctx.get("node") is not None and lk.ctx["node"].raw == node.raw:
                    if best is None:
                        best = lk
                    t = A.terminus_fields(lk.target).get("address")
                    if reply_to and (t == reply_to or lk.address == reply_to):
                        best = lk
        return best

    def _respond(self, req_link, parsed, status, body, desc="OK", cond=None):
        cbs = req_link.ctx["node"].kind == "cbs"
        reply_to = parsed["properties"].get("reply_to")
        out = self._reply_link(req_link, reply_to)
        if A.TRACE:
            print("SB respond", status, desc, "link", out and out.credit, flush=True)
        if out is None or out.credit <= 0:
            return
        app = ({"status-code": status, "status-description": desc} if cbs else
               {"statusCode": status, "statusDescription": desc})
        if cond:
            app["error-condition" if cbs else "errorCondition"] = A.Symbol(cond)
        props = {"correlation_id": parsed["properties"].get("message_id"), "to": reply_to}
        payload = A.build_message(properties=props, application_properties=app,
                                  raw_body=A.encode(A.Described(A.ULong(A.D_VALUE), body)))
        out.send_transfer(payload, _uuid.uuid4().bytes, settled=True)
        link_conn = req_link.conn
        link_conn.kick()

    def _cbs(self, link, delivery):
        p = A.parse_message(delivery.payload)
        app = {str(k): v for k, v in p["application_properties"].items()}
        if str(app.get("operation")) == "put-token":
            tok = p["body"][0] if p["body"] else None
            if isinstance(tok, (bytes, bytearray)):
                tok = bytes(tok).decode("utf-8", "replace")
            link.conn.ctx.setdefault("tokens", {})[str(app.get("name"))] = {"type": str(app.get("type")), "token": tok}
            self._respond(link, p, 202, None, "Accepted")
        else:
            self._respond(link, p, 400, None, "Unsupported CBS operation", "amqp:not-implemented")

    # -- $management ----------------------------------------------------------
    def _mgmt(self, store, link, node, delivery):
        p = A.parse_message(delivery.payload)
        app = {str(k): v for k, v in p["application_properties"].items()}
        op = str(app.get("operation") or "")
        body = p["body"][0] if p["body"] and isinstance(p["body"][0], dict) else {}
        body = {str(k): v for k, v in body.items()}
        # re-resolve (the entity may have changed since attach)
        try:
            node = parse_address(store, link.address)
        except SbError as e:
            return self._respond(link, p, 404, None, e.description, VENDOR + "entity-not-found")
        fn = getattr(self, "_op_" + op.replace(VENDOR, "").replace("-", "_").replace(":", "_"), None)
        if fn is None:
            return self._respond(link, p, 501, None, "Unsupported management operation '%s'" % op, "amqp:not-implemented")
        try:
            res = fn(store, node, body, link)
        except SbError as e:
            return self._respond(link, p, e.status, None, e.description, e.condition)
        status, rbody = res if isinstance(res, tuple) else (200, res)
        self._respond(link, p, status, rbody)

    def _box(self, node, sess=None):
        return node.box()

    def _op_peek_message(self, store, node, b, link):
        frm = int(b.get("from-sequence-number") or 0)
        cnt = int(b.get("message-count") or 1)
        sid = b.get("session-id")
        msgs = sorted((m for m in node.box() if int(m["SequenceNumber"]) >= frm
                       and (sid is None or m.get("_session") == sid)), key=lambda m: int(m["SequenceNumber"]))[:cnt]
        if not msgs:
            return 204, None
        return 200, {"messages": [{"message": encode_message(m, with_header=True)} for m in msgs]}

    def _op_schedule_message(self, store, node, b, link):
        seqs = []
        now = self.broker.now(store)
        for item in b.get("messages") or []:
            raw = item.get("message")
            parsed = A.parse_message(bytes(raw))
            m = message_from_amqp(store, parsed, now)
            if item.get("session-id") and not m.get("_session"):
                m["_session"] = item["session-id"]
            sched = parsed["message_annotations"].get(A.Symbol("x-opt-scheduled-enqueue-time")) \
                or parsed["message_annotations"].get("x-opt-scheduled-enqueue-time")
            at = int(sched) / 1000.0 if sched else now
            seq = self.broker.enqueue(store, node, m, at if at > now else None)
            seqs.append(seq if seq is not None else 0)
        return 200, {"sequence-numbers": seqs}

    def _op_cancel_scheduled_message(self, store, node, b, link):
        wanted = {int(x) for x in b.get("sequence-numbers") or []}
        ent = node.entity
        before = len(ent.get("scheduled", []))
        ent["scheduled"] = [m for m in ent.get("scheduled", []) if int(m["SequenceNumber"]) not in wanted]
        if len(ent["scheduled"]) == before and wanted:
            raise SbError(VENDOR + "message-not-found", "Scheduled message not found", 404)
        return 200, {}

    def _op_renew_lock(self, store, node, b, link):
        now = self.broker.now(store)
        exps = []
        lock_s = float(_opt(node.owner, node.topic, "lock_duration", DEFAULT_LOCK_S))
        for tok in b.get("lock-tokens") or []:
            found = self.broker.find_locked(store, str(tok))
            if not found:
                raise SbError(VENDOR + "message-lock-lost", "The lock supplied is invalid. Either the lock expired, or the message has already been removed from the queue.", 410)
            found[2]["_lock_until"] = now + lock_s
            exps.append(A.Timestamp(_ms(now + lock_s)))
        return 200, {"expirations": exps}

    def _op_receive_by_sequence_number(self, store, node, b, link):
        now = self.broker.now(store)
        mode = int(b.get("receiver-settle-mode") or 0)     # 0 first (receive-and-delete), 1 second (peek-lock)
        lock_s = float(_opt(node.owner, node.topic, "lock_duration", DEFAULT_LOCK_S))
        out = []
        for sq in b.get("sequence-numbers") or []:
            m = self.broker.find_seq(node.owner, node.box_name, sq)
            if m is None or m.get("_locked"):
                continue
            m["DeliveryCount"] = int(m.get("DeliveryCount") or 0) + 1
            if mode == 0:
                node.owner[node.box_name] = [x for x in node.box() if x["_id"] != m["_id"]]
                out.append({"message": encode_message(m)})
            else:
                tok = str(_uuid.uuid4())
                m["_locked"], m["_lock_until"], m["_deferred"] = tok, now + lock_s, False
                out.append({"message": encode_message(m, locked_until=m["_lock_until"]), "lock-token": _uuid.UUID(tok)})
        if not out:
            raise SbError(VENDOR + "message-not-found", "The message with the given sequence number was not found.", 404)
        return 200, {"messages": out}

    def _op_update_disposition(self, store, node, b, link):
        status = str(b.get("disposition-status") or "").lower()
        props = b.get("properties-to-modify") if isinstance(b.get("properties-to-modify"), dict) else None
        for tok in b.get("lock-tokens") or []:
            found = self.broker.find_locked(store, str(tok))
            if not found:
                raise SbError(VENDOR + "message-lock-lost", "The lock supplied is invalid. Either the lock expired, or the message has already been removed from the queue.", 410)
            owner, boxname, m = found
            if status.startswith("comp"):
                self.broker.complete(store, owner, boxname, m)
            elif status.startswith("aband"):
                self.broker.abandon(store, owner, boxname, m, props)
            elif status.startswith("defer"):
                self.broker.defer(store, owner, boxname, m, props)
            elif status.startswith(("susp", "dead")):
                self.broker.deadletter(store, owner, boxname, m, b.get("deadletter-reason") or "DeadLetterReasonNotSpecified",
                                       b.get("deadletter-description"), props)
            else:
                raise SbError("amqp:invalid-field", "Unknown disposition-status '%s'" % status, 400)
        return 200, {}

    def _sess(self, node, b, create=False):
        sid = b.get("session-id")
        if sid is None:
            raise SbError("amqp:invalid-field", "session-id is required")
        return str(sid)

    def _op_renew_session_lock(self, store, node, b, link):
        sid = self._sess(node, b)
        now = self.broker.now(store)
        lock_s = float(_opt(node.owner, node.topic, "lock_duration", DEFAULT_LOCK_S))
        lk = (node.owner.get("_slocks") or {}).get(sid)
        if lk is None:
            raise SbError(VENDOR + "session-lock-lost", "The session lock has expired on the MessageSession.", 410)
        lk["until"] = now + lock_s
        return 200, {"expiration": A.Timestamp(_ms(now + lock_s))}

    def _op_set_session_state(self, store, node, b, link):
        sid = self._sess(node, b)
        st = b.get("session-state")
        d = node.owner.setdefault("_sstate", {})
        if st is None:
            d.pop(sid, None)
        else:
            d[sid] = bytes(st)
        return 200, {}

    def _op_get_session_state(self, store, node, b, link):
        sid = self._sess(node, b)
        st = (node.owner.get("_sstate") or {}).get(sid)
        return 200, {"session-state": st}

    def _op_get_message_sessions(self, store, node, b, link):
        skip, top = int(b.get("skip") or 0), int(b.get("top") or 100)
        ids = []
        for m in node.box():
            s = m.get("_session")
            if s and s not in ids:
                ids.append(s)
        part = ids[skip:skip + top]
        return 200, {"skip": skip + len(part) if len(ids) > skip + top else 0, "sessions-ids": part}

    # rules ------------------------------------------------------------------
    def _need_sub(self, node):
        if node.sub is None:
            raise SbError("amqp:not-allowed", "Rules can only be managed on a topic subscription.", 400)
        return node.owner

    def _op_add_rule(self, store, node, b, link):
        sub = self._need_sub(node)
        name = str(b.get("rule-name") or "")
        desc = b.get("rule-description") or {}
        if isinstance(desc, A.Described):
            raise SbError("amqp:invalid-field", "unsupported rule-description encoding")
        rules = sub.get("rules")
        if rules is None:
            rules = sub["rules"] = R.default_rules()
        if name in rules:
            raise SbError(VENDOR + "entity-already-exists", "Rule '%s' already exists." % name, 409)
        rule = {"name": name, "type": "true", "sql": "1=1", "action": None}
        desc = {str(k): v for k, v in desc.items()}
        if "sql-filter" in desc:
            expr = str((desc["sql-filter"] or {}).get("expression") or "1=1")
            try:
                R.validate_sql(expr)
            except R.FilterError as e:
                raise SbError("amqp:invalid-field", str(e), 400)
            rule.update(type="sql", sql=expr)
        elif "correlation-filter" in desc:
            c = {str(k): v for k, v in (desc["correlation-filter"] or {}).items()}
            corr = {"correlation_id": c.get("correlation-id"), "message_id": c.get("message-id"), "to": c.get("to"),
                    "reply_to": c.get("reply-to"), "subject": c.get("label"), "session_id": c.get("session-id"),
                    "reply_to_session_id": c.get("reply-to-session-id"), "content_type": c.get("content-type"),
                    "properties": {str(k): _plain(v) for k, v in (c.get("properties") or {}).items()} or None}
            rule.update(type="correlation", correlation=corr)
        elif "true-filter" in desc:
            pass
        if "sql-rule-action" in desc:
            rule["action"] = str((desc["sql-rule-action"] or {}).get("expression") or "") or None
        rules[name] = rule
        return 200, {}

    def _op_remove_rule(self, store, node, b, link):
        sub = self._need_sub(node)
        name = str(b.get("rule-name") or "")
        rules = sub.get("rules")
        if rules is None:
            rules = sub["rules"] = R.default_rules()
        if name not in rules:
            raise SbError(VENDOR + "entity-not-found", "Rule '%s' could not be found." % name, 404)
        rules.pop(name)
        return 200, {}

    def _op_enumerate_rules(self, store, node, b, link):
        sub = self._need_sub(node)
        rules = sub.get("rules")
        if rules is None:
            rules = R.default_rules()
        items = list(rules.values())
        skip, top = int(b.get("skip") or 0), int(b.get("top") or 100)
        out = []
        for r in items[skip:skip + top]:
            t = r.get("type")
            if t == "true":
                f = A.Described(A.ULong(83483426823), [])
            elif t == "false":
                f = A.Described(A.ULong(83483426824), [])
            elif t == "sql":
                f = A.Described(A.ULong(83483426822), [r.get("sql"), 20])
            else:
                c = r.get("correlation") or {}
                f = A.Described(A.ULong(83483426825), [c.get("correlation_id"), c.get("message_id"), c.get("to"),
                                                       c.get("reply_to"), c.get("subject"), c.get("session_id"),
                                                       c.get("reply_to_session_id"), c.get("content_type"),
                                                       c.get("properties")])
            a = A.Described(A.ULong(1335734829062), [r["action"], 20] if r.get("action") else [])
            out.append({"rule-description": A.Described(A.ULong(1335734829060), [f, a, r.get("name")])})
        if not out:
            return 204, None
        return 200, {"rules": out}
