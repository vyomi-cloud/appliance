# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS console resource-detail model — the data behind each detail tab.

One engine for both substrates: the offline appliance (FastAPI routes over the
server's state dicts) and Nano (the in-browser adapter over the shared registry
stores) call the SAME functions here, so a tab shows the same thing in both.
Pure stdlib (no fastapi / boto3 / sockets) so it loads under Pyodide; vendored
into wasm/core by wasm/build_cores.py.

What lives here is the part of each AWS resource the console's detail tabs read
that the service engines did not model yet, shaped the way the real APIs return
it:

  EC2   default VPC (172.31.0.0/16 + one default subnet per AZ + default SG + IGW),
        launch into it, the launch-wizard security group, the primary network
        interface, the root EBS volume, instance attributes
        (DescribeInstanceAttribute / ModifyInstanceAttribute), user data, the IAM
        instance profile association, state-transition reason, console output,
        the account's serial-console access setting.
  IAM   which identity policies grant actions on a given resource ARN (the
        Permissions tab of every service).

Network state comes in two shapes (offline `vpc_state` and vpc_core's model);
`OfflineNet` / `CoreNet` adapt them to one small interface.
"""
from __future__ import annotations

import fnmatch
import ipaddress
import time
import uuid

REGION = "us-east-1"
DEFAULT_VPC_CIDR = "172.31.0.0/16"
# The default VPC has one default subnet per Availability Zone (us-east-1 has six).
DEFAULT_SUBNETS = [("us-east-1a", "172.31.0.0/20"), ("us-east-1b", "172.31.16.0/20"),
                   ("us-east-1c", "172.31.32.0/20"), ("us-east-1d", "172.31.48.0/20"),
                   ("us-east-1e", "172.31.64.0/20"), ("us-east-1f", "172.31.80.0/20")]


class DetailError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _hex(n: int) -> str:
    return (uuid.uuid4().hex + uuid.uuid4().hex)[:n]


def _all_traffic(source: str, description: str = "") -> dict:
    return {"protocol": "-1", "from_port": None, "to_port": None, "source": source, "description": description}


# ── network adapters ─────────────────────────────────────────────────────────
class OfflineNet:
    """The offline appliance's `vpc_state` (vpcs / subnets / security_groups /
    route_tables / internet_gateways keyed by id, snake_case records)."""

    def __init__(self, state: dict, id_gen=None, now=None):
        self.s = state
        for k in ("vpcs", "subnets", "security_groups", "route_tables", "internet_gateways"):
            self.s.setdefault(k, {})
        self._id = id_gen or (lambda p: f"{p}-{_hex(17)}")
        self._now = now or _now

    def default_vpc(self) -> dict:
        for v in self.s["vpcs"].values():
            if v.get("is_default"):
                return self._vpc_view(v)
        vpc_id, rt_id, sg_id, igw_id = self._id("vpc"), self._id("rtb"), self._id("sg"), self._id("igw")
        now = self._now()
        self.s["vpcs"][vpc_id] = {
            "vpc_id": vpc_id, "name": "", "cidr_block": DEFAULT_VPC_CIDR, "is_default": True,
            "tenancy": "default", "state": "available", "created": now, "tags": [],
            "dhcp_options_id": "dopt-" + vpc_id.split("-", 1)[1][:8], "encryption_controls": "",
            "ipv6_mode": "", "main_route_table_id": rt_id, "default_security_group_id": sg_id,
            "internet_gateway_id": igw_id}
        self.s["internet_gateways"][igw_id] = {"internet_gateway_id": igw_id, "name": "", "attached_vpc_id": vpc_id,
                                               "state": "available", "created": now, "tags": []}
        subnet_ids = []
        for az, cidr in DEFAULT_SUBNETS:
            sid = self._id("subnet")
            subnet_ids.append(sid)
            self.s["subnets"][sid] = {"subnet_id": sid, "vpc_id": vpc_id, "cidr_block": cidr, "availability_zone": az,
                                      "name": "", "route_table_id": rt_id, "default_for_az": True,
                                      "map_public_ip_on_launch": True, "created": now, "tags": []}
        self.s["route_tables"][rt_id] = {
            "route_table_id": rt_id, "vpc_id": vpc_id, "name": "", "is_main": True, "created": now, "tags": [],
            "subnet_ids": subnet_ids,
            "routes": [{"destination": DEFAULT_VPC_CIDR, "target_type": "local", "target_id": "local", "type": "CreateRouteTable", "created": now},
                       {"destination": "0.0.0.0/0", "target_type": "igw", "target_id": igw_id, "type": "CreateRoute", "created": now}]}
        self.s["security_groups"][sg_id] = {
            "security_group_id": sg_id, "vpc_id": vpc_id, "group_name": "default",
            "description": "default VPC security group", "is_default": True, "created": now, "tags": [],
            "ingress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "", "source_sg": sg_id, "description": "", "created": now}],
            "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": "", "description": "", "created": now}]}
        return self._vpc_view(self.s["vpcs"][vpc_id])

    def _vpc_view(self, v: dict) -> dict:
        return {"vpc_id": v["vpc_id"], "cidr": v.get("cidr_block", ""), "is_default": bool(v.get("is_default")),
                "default_sg": v.get("default_security_group_id", "")}

    def vpc(self, vpc_id: str):
        v = self.s["vpcs"].get(vpc_id)
        return self._vpc_view(v) if v else None

    def subnet(self, subnet_id: str):
        s = self.s["subnets"].get(subnet_id)
        if not s:
            return None
        return {"subnet_id": s["subnet_id"], "vpc_id": s.get("vpc_id", ""), "cidr": s.get("cidr_block", ""),
                "az": s.get("availability_zone", ""), "default_for_az": bool(s.get("default_for_az"))}

    def subnets_of(self, vpc_id: str) -> list:
        return [self.subnet(sid) for sid, s in self.s["subnets"].items() if s.get("vpc_id") == vpc_id]

    def sg(self, sg_id: str):
        g = self.s["security_groups"].get(sg_id)
        if not g:
            return None

        def rule(r):
            src = r.get("cidr") or r.get("source_sg") or ""
            return {"protocol": str(r.get("protocol", "-1")), "from_port": r.get("from_port"),
                    "to_port": r.get("to_port"), "source": src, "description": r.get("description", "")}
        return {"group_id": sg_id, "group_name": g.get("group_name") or g.get("name") or sg_id,
                "description": g.get("description", ""), "vpc_id": g.get("vpc_id", ""),
                "inbound": [rule(r) for r in g.get("ingress", [])],
                "outbound": [rule(r) for r in g.get("egress", [])]}

    def sg_names(self, vpc_id: str) -> list:
        return [g.get("group_name", "") for g in self.s["security_groups"].values() if g.get("vpc_id") == vpc_id]

    def create_sg(self, vpc_id: str, name: str, description: str, inbound: list) -> str:
        sg_id, now = self._id("sg"), self._now()
        self.s["security_groups"][sg_id] = {
            "security_group_id": sg_id, "vpc_id": vpc_id, "group_name": name, "description": description,
            "is_default": False, "created": now, "tags": [],
            "ingress": [{"protocol": r["protocol"], "from_port": r["from_port"], "to_port": r["to_port"],
                         "cidr": r["source"], "source_sg": "", "description": r.get("description", ""), "created": now}
                        for r in inbound],
            "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": "", "description": "", "created": now}]}
        return sg_id


class CoreNet:
    """vpc_core's model (`store._vpc_model`: vpcs / subnets / sgs / route_tables /
    igws / nacls; rules carry `cidrs` + `sgs` lists). Used by Nano."""

    def __init__(self, store):
        m = getattr(store, "_vpc_model", None)
        if m is None:
            m = {"vpcs": {}, "subnets": {}, "sgs": {}, "route_tables": {}, "igws": {}, "nacls": {}}
            store._vpc_model = m
        for k in ("vpcs", "subnets", "sgs", "route_tables", "igws", "nacls"):
            m.setdefault(k, {})
        self.m = m

    def default_vpc(self) -> dict:
        for v in self.m["vpcs"].values():
            if v.get("is_default"):
                return self._vpc_view(v)
        vpc_id, rt_id, sg_id, igw_id = (f"vpc-{_hex(17)}", f"rtb-{_hex(17)}", f"sg-{_hex(17)}", f"igw-{_hex(17)}")
        self.m["vpcs"][vpc_id] = {"id": vpc_id, "cidr": DEFAULT_VPC_CIDR, "igw": igw_id, "name": "",
                                  "is_default": True, "created": _now()}
        self.m["igws"][igw_id] = {"id": igw_id, "vpc_id": vpc_id}
        subs = []
        for az, cidr in DEFAULT_SUBNETS:
            sid = f"subnet-{_hex(17)}"
            subs.append(sid)
            self.m["subnets"][sid] = {"id": sid, "vpc_id": vpc_id, "cidr": cidr, "az": az, "route_table": rt_id,
                                      "nacl": None, "default_for_az": True}
        self.m["route_tables"][rt_id] = {"id": rt_id, "vpc_id": vpc_id, "main": True, "subnets": subs,
                                         "routes": [{"dest": DEFAULT_VPC_CIDR, "target": "local"},
                                                    {"dest": "0.0.0.0/0", "target": igw_id}]}
        self.m["sgs"][sg_id] = {"id": sg_id, "vpc_id": vpc_id, "name": "default",
                                "description": "default VPC security group",
                                "ingress": [{"protocol": "-1", "from_port": None, "to_port": None, "cidrs": [], "sgs": [sg_id]}],
                                "egress": [{"protocol": "-1", "from_port": None, "to_port": None, "cidrs": ["0.0.0.0/0"], "sgs": []}]}
        return self._vpc_view(self.m["vpcs"][vpc_id])

    def _vpc_view(self, v: dict) -> dict:
        sg = next((g["id"] for g in self.m["sgs"].values() if g.get("vpc_id") == v["id"] and g.get("name") == "default"), "")
        return {"vpc_id": v["id"], "cidr": v.get("cidr", ""), "is_default": bool(v.get("is_default")), "default_sg": sg}

    def vpc(self, vpc_id: str):
        v = self.m["vpcs"].get(vpc_id)
        return self._vpc_view(v) if v else None

    def subnet(self, subnet_id: str):
        s = self.m["subnets"].get(subnet_id)
        if not s:
            return None
        return {"subnet_id": s["id"], "vpc_id": s.get("vpc_id", ""), "cidr": s.get("cidr", ""),
                "az": s.get("az") or "us-east-1a", "default_for_az": bool(s.get("default_for_az"))}

    def subnets_of(self, vpc_id: str) -> list:
        return [self.subnet(sid) for sid, s in self.m["subnets"].items() if s.get("vpc_id") == vpc_id]

    def sg(self, sg_id: str):
        g = self.m["sgs"].get(sg_id)
        if not g:
            return None

        def rules(rs):
            out = []
            for r in rs:
                for src in (r.get("cidrs") or []) + (r.get("sgs") or []) or [""]:
                    out.append({"protocol": str(r.get("protocol", "-1")), "from_port": r.get("from_port"),
                                "to_port": r.get("to_port"), "source": src, "description": r.get("description", "")})
            return out
        return {"group_id": sg_id, "group_name": g.get("name") or sg_id, "description": g.get("description", ""),
                "vpc_id": g.get("vpc_id", ""), "inbound": rules(g.get("ingress", [])), "outbound": rules(g.get("egress", []))}

    def sg_names(self, vpc_id: str) -> list:
        return [g.get("name", "") for g in self.m["sgs"].values() if g.get("vpc_id") == vpc_id]

    def create_sg(self, vpc_id: str, name: str, description: str, inbound: list) -> str:
        sg_id = f"sg-{_hex(17)}"
        self.m["sgs"][sg_id] = {"id": sg_id, "vpc_id": vpc_id, "name": name, "description": description,
                                "ingress": [{"protocol": r["protocol"], "from_port": r["from_port"], "to_port": r["to_port"],
                                             "cidrs": [r["source"]], "sgs": [], "description": r.get("description", "")}
                                            for r in inbound],
                                "egress": [{"protocol": "-1", "from_port": None, "to_port": None, "cidrs": ["0.0.0.0/0"], "sgs": []}]}
        return sg_id


# ── EC2 instance model ───────────────────────────────────────────────────────
_TRUE = (True, "true", "True", "1", 1, "on", "yes", "enable", "enabled")


def default_username(instance: dict) -> str:
    """The login user the AMI ships with (what the Connect tab tells you to use)."""
    fam = str(instance.get("os_family") or instance.get("ami") or instance.get("image_id") or "").lower()
    name = str(instance.get("ami_name") or "").lower()
    if "ubuntu" in fam or "ubuntu" in name:
        return "ubuntu"
    if "debian" in fam or "debian" in name:
        return "admin"
    if "rhel" in fam or "red hat" in name:
        return "ec2-user"
    if "windows" in fam or "windows" in name:
        return "Administrator"
    return "ec2-user"


def _platform(instance: dict) -> str:
    fam = str(instance.get("os_family") or instance.get("ami") or instance.get("image_id") or "").lower()
    if "windows" in fam:
        return "Windows"
    if "rhel" in fam:
        return "Red Hat Enterprise Linux"
    return "Linux/UNIX"


def _launch_wizard_rules(body: dict) -> list:
    """Inbound rules the launch wizard's "Create security group" option adds."""
    sg = body.get("create_security_group") or {}
    rules = []
    ssh = sg.get("ssh_cidr", "0.0.0.0/0")
    if ssh:
        rules.append({"protocol": "tcp", "from_port": 22, "to_port": 22, "source": str(ssh), "description": ""})
    if sg.get("allow_https") in _TRUE:
        rules.append({"protocol": "tcp", "from_port": 443, "to_port": 443, "source": "0.0.0.0/0", "description": ""})
    if sg.get("allow_http") in _TRUE:
        rules.append({"protocol": "tcp", "from_port": 80, "to_port": 80, "source": "0.0.0.0/0", "description": ""})
    return rules


