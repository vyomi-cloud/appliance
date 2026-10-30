"""Nano: launching an EC2 instance with the form defaults comes back fully described
(instance id, running state, public/private IPv4, AMI, AZ, launch time)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from wasm.backends.store import Backends
from wasm import providers as P

failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


b = Backends()
r = P.dispatch(b, "aws", "_resource", "Create", params={"service": "ec2", "body": {"name": "my-ec2-instance"}})
check("create ok", r.get("ok"), r)
check("instance id is i-<17 hex>", re.fullmatch(r"i-[0-9a-f]{17}", r.get("instance_id", "")), r)
check("state running", r.get("state") == "running", r)
check("private IPv4 inside its default-VPC subnet", r.get("private_ip", "").startswith("172.31.") and r.get("subnet_id", "").startswith("subnet-"), r)
check("public IPv4 + DNS", bool(r.get("public_ip")) and r["public_ip"].replace(".", "-") in r.get("public_dns", ""), r)
check("AMI / AZ / launch time", r.get("image_id", "").startswith("ami-") and r.get("availability_zone") and r.get("launch_time"), r)
check("instance type default kept", r.get("instance_type") == "t3.micro", r)
r2 = P.dispatch(b, "aws", "_resource", "Create", params={"service": "ec2", "body": {"name": "big", "instance_type": "m5.large"}})
check("explicit instance type preserved", r2.get("instance_type") == "m5.large", r2)
check("ids unique", r2.get("instance_id") != r.get("instance_id"))
rows = P.dispatch(b, "aws", "_resource", "List", params={"service": "ec2"}).get("items", [])
check("list shows both", len(rows) == 2, rows)
g = P.dispatch(b, "aws", "_resource", "Get", params={"service": "ec2", "name": r["instance_id"]})
check("detail page opens by instance id", g.get("ok") and g.get("name") == "my-ec2-instance", g)
P.dispatch(b, "aws", "_resource", "Stop", params={"service": "ec2", "name": r["instance_id"]})
g = P.dispatch(b, "aws", "_resource", "Get", params={"service": "ec2", "name": "my-ec2-instance"})
check("stop by instance id flips state", g.get("state") == "stopped", g)
d = P.dispatch(b, "aws", "_resource", "Delete", params={"service": "ec2", "name": r2["instance_id"]})
check("delete by instance id", d.get("ok"), d)
sys.exit(1 if failed else 0)
