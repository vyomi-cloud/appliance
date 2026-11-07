"""Azure Network Watcher packet capture (Microsoft.Network/networkWatchers/{nw}/packetCaptures) -- pure Python, Nano + offline.

Real ARM resource with the real contract:
  PUT  .../networkWatchers/{nw}/packetCaptures/{name}   create AND start a capture (a capture cannot be updated)
  GET  .../packetCaptures/{name}  |  GET .../packetCaptures (list)  |  DELETE .../packetCaptures/{name}
  POST .../packetCaptures/{name}/stop          -> stop (stopReason Manual)
  POST .../packetCaptures/{name}/queryStatus   -> {name,id,captureStartTime,packetCaptureStatus,stopReason,packetCaptureError}
Validated like the service: the network watcher must exist, the target must be an existing VM / VM scale set in the SAME region as the
watcher, a storage account (storageId) or a guest filePath is required, bytesToCapturePerPacket >= 0, totalBytesPerSession <= 1 GiB,
timeLimitInSeconds 1..18000, <= 10 filters with protocol TCP|UDP|Any and well-formed IP / port lists ("a;b", "a-b", CIDR).

WHAT IS CAPTURED (honest -- see core/capabilities/azure/nsgs.json): the simulator has no packet data plane, so a "packet" is
reconstructed from the flow records the simulator really produces while a capture is Running:
  * offline (Docker backend, netsim enforcement on): the per-flow nftables counter deltas of traffic that PASSED the forward chain
    (``ingest_flows`` is called from core/netsim/wiring.deliver_flows with the same delta rows that feed NSG flow logs);
  * Nano / offline: every flow the shared netsim EVALUATOR allows for the target VM -- ipFlowVerify and connectivityCheck calls
    (``record_evaluated`` is called from core/azure_arm_core.py) -- becomes one probe packet.
Denied flows are never captured. Each flow record becomes ONE libpcap record (Ethernet + IPv4 + TCP/UDP/ICMP header, header bytes
only; ``caplen`` = header length, ``origlen`` = the flow's average packet size, so the file is a legal snaplen-truncated capture).
There is NO payload, no handshake/retransmit detail and no per-packet timing: the pcap opens in Wireshark/tcpdump and the 5-tuples,
counts, MACs and TTLs are the flow's, but it is a flow summary in pcap clothing, not a wire capture. When the capture stops
(Manual, TimeExceeded, BytesExceeded or delete) the .cap file is written into
``network-watcher-logs/subscriptions/<id>/resourcegroups/<rg>/providers/microsoft.compute/virtualmachines/<vm>/<yyyy>/<mm>/<dd>/
packetcapture_<HH_MM_SS>.<ms>.cap`` of the target storage account (real layout). A filePath-only capture keeps its bytes in the
simulator (no guest filesystem is written).
"""
from __future__ import annotations

import datetime
import ipaddress
import re
import struct
import time
import uuid

PC_T = "Microsoft.Network/networkWatchers/packetCaptures"
PC_LOW = PC_T.lower()
NW_LOW = "microsoft.network/networkwatchers"
VM_LOW = "microsoft.compute/virtualmachines"
VMSS_LOW = "microsoft.compute/virtualmachinescalesets"
STORAGE_LOW = "microsoft.storage/storageaccounts"
CONTAINER = "network-watcher-logs"
MAX_SESSION_BYTES = 1073741824
MAX_TIME = 18000
PROTOS = {"tcp": 6, "udp": 17, "icmp": 1}
MAX_PACKETS = 100000


class _E(Exception):
    def __init__(self, status, code, msg):
        super().__init__(msg)
        self.status, self.code, self.msg = status, code, msg


def _err(status, code, msg):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200):
    return {"status": status, "headers": {}, "body": body}


def _now_dt():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc)


