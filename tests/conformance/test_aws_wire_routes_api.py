"""API coverage: the raw wire-protocol routes /api/dynamodb/aws (DynamoDB JSON 1.0)
and /api/ec2/aws (EC2 Query protocol), incl. DescribeRegions / DescribeAvailabilityZones."""
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def ddb(op, body):
    req = urllib.request.Request(BASE + "/api/dynamodb/aws", method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/x-amz-json-1.0",
                                          "X-Amz-Target": f"DynamoDB_20120810.{op}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def ec2(action, **kw):
    data = urllib.parse.urlencode({"Action": action, "Version": "2016-11-15", **kw}).encode()
    req = urllib.request.Request(BASE + "/api/ec2/aws", method="POST", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        xml = r.read().decode()
    return ET.fromstring(xml.replace(' xmlns="http://ec2.amazonaws.com/doc/2016-11-15/"', ""))


def check(name, fn):
    global failed
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:200]}")
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


T = "wire-" + uuid.uuid4().hex[:8]
ddb("CreateTable", {"TableName": T, "BillingMode": "PAY_PER_REQUEST",
                    "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}],
                    "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}]})
check("DynamoDB wire route lists the created table", lambda: T in ddb("ListTables", {})["TableNames"])
ddb("PutItem", {"TableName": T, "Item": {"pk": {"S": "a"}, "v": {"N": "7"}}})
check("DynamoDB wire route GetItem returns the written item",
      lambda: ddb("GetItem", {"TableName": T, "Key": {"pk": {"S": "a"}}})["Item"]["v"]["N"] == "7")
ddb("DeleteTable", {"TableName": T})
check("DynamoDB wire route DeleteTable removes it", lambda: T not in ddb("ListTables", {})["TableNames"])

check("EC2 wire route DescribeInstances answers", lambda: ec2("DescribeInstances").tag.endswith("DescribeInstancesResponse"))
check("EC2 wire route DescribeRegions lists regions with endpoints",
      lambda: (lambda r: "us-east-1" in [x.text for x in r.iter("regionName")]
               and "ec2.us-east-1.amazonaws.com" in [x.text for x in r.iter("regionEndpoint")])(ec2("DescribeRegions")))
check("EC2 wire route DescribeRegions honours RegionName.1",
      lambda: [x.text for x in ec2("DescribeRegions", **{"RegionName.1": "eu-west-1"}).iter("regionName")] == ["eu-west-1"])
check("EC2 wire route DescribeAvailabilityZones returns available zones",
      lambda: (lambda z: len(z) >= 2 and all(x.text == "available" for x in z))(list(ec2("DescribeAvailabilityZones").iter("zoneState"))))
sys.exit(1 if failed else 0)
