"""Azure NSG → iptables enforcement for LXD-backed Azure VMs.

Mirrors core/gcp_vpc_enforce.py but translates Azure NSG security rule format
instead of GCP firewall rules.
"""
from __future__ import annotations

_CHAIN = "CL_NSG"  # custom chain name


def build_script(rules: list[dict]) -> str:
    """Generate an iptables script from Azure NSG security rules.

    Azure NSG rule format:
    {
        "properties": {
            "priority": 100,
            "direction": "Inbound",  # or "Outbound"
            "access": "Allow",       # or "Deny"
            "protocol": "Tcp",       # Tcp, Udp, Icmp, *
            "sourceAddressPrefix": "*",
            "destinationAddressPrefix": "*",
            "sourcePortRange": "*",
            "destinationPortRange": "22",  # or "80-443"
        }
    }
    """
    lines = [
        "#!/bin/sh",
        "set -e",
        f"iptables -N {_CHAIN} 2>/dev/null || iptables -F {_CHAIN}",
        f"iptables -C INPUT -j {_CHAIN} 2>/dev/null || iptables -I INPUT 1 -j {_CHAIN}",
        f"iptables -C OUTPUT -j {_CHAIN} 2>/dev/null || iptables -I OUTPUT 1 -j {_CHAIN}",
    ]

    # Sort by priority (lower number = higher priority)
    sorted_rules = sorted(rules, key=lambda r: int((r.get("properties") or {}).get("priority", 65000)))

    for rule in sorted_rules:
        props = rule.get("properties") or {}
        direction = str(props.get("direction", "")).lower()
        access = str(props.get("access", "")).upper()
        protocol = str(props.get("protocol", "*")).lower()
        src = str(props.get("sourceAddressPrefix", "*"))
        dst = str(props.get("destinationAddressPrefix", "*"))
        src_port = str(props.get("sourcePortRange", "*"))
        dst_port = str(props.get("destinationPortRange", "*"))

        action = "ACCEPT" if access == "ALLOW" else "DROP"
        chain_dir = "INPUT" if direction == "inbound" else "OUTPUT"

        cmd = f"iptables -A {_CHAIN}"

        if protocol not in ("*", "any", ""):
            proto = protocol.lower()
            if proto == "tcp":
                cmd += " -p tcp"
            elif proto == "udp":
                cmd += " -p udp"
            elif proto == "icmp":
                cmd += " -p icmp"

        if src not in ("*", "", "any") and direction == "inbound":
            cmd += f" -s {src}"
        if dst not in ("*", "", "any") and direction == "outbound":
            cmd += f" -d {dst}"

        if dst_port not in ("*", "", "any") and protocol.lower() in ("tcp", "udp"):
            if "-" in dst_port:
                cmd += f" --dport {dst_port.replace('-', ':')}"
            else:
                cmd += f" --dport {dst_port}"

        cmd += f" -j {action}"
        lines.append(cmd)

    return "\n".join(lines)


def clear_script() -> str:
    """Remove all NSG rules — restore full access."""
    return f"""#!/bin/sh
iptables -D INPUT -j {_CHAIN} 2>/dev/null || true
iptables -D OUTPUT -j {_CHAIN} 2>/dev/null || true
iptables -F {_CHAIN} 2>/dev/null || true
iptables -X {_CHAIN} 2>/dev/null || true
"""


def rule_applies(rule: dict, vm_subnet: str = "") -> bool:
    """Check if an NSG rule applies (Azure NSG rules apply to all VMs in the subnet)."""
    props = rule.get("properties") or {}
    return str(props.get("provisioningState", "")).lower() == "succeeded"