# ── filters ─────────────────────────────────────────────────────────────────────────────
def _ip_terms(text):
    out = []
    for t in str(text or "").split(";"):
        t = t.strip()
        if not t:
            continue
        try:
            if "-" in t:
                a, b = (ipaddress.ip_address(x.strip()) for x in t.split("-", 1))
                out.append((int(a), int(b)))
            elif "/" in t:
                n = ipaddress.ip_network(t, strict=False)
                out.append((int(n.network_address), int(n.broadcast_address)))
            else:
                a = ipaddress.ip_address(t)
                out.append((int(a), int(a)))
        except ValueError:
            raise _E(400, "InvalidPacketCaptureFilter", f"'{t}' is not a valid IP address, IP range (a-b) or CIDR in a packet capture filter.")
    return out


def _port_terms(text):
    out = []
    for t in str(text or "").split(";"):
        t = t.strip()
        if not t:
            continue
        m = re.fullmatch(r"(\d{1,5})(?:-(\d{1,5}))?", t)
        if not m or int(m.group(1)) > 65535 or (m.group(2) and (int(m.group(2)) > 65535 or int(m.group(2)) < int(m.group(1)))):
            raise _E(400, "InvalidPacketCaptureFilter", f"'{t}' is not a valid port or port range (a-b) in a packet capture filter.")
        out.append((int(m.group(1)), int(m.group(2) or m.group(1))))
    return out


def _validate_filters(filters):
    if filters is None:
        return []
    if not isinstance(filters, list) or len(filters) > 10:
        raise _E(400, "InvalidPacketCaptureFilter", "A packet capture accepts at most 10 filters.")
    out = []
    for f in filters:
        f = dict(f or {})
        proto = str(f.get("protocol") or "Any")
        if proto.lower() not in ("tcp", "udp", "any"):
            raise _E(400, "InvalidPacketCaptureFilter", "filters[].protocol must be TCP, UDP or Any.")
        f["protocol"] = {"tcp": "TCP", "udp": "UDP", "any": "Any"}[proto.lower()]
        _ip_terms(f.get("localIPAddress"))
        _ip_terms(f.get("remoteIPAddress"))
        _port_terms(f.get("localPort"))
        _port_terms(f.get("remotePort"))
        out.append({k: v for k, v in f.items() if v not in (None, "")})
    return out


def _in(terms, val):
    return not terms or any(a <= val <= b for a, b in terms)


def _matches(filters, local_ip, remote_ip, lport, rport, proto):
    """A packet is kept when it satisfies ANY filter (filters are OR-ed, fields inside one filter AND-ed); no filters = everything."""
    if not filters:
        return True
    lip, rip = int(ipaddress.ip_address(local_ip)), int(ipaddress.ip_address(remote_ip))
    for f in filters:
        fp = f.get("protocol", "Any")
        if fp != "Any" and PROTOS[fp.lower()] != proto:
            continue
        if _in(_ip_terms(f.get("localIPAddress")), lip) and _in(_ip_terms(f.get("remoteIPAddress")), rip) \
                and _in(_port_terms(f.get("localPort")), lport) and _in(_port_terms(f.get("remotePort")), rport):
            return True
    return False


# ── target resolution ───────────────────────────────────────────────────────────────────
def _vm_nics(state, vm):
    out = []
    for n in ((vm.get("properties") or {}).get("networkProfile") or {}).get("networkInterfaces") or []:
        nic = state.get(str(n.get("id", "")).lower())
        if nic:
            out.append(nic)
    return out


def _target_addrs(state, target_id):
    """[(private_ip, mac)] and public ips of the target VM (or every instance of a scale set)."""
    t = state.get(target_id.lower())
    if t is None:
        return []
    low = (t.get("_type") or "").lower()
    vms = [t] if low == VM_LOW else [r for r in state.values() if isinstance(r, dict) and (r.get("_type") or "").lower() == "microsoft.compute/virtualmachinescalesets/virtualmachines"
                                       and str(r.get("id", "")).lower().startswith(target_id.lower() + "/")]
    out = []
    for vm in vms:
        for nic in _vm_nics(state, vm):
            np = nic.get("properties") or {}
            mac = str(np.get("macAddress") or "").replace("-", ":").lower()
            for ic in np.get("ipConfigurations") or []:
                ip = (ic.get("properties") or {}).get("privateIPAddress")
                if ip:
                    out.append((ip, mac or _mac_for(ip)))
    return out


