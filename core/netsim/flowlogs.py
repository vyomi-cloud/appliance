"""netsim flow logs — turn the enforcer's per-flow nft counters into cloud flow-log records.

Hook (enforce.py): every packet that PASSES the space's forward chain updates the dynamic
set `flows`, every packet that is DROPPED updates `rejects` — both keyed by the 5-tuple
`saddr . daddr . l4proto . sport . dport` with per-element packet/byte counters. Reading
them is `nft -j list set inet vyomi_<space> flows|rejects` (no kernel log, no privileges
beyond NET_ADMIN). This module is pure: it parses that JSON and aggregates snapshots into
capture windows the way the clouds do.

Formats:
  AWS  VPC Flow Logs default format v2 (space-separated, per ENI, both directions):
       version account-id interface-id srcaddr dstaddr srcport dstport protocol packets bytes
       start end action log-status
  GCP  VPC Flow Logs JSON-ish record (connection{src_ip,dest_ip,src_port,dest_port,protocol},
       bytes_sent, packets_sent, start_time, end_time, reporter SRC|DEST) — ACCEPT flows only,
       like real VPC flow logs (denials go to Firewall Rules Logging)
  Azure NSG flow log v2 flow tuple:
       unixtime,srcIP,dstIP,srcPort,dstPort,T|U,I|O,A|D,B|C|E,pktsS2D,bytesS2D,pktsD2S,bytesD2S
"""
from __future__ import annotations

import datetime
import json

_PROTO_NUM = {"tcp": 6, "udp": 17, "icmp": 1}


def parse_nft_set(js) -> list:
    """`nft -j list set …` → [{src,dst,proto,sport,dport,packets,bytes}]"""
    doc = json.loads(js) if isinstance(js, (str, bytes)) else js
    out = []
    for item in doc.get("nftables", []):
        st = item.get("set")
        if not st:
            continue
        for e in st.get("elem", []) or []:
            el = e.get("elem", e) if isinstance(e, dict) else {}
            val = el.get("val", el) if isinstance(el, dict) else e
            concat = val.get("concat") if isinstance(val, dict) else None
            if not concat or len(concat) != 5:
                continue
            src, dst, proto, sport, dport = concat
            ctr = el.get("counter") or {}
            p = _PROTO_NUM.get(str(proto).lower(), proto)
            out.append({"src": src, "dst": dst, "proto": int(p), "sport": int(sport), "dport": int(dport),
                        "packets": int(ctr.get("packets", 0)), "bytes": int(ctr.get("bytes", 0))})
    return out


