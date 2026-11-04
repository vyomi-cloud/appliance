# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""VPC Encryption Controls (EC2 Query actions on the shared EC2/VPC model): per-VPC monitor / enforce mode, resource exclusions and
an audit of the VPC's network interfaces and load balancers.

CreateVpcEncryptionControl / DescribeVpcEncryptionControls / ModifyVpcEncryptionControl / DeleteVpcEncryptionControl /
GetVpcResourcesBlockingEncryptionEnforcement. State lives in the EC2 model (`model["vpc_encryption_controls"]`).

What is real: the control lifecycle (one per VPC, monitor <-> enforce, exclusions, creating -> available, delete), the audit over
the VPC's actual resources, and enforcement - switching to `enforce` is refused while non-excluded unencrypted resources exist
(see GetVpcResourcesBlockingEncryptionEnforcement), and in an enforced VPC RunInstances of an instance type that cannot encrypt
traffic is rejected.

Honest limit: Vyomi moves no packets, so "encrypted" is a classification rule, not an observation of traffic. A network interface
is encrypted when the instance it is attached to is of a family that supports Nitro in-transit encryption - a documented approximation
(6th generation and later Intel/AMD, Graviton2 and later, plus c5n/m5n/m5dn/r5n/r5dn/i3en/g4dn/p3dn), not AWS's authoritative
list; interfaces owned by AWS services (VPC endpoints, NAT gateways, load balancers) follow the service; a load balancer is
unencrypted when it has a plaintext (HTTP/TCP/UDP) listener - a Vyomi audit rule, not an AWS notion. Unattached interfaces carry no
traffic and do not block enforcement.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone

_EXCL = ("InternetGateway", "EgressOnlyInternetGateway", "NatGateway", "VirtualPrivateGateway", "VpcPeering", "Lambda", "VpcLattice", "ElasticFileSystem")
_ENC_EXTRA = {"c5n", "m5n", "m5dn", "r5n", "r5dn", "i3en", "g4dn", "p3dn"}


def _V():
    try:
        from core import vpc_core
    except ImportError:  # Pyodide flat layout
        import vpc_core  # type: ignore
    return vpc_core


def _err(code, msg, status=400):
    return _V().VpcError(code, msg, status)


def _x(v):
    return _V()._xml_escape(str(v))


def _bag(m):
    return m.setdefault("vpc_encryption_controls", {})


def family_encrypts(itype: str) -> bool:
    fam = (itype or "").split(".")[0].lower()
    if fam in _ENC_EXTRA:
        return True
    mt = re.match(r"^([a-z]+)(\d+)([a-z]*)$", fam)
    if not mt:
        return False
    gen, suffix = int(mt.group(2)), mt.group(3)
    if "g" in suffix and gen >= 2 and not fam.startswith("g"):     # Graviton2 and later (m6g, c6g, t4g, ...)
        return True
    return gen >= 6


def audit(store, vpc_id: str, excl: dict | None = None) -> list:
    """[{Id, Type, Description, Encrypted, Reason, IsExcludable, Excluded}] for the VPC's resources."""
    m = _V()._model(store)
    excl = excl or {}
    rows = []
    for e in m["enis"].values():
        if e.get("vpc_id") != vpc_id:
            continue
        desc = str(e.get("description") or "")
        att = e.get("attachment") or {}
        kind, excludable, excluded_key = "network-interface", False, None
        if desc.startswith("VPC Endpoint"):
            enc, reason, kind = True, "AWS-managed PrivateLink interface", "vpc-endpoint"
        elif "NAT Gateway" in desc:
            enc, reason, kind, excludable, excluded_key = True, "AWS-managed NAT gateway interface", "nat-gateway", True, "NatGateway"
        elif att.get("instance_id"):
            inst = m["instances"].get(att["instance_id"], {})
            t = inst.get("instance_type", "")
            enc = family_encrypts(t)
            reason = f"instance {att['instance_id']} ({t}) " + ("supports in-transit encryption" if enc else "is an instance family without in-transit encryption")
        else:
            continue                                  # unattached: carries no traffic
        rows.append({"Id": e["id"], "Type": kind, "Description": desc, "Encrypted": enc, "Reason": reason, "IsExcludable": excludable,
                     "Excluded": bool(excluded_key and excl.get(excluded_key) == "enable")})
    for i in m["instances"].values():                 # every instance's primary network interface is implicit in the model
        if i.get("vpc_id") != vpc_id or i.get("state") not in ("running", "pending"):
            continue
        enc = family_encrypts(i.get("instance_type", ""))
        rows.append({"Id": i["id"], "Type": "instance-network-interface", "Description": f"Primary network interface of {i['id']}", "Encrypted": enc,
                     "Reason": f"instance type {i.get('instance_type')} " + ("supports in-transit encryption" if enc else "is a family without in-transit encryption"),
                     "IsExcludable": False, "Excluded": False})
    elb = getattr(store, "elbv2_store", None)
    if elb is not None:
        for lb in elb.load_balancers.values():
            lb_vpcs = {(m["subnets"].get(a.get("SubnetId")) or {}).get("vpc_id") for a in lb.get("AvailabilityZones", [])}
            if vpc_id not in lb_vpcs and lb.get("VpcId") != vpc_id:
                continue
            plain = [ls.get("Protocol") for ls in (getattr(elb, "listeners", {}) or {}).values()
                     if ls.get("LoadBalancerArn") == lb["LoadBalancerArn"] and ls.get("Protocol") in ("HTTP", "TCP", "UDP", "TCP_UDP")]
            rows.append({"Id": lb["LoadBalancerArn"], "Type": "load-balancer", "Description": lb.get("LoadBalancerName", ""), "Encrypted": not plain,
                         "Reason": ("plaintext listener(s): " + ", ".join(sorted(set(plain)))) if plain else "all listeners use TLS or there are none",
                         "IsExcludable": False, "Excluded": False})
    return rows


