"""GCP VPC firewall enforcement via in-container iptables.

Translates GCP firewall rules into iptables rules installed *inside* each
governed Compute (LXD) instance, so traffic between instances really obeys the
rules. The base policy stays full access (ACCEPT) — a dedicated CL_FW chain
returns by default and only adds explicit ACCEPT/DROP entries from the rules, so
ungoverned instances and the no-rules case are never restricted.

Enforcement is opt-in per space (enforce_vpc). The simulator drives the rules
through the runtime bridge (`lxc exec <container> -- sh -c "<iptables...>"`).
"""

from __future__ import annotations

_CHAIN = "CL_FW"


def _norm_ports(entry: dict) -> list[str]:
    ports = entry.get("ports") or []
    if not isinstance(ports, list):
        ports = [ports]
    out = []
    for p in ports:
        p = str(p).strip().replace("-", ":")  # GCP "8000-8010" -> iptables "8000:8010"
        if p:
            out.append(p)
    return out


_EGRESS_CHAIN = "CL_FW_EGRESS"


def _rule_lines(firewall_rules: list[dict]) -> tuple[list[str], list[str]]:
    """Return (allow_lines, deny_lines) of iptables CL_FW append commands."""
    allow_lines: list[str] = []
    deny_lines: list[str] = []
    for rule in firewall_rules or []:
        if not isinstance(rule, dict) or rule.get("disabled"):
            continue
        direction = str(rule.get("direction") or "INGRESS").upper()
        if direction == "EGRESS":
            # EGRESS rules use the OUTPUT chain with destinationRanges
            destinations = rule.get("destinationRanges") or ["0.0.0.0/0"]
            if not isinstance(destinations, list) or not destinations:
                destinations = ["0.0.0.0/0"]
            for spec, action, bucket in (("allowed", "RETURN", allow_lines), ("denied", "DROP", deny_lines)):
                for entry in (rule.get(spec) or []):
                    if not isinstance(entry, dict):
                        continue
                    proto = str(entry.get("IPProtocol") or entry.get("protocol") or "all").lower()
                    ports = _norm_ports(entry)
                    for dst in destinations:
                        base = f"iptables -A {_EGRESS_CHAIN} -d {dst}"
                        if proto in ("tcp", "udp") and ports:
                            for port in ports:
                                bucket.append(f"{base} -p {proto} --dport {port} -j {action}")
                        elif proto in ("tcp", "udp"):
                            bucket.append(f"{base} -p {proto} -j {action}")
                        elif proto in ("icmp", "1"):
                            bucket.append(f"{base} -p icmp -j {action}")
                        else:
                            bucket.append(f"{base} -j {action}")
            continue
        if direction != "INGRESS":
            continue
        sources = rule.get("sourceRanges") or ["0.0.0.0/0"]
        if not isinstance(sources, list) or not sources:
            sources = ["0.0.0.0/0"]
        for spec, action, bucket in (("allowed", "RETURN", allow_lines), ("denied", "DROP", deny_lines)):
            for entry in (rule.get(spec) or []):
                if not isinstance(entry, dict):
                    continue
                proto = str(entry.get("IPProtocol") or entry.get("protocol") or "all").lower()
                ports = _norm_ports(entry)
                for src in sources:
                    base = f"iptables -A {_CHAIN} -s {src}"
                    if proto in ("tcp", "udp") and ports:
                        for port in ports:
                            bucket.append(f"{base} -p {proto} --dport {port} -j {action}")
                    elif proto in ("tcp", "udp"):
                        bucket.append(f"{base} -p {proto} -j {action}")
                    elif proto in ("icmp", "1"):
                        bucket.append(f"{base} -p icmp -j {action}")
                    else:
                        bucket.append(f"{base} -j {action}")
    return allow_lines, deny_lines


def build_script(firewall_rules: list[dict]) -> str:
    """Idempotent shell script that (re)programs the CL_FW ingress chain and
    the CL_FW_EGRESS output chain. With no DROP rules the result is full access
    (everything RETURNs to the ACCEPT base)."""
    allow_lines, deny_lines = _rule_lines(firewall_rules)
    lines = [
        # Ingress chain
        f"iptables -N {_CHAIN} 2>/dev/null || true",
        f"iptables -F {_CHAIN}",
        f"iptables -C INPUT -j {_CHAIN} 2>/dev/null || iptables -I INPUT -j {_CHAIN}",
        # never break loopback or return traffic
        f"iptables -A {_CHAIN} -i lo -j RETURN",
        f"iptables -A {_CHAIN} -m state --state ESTABLISHED,RELATED -j RETURN",
        # Egress chain
        f"iptables -N {_EGRESS_CHAIN} 2>/dev/null || true",
        f"iptables -F {_EGRESS_CHAIN}",
        f"iptables -C OUTPUT -j {_EGRESS_CHAIN} 2>/dev/null || iptables -I OUTPUT -j {_EGRESS_CHAIN}",
        f"iptables -A {_EGRESS_CHAIN} -o lo -j RETURN",
        f"iptables -A {_EGRESS_CHAIN} -m state --state ESTABLISHED,RELATED -j RETURN",
    ]
    # allow rules first so a specific ACCEPT can override a broader DROP;
    # de-dup while preserving order (multiple rules can yield identical entries).
    seen: set[str] = set()
    for line in allow_lines + deny_lines:
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return "; ".join(lines)


def clear_script() -> str:
    """Flush and unhook CL_FW and CL_FW_EGRESS — restores full access."""
    return (
        f"iptables -D INPUT -j {_CHAIN} 2>/dev/null || true; iptables -F {_CHAIN} 2>/dev/null || true; "
        f"iptables -D OUTPUT -j {_EGRESS_CHAIN} 2>/dev/null || true; iptables -F {_EGRESS_CHAIN} 2>/dev/null || true"
    )


def rule_applies(rule: dict, instance_tags: list[str]) -> bool:
    """A rule with no targetTags applies to every instance in the network;
    otherwise the instance must carry at least one of the target tags."""
    target_tags = rule.get("targetTags") or []
    if not isinstance(target_tags, list) or not target_tags:
        return True
    tags = set(str(t) for t in (instance_tags or []))
    return any(str(t) in tags for t in target_tags)
