"""Offline appliance wiring of netsim (real server.py in-process, FastAPI TestClient):

  * the EC2 Query VPC actions land in the ONE engine (core/vpc_core) and stay visible to the
    pre-v4 readers (vpc_state mirror); Reachability Analyzer answers from netsim
  * an EC2 launch into a core subnet gets an in-subnet private IP and becomes a netsim interface
  * GCP Connectivity Tests + Azure Network Watcher are served offline by the same cores
  * enforcement is a NO-OP by default (VYOMI_NETSIM_ENFORCE unset) — never an error

    PYTHONPATH=. python3 -m pytest -q tests/netsim/test_offline_wiring.py
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_D = Path(tempfile.mkdtemp(prefix="vyomi-netsim-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_D / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_D / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.pop("VYOMI_NETSIM_ENFORCE", None)

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from core.netsim import wiring  # noqa: E402

C = TestClient(server.app)
EC2H = {"Authorization": "AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/ec2/aws4_request, "
                         "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64,
        "content-type": "application/x-www-form-urlencoded"}


def ec2(action, **p):
    r = C.post("/", data={"Action": action, "Version": "2016-11-15", **{k: str(v) for k, v in p.items()}}, headers=EC2H)
    return r.status_code, r.text


def xid(body, tag):
    m = re.search(f"<{tag}>([^<]+)</{tag}>", body)
    assert m, body[:500]
    return m.group(1)


def test_vpc_actions_use_the_core_engine_and_analyzer():
    st, body = ec2("CreateVpc", CidrBlock="10.91.0.0/16")
    assert st == 200, body
    vpc = xid(body, "vpcId")
    sub = xid(ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.91.1.0/24")[1], "subnetId")
    sg = xid(ec2("CreateSecurityGroup", VpcId=vpc, GroupName="web", GroupDescription="web")[1], "groupId")
    m = server._Ec2CoreSpaceStore()._vpc_model
    assert vpc in m["vpcs"] and sub in m["subnets"] and sg in m["sgs"]          # one engine
    assert server.vpc_state["subnets"][sub]["_engine"] == "vpc_core"             # legacy readers bridged
    st, body = ec2("CreateNetworkAcl", VpcId=vpc)                                # was split-brain before
    assert st == 200, body
    st, body = ec2("DescribeSecurityGroups", **{"GroupId.1": sg})
    assert st == 200 and sg in body
    # Reachability Analyzer from netsim
    st, body = ec2("AnalyzeReachability", **{"Source.Ip": "10.91.1.10", "Destination.Ip": "10.91.1.20",
                                             "Destination.SecurityGroupId.1": sg, "DestinationPort": "22"})
    assert st == 200 and "<reachable>false</reachable>" in body and "<code>INGRESS_DENIED</code>" in body, body
    ec2("AuthorizeSecurityGroupIngress", GroupId=sg, **{"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "22",
                                                        "IpPermissions.1.ToPort": "22", "IpPermissions.1.IpRanges.1.CidrIp": "10.91.0.0/16"})
    st, body = ec2("AnalyzeReachability", **{"Source.Ip": "10.91.1.10", "Destination.Ip": "10.91.1.20",
                                             "Destination.SecurityGroupId.1": sg, "DestinationPort": "22"})
    assert "<reachable>true</reachable>" in body, body


def test_launch_into_core_subnet_gets_subnet_ip_and_interface():
    vpc = xid(ec2("CreateVpc", CidrBlock="10.92.0.0/16")[1], "vpcId")
    sub = xid(ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.92.5.0/24")[1], "subnetId")
    req = server.EC2InstanceRequest(name="n1", instance_type="t3.micro", ami="ami-amzn2023", runtime="python",
                                    key_pair="", subnet_id=sub, vpc_id=vpc, security_group_ids=[], az="us-east-1a",
                                    storage_gb=8, command="", user_data="")
    try:
        inst = server.api_ec2_create_instance(req, auto_start=False, host_os_hint="linux")
    except Exception as exc:          # no runtime backend on this host → launch policy refuses; skip the rest
        import pytest
        pytest.skip(f"no instance runtime on this host: {exc}")
    assert inst["private_ip"].startswith("10.92.5.") and int(inst["private_ip"].split(".")[-1]) >= 4
    t = wiring.netsim_topology()
    assert any(i.instance == inst["instance_id"] and i.subnet == sub for i in t.interfaces.values())


def test_gcp_connectivity_test_offline():
    p = "netsim-offline"
    assert C.post(f"/compute/v1/projects/{p}/global/networks", json={"name": "n1", "autoCreateSubnetworks": False}).status_code == 200
    r = C.post(f"/v1/projects/{p}/locations/global/connectivityTests", params={"testId": "t1"},
               json={"source": {"ipAddress": "10.0.0.5"}, "destination": {"ipAddress": "203.0.113.4", "port": 443},
                     "protocol": "TCP"})
    assert r.status_code == 200, r.text
    assert r.json()["response"]["reachabilityDetails"]["result"] in ("REACHABLE", "UNREACHABLE")
    assert C.get(f"/v1/projects/{p}/locations/global/connectivityTests/t1").json()["name"].endswith("/t1")


def test_azure_network_watcher_offline():
    sub, rg = "00000000-0000-0000-0000-00000000ab01", "ns-rg"
    base = f"/subscriptions/{sub}/resourceGroups/{rg}"
    q = {"api-version": "2023-11-01"}
    assert C.put(base, params={"api-version": "2021-04-01"}, json={"location": "eastus"}).status_code < 300
    net = f"{base}/providers/Microsoft.Network"
    r = C.put(f"{net}/virtualNetworks/v1", params=q, json={"location": "eastus", "properties": {
        "addressSpace": {"addressPrefixes": ["10.93.0.0/16"]}, "subnets": [{"name": "s1", "properties": {"addressPrefix": "10.93.1.0/24"}}]}})
    assert r.status_code < 300, r.text
    r = C.put(f"{net}/networkInterfaces/nic1", params=q, json={"location": "eastus", "properties": {"ipConfigurations": [
        {"name": "ip1", "properties": {"subnet": {"id": f"{net}/virtualNetworks/v1/subnets/s1"}}}]}})
    assert r.status_code < 300, r.text
    assert r.json()["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"] == "10.93.1.4"
    assert C.put(f"{net}/networkWatchers/nw", params=q, json={"location": "eastus"}).status_code < 300
    r = C.post(f"{net}/networkWatchers/nw/nextHop", params=q, json={
        "targetResourceId": f"{net}/networkInterfaces/nic1", "destinationIPAddress": "8.8.8.8"})
    assert r.status_code == 200 and r.json()["nextHopType"] == "Internet", r.text


def test_enforcement_off_is_a_noop():
    assert wiring.enabled() is False
    assert wiring.schedule_apply("test") is False
    assert wiring.apply_now("test") is None
    assert wiring.docker_attach({"instance_id": "i-0123456789abcdef0"}) is None
    assert wiring.status()["enabled"] is False