def blocking(store, vpc_id: str, excl: dict | None = None) -> list:
    return [r for r in audit(store, vpc_id, excl) if not r["Encrypted"] and not r["Excluded"]]


def _excl_from_params(p, base=None):
    out = dict(base or {k: "disable" for k in _EXCL})
    for k in _EXCL:
        v = p.get(f"{k}Exclusion")
        if v is not None:
            if str(v) not in ("enable", "disable"):
                raise _err("InvalidParameterValue", f"Invalid value for {k}Exclusion: {v}. Valid values: enable, disable.")
            out[k] = str(v)
    return out


def _xml(c, store):
    ex = "".join(f"<{k[0].lower() + k[1:]}><state>{'enabled' if c['exclusions'][k] == 'enable' else 'disabled'}</state></{k[0].lower() + k[1:]}>" for k in _EXCL)
    tags = "".join(f"<item><key>{_x(k)}</key><value>{_x(v)}</value></item>" for k, v in c["tags"].items())
    return (f"<vpcEncryptionControlId>{c['id']}</vpcEncryptionControlId><vpcId>{c['vpc_id']}</vpcId><mode>{c['mode']}</mode><state>{c['state']}</state>"
            f"<stateMessage>{_x(c['message'])}</stateMessage><resourceExclusions>{ex}</resourceExclusions><tagSet>{tags}</tagSet>")


def _settle(c):
    if c["state"] == "creating" and time.time() - c["created"] >= 0:
        c["state"] = "available"


def _create(store, p):
    m = _V()._model(store)
    vpc_id = str(p.get("VpcId") or "")
    if not vpc_id:
        raise _err("MissingParameter", "The request must contain the parameter VpcId")
    if vpc_id not in m["vpcs"]:
        raise _err("InvalidVpcID.NotFound", f"The vpc ID '{vpc_id}' does not exist")
    if any(c["vpc_id"] == vpc_id for c in _bag(m).values()):
        raise _err("InvalidParameterValue", f"VPC {vpc_id} already has a VPC Encryption Control.")
    cid = "vpcec-" + uuid.uuid4().hex[:17]
    tags = _V()._parse_tag_specifications(p).get("vpc-encryption-control", {})
    c = {"id": cid, "vpc_id": vpc_id, "mode": "monitor", "state": "available", "message": "", "exclusions": _excl_from_params(p), "tags": tags, "created": time.time()}
    _bag(m)[cid] = c
    return _V()._envelope("CreateVpcEncryptionControl", f"<vpcEncryptionControl>{_xml(c, store)}</vpcEncryptionControl>")


def _get(m, cid):
    c = _bag(m).get(cid)
    if not c:
        raise _err("InvalidVpcEncryptionControlId.NotFound", f"The VPC Encryption Control '{cid}' does not exist")
    return c


def _describe(store, p):
    m = _V()._model(store)
    ids = [v for k, v in sorted(p.items()) if re.match(r"VpcEncryptionControlId\.\d+$", k)]
    for i in ids:
        _get(m, i)
    flt = {}
    for k, v in p.items():
        mt = re.match(r"Filter\.(\d+)\.Name$", k)
        if mt:
            flt[str(v)] = [str(p[kk]) for kk in sorted(p) if kk.startswith(f"Filter.{mt.group(1)}.Value.")]
    rows = []
    for c in _bag(m).values():
        _settle(c)
        if ids and c["id"] not in ids:
            continue
        if "vpc-id" in flt and c["vpc_id"] not in flt["vpc-id"]:
            continue
        if "mode" in flt and c["mode"] not in flt["mode"]:
            continue
        rows.append(f"<item>{_xml(c, store)}</item>")
    return _V()._envelope("DescribeVpcEncryptionControls", f"<vpcEncryptionControlSet>{''.join(rows)}</vpcEncryptionControlSet>")