def _ip_in(cidr: str, ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def _pick_ip(cidr: str) -> str:
    net = ipaddress.ip_network(cidr, strict=False)
    # AWS reserves the first four addresses and the last one of every subnet.
    span = max(1, net.num_addresses - 5)
    return str(net.network_address + 4 + int(uuid.uuid4().hex[:6], 16) % span)


# The launch wizard's Quick Start images (core/aws_wizards.py __os__ choices).
QUICKSTART_AMIS = {
    "ami-amzn2023-x86_64": ("Amazon Linux 2023 AMI", "amazon-linux"),
    "ami-amzn2-x86_64": ("Amazon Linux 2 AMI (HVM) - Kernel 5.10", "amazon-linux"),
    "ami-ubuntu-24.04-x86_64": ("Ubuntu Server 24.04 LTS (HVM), SSD Volume Type", "ubuntu"),
    "ami-ubuntu-22.04-x86_64": ("Ubuntu Server 22.04 LTS (HVM), SSD Volume Type", "ubuntu"),
    "ami-rhel-9-x86_64": ("Red Hat Enterprise Linux 9 (HVM), SSD Volume Type", "rhel"),
    "ami-windows-2022-x86_64": ("Microsoft Windows Server 2022 Base", "windows"),
}


def apply_launch(instance: dict, body: dict | None, net, iam_lookup=None) -> dict:
    """RunInstances placement + the launch options the console sends, recorded on
    the instance: VPC/subnet (the default VPC's default subnet for the AZ when none
    is given), security groups (the VPC's default group, or the launch-wizard group
    it creates), the primary network interface, the root EBS volume, monitoring,
    user data, the key pair and the IAM instance profile."""
    body = dict(body or {})
    img = str(instance.get("image_id") or instance.get("ami") or "")
    if img in QUICKSTART_AMIS and not instance.get("ami_name"):
        instance["ami_name"], instance["os_family"] = QUICKSTART_AMIS[img]
    vpc_id = str(body.get("vpc_id") or instance.get("vpc_id") or "")
    subnet_id = str(body.get("subnet_id") or instance.get("subnet_id") or "")
    if vpc_id in ("default", "") and not subnet_id:
        vpc_id = net.default_vpc()["vpc_id"]
    sub = net.subnet(subnet_id) if subnet_id else None
    if not sub:
        az = str(instance.get("az") or instance.get("availability_zone") or body.get("az") or "us-east-1a")
        subs = net.subnets_of(vpc_id) or []
        sub = next((s for s in subs if s["az"] == az), None) or (subs[0] if subs else None)
        if sub is None and vpc_id:
            # A custom VPC with no subnet: real RunInstances fails the same way.
            raise DetailError("MissingInput", "No subnets found for the VPC; specify a subnet.")
    if sub:
        subnet_id, vpc_id = sub["subnet_id"], sub["vpc_id"]
        instance["az"] = instance.get("az") or sub["az"]
    instance["vpc_id"], instance["subnet_id"] = vpc_id, subnet_id
    instance.setdefault("availability_zone", instance.get("az") or (sub or {}).get("az") or "us-east-1a")

    sgs = [g for g in (body.get("security_group_ids") or instance.get("security_group_ids") or []) if net.sg(g)]
    if not sgs and (body.get("create_security_group") or {}).get("requested") in _TRUE:
        req = body["create_security_group"] or {}
        taken = set(net.sg_names(vpc_id))
        name = str(req.get("name") or "").strip()
        if not name or name in taken:
            n = 1
            while f"launch-wizard-{n}" in taken:
                n += 1
            name = f"launch-wizard-{n}"
        desc = str(req.get("description") or f"{name} created {_now()[:19].replace('T', ' ')}")
        sgs = [net.create_sg(vpc_id, name, desc, _launch_wizard_rules(body))]
    if not sgs:
        sgs = [net.vpc(vpc_id)["default_sg"]] if net.vpc(vpc_id) and net.vpc(vpc_id)["default_sg"] else []
    instance["security_group_ids"] = sgs
    if not instance.get("private_ip") or (sub and not instance.get("runtime_backend")
                                           and not _ip_in(sub["cidr"], instance["private_ip"])):
        if sub:
            instance["private_ip"] = _pick_ip(sub["cidr"])
    key = body.get("key_name") or body.get("key_pair")
    if key:
        instance["key_pair"] = str(key)
        instance["key_name"] = str(key)
    if body.get("user_data") and not instance.get("user_data"):
        instance["user_data"] = str(body["user_data"])
    if body.get("monitoring") in _TRUE:
        instance["monitoring"] = "enabled"
    ensure_instance_model(instance, net, root=body)
    prof = body.get("iam_instance_profile")
    if prof:
        associate_iam_instance_profile(instance, str(prof), iam_lookup)
    return instance


def ensure_instance_model(instance: dict, net=None, root: dict | None = None) -> dict:
    """Fill the parts of an instance every launch has (idempotent; also upgrades
    instances recorded before these were modeled): the primary ENI, the root
    volume, attributes and the reservation/launch facts."""
    root = root or {}
    iid = str(instance.get("instance_id") or "")
    if net is not None and not (instance.get("subnet_id") and net.subnet(instance["subnet_id"])):
        # Not placed yet (or placed in a network that no longer exists): RunInstances
        # without a subnet lands in the default VPC's default subnet for the AZ.
        instance["vpc_id"] = instance.get("vpc_id") if instance.get("vpc_id") and net.vpc(instance["vpc_id"]) else ""
        instance["subnet_id"] = ""
        instance["security_group_ids"] = [g for g in instance.get("security_group_ids") or [] if net.sg(g)]
        apply_launch(instance, {}, net)
        return instance
    instance.setdefault("launch_time", instance.get("created") or _now())
    instance.setdefault("reservation_id", "r-" + (iid[2:] if iid.startswith("i-") else _hex(17)))
    instance.setdefault("monitoring", "disabled")
    instance.setdefault("root_device_name", "/dev/sda1" if default_username(instance) == "ubuntu" else "/dev/xvda")
    instance.setdefault("attributes", {"disable_api_termination": False, "disable_api_stop": False,
                                       "instance_initiated_shutdown_behavior": "stop"})
    if not instance.get("block_device_mappings"):
        enc = root.get("root_volume_encrypted")
        instance["block_device_mappings"] = [{
            "device_name": instance["root_device_name"], "volume_id": f"vol-{_hex(17)}",
            "size": int(root.get("storage_gb") or instance.get("storage_gb") or 8),
            "volume_type": str(root.get("root_volume_type") or "gp3"),
            "iops": 3000, "encrypted": enc in _TRUE, "delete_on_termination": True,
            "attach_time": instance["launch_time"], "status": "attached"}]
    if not instance.get("network_interfaces"):
        instance["network_interfaces"] = [{
            "network_interface_id": f"eni-{_hex(17)}", "device_index": 0, "attachment_id": f"eni-attach-{_hex(17)}",
            "mac_address": "0e:" + ":".join(_hex(2) for _ in range(5)), "description": "",
            "interface_type": "interface", "source_dest_check": True, "attach_time": instance["launch_time"]}]
    return instance


def network_interfaces_view(instance: dict, net) -> list:
    """DescribeNetworkInterfaces for this instance's attachments (live IPs/SGs)."""
    sub = net.subnet(instance.get("subnet_id", "")) if net else None
    out = []
    for eni in instance.get("network_interfaces") or []:
        priv = instance.get("private_ip") or ""
        out.append({
            **eni,
            "subnet_id": instance.get("subnet_id", ""), "vpc_id": instance.get("vpc_id", ""),
            "availability_zone": instance.get("az") or instance.get("availability_zone", ""),
            "private_ip_address": priv,
            "private_dns_name": private_dns_name(instance),
            "public_ip_address": instance.get("public_ip") or "",
            "public_dns_name": instance.get("public_dns") or "",
            "security_groups": [{"group_id": g, "group_name": (net.sg(g) or {}).get("group_name", g) if net else g}
                                for g in instance.get("security_group_ids") or []],
            "status": "in-use", "attachment_status": "attached" if instance.get("state") != "terminated" else "detached",
            "subnet_cidr": (sub or {}).get("cidr", "")})
    return out


def private_dns_name(instance: dict) -> str:
    ip = instance.get("private_ip") or ""
    return f"ip-{ip.replace('.', '-')}.ec2.internal" if ip else ""


def security_view(instance: dict, net) -> dict:
    groups = [net.sg(g) for g in instance.get("security_group_ids") or []] if net else []
    groups = [g for g in groups if g]

    def rows(direction):
        out = []
        for g in groups:
            for r in g[direction]:
                out.append({**r, "group_id": g["group_id"], "group_name": g["group_name"],
                            "port_range": port_range(r)})
        return out
    return {"iam_instance_profile": instance.get("iam_instance_profile") or None,
            "owner_id": instance.get("owner_id", ""), "launch_time": instance.get("launch_time", ""),
            "key_name": instance.get("key_pair") or instance.get("key_name") or "",
            "security_groups": [{"group_id": g["group_id"], "group_name": g["group_name"], "description": g["description"]} for g in groups],
            "inbound_rules": rows("inbound"), "outbound_rules": rows("outbound")}


def port_range(r: dict) -> str:
    if str(r.get("protocol")) in ("-1", "all"):
        return "All"
    f, t = r.get("from_port"), r.get("to_port")
    if f is None:
        return "All"
    return str(f) if f == t else f"{f} - {t}"


def storage_view(instance: dict, attached_volumes: list | None = None) -> dict:
    """The instance's block devices: the root volume plus any EBS volume attached
    to it (DescribeVolumes filtered on attachment.instance-id)."""
    vols = []
    for b in instance.get("block_device_mappings") or []:
        vols.append({"volume_id": b["volume_id"], "device_name": b["device_name"], "size": b["size"],
                     "volume_type": b["volume_type"], "iops": b.get("iops"), "encrypted": b["encrypted"],
                     "delete_on_termination": b["delete_on_termination"], "attach_time": b["attach_time"],
                     "attachment_status": b.get("status", "attached"), "root": True})
    for v in attached_volumes or []:
        att = next((a for a in v.get("attachments") or [] if a.get("instance_id") == instance.get("instance_id")), {})
        vols.append({"volume_id": v.get("volume_id"), "device_name": att.get("device", ""), "size": v.get("size"),
                     "volume_type": v.get("volume_type"), "iops": v.get("iops"), "encrypted": bool(v.get("encrypted")),
                     "delete_on_termination": False, "attach_time": att.get("attach_time", ""),
                     "attachment_status": att.get("state", "attached"), "root": False})
    return {"root_device_name": instance.get("root_device_name", ""), "root_device_type": "ebs",
            "ebs_optimized": False, "block_devices": vols}


def details_view(instance: dict) -> dict:
    """The instance summary DescribeInstances returns (Details tab)."""
    a = instance.get("attributes") or {}
    return {
        "instance_id": instance.get("instance_id", ""), "state": instance.get("state", ""),
        "instance_type": instance.get("instance_type", ""),
        "image_id": instance.get("ami") or instance.get("image_id") or "",
        "image_name": instance.get("ami_name") or "", "platform_details": _platform(instance),
        "public_ip_address": instance.get("public_ip") or "", "public_dns_name": instance.get("public_dns") or "",
        "private_ip_address": instance.get("private_ip") or "", "private_dns_name": private_dns_name(instance),
        "vpc_id": instance.get("vpc_id", ""), "subnet_id": instance.get("subnet_id", ""),
        "availability_zone": instance.get("az") or instance.get("availability_zone", ""),
        "launch_time": instance.get("launch_time") or instance.get("created", ""),
        "reservation_id": instance.get("reservation_id", ""), "owner_id": instance.get("owner_id", ""),
        "key_name": instance.get("key_pair") or instance.get("key_name") or "",
        "monitoring": instance.get("monitoring", "disabled"),
        "iam_instance_profile": (instance.get("iam_instance_profile") or {}).get("arn", "") if isinstance(instance.get("iam_instance_profile"), dict) else "",
        "state_transition_reason": instance.get("state_transition_reason", ""),
        "termination_protection": bool(a.get("disable_api_termination")),
        "stop_protection": bool(a.get("disable_api_stop")),
        "instance_initiated_shutdown_behavior": a.get("instance_initiated_shutdown_behavior", "stop"),
        "root_device_name": instance.get("root_device_name", ""), "root_device_type": "ebs",
        "default_username": default_username(instance),
        "ssh_command": ssh_command(instance),
    }


def ssh_command(instance: dict) -> str:
    host = instance.get("public_dns") or instance.get("public_ip") or ""
    if not host:
        return ""
    key = instance.get("key_pair") or instance.get("key_name") or ""
    return (f'ssh -i "{key}.pem" ' if key else "ssh ") + f"{default_username(instance)}@{host}"


_ATTRS = {"disable_api_termination": bool, "disable_api_stop": bool, "instance_initiated_shutdown_behavior": str}


def modify_attributes(instance: dict, changes: dict) -> dict:
    """ModifyInstanceAttribute (termination/stop protection, shutdown behavior) +
    MonitorInstances/UnmonitorInstances."""
    a = instance.setdefault("attributes", {"disable_api_termination": False, "disable_api_stop": False,
                                           "instance_initiated_shutdown_behavior": "stop"})
    for k, v in (changes or {}).items():
        if k == "monitoring":
            instance["monitoring"] = "enabled" if v in _TRUE else "disabled"
        elif k in _ATTRS:
            if k == "instance_initiated_shutdown_behavior":
                if v not in ("stop", "terminate"):
                    raise DetailError("InvalidParameterValue", "Shutdown behavior must be stop or terminate.")
                a[k] = v
            else:
                a[k] = v in _TRUE
    return details_view(instance)


def check_terminate(instance: dict) -> None:
    if (instance.get("attributes") or {}).get("disable_api_termination"):
        raise DetailError("OperationNotPermitted",
                          f"The instance '{instance.get('instance_id')}' may not be terminated. Modify its "
                          "'disableApiTermination' instance attribute and try again.")


def check_stop(instance: dict) -> None:
    if (instance.get("attributes") or {}).get("disable_api_stop"):
        raise DetailError("OperationNotPermitted",
                          f"The instance '{instance.get('instance_id')}' may not be stopped. Modify its "
                          "'disableApiStop' instance attribute and try again.")


def set_user_data(instance: dict, data: str) -> dict:
    """ModifyInstanceAttribute userData — only allowed while the instance is stopped."""
    if str(instance.get("state", "")).lower() not in ("stopped",):
        raise DetailError("IncorrectInstanceState",
                          f"The instance '{instance.get('instance_id')}' is not in the 'stopped' state.")
    instance["user_data"] = str(data or "")
    return {"instance_id": instance.get("instance_id"), "user_data": instance["user_data"]}


def record_state_change(instance: dict, new_state: str, user: bool = True) -> None:
    """StateTransitionReason as DescribeInstances reports it."""
    new_state = str(new_state or "").lower()
    if new_state in ("stopped", "stopping", "terminated", "shutting-down"):
        instance["state_transition_reason"] = f"User initiated ({time.strftime('%Y-%m-%d %H:%M:%S GMT', time.gmtime())})" if user else "Server.InternalError"
    elif new_state in ("running", "pending"):
        instance["state_transition_reason"] = ""


def associate_iam_instance_profile(instance: dict, profile: str, iam_lookup=None, account: str = "") -> dict:
    """AssociateIamInstanceProfile / ReplaceIamInstanceProfileAssociation. `profile`
    is an instance-profile name or ARN; the console creates an instance profile per
    role, so the role must exist (iam_lookup(name) -> role dict or None)."""
    name = str(profile or "").strip()
    if not name:
        raise DetailError("MissingParameter", "An IAM instance profile name or ARN is required.")
    name = name.rsplit("/", 1)[-1]
    role = iam_lookup(name) if iam_lookup else {"role_name": name}
    if not role:
        raise DetailError("InvalidParameterValue", f"Value ({name}) for parameter iamInstanceProfile.name is invalid. "
                          "Invalid IAM Instance Profile name", 400)
    acct = account or instance.get("owner_id") or "123456789012"
    instance["iam_instance_profile"] = {
        "arn": f"arn:aws:iam::{acct}:instance-profile/{name}", "id": "AIPA" + _hex(17).upper(),
        "role_name": role.get("role_name") or name, "role_arn": role.get("arn") or f"arn:aws:iam::{acct}:role/{name}",
        "association_id": f"iip-assoc-{_hex(17)}", "state": "associated"}
    return instance["iam_instance_profile"]


def disassociate_iam_instance_profile(instance: dict) -> dict:
    if not instance.get("iam_instance_profile"):
        raise DetailError("InvalidAssociationID.NotFound", "The instance has no IAM instance profile associated.")
    old = instance.pop("iam_instance_profile")
    instance["iam_instance_profile"] = None
    return {**old, "state": "disassociated"}


def console_output(instance: dict, output: str = "") -> dict:
    """GetConsoleOutput: the instance's console log (empty when it produced none)."""
    return {"instance_id": instance.get("instance_id", ""), "timestamp": _now(), "output": output or ""}


# ── IAM: identity policies that apply to a resource (Permissions tab) ─────────
def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _match(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(value.lower(), str(pattern).lower())


def resource_access(principals: list, resource_arn: str, service: str) -> list:
    """Each statement of each principal's policies whose Action covers `service`
    and whose Resource covers `resource_arn`. `principals` is
    [{type, name, arn, policies:[{name, arn, document}]}]."""
    out = []
    svc = service.lower()
    for p in principals or []:
        for pol in p.get("policies") or []:
            doc = pol.get("document")
            if isinstance(doc, str):
                try:
                    import json
                    doc = json.loads(doc)
                except Exception:
                    doc = {}
            for st in _as_list((doc or {}).get("Statement")):
                if not isinstance(st, dict):
                    continue
                acts = [str(a) for a in _as_list(st.get("Action"))]
                hit = [a for a in acts if a == "*" or a.lower().split(":", 1)[0] == svc]
                if not hit:
                    continue
                res = [str(r) for r in _as_list(st.get("Resource"))] or ["*"]
                if not any(_match(r, resource_arn) for r in res):
                    continue
                out.append({"principal_type": p.get("type", ""), "principal": p.get("name", ""),
                            "principal_arn": p.get("arn", ""), "policy": pol.get("name", ""),
                            "policy_arn": pol.get("arn", ""), "effect": st.get("Effect", "Allow"),
                            "actions": ", ".join(hit), "resource": ", ".join(res)})
    return out


# ── S3 bucket configuration (Properties / Permissions tabs) ──────────────────
S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
S3_KINDS = ("lifecycle", "cors", "encryption", "public_access_block", "policy", "ownership")
_STORAGE_CLASSES = {"STANDARD_IA": 30, "ONEZONE_IA": 30, "INTELLIGENT_TIERING": 0, "GLACIER_IR": 0,
                    "GLACIER": 0, "DEEP_ARCHIVE": 0}
_CORS_METHODS = {"GET", "PUT", "POST", "DELETE", "HEAD"}


def _x(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _int(v, field):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise DetailError("InvalidArgument", f"{field} must be an integer.")
    if n <= 0:
        raise DetailError("InvalidArgument", f"'{field}' for the rule must be a positive integer.")
    return n


def _lifecycle_rule(r: dict, i: int) -> dict:
    rid = str(r.get("id") or r.get("ID") or "").strip() or f"rule-{i + 1}"
    if len(rid) > 255:
        raise DetailError("InvalidArgument", "ID length should not exceed allowed limit of 255")
    status = str(r.get("status") or "Enabled")
    if status not in ("Enabled", "Disabled"):
        raise DetailError("MalformedXML", "Rule Status must be Enabled or Disabled.")
    out = {"id": rid, "status": status, "prefix": str(r.get("prefix") or "")}
    if r.get("expiration_days") not in (None, ""):
        out["expiration_days"] = _int(r["expiration_days"], "Days")
    if r.get("noncurrent_expiration_days") not in (None, ""):
        out["noncurrent_expiration_days"] = _int(r["noncurrent_expiration_days"], "NoncurrentDays")
    if r.get("abort_incomplete_multipart_days") not in (None, ""):
        out["abort_incomplete_multipart_days"] = _int(r["abort_incomplete_multipart_days"], "DaysAfterInitiation")
    tr = []
    for t in r.get("transitions") or []:
        sc = str(t.get("storage_class") or "")
        if sc not in _STORAGE_CLASSES:
            raise DetailError("InvalidArgument", f"The storage class you specified is not valid: {sc}")
        days = _int(t.get("days"), "Days")
        if days < _STORAGE_CLASSES[sc]:
            raise DetailError("InvalidArgument", f"'Days' in Transition action must be greater than or equal to "
                              f"{_STORAGE_CLASSES[sc]} for storageClass '{sc}'")
        tr.append({"days": days, "storage_class": sc})
    if tr:
        out["transitions"] = tr
    if not any(k in out for k in ("expiration_days", "noncurrent_expiration_days", "abort_incomplete_multipart_days", "transitions")):
        raise DetailError("InvalidRequest", "At least one action needs to be specified in a rule")
    return out


def _lifecycle_xml(rules: list) -> str:
    parts = []
    for r in rules:
        x = f"<Rule><ID>{_x(r['id'])}</ID><Filter><Prefix>{_x(r['prefix'])}</Prefix></Filter><Status>{r['status']}</Status>"
        for t in r.get("transitions", []):
            x += f"<Transition><Days>{t['days']}</Days><StorageClass>{t['storage_class']}</StorageClass></Transition>"
        if "expiration_days" in r:
            x += f"<Expiration><Days>{r['expiration_days']}</Days></Expiration>"
        if "noncurrent_expiration_days" in r:
            x += (f"<NoncurrentVersionExpiration><NoncurrentDays>{r['noncurrent_expiration_days']}"
                  "</NoncurrentDays></NoncurrentVersionExpiration>")
        if "abort_incomplete_multipart_days" in r:
            x += (f"<AbortIncompleteMultipartUpload><DaysAfterInitiation>{r['abort_incomplete_multipart_days']}"
                  "</DaysAfterInitiation></AbortIncompleteMultipartUpload>")
        parts.append(x + "</Rule>")
    return f'<?xml version="1.0" encoding="UTF-8"?><LifecycleConfiguration xmlns="{S3_NS}">{"".join(parts)}</LifecycleConfiguration>'


def _cors_rule(r: dict) -> dict:
    def lst(v):
        if isinstance(v, str):
            v = v.split(",")
        return [str(x).strip() for x in (v or []) if str(x).strip()]
    methods = [m.upper() for m in lst(r.get("allowed_methods"))]
    origins = lst(r.get("allowed_origins"))
    if not methods or not origins:
        raise DetailError("MalformedXML", "Each CORS rule needs at least one AllowedMethod and one AllowedOrigin.")
    bad = [m for m in methods if m not in _CORS_METHODS]
    if bad:
        raise DetailError("InvalidRequest", f"Found unsupported HTTP method in CORS config. Unsupported method is {bad[0]}")
    out = {"id": str(r.get("id") or ""), "allowed_methods": methods, "allowed_origins": origins,
           "allowed_headers": lst(r.get("allowed_headers")), "expose_headers": lst(r.get("expose_headers"))}
    if r.get("max_age_seconds") not in (None, ""):
        out["max_age_seconds"] = _int(r["max_age_seconds"], "MaxAgeSeconds")
    return out


def _cors_xml(rules: list) -> str:
    parts = []
    for r in rules:
        x = "<CORSRule>" + (f"<ID>{_x(r['id'])}</ID>" if r.get("id") else "")
        x += "".join(f"<AllowedMethod>{m}</AllowedMethod>" for m in r["allowed_methods"])
        x += "".join(f"<AllowedOrigin>{_x(o)}</AllowedOrigin>" for o in r["allowed_origins"])
        x += "".join(f"<AllowedHeader>{_x(h)}</AllowedHeader>" for h in r["allowed_headers"])
        x += "".join(f"<ExposeHeader>{_x(h)}</ExposeHeader>" for h in r["expose_headers"])
        if "max_age_seconds" in r:
            x += f"<MaxAgeSeconds>{r['max_age_seconds']}</MaxAgeSeconds>"
        parts.append(x + "</CORSRule>")
    return f'<?xml version="1.0" encoding="UTF-8"?><CORSConfiguration xmlns="{S3_NS}">{"".join(parts)}</CORSConfiguration>'


def _xml_rules(xml: str, kind: str) -> list:
    """Rules an SDK/CLI wrote over the native wire (XML), for the console view."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    def loc(el):
        return el.tag.split("}")[-1]

    def t(el, name):
        for c in el.iter():
            if loc(c) == name:
                return (c.text or "").strip()
        return ""

    def all_(el, name):
        return [(c.text or "").strip() for c in el if loc(c) == name]
    out = []
    for r in root:
        if kind == "cors" and loc(r) == "CORSRule":
            o = {"id": t(r, "ID"), "allowed_methods": all_(r, "AllowedMethod"), "allowed_origins": all_(r, "AllowedOrigin"),
                 "allowed_headers": all_(r, "AllowedHeader"), "expose_headers": all_(r, "ExposeHeader")}
            if t(r, "MaxAgeSeconds"):
                o["max_age_seconds"] = int(t(r, "MaxAgeSeconds"))
            out.append(o)
        elif kind == "lifecycle" and loc(r) == "Rule":
            o = {"id": t(r, "ID"), "status": t(r, "Status") or "Enabled", "prefix": t(r, "Prefix")}
            for c in r:
                if loc(c) == "Expiration" and t(c, "Days"):
                    o["expiration_days"] = int(t(c, "Days"))
                elif loc(c) == "NoncurrentVersionExpiration" and t(c, "NoncurrentDays"):
                    o["noncurrent_expiration_days"] = int(t(c, "NoncurrentDays"))
                elif loc(c) == "AbortIncompleteMultipartUpload" and t(c, "DaysAfterInitiation"):
                    o["abort_incomplete_multipart_days"] = int(t(c, "DaysAfterInitiation"))
                elif loc(c) == "Transition" and t(c, "Days"):
                    o.setdefault("transitions", []).append({"days": int(t(c, "Days")), "storage_class": t(c, "StorageClass")})
            out.append(o)
    return out


def _is_public_policy(doc: dict) -> bool:
    for st in _as_list(doc.get("Statement")):
        if not isinstance(st, dict) or st.get("Effect") != "Allow" or st.get("Condition"):
            continue
        pr = st.get("Principal")
        if pr == "*" or (isinstance(pr, dict) and "*" in _as_list(pr.get("AWS"))):
            return True
    return False


def s3_bucket_config(bucket: dict, kind: str):
    """GetBucket{Lifecycle,Cors,Encryption,PublicAccessBlock,Policy,OwnershipControls}.
    Buckets that never had one set get what S3 gives every new bucket since 2023:
    SSE-S3 default encryption, all four Block Public Access settings on, Object
    Ownership "Bucket owner enforced"; no lifecycle, CORS or policy."""
    if kind == "lifecycle":
        rules = bucket.get("lifecycle_rules")
        if rules is None and bucket.get("lifecycle"):
            rules = _xml_rules(bucket["lifecycle"], "lifecycle")
        return rules or []
    if kind == "cors":
        rules = bucket.get("cors_rules")
        if rules is None and bucket.get("cors"):
            rules = _xml_rules(bucket["cors"], "cors")
        return rules or []
    if kind == "encryption":
        return dict(bucket.get("encryption_config") or {"sse_algorithm": "AES256", "kms_master_key_id": "", "bucket_key_enabled": False})
    if kind == "public_access_block":
        return dict(bucket.get("public_access_block") or {"block_public_acls": True, "ignore_public_acls": True,
                                                          "block_public_policy": True, "restrict_public_buckets": True})
    if kind == "policy":
        return bucket.get("policy") or ""
    if kind == "ownership":
        return bucket.get("object_ownership") or "BucketOwnerEnforced"
    raise DetailError("InvalidRequest", f"Unknown bucket configuration '{kind}'.")


def s3_put_bucket_config(bucket: dict, name: str, kind: str, value):
    """PutBucket* with S3's validation. Lifecycle/CORS also keep the native-wire XML
    so an SDK GetBucketCors / GetBucketLifecycleConfiguration returns the same rules."""
    import json
    if kind == "lifecycle":
        rules = [_lifecycle_rule(r, i) for i, r in enumerate(value or [])]
        ids = [r["id"] for r in rules]
        if len(ids) != len(set(ids)):
            raise DetailError("InvalidArgument", "Rule ID must be unique. Found same ID for more than one rule")
        bucket["lifecycle_rules"] = rules
        bucket["lifecycle"] = _lifecycle_xml(rules) if rules else ""
        return rules
    if kind == "cors":
        rules = [_cors_rule(r) for r in (value or [])]
        if len(rules) > 100:
            raise DetailError("InvalidRequest", "The number of CORS rules should not exceed allowed limit of 100 rules.")
        bucket["cors_rules"] = rules
        bucket["cors"] = _cors_xml(rules) if rules else ""
        return rules
    if kind == "encryption":
        v = dict(value or {})
        alg = str(v.get("sse_algorithm") or "AES256")
        if alg not in ("AES256", "aws:kms", "aws:kms:dsse"):
            raise DetailError("MalformedXML", f"Unsupported SSEAlgorithm: {alg}")
        key = str(v.get("kms_master_key_id") or "") if alg != "AES256" else ""
        bucket["encryption_config"] = {"sse_algorithm": alg, "kms_master_key_id": key,
                                       "bucket_key_enabled": v.get("bucket_key_enabled") in _TRUE}
        return bucket["encryption_config"]
    if kind == "public_access_block":
        v = dict(value or {})
        bucket["public_access_block"] = {k: v.get(k) in _TRUE for k in
                                         ("block_public_acls", "ignore_public_acls", "block_public_policy", "restrict_public_buckets")}
        return bucket["public_access_block"]
    if kind == "policy":
        if not value:
            bucket["policy"] = ""
            return ""
        try:
            doc = json.loads(value) if isinstance(value, str) else dict(value)
        except (ValueError, TypeError):
            raise DetailError("MalformedPolicy", "Policies must be valid JSON and the first byte must be '{'")
        sts = _as_list(doc.get("Statement"))
        if not sts:
            raise DetailError("MalformedPolicy", "Missing required field Statement")
        arn = f"arn:aws:s3:::{name}"
        for st in sts:
            if not isinstance(st, dict) or st.get("Effect") not in ("Allow", "Deny"):
                raise DetailError("MalformedPolicy", "Invalid effect")
            if "Principal" not in st and "NotPrincipal" not in st:
                raise DetailError("MalformedPolicy", "Missing required field Principal")
            for res in _as_list(st.get("Resource")):
                if not (str(res) == arn or str(res).startswith(arn + "/")):
                    raise DetailError("MalformedPolicy", "Policy has invalid resource")
        if _is_public_policy(doc) and s3_bucket_config(bucket, "public_access_block").get("block_public_policy"):
            raise DetailError("AccessDenied", "User is not authorized to perform s3:PutBucketPolicy because public "
                              "policies are blocked by the BlockPublicPolicy block public access setting.", 403)
        bucket["policy"] = json.dumps(doc, indent=2)
        return bucket["policy"]
    if kind == "ownership":
        if value not in ("BucketOwnerEnforced", "BucketOwnerPreferred", "ObjectWriter"):
            raise DetailError("MalformedXML", "ObjectOwnership must be BucketOwnerEnforced, BucketOwnerPreferred or ObjectWriter.")
        bucket["object_ownership"] = value
        return value
    raise DetailError("InvalidRequest", f"Unknown bucket configuration '{kind}'.")


def s3_versions(objects: dict, prefix: str = "") -> list:
    """ListObjectVersions over the {key: {versions:[…]}} map both substrates keep."""
    out = []
    for key in sorted(objects or {}):
        if prefix and not key.startswith(prefix):
            continue
        entry = objects[key] if isinstance(objects[key], dict) else {}
        for i, v in enumerate(entry.get("versions") or []):
            out.append({"key": key, "version_id": v.get("version_id") or "null", "is_latest": i == 0,
                        "is_delete_marker": bool(v.get("is_delete_marker")), "last_modified": v.get("last_modified", ""),
                        "size": v.get("size", 0), "storage_class": v.get("storage_class", "STANDARD"),
                        "etag": v.get("etag", "")})
    return out


def s3_notifications_default() -> dict:
    return {"eventBridgeEnabled": False, "topicConfigurations": [], "queueConfigurations": [],
            "cloudFunctionConfigurations": []}


def s3_put_notifications(bucket: dict, payload: dict) -> dict:
    """PutBucketNotificationConfiguration in the shape the offline appliance keeps
    (queue / topic / Lambda configurations + EventBridge)."""
    notif = s3_notifications_default()
    notif["eventBridgeEnabled"] = (payload or {}).get("event_bridge_enabled") in _TRUE
    key = {"QueueConfiguration": ("queueConfigurations", "queue"),
           "CloudFunctionConfiguration": ("cloudFunctionConfigurations", "cloudFunction"),
           "TopicConfiguration": ("topicConfigurations", "topic")}
    for i, r in enumerate((payload or {}).get("rules") or []):
        events = [e.strip() for e in (r.get("events") or []) if e and e.strip()]
        dest = str(r.get("destination") or "").strip()
        if not events or not dest:
            raise DetailError("InvalidArgument", "A notification configuration needs at least one event and a destination ARN.")
        coll, field = key.get(r.get("destination_type") or "", key["TopicConfiguration"])
        notif[coll].append({"id": str(r.get("id") or "").strip() or f"notification-{i + 1}", "events": events,
                            "prefix": str(r.get("prefix") or ""), "suffix": str(r.get("suffix") or ""), field: dest})
    notif["updatedAt"] = _now()
    bucket["notifications"] = {**(bucket.get("notifications") or {}), **notif}
    return bucket["notifications"]


def s3_access_summary(bucket: dict) -> str:
    """The bucket list's "Access" column: public only with a public bucket policy
    that Block Public Access does not restrict."""
    import json
    pol = bucket.get("policy")
    if pol and not s3_bucket_config(bucket, "public_access_block").get("restrict_public_buckets"):
        try:
            if _is_public_policy(json.loads(pol)):
                return "Public"
        except ValueError:
            pass
    return "Bucket and objects not public"


# ── RDS DB instance detail (Connectivity, Maintenance & backups, Logs & events,
#    Performance Insights, Modify) ───────────────────────────────────────────
RDS_INSTANCE_CLASSES = ["db.t3.micro", "db.t3.small", "db.t3.medium", "db.t3.large", "db.t4g.micro", "db.t4g.small",
                        "db.t4g.medium", "db.m5.large", "db.m5.xlarge", "db.m6g.large", "db.m6i.large", "db.r5.large",
                        "db.r6g.large"]
RDS_LOG_TYPES = {"postgres": ["postgresql", "upgrade"], "mysql": ["audit", "error", "general", "slowquery"],
                 "mariadb": ["audit", "error", "general", "slowquery"]}
_RDS_EVENT_TEXT = {
    "CreateDBInstance": ("creation", "DB instance created"),
    "StartDBInstance": ("notification", "DB instance started"),
    "StopDBInstance": ("notification", "DB instance stopped"),
    "RebootDBInstance": ("availability", "DB instance restarted"),
    "ModifyDBInstance": ("configuration change", "Finished applying modification to DB instance"),
    "CreateDBSnapshot": ("backup", "Manual snapshot created"),
}
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError
    return h * 60 + m


def _check_backup_window(w: str) -> None:
    try:
        a, b = w.split("-")
        span = (_hhmm(b) - _hhmm(a)) % 1440
    except (ValueError, AttributeError):
        raise DetailError("InvalidParameterValue", "The backup window must be in the format hh24:mi-hh24:mi.")
    if span < 30:
        raise DetailError("InvalidParameterValue", "The backup window must be at least 30 minutes.")


def _check_maintenance_window(w: str) -> None:
    try:
        a, b = w.lower().split("-")
        da, ta = a.split(":", 1)
        db_, tb = b.split(":", 1)
        if da not in _DAYS or db_ not in _DAYS:
            raise ValueError
        start = _DAYS.index(da) * 1440 + _hhmm(ta)
        end = _DAYS.index(db_) * 1440 + _hhmm(tb)
    except (ValueError, AttributeError):
        raise DetailError("InvalidParameterValue", "The maintenance window must be in the format ddd:hh24:mi-ddd:hh24:mi.")
    if (end - start) % (7 * 1440) < 30:
        raise DetailError("InvalidParameterValue", "The maintenance window must be at least 30 minutes.")


def rds_ensure(db: dict, net=None) -> dict:
    """Settings DescribeDBInstances always returns, filled once (and kept) for DB
    instances recorded before they were modeled. Windows default to the ones the
    RDS console proposes for us-east-1 (backup 03:00-03:30 UTC, maintenance
    sun:05:00-sun:05:30) unless the instance already has one."""
    db.setdefault("preferred_backup_window", "03:00-03:30")
    db.setdefault("preferred_maintenance_window", "sun:05:00-sun:05:30")
    db.setdefault("backup_retention_period", 7)
    db.setdefault("auto_minor_version_upgrade", True)
    db.setdefault("copy_tags_to_snapshot", True)
    db.setdefault("deletion_protection", False)
    db.setdefault("storage_encrypted", True)
    db.setdefault("kms_key_id", "alias/aws/rds")
    db.setdefault("performance_insights_enabled", False)
    db.setdefault("performance_insights_retention_period", 7)
    db.setdefault("enabled_cloudwatch_logs_exports", [])
    db.setdefault("ca_certificate_identifier", "rds-ca-rsa2048-g1")
    db.setdefault("iam_database_authentication_enabled", False)
    db.setdefault("network_type", "IPV4")
    db.setdefault("multi_az", False)
    db.setdefault("publicly_accessible", False)
    db.setdefault("availability_zone", "us-east-1a")
    db.setdefault("rds_events", [])
    if net is not None:
        vpc = db.get("vpc_id") if db.get("vpc_id") and net.vpc(db["vpc_id"]) else ""
        if not vpc:
            sg = (db.get("db_subnet_group") or {}).get("vpc_id") or ""
            vpc = sg if sg and net.vpc(sg) else net.default_vpc()["vpc_id"]
            db["vpc_id"] = vpc
        if not [g for g in db.get("vpc_security_group_ids") or db.get("security_group_ids") or [] if net.sg(g)]:
            d = (net.vpc(vpc) or {}).get("default_sg")
            db["vpc_security_group_ids"] = [d] if d else []
    return db


def rds_record_event(db: dict, action: str, message: str = "") -> None:
    cat, text = _RDS_EVENT_TEXT.get(action, ("notification", action))
    db.setdefault("rds_events", []).append({"date": _now(), "category": cat, "message": message or text,
                                            "source_identifier": db.get("db_instance_identifier", ""),
                                            "source_type": "db-instance"})
    del db["rds_events"][:-100]


def rds_events(db: dict, account_events: list | None = None) -> list:
    """DescribeEvents for this DB instance (newest first)."""
    did = db.get("db_instance_identifier", "")
    out = list(db.get("rds_events") or [])
    for e in account_events or []:
        det = e.get("detail") or {}
        if str(det.get("db_instance_identifier", "")).lower() == did.lower() and e.get("action") in _RDS_EVENT_TEXT:
            cat, text = _RDS_EVENT_TEXT[e["action"]]
            out.append({"date": e.get("timestamp", ""), "category": cat, "message": text,
                        "source_identifier": did, "source_type": "db-instance"})
    return sorted(out, key=lambda x: x.get("date", ""), reverse=True)


def rds_connectivity(db: dict, net, subnet_group: dict | None = None) -> dict:
    """Connectivity & security: endpoint, network placement and VPC security groups."""
    vpc = db.get("vpc_id", "")
    sg_rec = subnet_group or db.get("db_subnet_group") or {}
    sids = [s for s in sg_rec.get("subnet_ids") or db.get("subnet_ids") or [] if net and net.subnet(s)]
    subnets = [net.subnet(s) for s in sids] if sids else (net.subnets_of(vpc) if net else [])
    sgs = []
    for g in db.get("vpc_security_group_ids") or db.get("security_group_ids") or []:
        rec = net.sg(g) if net else None
        sgs.append({"group_id": g, "group_name": (rec or {}).get("group_name", ""), "status": "active"})
    return {"endpoint": db.get("endpoint_address") or db.get("endpoint") or "", "port": db.get("endpoint_port") or db.get("port"),
            "availability_zone": db.get("availability_zone", ""), "vpc_id": vpc, "network_type": db.get("network_type", "IPV4"),
            "subnet_group": sg_rec.get("db_subnet_group_name") or db.get("db_subnet_group_name") or "default",
            "subnets": [{"subnet_id": s["subnet_id"], "cidr": s["cidr"], "availability_zone": s["az"]} for s in subnets if s],
            "security_groups": sgs, "publicly_accessible": bool(db.get("publicly_accessible")),
            "certificate_authority": db.get("ca_certificate_identifier", ""), "multi_az": bool(db.get("multi_az")),
            "master_username": db.get("master_username", ""), "iam_db_auth": bool(db.get("iam_database_authentication_enabled"))}


_RDS_KEYS = ("db_instance_class", "allocated_storage", "storage_type", "backup_retention_period", "preferred_backup_window",
             "preferred_maintenance_window", "auto_minor_version_upgrade", "copy_tags_to_snapshot", "deletion_protection",
             "publicly_accessible", "multi_az", "performance_insights_enabled", "performance_insights_retention_period",
             "enabled_cloudwatch_logs_exports", "storage_encrypted", "kms_key_id", "ca_certificate_identifier",
             "engine", "engine_version", "db_instance_status", "status", "latest_restorable_time", "created",
             "iam_database_authentication_enabled")

_RDS_MODIFIABLE = _RDS_KEYS[:14]   # class … log exports: what ModifyDBInstance changes from the console


def rds_configuration(db: dict) -> dict:
    out = {k: db.get(k) for k in _RDS_KEYS if k in db}
    out["db_instance_identifier"] = db.get("db_instance_identifier", "")
    out["log_types"] = RDS_LOG_TYPES.get(str(db.get("engine", "postgres")).split("-")[0], [])
    out["instance_classes"] = RDS_INSTANCE_CLASSES
    out["automated_backups"] = "Enabled" if int(db.get("backup_retention_period") or 0) > 0 else "Disabled"
    out["pending_maintenance"] = []
    return out


def rds_modify(db: dict, changes: dict) -> dict:
    """ModifyDBInstance with RDS's rules for the fields the console edits."""
    c = dict(changes or {})
    if "db_instance_class" in c and c["db_instance_class"] not in RDS_INSTANCE_CLASSES:
        raise DetailError("InvalidParameterCombination", f"RDS does not support creating a DB instance with the following "
                          f"combination: DBInstanceClass={c['db_instance_class']}, Engine={db.get('engine', 'postgres')}.")
    if "allocated_storage" in c:
        n = int(c["allocated_storage"])
        if n < int(db.get("allocated_storage") or 20):
            raise DetailError("InvalidParameterValue", "Invalid storage size: you can't reduce the allocated storage of a DB instance.")
        if n > 65536:
            raise DetailError("InvalidParameterValue", "Invalid storage size: the maximum is 65536 GiB.")
        c["allocated_storage"] = n
    if "backup_retention_period" in c:
        n = int(c["backup_retention_period"])
        if not 0 <= n <= 35:
            raise DetailError("InvalidParameterValue", "The backup retention period must be between 0 and 35 days.")
        c["backup_retention_period"] = n
    if "preferred_backup_window" in c:
        _check_backup_window(str(c["preferred_backup_window"]))
    if "preferred_maintenance_window" in c:
        _check_maintenance_window(str(c["preferred_maintenance_window"]))
    if "performance_insights_retention_period" in c:
        n = int(c["performance_insights_retention_period"])
        if not (n in (7, 731) or (n % 31 == 0 and 31 <= n <= 713)):
            raise DetailError("InvalidParameterValue", "Performance Insights retention must be 7 days, 731 days, or a multiple of 31.")
        c["performance_insights_retention_period"] = n
    if "enabled_cloudwatch_logs_exports" in c:
        allowed = RDS_LOG_TYPES.get(str(db.get("engine", "postgres")).split("-")[0], [])
        bad = [t for t in c["enabled_cloudwatch_logs_exports"] or [] if t not in allowed]
        if bad:
            raise DetailError("InvalidParameterCombination", f"You cannot use the log types '{bad[0]}' with engine {db.get('engine')}.")
    for k in ("auto_minor_version_upgrade", "copy_tags_to_snapshot", "deletion_protection", "publicly_accessible",
              "multi_az", "performance_insights_enabled"):
        if k in c:
            c[k] = c[k] in _TRUE
    applied = [k for k in c if k in _RDS_MODIFIABLE and db.get(k) != c[k]]
    for k in applied:
        db[k] = c[k]
    db["updated"] = _now()
    if applied:
        rds_record_event(db, "ModifyDBInstance", "Finished applying modification to " + ", ".join(applied))
    return rds_configuration(db)


def rds_check_delete(db: dict) -> None:
    if db.get("deletion_protection"):
        raise DetailError("InvalidParameterCombination",
                          "Cannot delete protected DB Instance, please disable deletion protection and try again.")


def rds_pending_maintenance(db: dict) -> list:
    """DescribePendingMaintenanceActions for this instance. Nothing is scheduled
    unless an engine upgrade or OS patch is pending; the simulator schedules none."""
    return list(db.get("pending_maintenance_actions") or [])


def rds_performance_insights(db: dict) -> dict:
    """Performance Insights GetResourceMetadata: whether PI is on for the instance."""
    on = bool(db.get("performance_insights_enabled"))
    return {"identifier": "db-" + str(db.get("db_instance_identifier", "")).upper(), "enabled": on,
            "retention_period": db.get("performance_insights_retention_period", 7),
            "kms_key_id": (db.get("kms_key_id") or "alias/aws/rds") if on else "",
            "features": {"UNIFIED_SQL_ID": "ENABLED" if on else "DISABLED"}}


# ── DynamoDB table settings (Indexes, Streams, Capacity, Encryption, TTL,
#    Backups, PITR, Contributor Insights) ──────────────────────────────────────
DDB_SECTIONS = ("general", "indexes", "streams", "capacity", "encryption", "ttl", "pitr", "backups", "insights")
_DDB_VIEW_TYPES = ("KEYS_ONLY", "NEW_IMAGE", "OLD_IMAGE", "NEW_AND_OLD_IMAGES")
_DDB_SSE = {"AWS_OWNED": "Owned by Amazon DynamoDB", "AWS_MANAGED": "AWS managed key (aws/dynamodb)",
            "CUSTOMER_MANAGED": "Customer managed key"}


def ddb_ensure(table: dict) -> dict:
    table.setdefault("table_class", "STANDARD")
    table.setdefault("deletion_protection", False)
    table.setdefault("sse", {"type": "AWS_OWNED", "kms_key_arn": ""})
    table.setdefault("ttl", {"status": "DISABLED", "attribute": ""})
    table.setdefault("pitr", {"status": "DISABLED"})
    table.setdefault("backups", [])
    table.setdefault("contributor_insights", "DISABLED")
    table.setdefault("local_indexes", [])
    st = table.setdefault("streams", {})
    if not isinstance(st, dict):
        st = table["streams"] = {}
    st.setdefault("enabled", False)
    st.setdefault("view_type", "")
    st.setdefault("latest_stream_label", "")
    return table


def _ddb_arn(table: dict, account: str = "123456789012") -> str:
    return table.get("table_arn") or f"arn:aws:dynamodb:{REGION}:{account}:table/{table.get('table_name', '')}"


def ddb_section(table: dict, section: str) -> dict:
    """DescribeTable / DescribeTimeToLive / DescribeContinuousBackups / ListBackups /
    DescribeContributorInsights for the table, one console section at a time."""
    ddb_ensure(table)
    arn = _ddb_arn(table)
    items = len(table.get("items") or {})
    size = int(table.get("table_size_bytes") or 0)
    if section == "general":
        return {"table_name": table.get("table_name"), "table_arn": arn, "table_status": table.get("table_status", "ACTIVE"),
                "partition_key": f"{table.get('partition_key_name')} ({table.get('partition_key_type')})",
                "sort_key": f"{table.get('sort_key_name')} ({table.get('sort_key_type')})" if table.get("sort_key_name") else "",
                "capacity_mode": "On-demand" if table.get("billing_mode") == "PAY_PER_REQUEST" else "Provisioned",
                "item_count": items, "table_size_bytes": size, "average_item_size": (size // items) if items else 0,
                "pitr": table["pitr"]["status"], "deletion_protection": bool(table.get("deletion_protection")),
                "table_class": table.get("table_class"), "created": table.get("created", ""),
                "indexes": len(table.get("indexes") or []) + len(table.get("local_indexes") or [])}
    if section == "indexes":
        def ix(g, kind):
            ks = {k.get("KeyType"): k.get("AttributeName") for k in g.get("key_schema") or []}
            return {"index_name": g.get("name"), "type": kind, "partition_key": ks.get("HASH") or g.get("partition_key_name", ""),
                    "sort_key": ks.get("RANGE") or g.get("sort_key_name", ""), "status": g.get("index_status", "ACTIVE"),
                    "projection": (g.get("projection") or {}).get("ProjectionType", "ALL"), "item_count": items,
                    "index_arn": f"{arn}/index/{g.get('name')}"}
        return {"global_secondary_indexes": [ix(g, "GSI") for g in table.get("indexes") or []],
                "local_secondary_indexes": [ix(g, "LSI") for g in table.get("local_indexes") or []]}
    if section == "streams":
        st = table["streams"]
        return {"stream_enabled": bool(st.get("enabled")), "view_type": st.get("view_type", ""),
                "latest_stream_label": st.get("latest_stream_label", ""),
                "latest_stream_arn": f"{arn}/stream/{st['latest_stream_label']}" if st.get("latest_stream_label") else ""}
    if section == "capacity":
        pt = table.get("provisioned_throughput") or {}
        return {"billing_mode": table.get("billing_mode", "PAY_PER_REQUEST"), "table_class": table.get("table_class"),
                "read_capacity_units": pt.get("ReadCapacityUnits", 0), "write_capacity_units": pt.get("WriteCapacityUnits", 0),
                "deletion_protection": bool(table.get("deletion_protection"))}
    if section == "encryption":
        s = table["sse"]
        return {"sse_type": s["type"], "description": _DDB_SSE.get(s["type"], s["type"]),
                "kms_key_arn": s.get("kms_key_arn") or ("arn:aws:kms:%s:%s:alias/aws/dynamodb" % (REGION, arn.split(":")[4]) if s["type"] == "AWS_MANAGED" else ""),
                "status": "ENABLED"}
    if section == "ttl":
        return {"time_to_live_status": table["ttl"]["status"], "attribute_name": table["ttl"].get("attribute", "")}
    if section == "pitr":
        p = table["pitr"]
        on = p["status"] == "ENABLED"
        return {"point_in_time_recovery_status": p["status"], "continuous_backups_status": "ENABLED",
                "earliest_restorable_date_time": p.get("enabled_at", "") if on else "",
                "latest_restorable_date_time": _now() if on else "", "recovery_period_in_days": 35 if on else 0}
    if section == "backups":
        return {"backups": list(table["backups"])}
    if section == "insights":
        return {"contributor_insights_status": table["contributor_insights"],
                "contributor_insights_rule_list": [f"DynamoDBContributorInsights-PKC-{table.get('table_name')}",
                                                   f"DynamoDBContributorInsights-PKT-{table.get('table_name')}"]
                if table["contributor_insights"] == "ENABLED" else []}
    raise DetailError("ValidationException", f"Unknown table section '{section}'.")


def _attr_def(table: dict, name: str, typ: str) -> None:
    defs = table.setdefault("attribute_definitions", [])
    cur = next((d for d in defs if d.get("AttributeName") == name), None)
    if cur and cur.get("AttributeType") != typ:
        raise DetailError("ValidationException", f"Cannot change the type of attribute {name} from {cur['AttributeType']} to {typ}.")
    if not cur:
        defs.append({"AttributeName": name, "AttributeType": typ})


def ddb_update_section(table: dict, section: str, body: dict) -> dict:
    """UpdateTable / UpdateTimeToLive / UpdateContinuousBackups / CreateBackup /
    DeleteBackup / UpdateContributorInsights with DynamoDB's validation."""
    ddb_ensure(table)
    b = dict(body or {})
    if section == "capacity":
        if "billing_mode" in b:
            mode = str(b["billing_mode"]).upper()
            if mode not in ("PAY_PER_REQUEST", "PROVISIONED"):
                raise DetailError("ValidationException", "BillingMode must be PAY_PER_REQUEST or PROVISIONED.")
            if mode == "PROVISIONED":
                r, w = int(b.get("read_capacity_units") or 0), int(b.get("write_capacity_units") or 0)
                if r < 1 or w < 1:
                    raise DetailError("ValidationException", "ProvisionedThroughput ReadCapacityUnits and WriteCapacityUnits must be at least 1.")
                table["provisioned_throughput"] = {"ReadCapacityUnits": r, "WriteCapacityUnits": w}
            table["billing_mode"] = mode
        if "table_class" in b:
            if b["table_class"] not in ("STANDARD", "STANDARD_INFREQUENT_ACCESS"):
                raise DetailError("ValidationException", "TableClass must be STANDARD or STANDARD_INFREQUENT_ACCESS.")
            table["table_class"] = b["table_class"]
        if "deletion_protection" in b:
            table["deletion_protection"] = b["deletion_protection"] in _TRUE
    elif section == "streams":
        st = table["streams"]
        on = b.get("stream_enabled") in _TRUE
        if on:
            vt = str(b.get("view_type") or "NEW_AND_OLD_IMAGES")
            if vt not in _DDB_VIEW_TYPES:
                raise DetailError("ValidationException", f"StreamViewType must be one of {', '.join(_DDB_VIEW_TYPES)}.")
            if st.get("enabled"):
                raise DetailError("ValidationException", f"Table already has an enabled stream: {st.get('latest_stream_label')}")
            st.update(enabled=True, view_type=vt, latest_stream_label=_now().replace("Z", "")[:23])
        else:
            if not st.get("enabled"):
                raise DetailError("ValidationException", "Table does not have an enabled stream.")
            st.update(enabled=False, view_type="")
    elif section == "encryption":
        typ = str(b.get("sse_type") or "AWS_OWNED")
        if typ not in _DDB_SSE:
            raise DetailError("ValidationException", "SSEType must be AWS_OWNED, AWS_MANAGED or CUSTOMER_MANAGED.")
        key = str(b.get("kms_key_arn") or "")
        if typ == "CUSTOMER_MANAGED" and not key:
            raise DetailError("ValidationException", "A KMS key ARN is required for a customer managed key.")
        table["sse"] = {"type": typ, "kms_key_arn": key if typ == "CUSTOMER_MANAGED" else ""}
    elif section == "ttl":
        on = b.get("enabled") in _TRUE
        cur = table["ttl"]
        if on and cur["status"] == "ENABLED":
            raise DetailError("ValidationException", "TimeToLive is already enabled")
        if not on and cur["status"] != "ENABLED":
            raise DetailError("ValidationException", "TimeToLive is already disabled")
        attr = str(b.get("attribute_name") or cur.get("attribute") or "").strip()
        if on and not attr:
            raise DetailError("ValidationException", "The TTL attribute name is required.")
        table["ttl"] = {"status": "ENABLED" if on else "DISABLED", "attribute": attr}
    elif section == "pitr":
        on = b.get("enabled") in _TRUE
        table["pitr"] = {"status": "ENABLED" if on else "DISABLED", "enabled_at": _now() if on else ""}
    elif section == "insights":
        table["contributor_insights"] = "ENABLED" if b.get("enabled") in _TRUE else "DISABLED"
    elif section == "indexes":
        if b.get("action") == "delete":
            name = str(b.get("index_name") or "")
            if not any(g.get("name") == name for g in table.get("indexes") or []):
                raise DetailError("ResourceNotFoundException", f"Requested resource not found: Index: {name} not found.")
            table["indexes"] = [g for g in table["indexes"] if g.get("name") != name]
        else:
            name = str(b.get("index_name") or "").strip()
            pk = str(b.get("partition_key") or "").strip()
            if not name or not pk:
                raise DetailError("ValidationException", "IndexName and a partition key are required.")
            if len(table.get("indexes") or []) >= 20:
                raise DetailError("LimitExceededException", "A table can have up to 20 global secondary indexes.")
            if any(g.get("name") == name for g in (table.get("indexes") or []) + (table.get("local_indexes") or [])):
                raise DetailError("ValidationException", f"Attempting to create an index which already exists: {name}")
            _attr_def(table, pk, str(b.get("partition_key_type") or "S"))
            ks = [{"AttributeName": pk, "KeyType": "HASH"}]
            sk = str(b.get("sort_key") or "").strip()
            if sk:
                _attr_def(table, sk, str(b.get("sort_key_type") or "S"))
                ks.append({"AttributeName": sk, "KeyType": "RANGE"})
            proj = str(b.get("projection") or "ALL")
            if proj not in ("ALL", "KEYS_ONLY", "INCLUDE"):
                raise DetailError("ValidationException", "ProjectionType must be ALL, KEYS_ONLY or INCLUDE.")
            table.setdefault("indexes", []).append({"name": name, "key_schema": ks, "partition_key_name": pk, "sort_key_name": sk,
                                                    "projection": {"ProjectionType": proj}, "index_status": "ACTIVE"})
    elif section == "backups":
        if b.get("action") == "delete":
            arn = str(b.get("backup_arn") or "")
            if not any(x["backup_arn"] == arn for x in table["backups"]):
                raise DetailError("BackupNotFoundException", f"Backup not found: {arn}")
            table["backups"] = [x for x in table["backups"] if x["backup_arn"] != arn]
        else:
            import re
            name = str(b.get("backup_name") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{3,255}", name):
                raise DetailError("ValidationException", "BackupName must be 3-255 characters: letters, numbers, '_', '-', '.'.")
            ts = int(time.time() * 1000)
            table["backups"].append({"backup_name": name, "backup_arn": f"{_ddb_arn(table)}/backup/{ts:013d}-{_hex(8)}",
                                     "backup_status": "AVAILABLE", "backup_type": "USER", "created": _now(),
                                     "size_bytes": int(table.get("table_size_bytes") or 0), "item_count": len(table.get("items") or {})})
    else:
        raise DetailError("ValidationException", f"Unknown table section '{section}'.")
    table["last_modified"] = _now()
    return ddb_section(table, section)


def ddb_check_delete(table: dict) -> None:
    if (table or {}).get("deletion_protection"):
        raise DetailError("ValidationException",
                          f"Resource cannot be deleted as it is currently protected against deletion. Disable deletion "
                          f"protection first.")
