"""AWS console resource-detail tabs show THIS resource's real data (offline appliance).

Each section creates a resource through the console's own API, then reads every
detail-tab route the console calls and checks the values are the resource's own
(placement, interfaces, volumes, settings…) — and that tab actions persist.
Engine: core/aws_console_detail.py; routes: routes/aws_console_detail.py.

    VYOMI_BASE_URL=http://localhost:9000 python3 tests/conformance/test_aws_detail_tabs_api.py
"""
import ipaddress
import os
import sys
import time

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else '  ' + str(extra)[:400]}")
    failed = failed or not ok


def get(path, **kw):
    return requests.get(BASE + path, timeout=60, **kw)


def ec2():
    print("── EC2 instance")
    sfx = str(int(time.time()))[-6:]
    r = requests.post(f"{BASE}/api/ec2/instances?auto_start=false", timeout=120, json={
        "name": f"tabs-{sfx}", "instance_type": "t3.micro", "key_name": f"kp-{sfx}", "storage_gb": 12,
        "root_volume_type": "gp2", "user_data": "#!/bin/bash\necho tabs", "monitoring": True,
        "create_security_group": {"requested": True, "ssh_cidr": "10.1.0.0/16", "allow_https": True}})
    check("launch", r.status_code < 300, r.text)
    inst = r.json()
    iid = inst["instance_id"]
    p = f"/api/ec2/instances/{iid}"

    d = get(p + "/details").json()
    check("Details: instance id + type", d["instance_id"] == iid and d["instance_type"] == "t3.micro", d)
    check("Details: key pair it was launched with", d["key_name"] == f"kp-{sfx}", d)
    check("Details: placed in the default VPC/subnet", d["vpc_id"].startswith("vpc-") and d["subnet_id"].startswith("subnet-"), d)
    check("Details: monitoring enabled at launch", d["monitoring"] == "enabled", d)
    vpcs = {v["vpc_id"]: v for v in get("/api/vpc/vpcs").json()["vpcs"]}
    check("default VPC exists in the VPC console (172.31.0.0/16)", vpcs.get(d["vpc_id"], {}).get("cidr_block") == "172.31.0.0/16", vpcs)

    n = get(p + "/network-interfaces").json()["network_interfaces"]
    check("Networking: one primary ENI", len(n) == 1 and n[0]["network_interface_id"].startswith("eni-"), n)
    subnets = {s["subnet_id"]: s for s in get("/api/vpc/subnets").json()["subnets"]}
    check("Networking: ENI subnet is a real subnet of the VPC", subnets.get(n[0]["subnet_id"], {}).get("vpc_id") == d["vpc_id"], n)
    check("Networking: ENI carries the instance's private IP", n[0]["private_ip_address"] == inst["private_ip"], n)

    s = get(p + "/security").json()
    names = [g["group_name"] for g in s["security_groups"]]
    check("Security: launch-wizard group created", len(names) == 1 and names[0].startswith("launch-wizard-"), s)
    ports = {(r["port_range"], r["source"]) for r in s["inbound_rules"]}
    check("Security: SSH from the chosen CIDR + HTTPS", ("22", "10.1.0.0/16") in ports and ("443", "0.0.0.0/0") in ports, ports)
    sgs = {g["security_group_id"]: g for g in get("/api/vpc/security-groups").json()["security_groups"]}
    check("Security: group listed in the VPC console", s["security_groups"][0]["group_id"] in sgs, s)

    st = get(p + "/storage").json()
    root = st["block_devices"][0]
    check("Storage: root volume size/type from the launch", root["size"] == 12 and root["volume_type"] == "gp2" and root["root"], st)

    u = get(p + "/user-data").json()
    check("User data: the launch script", u["user_data"] == "#!/bin/bash\necho tabs", u)

    # Settings persist (ModifyInstanceAttribute) and termination protection is enforced.
    r = requests.put(BASE + p + "/attributes", json={"disable_api_termination": True}, timeout=30)
    check("Details: enable termination protection", r.status_code == 200 and r.json()["termination_protection"], r.text)
    check("Details: setting survives a re-read", get(p + "/details").json()["termination_protection"] is True)
    r = requests.post(BASE + p + "/terminate", timeout=60)
    check("terminate refused while protected", r.status_code == 400 and "disableApiTermination" in r.text, r.text)
    requests.put(BASE + p + "/attributes", json={"disable_api_termination": False}, timeout=30)

    # IAM role: associate a real role, then remove it.
    role = f"tabs-role-{sfx}"
    requests.post(BASE + "/api/iam/roles", json={"role_name": role}, timeout=30)
    r = requests.put(BASE + p + "/iam-instance-profile", json={"name": role}, timeout=30)
    check("IAM role: associate", r.status_code == 200 and r.json()["iam_instance_profile"]["role_name"] == role, r.text)
    check("Security tab shows the role", (get(p + "/security").json()["iam_instance_profile"] or {}).get("role_name") == role)
    r = requests.put(BASE + p + "/iam-instance-profile", json={"name": "no-such-role"}, timeout=30)
    check("IAM role: unknown role rejected", r.status_code == 400, r.text)
    r = requests.delete(BASE + p + "/iam-instance-profile", timeout=30)
    check("IAM role: remove", r.status_code == 200 and get(p + "/iam-instance-profile").json()["iam_instance_profile"] is None, r.text)

    # User data can only change while stopped.
    state = get(p).json().get("state")
    r = requests.put(BASE + p + "/user-data", json={"user_data": "echo changed"}, timeout=30)
    if state == "stopped":
        check("User data: edit while stopped persists", r.status_code == 200 and get(p + "/user-data").json()["user_data"] == "echo changed", r.text)
    else:
        check("User data: edit refused unless stopped", r.status_code == 400 and "stopped" in r.text, r.text)

    # Serial console access is an account setting.
    cur = get("/api/ec2/serial-console-access").json()["serial_console_access_enabled"]
    requests.put(BASE + "/api/ec2/serial-console-access", json={"enabled": not cur}, timeout=30)
    check("Serial console: account access toggles", get("/api/ec2/serial-console-access").json()["serial_console_access_enabled"] is (not cur))
    requests.put(BASE + "/api/ec2/serial-console-access", json={"enabled": cur}, timeout=30)
    co = get(p + "/console-output").json()
    check("Serial console: console output for this instance", co["instance_id"] == iid and "output" in co, co)

    # Permissions: an identity policy naming this instance shows up; one for another service does not.
    arn = f"arn:aws:ec2:us-east-1:123456789012:instance/{iid}"
    pol = requests.post(BASE + "/api/iam/policies", json={"policy_name": f"tabs-ec2-{sfx}", "document": {
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["ec2:StopInstances"], "Resource": arn}]}}, timeout=30).json()
    user = requests.post(BASE + "/api/iam/users", json={"user_name": f"tabs-user-{sfx}"}, timeout=30).json()
    requests.post(BASE + "/api/iam/attach-policy", json={"target_type": "user", "target_id": user["user_id"], "policy_id": pol["policy_id"]}, timeout=30)
    acc = get("/api/aws/resource-access", params={"arn": arn, "service": "ec2"}).json()["statements"]
    check("Permissions: the user's policy for this instance applies", any(x["principal"] == f"tabs-user-{sfx}" and x["actions"] == "ec2:StopInstances" for x in acc), acc)
    other = get("/api/aws/resource-access", params={"arn": arn.replace(iid, "i-other"), "service": "ec2"}).json()["statements"]
    check("Permissions: not listed for a different instance", not any(x["principal"] == f"tabs-user-{sfx}" for x in other), other)

    ev = get("/api/cloudsim/events").json().get("events", [])
    check("Activity: attribute change recorded for this instance",
          any(((e.get("detail") or {}).get("detail") or e.get("detail") or {}).get("resource_id") == iid and "modify_instance_attribute" in e.get("event", "") for e in ev))
    requests.post(BASE + p + "/terminate", timeout=60)


SECTIONS = {"ec2": ec2}

if __name__ == "__main__":
    only = sys.argv[1:] or list(SECTIONS)
    for k in only:
        try:
            SECTIONS[k]()
        except Exception as e:  # a crashed section is a failure, not a skip
            check(f"{k}: section ran", False, repr(e))
    sys.exit(1 if failed else 0)