def _modify(store, p):
    m = _V()._model(store)
    c = _get(m, str(p.get("VpcEncryptionControlId") or ""))
    new_ex = _excl_from_params(p, c["exclusions"])
    mode = str(p.get("Mode") or c["mode"])
    if mode not in ("monitor", "enforce"):
        raise _err("InvalidParameterValue", f"Invalid mode: {mode}. Valid values: monitor, enforce.")
    if mode == "enforce":
        bad = blocking(store, c["vpc_id"], new_ex)
        if bad:
            raise _err("OperationNotPermitted", f"VPC {c['vpc_id']} cannot enter enforce mode: {len(bad)} unencrypted resource(s) must be remediated or excluded first "
                       f"(e.g. {bad[0]['Id']}). See GetVpcResourcesBlockingEncryptionEnforcement.")
    c["mode"], c["exclusions"] = mode, new_ex
    return _V()._envelope("ModifyVpcEncryptionControl", f"<vpcEncryptionControl>{_xml(c, store)}</vpcEncryptionControl>")


def _delete(store, p):
    m = _V()._model(store)
    c = _get(m, str(p.get("VpcEncryptionControlId") or ""))
    del _bag(m)[c["id"]]
    c["state"] = "deleted"
    return _V()._envelope("DeleteVpcEncryptionControl", f"<vpcEncryptionControl>{_xml(c, store)}</vpcEncryptionControl>")


def _blocking(store, p):
    m = _V()._model(store)
    vpc_id = str(p.get("VpcId") or "")
    if vpc_id not in m["vpcs"]:
        raise _err("InvalidVpcID.NotFound", f"The vpc ID '{vpc_id}' does not exist")
    ctl = next((c for c in _bag(m).values() if c["vpc_id"] == vpc_id), None)
    rows = blocking(store, vpc_id, ctl["exclusions"] if ctl else None)
    items = "".join(f"<item><id>{_x(r['Id'])}</id><type>{r['Type']}</type><description>{_x(r['Description'])}</description>"
                    f"<reason>{_x(r['Reason'])}</reason><isExcludable>{str(r['IsExcludable']).lower()}</isExcludable></item>" for r in rows)
    return _V()._envelope("GetVpcResourcesBlockingEncryptionEnforcement", f"<nonCompliantResources>{items}</nonCompliantResources>")


def _vyomi_audit(store, p):
    """Vyomi extension: the full audit (encrypted + unencrypted) for the console."""
    m = _V()._model(store)
    vpc_id = str(p.get("VpcId") or "")
    if vpc_id not in m["vpcs"]:
        raise _err("InvalidVpcID.NotFound", f"The vpc ID '{vpc_id}' does not exist")
    ctl = next((c for c in _bag(m).values() if c["vpc_id"] == vpc_id), None)
    rows = audit(store, vpc_id, ctl["exclusions"] if ctl else None)
    items = "".join(f"<item><id>{_x(r['Id'])}</id><type>{r['Type']}</type><description>{_x(r['Description'])}</description><encrypted>{str(r['Encrypted']).lower()}</encrypted>"
                    f"<excluded>{str(r['Excluded']).lower()}</excluded><reason>{_x(r['Reason'])}</reason></item>" for r in rows)
    return _V()._envelope("VyomiDescribeVpcEncryptionAudit", f"<resourceSet>{items}</resourceSet>")


_SIMPLE = {"CreateVpcEncryptionControl": _create, "DescribeVpcEncryptionControls": _describe, "ModifyVpcEncryptionControl": _modify,
           "DeleteVpcEncryptionControl": _delete, "GetVpcResourcesBlockingEncryptionEnforcement": _blocking,
           "VyomiDescribeVpcEncryptionAudit": _vyomi_audit}


def install(ops):
    ops.update(_SIMPLE)
    run = ops["RunInstances"]

    def _run(store, p):
        m = _V()._model(store)
        ctls = _bag(m)
        if ctls:
            sid = str(p.get("SubnetId") or p.get("NetworkInterface.1.SubnetId") or "")
            vpc = (m["subnets"].get(sid) or {}).get("vpc_id") if sid else None
            if vpc is None:                                            # default VPC placement
                vpc = next((v for v, d in m["vpcs"].items() if d.get("default")), None)
            c = next((c for c in ctls.values() if c["vpc_id"] == vpc), None)
            if c and c["mode"] == "enforce" and not family_encrypts(str(p.get("InstanceType") or "t2.micro")):
                raise _err("OperationNotPermitted", f"VPC {vpc} has encryption control in enforce mode: instance type {p.get('InstanceType')} does not support in-transit encryption.")
        return run(store, p)
    ops["RunInstances"] = _run
