"""REAL packets driven end-to-end through the OFFLINE APPLIANCE: server.py EC2 Query API →
core/vpc_core → core/netsim/wiring (netsim_topology + DockerEnforcer, enabled with
VYOMI_NETSIM_ENFORCE=1) → Docker networks + nftables. The appliance's own Reachability
Analyzer answer (AnalyzeReachability over the wire) must equal the kernel outcome.

Instances are the appliance's EC2 records (api_ec2_create_instance), attached to the network
exactly the way server._docker_instance_obj does it (wiring.docker_attach). Everything created
is netsim-test-* (nft table vyomi_netsimtest-…) and removed. Skipped without Docker/nft.

    PYTHONPATH=. python3 -m pytest -q -s tests/netsim/test_docker_offline_e2e.py
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from tests.netsim.test_docker_e2e import CLIENT, SERVER, SKIP, docker_ok  # noqa: F401  (reuse probes)

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(SKIP is not None, reason=SKIP or "")

_D = Path(tempfile.mkdtemp(prefix="vyomi-netsim-e2e-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_D / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_D / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.update({"VYOMI_NETSIM_ENFORCE": "1", "VYOMI_NETSIM_PREFIX": "netsim-test-",
                   "VYOMI_NETD_NAME": "netsim-test-netd", "VYOMI_NETD_IMAGE": "netsim-test-netd:latest",
                   "VYOMI_NETSIM_SPACE_PREFIX": "netsimtest-", "VYOMI_NETSIM_DEBOUNCE_MS": "50"})

RESULTS: list = []


def sh(*a, check=True):
    p = subprocess.run(list(a), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(a[:5])}: {p.stderr.strip()}")
    return p


@pytest.fixture(scope="module")
def appliance():
    if SKIP:
        pytest.skip(SKIP)
    sh("docker", "build", "-q", "-t", "netsim-test-netd:latest", str(ROOT / "docker" / "netd"))
    from fastapi.testclient import TestClient
    import server
    from core.netsim import wiring
    yield server, TestClient(server.app), wiring
    try:
        for enf in wiring._ENFORCERS.values():
            enf.teardown(remove_networks=False)
    except Exception as exc:                    # noqa: BLE001
        print("teardown:", exc)
    for c in sh("docker", "ps", "-aq", "--filter", "name=^netsim-test-", check=False).stdout.split():
        sh("docker", "rm", "-f", c, check=False)
    for n in sh("docker", "network", "ls", "--format", "{{.Name}}", check=False).stdout.split():
        if n.startswith("netsim-test-"):
            sh("docker", "network", "rm", n, check=False)
    sh("docker", "rmi", "netsim-test-netd:latest", check=False)
    print("\n| # | case (driven via the appliance API) | analyzer (AnalyzeReachability) | real packets | match |\n|---|---|---|---|---|")
    for n, r in enumerate(RESULTS, 1):
        print(f"| {n} | {r[0]} | {r[1]} | {r[2]} | {'yes' if r[3] else 'NO'} |")


def test_appliance_api_to_packets(appliance):
    server, c, wiring = appliance
    h = {"Authorization": "AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/ec2/aws4_request, "
                          "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64,
         "content-type": "application/x-www-form-urlencoded"}

    def ec2(action, **p):
        r = c.post("/", data={"Action": action, "Version": "2016-11-15", **{k: str(v) for k, v in p.items()}}, headers=h)
        assert r.status_code == 200, (action, r.text[:400])
        return r.text

    def xid(body, tag):
        return re.search(f"<{tag}>([^<]+)</{tag}>", body).group(1)

    vpc = xid(ec2("CreateVpc", CidrBlock="10.216.0.0/16"), "vpcId")
    sa = xid(ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.216.1.0/24"), "subnetId")
    sb = xid(ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.216.2.0/24"), "subnetId")
    sg = xid(ec2("CreateSecurityGroup", VpcId=vpc, GroupName="web", GroupDescription="web"), "groupId")
    ec2("AuthorizeSecurityGroupIngress", GroupId=sg, **{"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "22",
                                                        "IpPermissions.1.ToPort": "22", "IpPermissions.1.IpRanges.1.CidrIp": "10.216.0.0/16"})
    insts = {}
    for key, sub in (("x", sa), ("y", sb)):
        req = server.EC2InstanceRequest(name=f"netsim-{key}", instance_type="t3.micro", ami="ami-amzn2023", runtime="python",
                                        key_pair="", subnet_id=sub, vpc_id=vpc, security_group_ids=[sg], az="us-east-1a",
                                        storage_gb=8, command="", user_data="")
        insts[key] = server.api_ec2_create_instance(req, auto_start=False, host_os_hint="linux")
    names = {}
    for key, inst in insts.items():
        att = wiring.docker_attach(inst)                  # what _docker_instance_obj uses
        assert att, wiring.status()
        assert att["ip"] == inst["private_ip"] and att["network"].startswith("netsim-test-")
        names[key] = f"netsim-test-app-{key}"
        sh("docker", "run", "-d", "--name", names[key], "--network", att["network"], "--ip", att["ip"],
           "--label", "netsim-test=1", "python:3-alpine", "python3", "-c", SERVER)
    time.sleep(1.5)

    def case(label, port, sport):
        wiring.apply_now(label)                           # deterministic (the API kick is debounced)
        assert wiring.status()["last_apply"]["ok"], wiring.status()
        body = ec2("AnalyzeReachability", **{"Source.Ip": insts["x"]["private_ip"], "Source.SecurityGroupId.1": sg,
                                             "Destination.Ip": insts["y"]["private_ip"], "Destination.SecurityGroupId.1": sg,
                                             "DestinationPort": str(port)})
        verdict = "<reachable>true</reachable>" in body
        code = xid(body, "code")
        out = sh("docker", "exec", names["x"], "python3", "-c", CLIENT, insts["y"]["private_ip"], str(port), str(sport)).stdout.strip()
        ok = out.startswith("OK")
        RESULTS.append((label, "ALLOW" if verdict else f"BLOCK {code}", "ALLOW" if ok else "BLOCK", verdict == ok))
        assert verdict == ok, (label, body, out)
        return verdict

    assert case("SG allows tcp/22 (created via API)", 22, 42001) is True
    assert case("SG has no tcp/80", 80, 42002) is False
    ec2("AuthorizeSecurityGroupIngress", GroupId=sg, **{"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "80",
                                                        "IpPermissions.1.ToPort": "80", "IpPermissions.1.IpRanges.1.CidrIp": "10.216.1.0/24"})
    assert case("after AuthorizeSecurityGroupIngress tcp/80", 80, 42003) is True
    acl = xid(ec2("CreateNetworkAcl", VpcId=vpc), "networkAclId")
    ec2("CreateNetworkAclEntry", NetworkAclId=acl, RuleNumber="90", Protocol="6", RuleAction="deny", Egress="false",
        CidrBlock="10.216.1.0/24", **{"PortRange.From": "22", "PortRange.To": "22"})
    ec2("CreateNetworkAclEntry", NetworkAclId=acl, RuleNumber="100", Protocol="-1", RuleAction="allow", Egress="false", CidrBlock="0.0.0.0/0")
    ec2("CreateNetworkAclEntry", NetworkAclId=acl, RuleNumber="100", Protocol="-1", RuleAction="allow", Egress="true", CidrBlock="0.0.0.0/0")
    ec2("AssociateNetworkAcl", NetworkAclId=acl, SubnetId=sb)
    assert case("NACL rule 90 denies tcp/22 (via API)", 22, 42004) is False
    assert case("NACL allows tcp/80", 80, 42005) is True
    # the debounced kick from the API calls really fires too
    t0 = wiring.status()["last_apply"]["at"]
    ec2("RevokeSecurityGroupIngress", GroupId=sg, **{"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "80",
                                                     "IpPermissions.1.ToPort": "80", "IpPermissions.1.IpRanges.1.CidrIp": "10.216.1.0/24"})
    for _ in range(50):
        if wiring.status()["last_apply"]["at"] > t0:
            break
        time.sleep(0.1)
    assert wiring.status()["last_apply"]["at"] > t0, "API mutation did not trigger an apply"
    assert "Revoke" in wiring.status()["last_apply"]["reason"]
    assert case("after RevokeSecurityGroupIngress tcp/80", 80, 42006) is False