def _mac_for(ip):
    o = [int(x) for x in ip.split(".")]
    return "00:0d:3a:%02x:%02x:%02x" % (o[1], o[2], o[3])


# ── pcap synthesis ──────────────────────────────────────────────────────────────────────
def _csum(b):
    if len(b) % 2:
        b += b"\0"
    s = sum(struct.unpack("!%dH" % (len(b) // 2), b))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF


def _mac_bytes(m):
    return bytes(int(x, 16) for x in m.split(":"))


def build_frame(src, dst, proto, sport, dport, avg_len, smac, dmac, flags="syn"):
    """Ethernet+IPv4+(TCP|UDP|ICMP) HEADERS only. Returns (header_bytes, original_frame_length)."""
    if proto == 6:
        fl = 0x02 if flags == "syn" else 0x18
        l4 = struct.pack("!HHIIBBHHH", sport, dport, 0x1000 + (sport << 8 & 0xFFFF), 0, 5 << 4, fl, 64240, 0, 0)
    elif proto == 17:
        l4 = struct.pack("!HHHH", sport, dport, 8, 0)
    else:
        l4 = struct.pack("!BBHHH", 8, 0, 0, sport & 0xFFFF, 1)
        l4 = l4[:2] + struct.pack("!H", _csum(l4)) + l4[4:]
    total = max(20 + len(l4), int(avg_len))
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total, 0, 0x4000, 64, proto, 0,
                     ipaddress.ip_address(src).packed, ipaddress.ip_address(dst).packed)
    ip = ip[:10] + struct.pack("!H", _csum(ip)) + ip[12:]
    if proto in (6, 17):       # L4 checksum over the pseudo header (header-only: payload counted as zeros, so it is advisory)
        pseudo = ip[12:20] + struct.pack("!BBH", 0, proto, total - 20)
        ck = _csum(pseudo + l4)
        off = 16 if proto == 6 else 6
        l4 = l4[:off] + struct.pack("!H", ck) + l4[off + 2:]
    eth = _mac_bytes(dmac) + _mac_bytes(smac) + b"\x08\x00"
    return eth + ip + l4, 14 + total


def build_pcap(packets, snaplen):
    """packets: [(ts_float, header_bytes, orig_len)] -> libpcap bytes (little endian, LINKTYPE_ETHERNET)."""
    snap = snaplen if snaplen else 65535
    out = [struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, snap, 1)]
    for ts, hdr, orig in packets:
        cap = hdr[:snap]
        sec = int(ts)
        out.append(struct.pack("<IIII", sec, int((ts - sec) * 1_000_000), len(cap), orig) + cap)
    return b"".join(out)


# ── record <-> view ─────────────────────────────────────────────────────────────────────
def _rid(sub, rg, nw, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkWatchers/{nw}/packetCaptures/{name}"


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _captures(state):
    return [r for r in state.values() if isinstance(r, dict) and (r.get("_type") or "").lower() == PC_LOW]


def _status(rec):
    return {"name": rec["name"], "id": rec["id"], "captureStartTime": rec["_start"], "packetCaptureStatus": rec["_status"],
            "stopReason": rec.get("_stop_reason") or ("" if rec["_status"] == "Running" else "Unknown"),
            "packetCaptureError": list(rec.get("_errors") or []),
            "vyomiSummary": {"packets": rec.get("_packets", len(rec.get("_pkts") or [])), "bytes": rec.get("_bytes", 0), "flows": rec.get("_flows", 0),
                             "file": rec.get("_blob", "")}}


# ── lifecycle ───────────────────────────────────────────────────────────────────────────
def _blob_path(rec):
    start = _parse_iso(rec["_start"])
    tid = rec["properties"]["target"].lower().lstrip("/")
    return f"{tid}/{start:%Y}/{start:%m}/{start:%d}/packetcapture_{start:%H_%M_%S}.{start.microsecond // 1000:03d}.cap"


def _finalize(rec, reason, blob_store, blob_mod):
    if rec["_status"] != "Running":
        return
    rec["_status"], rec["_stop_reason"] = "Stopped", reason
    pk = [(p[0], bytes.fromhex(p[1]), p[2]) for p in rec["_pkts"]]
    data = build_pcap(pk, rec["properties"].get("bytesToCapturePerPacket") or 0)
    rec["_cap_bytes"], rec["_packets"] = len(data), len(pk)
    st = rec["properties"]["storageLocation"]
    if st.get("storageId"):
        acct = st["storageId"].rsplit("/", 1)[-1].lower()
        try:
            if blob_store is None or blob_mod is None:
                raise RuntimeError("no blob store")
            ck = f"{acct}/{CONTAINER}"
            if not blob_store.container_exists(ck):
                blob_store.create_container(ck)
            path = _blob_path(rec)
            r = blob_mod.dispatch(blob_store, "PUT", f"/{CONTAINER}/{path}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/octet-stream"}, data, account=acct)
            if r.status >= 300:
                raise RuntimeError(r.status)
            rec["_blob"] = f"{acct}/{CONTAINER}/{path}"
        except Exception as e:                        # the capture itself ran; delivery failed
            rec["_status"] = "Error"
            rec["_errors"] = ["StorageAccountDeliveryFailed"]
            rec["_deliver_error"] = str(e)[:200]
    else:
        rec["_file"] = data.hex() if len(data) <= 1_000_000 else ""
    rec["_pkts"] = []


def _refresh(rec, blob_store=None, blob_mod=None):
    if rec["_status"] != "Running":
        return
    p = rec["properties"]
    if time.time() - rec["_t0"] >= p["timeLimitInSeconds"]:
        _finalize(rec, "TimeExceeded", blob_store, blob_mod)


def _add_packet(rec, ts, hdr, orig, blob_store=None, blob_mod=None):
    p = rec["properties"]
    rec["_pkts"].append([ts, hdr.hex(), orig])
    rec["_bytes"] = rec.get("_bytes", 0) + orig
    if rec["_bytes"] >= p["totalBytesPerSession"] or len(rec["_pkts"]) >= MAX_PACKETS:
        _finalize(rec, "BytesExceeded", blob_store, blob_mod)


def _feed(state, ev, blob_store=None, blob_mod=None):
    """Offer one allowed flow event {src,dst,proto,sport,dport,packets,bytes,ts} to every Running capture whose target VM owns an end."""
    n = 0
    caps = [r for r in _captures(state) if r["_status"] == "Running"]
    if not caps:
        return 0
    addrs = {}
    for rec in caps:
        _refresh(rec, blob_store, blob_mod)
        if rec["_status"] != "Running":
            continue
        tid = rec["properties"]["target"]
        mine = addrs.get(tid) or addrs.setdefault(tid, _target_addrs(state, tid))
        for ip, mac in mine:
            if ip == ev["src"]:
                local, remote, lp, rp, smac, dmac = ev["src"], ev["dst"], ev["sport"], ev["dport"], mac, _mac_for(ev["dst"])
            elif ip == ev["dst"]:
                local, remote, lp, rp, smac, dmac = ev["dst"], ev["src"], ev["dport"], ev["sport"], _mac_for(ev["src"]), mac
            else:
                continue
            if not _matches(rec["properties"].get("filters") or [], local, remote, lp, rp, ev["proto"]):
                continue
            avg = max(40, ev["bytes"] // max(ev["packets"], 1))
            hdr, orig = build_frame(ev["src"], ev["dst"], ev["proto"], ev["sport"], ev["dport"], avg, smac, dmac,
                                    flags="syn" if ev.get("bytes", 0) == 0 or ev.get("source") == "evaluator" else "data")
            _add_packet(rec, ev["ts"], hdr, orig, blob_store, blob_mod)
            rec["_flows"] = rec.get("_flows", 0) + 1
            n += 1
            break
    return n


def ingest_flows(state, rows, blob_store=None, blob_mod=None, now=None):
    """netsim delta rows (ACCEPT only) -> Running captures. Called from core/netsim/wiring.deliver_flows."""
    n = 0
    ts = float(now if now is not None else time.time())
    for r in rows or []:
        if r.get("action", "ACCEPT") != "ACCEPT":
            continue
        n += _feed(state, {"src": r["src"], "dst": r["dst"], "proto": int(r["proto"]), "sport": int(r["sport"]), "dport": int(r["dport"]),
                           "packets": int(r.get("packets", 1)), "bytes": int(r.get("bytes", 0)), "ts": ts, "source": "netsim"}, blob_store, blob_mod)
    return n


def record_evaluated(state, local_ip, remote_ip, direction, proto, lport, rport, allowed, blob_store=None, blob_mod=None):
    """One flow the shared netsim evaluator ruled on (ipFlowVerify / connectivityCheck). Allowed -> one probe packet."""
    if not allowed or not local_ip or not remote_ip:
        return 0
    try:
        ipaddress.ip_address(local_ip), ipaddress.ip_address(remote_ip)
    except ValueError:
        return 0
    inbound = str(direction).lower() == "inbound"
    src, dst = (remote_ip, local_ip) if inbound else (local_ip, remote_ip)
    sport, dport = (rport, lport) if inbound else (lport, rport)
    return _feed(state, {"src": src, "dst": dst, "proto": PROTOS.get(str(proto).lower(), 6), "sport": int(sport or 49152), "dport": int(dport or 0),
                         "packets": 1, "bytes": 0, "ts": time.time(), "source": "evaluator"}, blob_store, blob_mod)


# ── ARM surface ─────────────────────────────────────────────────────────────────────────
def handles(chain):
    return len(chain) >= 3 and chain[0].lower() == "networkwatchers" and chain[2].lower() == "packetcaptures"


def _create(state, sub, rg, nw_name, name, payload):
    nw = state.get(f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkWatchers/{nw_name}".lower())
    if nw is None:
        raise _E(404, "ResourceNotFound", f"The Resource 'Microsoft.Network/networkWatchers/{nw_name}' under resource group '{rg}' was not found.")
    props = (payload or {}).get("properties") or {}
    target = str(props.get("target") or "")
    if not target:
        raise _E(400, "InvalidRequestFormat", "properties.target is required (a virtual machine or virtual machine scale set id).")
    t = state.get(target.lower())
    if t is None or (t.get("_type") or "").lower() not in (VM_LOW, VMSS_LOW):
        raise _E(400, "InvalidResourceReference", f"Resource {target} referenced by the packet capture was not found or is not a virtual machine / scale set.")
    if (t.get("location") or "").lower() != (nw.get("location") or "").lower():
        raise _E(400, "NetworkWatcherNotInRegion", f"The target {target} is in {t.get('location')} but network watcher {nw_name} is in {nw.get('location')}; "
                                                   "a packet capture needs a network watcher in the target's region.")
    st = props.get("storageLocation") or {}
    sid, fpath = str(st.get("storageId") or ""), str(st.get("filePath") or "")
    if not sid and not fpath:
        raise _E(400, "InvalidRequestFormat", "properties.storageLocation must have a storageId (storage account) or a filePath.")
    if sid:
        sa = state.get(sid.lower())
        if sa is None or (sa.get("_type") or "").lower() != STORAGE_LOW:
            raise _E(400, "InvalidResourceReference", f"Storage account {sid} referenced by the packet capture was not found.")
    ints = {}
    for key, default, lo, hi in (("bytesToCapturePerPacket", 0, 0, 4294967295), ("totalBytesPerSession", MAX_SESSION_BYTES, 1, MAX_SESSION_BYTES),
                                 ("timeLimitInSeconds", MAX_TIME, 1, MAX_TIME)):
        v = props.get(key, default)
        if not isinstance(v, int) or isinstance(v, bool) or v < lo or v > hi:
            raise _E(400, "InvalidRequestFormat", f"properties.{key} must be an integer between {lo} and {hi}.")
        ints[key] = v
    filters = _validate_filters(props.get("filters"))
    rid = _rid(sub, rg, nw_name, name)
    if rid.lower() in state:
        raise _E(400, "PacketCaptureAlreadyExists", f"A packet capture named '{name}' already exists on network watcher '{nw_name}'. Packet captures cannot be updated; delete it first.")
    start = _now_dt()
    rec = {"id": rid, "name": name, "type": PC_T, "_type": PC_LOW, "etag": f'W/"{uuid.uuid4()}"',
           "properties": {"provisioningState": "Succeeded", "target": target, "targetType": "AzureVM" if (t.get("_type") or "").lower() == VM_LOW else "AzureVMSS",
                          **ints, "storageLocation": {k: v for k, v in {"storageId": sid, "filePath": fpath}.items() if v}, "filters": filters},
           "_start": _iso(start), "_t0": time.time(), "_status": "Running", "_pkts": [], "_bytes": 0}
    if sid:
        rec["properties"]["storageLocation"]["storagePath"] = f"https://{sid.rsplit('/', 1)[-1].lower()}.blob.core.windows.net/{CONTAINER}/{_blob_path(rec)}"
    state[rid.lower()] = rec
    return rec


def dispatch(state, method, sub, rg, chain, payload=None, query=None, blob_store=None, blob_mod=None):
    method = (method or "GET").upper()
    if rg is None:
        return _err(400, "InvalidResourceId", "packetCaptures must be addressed within a resource group.")
    try:
        nw = chain[1]
        if len(chain) == 3:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            pre = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkWatchers/{nw}/packetCaptures/".lower()
            if state.get(f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkWatchers/{nw}".lower()) is None:
                raise _E(404, "ResourceNotFound", f"The Resource 'Microsoft.Network/networkWatchers/{nw}' under resource group '{rg}' was not found.")
            items = [r for r in _captures(state) if r["id"].lower().startswith(pre)]
            for r in items:
                _refresh(r, blob_store, blob_mod)
            return _ok({"value": [_view(r) for r in sorted(items, key=lambda r: r["name"].lower())]})
        name = chain[3]
        rid = _rid(sub, rg, nw, name)
        rec = state.get(rid.lower())
        if len(chain) == 4:
            if method == "PUT":
                rec = _create(state, sub, rg, nw, name, payload)
                return _ok(_view(rec), 201)
            if rec is None and method in ("GET",):
                raise _E(404, "ResourceNotFound", f"The Resource 'Microsoft.Network/networkWatchers/{nw}/packetCaptures/{name}' under resource group '{rg}' was not found.")
            if method == "GET":
                _refresh(rec, blob_store, blob_mod)
                return _ok(_view(rec))
            if method == "DELETE":
                if rec is None:
                    return _ok(None, 204)
                _finalize(rec, "Manual", blob_store, blob_mod)       # deleting a running capture stops it first; the file is kept
                state.pop(rid.lower(), None)
                return _ok(None, 204)
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        if len(chain) == 5 and method == "POST" and chain[4].lower() in ("stop", "querystatus"):
            if rec is None:
                raise _E(404, "ResourceNotFound", f"The Resource 'Microsoft.Network/networkWatchers/{nw}/packetCaptures/{name}' under resource group '{rg}' was not found.")
            _refresh(rec, blob_store, blob_mod)
            if chain[4].lower() == "stop":
                if rec["_status"] == "Running":
                    _finalize(rec, "Manual", blob_store, blob_mod)
                return _ok(None, 200)
            return _ok(_status(rec))
        return _err(404, "ResourceTypeNotSupported", f"The resource type 'networkWatchers/{'/'.join(chain[2:])}' is not supported.")
    except _E as e:
        return _err(e.status, e.code, e.msg)


def packet_count(rec):
    return rec.get("_packets", len(rec.get("_pkts") or []))
