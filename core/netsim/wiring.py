"""netsim offline wiring — the appliance side of enforcement (NOT vendored to Nano).

    enabled()                    VYOMI_NETSIM_ENFORCE: 0 (default) | 1 | auto
    netsim_topology(space)       one Topology for the active space from the offline stores:
                                 AWS vpc_core slot (+ the legacy EC2 instance records),
                                 GCP compute VPC + VM core stores, Azure ARM state
    schedule_apply(reason)       debounced (VYOMI_NETSIM_DEBOUNCE_MS, 250) DockerEnforcer.apply
    docker_attach(instance)      {"network", "ip"} for a Docker-backed instance, applying first
    status()                     last apply result (diagnostics: /api/netsim/status if mounted)

Contract: every entry point is a NO-OP returning None/False when enforcement is off, Docker or
nft-in-host-netns is unavailable, or anything fails — instance launch must never break because of
networking. Failures are recorded in status() and logged once.

Enabling on an appliance (Linux Docker host or Docker Desktop):
    docker build -t vyomi/netd:1 docker/netd          (or pull the published image)
    VYOMI_NETSIM_ENFORCE=1   (or auto: on when `docker` works and a host-netns nft probe passes)
The appliance container only needs the docker socket; the privileged part runs in the
`vyomi-netd` sidecar (`--network host --cap-add NET_ADMIN`) that DockerEnforcer starts.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time

from core.netsim import enforce as _enf
from core.netsim import from_aws, from_azure, from_gcp
from core.netsim.model import Interface, Topology, ip_in

_log = logging.getLogger("vyomi.netsim")
_STATE = {"probe": None, "last": None, "timer": None, "lock": threading.Lock(), "warned": set()}


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip().lower()


def _probe() -> bool:
    if _STATE["probe"] is None:
        ok = False
        try:
            p = subprocess.run(["docker", "info", "--format", "{{.OSType}}"], capture_output=True, text=True, timeout=10)
            ok = p.returncode == 0 and p.stdout.strip() == "linux"
        except Exception:
            ok = False
        _STATE["probe"] = ok
    return bool(_STATE["probe"])


def enabled() -> bool:
    mode = _env("VYOMI_NETSIM_ENFORCE", "0")
    if mode in ("1", "true", "on", "yes"):
        return True
    if mode == "auto":
        return _probe()
    return False


def _warn_once(key: str, msg: str) -> None:
    if key not in _STATE["warned"]:
        _STATE["warned"].add(key)
        _log.warning("netsim: %s", msg)


def _space_id() -> str:
    try:
        from core.app_context import PLATFORM
        sid = (PLATFORM.kernel.state.get("spaces") or {}).get("active_space_id") or "default"
    except Exception:
        sid = "default"
    return (os.environ.get("VYOMI_NETSIM_SPACE_PREFIX") or "") + str(sid)


def mgmt_cidrs() -> list:
    """Sources allowed to reach instances regardless of rules (console SSH bridge): the
    appliance container's own addresses + VYOMI_NETSIM_MGMT_CIDRS."""
    out = [c.strip() for c in (os.environ.get("VYOMI_NETSIM_MGMT_CIDRS") or "").split(",") if c.strip()]
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                out.append(f"{ip}/32")
    except Exception:
        pass
    return out


# ── topology from the offline stores ─────────────────────────────────────────
def _merge(dst: Topology, src: Topology) -> Topology:
    for k in ("networks", "subnets", "interfaces", "rulesets", "route_tables", "gateways", "peerings"):
        getattr(dst, k).update(getattr(src, k))
    dst.warnings.extend(src.warnings)
    return dst


def aws_model() -> dict | None:
    try:
        from core.app_context import PLATFORM
        spaces = PLATFORM.kernel.state.get("spaces") or {}
        sid = spaces.get("active_space_id") or "default"
        return ((spaces.get("spaces") or {}).get(sid) or {}).get("service_states", {}).get("ec2_vpc_core")
    except Exception:
        return None


def _aws_topology() -> Topology:
    m = aws_model()
    if not m:
        return Topology(cloud="aws")
    t = from_aws.from_aws(m)
    try:                                   # the legacy EC2 handler owns RunInstances offline
        from core.app_context import ec2_state
        insts = dict(ec2_state.get("instances") or {})
    except Exception:
        insts = {}
    for iid, inst in insts.items():
        if not isinstance(inst, dict) or inst.get("state") in ("terminated", "shutting-down"):
            continue
        sid = inst.get("subnet_id")
        if sid not in t.subnets or not ip_in(str(inst.get("private_ip") or ""), t.subnets[sid].cidr):
            continue
        sgs = [g for g in inst.get("security_group_ids") or [] if g in t.rulesets]
        if not sgs:
            vpc = t.subnets[sid].network
            sgs = [g["id"] for g in m.get("sgs", {}).values() if g.get("vpc_id") == vpc and g.get("is_default")][:1]
        t.add(Interface(id=from_aws.primary_eni(iid), instance=iid, subnet=sid, ip=inst["private_ip"],
                        public_ip=inst.get("public_ip") or None, groups=sgs, rulesets=sgs,
                        source_dest_check=inst.get("source_dest_check", True), name=str(inst.get("name") or "")))
    return t