class FlowLogCollector:
    """Accumulates snapshots (call `ingest` periodically, e.g. every 60 s = AWS's 1-minute
    aggregation interval) and emits records for the counter DELTAS since the last ingest."""

    def __init__(self, topo, account_id: str = "123456789012"):
        self.topo = topo
        self.account_id = account_id
        self._last: dict = {}          # (action, 5-tuple) -> (packets, bytes)
        self._window_start: int | None = None
        self.windows: list = []        # [(start, end, [delta rows])]

    def ingest(self, accepted: list, rejected: list, now: int | None = None) -> list:
        now = int(now if now is not None else datetime.datetime.now(datetime.timezone.utc).timestamp())
        start = self._window_start if self._window_start is not None else now - 60
        rows = []
        for action, flows in (("ACCEPT", accepted), ("REJECT", rejected)):
            for f in flows:
                key = (action, f["src"], f["dst"], f["proto"], f["sport"], f["dport"])
                pp, pb = self._last.get(key, (0, 0))
                dp, db = f["packets"] - pp, f["bytes"] - pb
                if dp < 0:              # set element expired and came back → counters restarted
                    dp, db = f["packets"], f["bytes"]
                self._last[key] = (f["packets"], f["bytes"])
                if dp > 0:
                    rows.append({**f, "packets": dp, "bytes": db, "action": action})
        self.windows.append((start, now, rows))
        self._window_start = now
        return rows

    # ── AWS ──
    def aws_rows(self) -> list:
        """Structured v2+ rows, one per OUR-ENI the flow touches (the cloud logs a flow on each ENI)."""
        out = []
        for start, end, rows in self.windows:
            for r in rows:
                for ip in dict.fromkeys((r["src"], r["dst"])):
                    iface = self.topo.iface_by_ip(ip)
                    if iface is None or iface.ip != ip:
                        continue
                    sub = self.topo.subnets.get(iface.subnet)
                    out.append({"version": 2, "account-id": self.account_id, "interface-id": iface.id, "srcaddr": r["src"], "dstaddr": r["dst"],
                                "srcport": r["sport"], "dstport": r["dport"], "protocol": r["proto"], "packets": r["packets"], "bytes": r["bytes"],
                                "start": start, "end": end, "action": r["action"], "log-status": "OK",
                                "vpc-id": getattr(sub, "network", "") or "-", "subnet-id": iface.subnet, "instance-id": iface.instance or "-",
                                "pkt-srcaddr": r["src"], "pkt-dstaddr": r["dst"],
                                "flow-direction": "egress" if ip == r["src"] else "ingress", "type": "IPv4"})
        return out

    def aws_records(self) -> list:
        return [" ".join(str(row[k]) for k in ("version", "account-id", "interface-id", "srcaddr", "dstaddr", "srcport", "dstport", "protocol",
                                                  "packets", "bytes", "start", "end", "action", "log-status")) for row in self.aws_rows()]

    # ── GCP ──
    def gcp_records(self) -> list:
        out = []
        for start, end, rows in self.windows:
            for r in rows:
                if r["action"] != "ACCEPT":
                    continue
                for reporter, ip in (("SRC", r["src"]), ("DEST", r["dst"])):
                    iface = self.topo.iface_by_ip(ip)
                    if iface is None or iface.ip != ip:
                        continue
                    out.append({
                        "connection": {"src_ip": r["src"], "dest_ip": r["dst"], "src_port": r["sport"],
                                       "dest_port": r["dport"], "protocol": r["proto"]},
                        "bytes_sent": str(r["bytes"]), "packets_sent": str(r["packets"]),
                        "start_time": _iso(start), "end_time": _iso(end), "reporter": reporter,
                        ("src_instance" if reporter == "SRC" else "dest_instance"): {
                            "vm_name": iface.instance, "zone": self.topo.subnet_of(iface).zone},
                    })
        return out

    # ── Azure ──
    def azure_rows(self) -> list:
        """One entry per (NSG, flow, role): {nsg, iface, rule, tuple}. `rule` is the NSG rule that decided the
        flow, found by the shared evaluator (DefaultRule_<n> for implied rules, UserRule_<n> otherwise)."""
        try:
            from core.netsim import evaluate as ev
            from core.netsim.model import EGRESS, INGRESS
        except ImportError:                                   # pragma: no cover - flat layout
            import evaluate as ev                             # type: ignore
            from model import EGRESS, INGRESS                 # type: ignore
        out = []
        for _start, end, rows in self.windows:
            for r in rows:
                proto = {6: "T", 17: "U"}.get(r["proto"], "T")
                pname = {6: "tcp", 17: "udp", 1: "icmp"}.get(r["proto"], "tcp")
                for direction, own, other in (("O", r["src"], r["dst"]), ("I", r["dst"], r["src"])):
                    iface = self.topo.iface_by_ip(own)
                    if iface is None or iface.ip != own:
                        continue
                    sub = self.topo.subnets.get(iface.subnet)
                    d = EGRESS if direction == "O" else INGRESS
                    for nsg_id in list(iface.rulesets) + list(getattr(sub, "rulesets", []) or []):
                        rs = self.topo.rulesets.get(nsg_id)
                        if rs is None or rs.kind != "nsg":
                            continue
                        dport = r["dport"] if direction == "I" else r["dport"]
                        allowed, desc = ev.eval_priority(self.topo, rs, d, pname, dport, other, self.topo.iface_by_ip(other), iface, r["sport"])
                        label = desc.split(" ")[0]
                        rule = next((x for x in rs.rules if x.name == label), None)
                        rname = ("DefaultRule_" if rule is not None and rule.implied else "UserRule_") + label
                        # an allowed flow that a LATER layer denied is still logged with this NSG's own decision
                        decision = "A" if (allowed and r["action"] == "ACCEPT") else "D"
                        state = "C" if decision == "A" else "B"
                        out.append({"nsg": nsg_id, "iface": iface.id, "rule": rname,
                                    "tuple": f"{end},{r['src']},{r['dst']},{r['sport']},{r['dport']},{proto},{direction},{decision},{state},{r['packets']},{r['bytes']},0,0"})
        return out

    def azure_tuples(self) -> list:
        out = []
        for _start, end, rows in self.windows:
            for r in rows:
                proto = {6: "T", 17: "U"}.get(r["proto"], "T")
                for direction, ip in (("O", r["src"]), ("I", r["dst"])):
                    iface = self.topo.iface_by_ip(ip)
                    if iface is None or iface.ip != ip:
                        continue
                    decision = "A" if r["action"] == "ACCEPT" else "D"
                    state = "C" if decision == "A" else "B"
                    out.append(f"{end},{r['src']},{r['dst']},{r['sport']},{r['dport']},{proto},{direction},"
                               f"{decision},{state},{r['packets']},{r['bytes']},0,0")
        return out


def _iso(ts: int) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