def _gcp_topology() -> Topology:
    try:
        from core import appliance_stores as aps
        return from_gcp.from_gcp(aps.gcp_compute_vpc_store(), aps.gcp_compute_vm_store(), None)
    except Exception as exc:
        _warn_once("gcp", f"GCP topology unavailable: {exc}")
        return Topology(cloud="gcp")


def _azure_topology() -> Topology:
    try:
        from providers import azure_services
        return from_azure.from_azure(azure_services._state)
    except Exception as exc:
        _warn_once("azure", f"Azure topology unavailable: {exc}")
        return Topology(cloud="azure")


def netsim_topology(space: str | None = None) -> Topology:
    t = Topology(cloud="multi")
    for part in (_aws_topology(), _gcp_topology(), _azure_topology()):
        _merge(t, part)
    return t


# ── enforcement ─────────────────────────────────────────────────────────────
def _enforcer(space: str) -> _enf.DockerEnforcer:
    return _enf.DockerEnforcer(space, prefix=os.environ.get("VYOMI_NETSIM_PREFIX", "vyomi-net-"),
                               netd_name=os.environ.get("VYOMI_NETD_NAME", "vyomi-netd"),
                               netd_image=os.environ.get("VYOMI_NETD_IMAGE", "vyomi/netd:1"),
                               mgmt_cidrs=mgmt_cidrs())


_ENFORCERS: dict = {}


def apply_now(reason: str = "") -> dict | None:
    if not enabled():
        return None
    space = _space_id()
    with _STATE["lock"]:
        t0 = time.time()
        try:
            enf = _ENFORCERS.setdefault(space, _enforcer(space))
            plan = enf.apply(netsim_topology(space))
            res = {"ok": True, "space": space, "reason": reason, "table": plan.table, "networks": len(plan.networks),
                   "warnings": plan.warnings[:20], "ms": int((time.time() - t0) * 1000), "at": time.time()}
        except Exception as exc:          # never propagate: enforcement is best-effort
            res = {"ok": False, "space": space, "reason": reason, "error": str(exc)[:500], "at": time.time()}
            _warn_once(f"apply:{type(exc).__name__}", f"apply failed ({reason}): {exc}")
        _STATE["last"] = res
        return res


def schedule_apply(reason: str = "") -> bool:
    """Debounced apply after a networking mutation / instance lifecycle change."""
    try:
        if not enabled():
            return False
        delay = int(os.environ.get("VYOMI_NETSIM_DEBOUNCE_MS", "250")) / 1000.0
        old = _STATE.get("timer")
        if old is not None:
            old.cancel()
        tm = threading.Timer(delay, apply_now, args=(reason,))
        tm.daemon = True
        _STATE["timer"] = tm
        tm.start()
        return True
    except Exception:
        return False


def _iface_for_instance(t: Topology, instance: dict):
    iid = str(instance.get("instance_id") or "")
    eni = from_aws.primary_eni(iid) if iid.startswith("i-") else ""
    if eni in t.interfaces:
        return t.interfaces[eni]
    try:                                    # GCE: the core record links its runtime by _runtimeId
        from core import appliance_stores as aps
        for full, rec in aps.gcp_compute_vm_store().instances.items():
            if rec.get("_runtimeId") == iid and f"{full}/nic0" in t.interfaces:
                return t.interfaces[f"{full}/nic0"]
    except Exception:
        pass
    return None


def docker_attach(instance: dict) -> dict | None:
    """Network + IP for a Docker-backed instance whose interface is modelled. Applies the
    space's plan first (so the subnet bridge exists). None → caller keeps its legacy network."""
    if not enabled():
        return None
    try:
        space = _space_id()
        t = netsim_topology(space)
        iface = _iface_for_instance(t, instance)
        if iface is None:
            return None
        res = apply_now(f"attach {instance.get('instance_id')}")
        if not res or not res.get("ok"):
            return None
        args = _ENFORCERS[space].run_args(t, iface.id)
        return {"network": args[1], "ip": args[3], "interface": iface.id}
    except Exception as exc:
        _warn_once("attach", f"attach skipped: {exc}")
        return None


def status() -> dict:
    return {"enabled": enabled(), "mode": _env("VYOMI_NETSIM_ENFORCE", "0"), "platform": sys.platform,
            "last_apply": _STATE.get("last")}
